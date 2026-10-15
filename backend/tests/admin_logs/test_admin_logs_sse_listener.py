"""frontend/features/admin_logs/sse_listener.py·logic.py 단위 테스트(네트워크·Streamlit 없이).

frontend에는 app.py가 있어 backend의 app 패키지와 이름이 겹치므로 sys.path에 넣지 않고 파일 경로로 읽는다.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

FEATURE_DIR = Path(__file__).resolve().parents[3] / "frontend" / "features" / "admin_logs"


def _load(name: str, filename: str):
    full = f"p6_frontend_admin_logs_{name}"
    if full in sys.modules:
        return sys.modules[full]
    spec = importlib.util.spec_from_file_location(full, FEATURE_DIR / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod


sse = _load("sse_listener", "sse_listener.py")
logic = _load("logic", "logic.py")


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, sec: float) -> None:
        self.now += sec


class FakeServer:
    """connect 대역. scripts[i]는 i번째 연결에서 낼 항목 목록. 예외 객체면 그 자리에서 던진다."""

    def __init__(self, scripts, clock=None, on_exhausted=None):
        self.scripts = list(scripts)
        self.calls = []
        self.closed = 0
        self.clock = clock

    def __call__(self, base_url, token, last_event_id):
        self.calls.append({"token": token, "last_event_id": last_event_id})
        script = self.scripts.pop(0) if self.scripts else [sse.StreamDisconnected("no more")]
        return self._gen(script)

    def _gen(self, script):
        try:
            for item in script:
                if isinstance(item, BaseException):
                    raise item
                if isinstance(item, (int, float)) and self.clock is not None:
                    self.clock.advance(item)        # 숫자: 시간이 흐름(연결 유지 신호를 기다리는 동안)
                    yield {"type": "ping"}
                    continue
                yield item
        finally:
            self.closed += 1


def _log(i):
    return {"type": "event", "event": "log", "id": str(i), "data": {"id": i, "request_id": f"r{i}",
                                                                      "endpoint": "/sessions", "status_code": 200}}


OPEN = {"type": "open"}


def _run(server, clock, shared=None, queue=None):
    import queue as q

    shared = shared or sse.SharedState(base_url="http://api.test", token="tok-1", clock=clock)
    out = queue or q.Queue()
    sleeps = []

    def fake_sleep(sec):
        sleeps.append(sec)
        clock.advance(sec)
        shared.touch()                             # 화면이 계속 보고 있다(대기 중에도 하트비트 유지)

    result = sse.run_listener(shared, out, connect=server, sleep=fake_sleep)
    items = []
    while not out.empty():
        items.append(out.get())
    return result, shared, items, sleeps


def test_admin_logs_listener_reconnects_with_last_event_id_and_backoff():
    clock = FakeClock()
    server = FakeServer([
        [OPEN, _log(1), _log(2), sse.StreamDisconnected("boom")],     # 연결 후 끊김
        [sse.StreamDisconnected("refused")],                           # 다시 연결 실패
        [sse.StreamDisconnected("refused")],
        [OPEN, _log(3), 20],                                          # 연결 → 20초 아무도 안 봄 → 중지
    ], clock=clock)
    result, shared, items, sleeps = _run(server, clock)
    assert [c["last_event_id"] for c in server.calls] == [None, 2, 2, 2]
    assert [x["id"] for x in items] == [1, 2, 3]
    # 연결 성공 뒤 끊김 → 1초, 실패 → 2초, 실패 → 4초 (0.25초 단위로 나눠 자며 하트비트 확인)
    assert sum(sleeps) == pytest.approx(1 + 2 + 4)
    assert max(sleeps) <= sse.SLEEP_STEP_SEC
    assert shared.snapshot()["connect_count"] == 2
    assert result == sse.STOPPED
    assert server.closed == 4                                           # 연결마다 닫음


def test_admin_logs_listener_backoff_caps_at_8_seconds():
    clock = FakeClock()
    fails = [[sse.StreamDisconnected("x")] for _ in range(6)]
    server = FakeServer(fails + [[OPEN, 20]], clock=clock)
    _, _, _, sleeps = _run(server, clock)
    assert sum(sleeps) == pytest.approx(1 + 2 + 4 + 8 + 8 + 8)


def test_admin_logs_listener_stops_on_heartbeat_timeout():
    """화면이 last_seen을 갱신하지 않으면(페이지 이동·로그아웃·탭 닫기) 연결을 닫고 끝난다."""
    clock = FakeClock()
    server = FakeServer([[OPEN, _log(1), 5, 5, 5, _log(2)]], clock=clock)
    shared = sse.SharedState(base_url="http://api.test", token="t", clock=clock)
    import queue as q
    out = q.Queue()
    result = sse.run_listener(shared, out, connect=server, sleep=lambda s: clock.advance(s))
    assert result == sse.STOPPED
    assert shared.snapshot()["status"] == sse.STOPPED
    assert server.closed == 1
    assert out.qsize() == 1                     # 멈춘 뒤에는 더 받지 않는다


def test_admin_logs_listener_stops_on_401_without_reconnect():
    clock = FakeClock()
    server = FakeServer([[sse.StreamUnauthorized(401)], [OPEN]], clock=clock)
    result, shared, _, sleeps = _run(server, clock)
    assert result == sse.UNAUTHORIZED
    assert len(server.calls) == 1 and sleeps == []
    assert shared.snapshot()["failed_token"] == "tok-1"


def test_admin_logs_listener_uses_updated_token_next_connection():
    clock = FakeClock()
    shared = sse.SharedState(base_url="http://api.test", token="old", clock=clock)

    class TokenSwap(FakeServer):
        def __call__(self, base_url, token, last_event_id):
            gen = super().__call__(base_url, token, last_event_id)
            shared.set_token("new")             # 연결 중에 화면이 토큰을 바꿈
            return gen

    server = TokenSwap([[OPEN, sse.StreamDisconnected("x")], [OPEN, 20]], clock=clock)
    _run(server, clock, shared=shared)
    assert [c["token"] for c in server.calls] == ["old", "new"]


def test_admin_logs_listener_reconnect_now_skips_wait():
    clock = FakeClock()
    shared = sse.SharedState(base_url="http://api.test", token="t", clock=clock)
    shared.update(reconnect_now=True)
    server = FakeServer([[sse.StreamDisconnected("x")], [OPEN, 20]], clock=clock)
    _, _, _, sleeps = _run(server, clock, shared=shared)
    assert sleeps == []


def test_admin_logs_listener_thread_ends_by_heartbeat():
    """실제 스레드: 화면이 touch하지 않으면 스스로 끝난다(세션당 1개, 남지 않음)."""
    clock = FakeClock()

    def connect(base_url, token, last_event_id):
        def gen():
            yield OPEN
            while True:
                clock.advance(1)
                yield {"type": "ping"}
        return gen()

    listener = sse.Listener("http://api.test", "t", connect=connect, clock=clock).start()
    listener.thread.join(timeout=5)
    assert not listener.is_alive()
    assert listener.shared.snapshot()["status"] == sse.STOPPED


def test_admin_logs_feed_buffer_dedups_by_id():
    feed = sse.FeedBuffer(max_items=3)
    assert feed.add([{"id": 1}, {"id": 2}]) == 2
    assert feed.add([{"id": 2}, {"id": 3}]) == 1          # 서버 재전송과 after_id 재조회가 겹쳐도 한 번
    assert [r["id"] for r in feed.rows()] == [3, 2, 1]
    assert feed.max_id == 3
    feed.add([{"id": 4}])
    assert [r["id"] for r in feed.rows()] == [4, 3, 2]     # 최대 개수 유지
    assert feed.add([{"id": None, "request_id": "x"}, {"id": None, "request_id": "x"}]) == 1


def test_admin_logs_parse_sse_lines():
    lines = [": ping", "event: log", 'data: {"id": 7}', "id: 7", "", "data: plain", ""]
    items = list(sse.parse_sse_lines(lines))
    assert items[0] == {"type": "ping"}
    assert items[1] == {"type": "event", "event": "log", "data": {"id": 7}, "id": "7"}
    assert items[2]["data"] == "plain" and items[2]["event"] == "message"


def test_admin_logs_filter_feed_hides_admin_by_default():
    rows = [
        {"endpoint": "/admin/metrics", "status_code": 200},
        {"endpoint": "/sessions", "status_code": 200},
        {"endpoint": "/listings/{listing_id}/analyses", "status_code": 502, "prompt_version": "v2"},
    ]
    assert [r["endpoint"] for r in logic.filter_feed(rows)] == ["/sessions", "/listings/{listing_id}/analyses"]
    assert len(logic.filter_feed(rows, include_admin=True)) == 3
    assert len(logic.filter_feed(rows, status="5xx")) == 1
    assert len(logic.filter_feed(rows, prompt_version="v2")) == 1
    assert logic.fmt_pct(None) == "데이터 없음" and logic.fmt_pct(0.125) == "12.5%"


def test_admin_logs_screen_text_avoids_error_rate_word_for_field_edits():
    """필드 수정 비율을 '오류율'이라고 부르지 않는다(정답 기반 아님)."""
    for name in ("logic.py", "components.py", "pages.py"):
        text = (FEATURE_DIR / name).read_text(encoding="utf-8")
        assert "오류율" not in text, name
