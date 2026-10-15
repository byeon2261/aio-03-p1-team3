"""운영 대시보드 실시간 수신 (백그라운드 스레드 + 큐 + 공유 객체).

공식 문서의 스레드 패턴을 따른다: 스레드 안에서는 st.*·st.session_state를 부르지 않는다.
이 모듈은 streamlit을 import하지 않는다(네트워크·Streamlit 없이 단위 테스트).

흐름
    1) 페이지가 세션마다 Listener 하나를 만들고 start()한다.
    2) 스레드는 httpx 스트리밍으로 /admin/logs/stream에 Authorization 헤더를 붙여 연결하고,
       받은 로그를 queue에 넣고 연결 상태를 SharedState에 적는다.
    3) 화면의 @st.fragment(run_every="2s")가 touch()로 last_seen을 갱신하고 큐를 비운다.
       토큰이 바뀌면 set_token()으로 넘긴다(다음 연결부터 씀).
    4) 끊기면 1·2·4·8초 간격으로 다시 연결한다(Last-Event-ID로 서버가 재전송). 401·403이면 끝낸다.
    5) last_seen이 HEARTBEAT_TIMEOUT_SEC 넘게 갱신되지 않으면 연결을 닫고 끝난다
       (페이지 이동·로그아웃·탭 닫기 모두 이 방식. Streamlit에는 페이지를 떠날 때 부르는 콜백이 없다).
"""

from __future__ import annotations

import json
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Iterator

import httpx

STREAM_PATH = "/admin/logs/stream"
HEARTBEAT_TIMEOUT_SEC = 10.0
BACKOFF_SEC = (1, 2, 4, 8)          # 다시 연결 간격(마지막 값 반복)
CONNECT_TIMEOUT_SEC = 10.0
READ_TIMEOUT_SEC = 30.0             # 서버가 15초마다 연결 유지 신호를 보내므로 그보다 길게
SLEEP_STEP_SEC = 0.25               # 기다리는 동안 하트비트를 확인하는 간격
FEED_MAX = 300                      # 화면에 들고 있는 최근 로그 수

# 연결 상태
CONNECTING = "connecting"
CONNECTED = "connected"
DISCONNECTED = "disconnected"
STOPPED = "stopped"                 # 하트비트 끊김(페이지를 떠남)
UNAUTHORIZED = "unauthorized"       # 401: 화면이 새 토큰으로 다시 띄운다
FORBIDDEN = "forbidden"             # 403: 운영자가 아님
TERMINAL = (STOPPED, UNAUTHORIZED, FORBIDDEN)


class StreamUnauthorized(Exception):
    def __init__(self, status: int):
        super().__init__(str(status))
        self.status = status


class StreamDisconnected(Exception):
    """연결 실패·끊김·서버 오류(5xx 등). 다시 연결한다."""


@dataclass
class SharedState:
    """스레드와 화면이 함께 보는 값. 모든 접근은 lock 안에서."""

    base_url: str
    token: str | None
    clock: Callable[[], float] = time.monotonic
    last_seen: float = 0.0
    status: str = CONNECTING
    connect_count: int = 0              # 연결에 성공한 횟수(늘면 화면이 after_id로 빈 구간을 채운다)
    last_event_id: int | None = None
    failed_token: str | None = None     # 401을 받은 토큰
    error: str | None = None
    reconnect_now: bool = False         # 화면의 '다시 연결': 대기 없이 바로 다시 연결
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        self.last_seen = self.clock()

    def touch(self) -> None:
        with self.lock:
            self.last_seen = self.clock()

    def set_token(self, token: str | None) -> None:
        with self.lock:
            self.token = token

    def heartbeat_expired(self, timeout: float = HEARTBEAT_TIMEOUT_SEC) -> bool:
        with self.lock:
            return self.clock() - self.last_seen > timeout

    def update(self, **values: Any) -> None:
        with self.lock:
            for k, v in values.items():
                setattr(self, k, v)

    def snapshot(self) -> dict:
        with self.lock:
            return {"status": self.status, "connect_count": self.connect_count, "last_event_id": self.last_event_id,
                    "error": self.error, "failed_token": self.failed_token, "token": self.token}


# ------------------------------------------------------------------ SSE 파싱·연결
def parse_sse_lines(lines: Iterable[str]) -> Iterator[dict]:
    """SSE 줄 → {"type": "event", "event", "data", "id"} 또는 {"type": "ping"}(주석·연결 유지 신호)."""
    event: dict[str, Any] = {"event": "message", "id": None}
    data: list[str] = []
    for line in lines:
        if line == "":
            if data:
                raw = "\n".join(data)
                try:
                    payload: Any = json.loads(raw)
                except ValueError:
                    payload = raw
                yield {"type": "event", "event": event["event"], "data": payload, "id": event["id"]}
            event, data = {"event": "message", "id": None}, []
        elif line.startswith(":"):
            yield {"type": "ping"}
        elif line.startswith("data:"):
            data.append(line[5:].lstrip(" "))
        elif line.startswith("event:"):
            event["event"] = line[6:].strip()
        elif line.startswith("id:"):
            event["id"] = line[3:].strip() or None


def httpx_connect(base_url: str, token: str | None, last_event_id: int | None) -> Iterator[dict]:
    """실제 연결. 먼저 {"type": "open"}을 내고, 이어서 parse_sse_lines 결과를 낸다."""
    headers = {"Accept": "text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if last_event_id is not None:
        headers["Last-Event-ID"] = str(last_event_id)
    timeout = httpx.Timeout(CONNECT_TIMEOUT_SEC, read=READ_TIMEOUT_SEC)
    try:
        with httpx.stream("GET", base_url.rstrip("/") + STREAM_PATH, headers=headers, timeout=timeout) as r:
            if r.status_code in (401, 403):
                raise StreamUnauthorized(r.status_code)
            if r.status_code >= 400:
                raise StreamDisconnected(f"HTTP {r.status_code}")
            yield {"type": "open"}
            yield from parse_sse_lines(r.iter_lines())
    except httpx.HTTPError as exc:
        raise StreamDisconnected(type(exc).__name__) from None
    raise StreamDisconnected("stream ended")


def _to_int(v: Any) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ 스레드 본체
def run_listener(shared: SharedState, out: "queue.Queue[dict]", *,
                 connect: Callable[[str, str | None, int | None], Iterator[dict]] = httpx_connect,
                 sleep: Callable[[float], None] = time.sleep,
                 heartbeat_timeout: float = HEARTBEAT_TIMEOUT_SEC,
                 backoff: tuple[float, ...] = BACKOFF_SEC) -> str:
    """연결 → 수신 → 끊기면 다시 연결. 끝난 이유(TERMINAL 상태)를 돌려준다."""
    attempt = 0
    while True:
        if shared.heartbeat_expired(heartbeat_timeout):
            shared.update(status=STOPPED)
            return STOPPED
        snap = shared.snapshot()
        token = snap["token"]
        shared.update(status=CONNECTING if snap["connect_count"] == 0 else DISCONNECTED)
        stream = connect(shared.base_url, token, snap["last_event_id"])
        try:
            for item in stream:
                kind = item.get("type")
                if kind == "open":
                    attempt = 0
                    with shared.lock:
                        shared.status = CONNECTED
                        shared.connect_count += 1
                        shared.error = None
                elif kind == "event" and item.get("event") == "log" and isinstance(item.get("data"), dict):
                    out.put(item["data"])
                    rid = _to_int(item.get("id"))
                    if rid is not None:
                        with shared.lock:
                            shared.last_event_id = max(rid, shared.last_event_id or 0)
                if shared.heartbeat_expired(heartbeat_timeout):
                    shared.update(status=STOPPED)
                    return STOPPED
        except StreamUnauthorized as exc:
            status = UNAUTHORIZED if exc.status == 401 else FORBIDDEN
            shared.update(status=status, failed_token=token, error=f"HTTP {exc.status}")
            return status
        except StreamDisconnected as exc:
            shared.update(status=DISCONNECTED, error=str(exc))
        except Exception as exc:  # 예상 못한 오류도 다시 연결로 처리(스레드가 조용히 죽지 않게)
            shared.update(status=DISCONNECTED, error=type(exc).__name__)
        finally:
            close = getattr(stream, "close", None)
            if close is not None:
                close()   # 생성기를 닫으면 httpx.stream 컨텍스트가 닫혀 연결이 끊긴다

        # 다시 연결 전 대기(대기 중에도 하트비트 확인)
        delay = backoff[min(attempt, len(backoff) - 1)]
        attempt += 1
        waited = 0.0
        while waited < delay:
            if shared.heartbeat_expired(heartbeat_timeout):
                shared.update(status=STOPPED)
                return STOPPED
            with shared.lock:
                if shared.reconnect_now:
                    shared.reconnect_now = False
                    attempt = 0
                    break
            step = min(SLEEP_STEP_SEC, delay - waited)
            sleep(step)
            waited += step


class Listener:
    """세션마다 하나. 화면은 is_alive()가 False면 새로 만든다."""

    def __init__(self, base_url: str, token: str | None, *, connect: Callable = httpx_connect,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.shared = SharedState(base_url=base_url, token=token, clock=clock)
        self.queue: "queue.Queue[dict]" = queue.Queue()
        self._connect = connect
        self.thread = threading.Thread(target=self._run, name="admin-logs-sse", daemon=True)

    def _run(self) -> None:
        run_listener(self.shared, self.queue, connect=self._connect)

    def start(self) -> "Listener":
        self.thread.start()
        return self

    def is_alive(self) -> bool:
        return self.thread.is_alive()

    def request_reconnect(self) -> None:
        """끊긴 상태에서 다음 대기를 건너뛰고 바로 다시 연결한다(스레드는 그대로 1개)."""
        self.shared.update(reconnect_now=True)

    def drain(self, max_items: int = 1000) -> list[dict]:
        items: list[dict] = []
        while len(items) < max_items:
            try:
                items.append(self.queue.get_nowait())
            except queue.Empty:
                break
        return items


# ------------------------------------------------------------------ 화면용 피드(중복 제거)
def _key(row: dict) -> Any:
    rid = row.get("id")
    return ("id", rid) if rid is not None else ("rq", row.get("request_id"))


class FeedBuffer:
    """최근 로그를 id(없으면 request_id)로 중복 없이 들고 있는다. 최신이 앞."""

    def __init__(self, max_items: int = FEED_MAX) -> None:
        self._rows: deque[dict] = deque()
        self._keys: set = set()
        self.max_items = max_items

    def add(self, rows: Iterable[dict]) -> int:
        """새로 들어간 개수."""
        added = 0
        for row in rows:
            k = _key(row)
            if k in self._keys:
                continue
            self._keys.add(k)
            self._rows.append(row)
            added += 1
        if added:
            ordered = sorted(self._rows, key=lambda r: (r.get("id") is not None, r.get("id") or 0,
                                                        str(r.get("created_at") or "")), reverse=True)
            ordered = ordered[: self.max_items]
            self._rows = deque(ordered)
            self._keys = {_key(r) for r in ordered}
        return added

    @property
    def max_id(self) -> int | None:
        ids = [r["id"] for r in self._rows if r.get("id") is not None]
        return max(ids) if ids else None

    def rows(self) -> list[dict]:
        return list(self._rows)

    def __len__(self) -> int:
        return len(self._rows)
