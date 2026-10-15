"""배포 점검(스모크 테스트) — F15 인수 조건을 실제 서버에 대고 한 번에 확인한다.

흐름: /health(깨우기, 최대 90초) → /ready(db false면 실패, redis false면 경고 후 계속)
      → 로그인 → 세션 생성 → 메모 2개 → 각각 분석 → 한 필드 수정 + 비추천(down) 평가 → 비교표
      → 운영자 로그인 → /admin/logs에서 분석 요청의 X-Request-ID 찾기
      → /admin/logs/stream에 잠깐 붙어 새 요청 이벤트 확인(Pub/Sub) → 테스트 세션 삭제
"재시작 후 기록 유지"는 자동으로 하지 않는다(docs/DEMO_CHECKLIST.md의 수동 절차).

입력(환경변수)
    API_BASE_URL            예: https://house-tour-notes-api.onrender.com
    SMOKE_USER_EMAIL        테스트 계정(일반 사용자)
    SMOKE_USER_PASSWORD
    SMOKE_ADMIN_EMAIL       운영자 계정(profiles.role = 'admin')
    SMOKE_ADMIN_PASSWORD
    SMOKE_FIRST_WAIT_SEC    선택, 기본 90 — 잠든 서버를 기다리는 시간
    SMOKE_STREAM_WAIT_SEC   선택, 기본 20 — 실시간 이벤트를 기다리는 시간

실행(저장소 루트, bash)
    API_BASE_URL=https://… SMOKE_USER_EMAIL=… SMOKE_USER_PASSWORD=… \
    SMOKE_ADMIN_EMAIL=… SMOKE_ADMIN_PASSWORD=… python backend/scripts/smoke_test.py
PowerShell은 `$env:API_BASE_URL="https://…"`처럼 먼저 설정하고 실행한다.

종료 코드: 0 실패 없음(경고는 허용), 1 실패 있음, 2 환경변수 누락.
출력에는 토큰·비밀번호·메모 원문을 남기지 않는다. 로그아웃은 부르지 않는다
(Supabase 로그아웃이 같은 계정의 다른 로그인까지 끊을 수 있어 시연 화면이 풀릴 수 있음).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import queue
import sys
import threading
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx

REQUIRED_ENV = (
    "API_BASE_URL",
    "SMOKE_USER_EMAIL",
    "SMOKE_USER_PASSWORD",
    "SMOKE_ADMIN_EMAIL",
    "SMOKE_ADMIN_PASSWORD",
)
DEFAULT_TIMEOUT_SEC = 30.0
ANALYSIS_TIMEOUT_SEC = 90.0       # GEMINI_TIMEOUT_SEC(30) + 호출 간격 대기 + 여유
RATE_LIMIT_RETRIES = 2            # 429 AI_RATE_LIMITED면 잠시 쉬고 다시
RATE_LIMIT_WAIT_SEC = 6.0
HEALTH_RETRY_SEC = 3.0
LOG_RETRY_SEC = 2.0
STREAM_TRIGGER_EVERY_SEC = 5.0    # 구독이 늦게 붙는 경우를 대비해 새 요청을 주기적으로 다시 만든다
EDIT_FIELD = "monthly_rent_manwon"
KST = dt.timezone(dt.timedelta(hours=9))

# 가상의 메모(실제 주소·연락처·실명 없음)
SAMPLE_MEMOS = (
    "보증금 500 월세 45 관리비 7(인터넷·수도 포함). 역까지 걸어서 8분. 3층 남향. "
    "채광 좋음, 수압 괜찮음, 곰팡이 없음. 단점: 큰길 옆이라 소음이 있음.",
    "보증금 1000 월세 38, 관리비는 물어보지 못함. 버스 정류장 5분. 반지하라 채광 약함. "
    "화장실 수압 약함. 옵션: 세탁기, 냉장고.",
)

PASS, WARN, FAIL, SKIP = "PASS", "WARN", "FAIL", "SKIP"


@dataclass
class StepResult:
    name: str
    status: str
    seconds: float
    message: str = ""


class StepFailed(Exception):
    """단계 실패. 메시지는 화면에 그대로 찍히므로 원문·토큰을 넣지 않는다."""


@dataclass
class Warn:
    """단계는 통과했지만 알려야 할 것이 있을 때 단계 함수가 돌려준다."""

    message: str


@dataclass
class Config:
    base_url: str
    user_email: str
    user_password: str
    admin_email: str
    admin_password: str
    first_wait_sec: float = 90.0
    stream_wait_sec: float = 20.0
    log_wait_sec: float = 10.0

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> tuple[Config | None, list[str]]:
        missing = [k for k in REQUIRED_ENV if not (env.get(k) or "").strip()]
        if missing:
            return None, missing
        return (
            cls(
                base_url=env["API_BASE_URL"].strip().rstrip("/"),
                user_email=env["SMOKE_USER_EMAIL"].strip(),
                user_password=env["SMOKE_USER_PASSWORD"],
                admin_email=env["SMOKE_ADMIN_EMAIL"].strip(),
                admin_password=env["SMOKE_ADMIN_PASSWORD"],
                first_wait_sec=float(env.get("SMOKE_FIRST_WAIT_SEC") or 90),
                stream_wait_sec=float(env.get("SMOKE_STREAM_WAIT_SEC") or 20),
            ),
            [],
        )


def iter_sse(lines: Iterable[str]) -> Iterator[dict[str, Any]]:
    """SSE 줄 → {"event", "data", "id"}. data가 JSON이면 해석한다. ':'로 시작하는 줄(keep-alive)은 무시."""
    event: dict[str, Any] = {"event": "message", "data": "", "id": None}
    data_lines: list[str] = []
    for line in lines:
        line = line.rstrip("\r")
        if line == "":
            if data_lines:
                raw = "\n".join(data_lines)
                try:
                    event["data"] = json.loads(raw)
                except ValueError:
                    event["data"] = raw
                yield event
            event, data_lines = {"event": "message", "data": "", "id": None}, []
        elif line.startswith(":"):
            continue
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip(" "))
        elif line.startswith("event:"):
            event["event"] = line[6:].strip()
        elif line.startswith("id:"):
            event["id"] = line[3:].strip()
    if data_lines:  # 마지막 빈 줄 없이 끝난 경우
        raw = "\n".join(data_lines)
        try:
            event["data"] = json.loads(raw)
        except ValueError:
            event["data"] = raw
        yield event


def describe_error(r: httpx.Response) -> str:
    """오류 응답 → 한 줄. 서버 오류 형식 {"error":{"code","message","detail":{"request_id"}}}을 쓴다."""
    code = message = None
    try:
        err = r.json().get("error") or {}
        code, message = err.get("code"), err.get("message")
    except (ValueError, AttributeError):
        pass
    rid = r.headers.get("x-request-id")
    parts = [f"HTTP {r.status_code}"]
    if code:
        parts.append(str(code))
    if message:
        parts.append(f"— {message}")
    if rid:
        parts.append(f"(request_id={rid})")
    return " ".join(parts)


class SmokeTest:
    def __init__(
        self,
        config: Config,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        out: Callable[[str], None] = print,
    ):
        self.config = config
        self._transport = transport
        self.sleep = sleep
        self.clock = clock
        self.out = out
        self.client = self._new_client()
        self.results: list[StepResult] = []
        self.user_token: str | None = None
        self.admin_token: str | None = None
        self.redis_ok = True
        self.session_id: str | None = None
        self.session_title: str | None = None
        self.listings: list[dict] = []          # ListingOut
        self.analyses: list[dict] = []          # AnalysisOut
        self.analysis_request_id: str | None = None
        self.edited_value: Any = None

    # ------------------------------------------------------------------ 공통
    def _new_client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.config.base_url,
            transport=self._transport,
            timeout=DEFAULT_TIMEOUT_SEC,
            headers={"User-Agent": "house-tour-notes-smoke/1"},
        )

    @staticmethod
    def _auth(token: str | None) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"} if token else {}

    def _request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        json_body: Any = None,
        timeout: float | None = None,
        expect: tuple[int, ...] = (200,),
    ) -> httpx.Response:
        kwargs: dict[str, Any] = {"headers": self._auth(token)}
        if json_body is not None:
            kwargs["json"] = json_body
        if timeout is not None:
            kwargs["timeout"] = timeout
        r = self.client.request(method, path, **kwargs)
        if r.status_code not in expect:
            raise StepFailed(f"{method} {path}: {describe_error(r)}")
        return r

    @staticmethod
    def _json(r: httpx.Response) -> Any:
        try:
            return r.json()
        except ValueError:
            raise StepFailed(f"{r.request.method} {r.request.url.path}: JSON 응답이 아님") from None

    def _run_step(self, no: int, name: str, fn: Callable[[], Any]) -> StepResult:
        started = self.clock()
        try:
            outcome = fn()
            if isinstance(outcome, Warn):
                status, message = WARN, outcome.message
            else:
                status, message = PASS, (outcome or "")
        except StepFailed as exc:
            status, message = FAIL, str(exc)
        except httpx.TimeoutException:
            status, message = FAIL, "응답 시간 초과"
        except httpx.HTTPError as exc:
            status, message = FAIL, f"연결 실패({type(exc).__name__})"
        except Exception as exc:  # noqa: BLE001 — 점검 스크립트는 멈추지 않고 실패로 적는다
            status, message = FAIL, f"예상하지 못한 오류({type(exc).__name__})"
        result = StepResult(name, status, self.clock() - started, str(message))
        self._record(no, result)
        return result

    def _record(self, no: int, result: StepResult) -> None:
        self.results.append(result)
        line = f"[{result.status}] {no:>2}. {result.name} ({result.seconds:.1f}s)"
        if result.message:
            line += f" — {result.message}"
        self.out(line)

    # ------------------------------------------------------------------ 실행
    def steps(self) -> list[tuple[str, Callable[[], Any]]]:
        return [
            ("서버 깨우기 /health", self.step_health),
            ("준비 상태 /ready", self.step_ready),
            ("로그인(테스트 계정)", self.step_login_user),
            ("세션 생성", self.step_create_session),
            ("메모 2개 저장", self.step_create_listings),
            ("메모 분석 2건", self.step_analyze),
            ("필드 수정 + 비추천(down) 평가", self.step_edit_and_rate),
            ("비교표 조회", self.step_comparison),
            ("운영자 로그인", self.step_login_admin),
            ("운영 로그에서 분석 요청 찾기", self.step_admin_logs),
            ("실시간 로그 스트림(Pub/Sub)", self.step_stream),
        ]

    def run(self) -> int:
        self.out(f"스모크 테스트 대상: {self.config.base_url}")
        total_started = self.clock()
        failed = False
        steps = self.steps()
        try:
            for no, (name, fn) in enumerate(steps, start=1):
                if failed:
                    self._record(no, StepResult(name, SKIP, 0.0, "앞 단계 실패로 건너뜀"))
                    continue
                if self._run_step(no, name, fn).status == FAIL:
                    failed = True
            cleanup_no = len(steps) + 1
            if self.session_id:
                self._run_step(cleanup_no, "테스트 세션 삭제", self.step_cleanup)
            else:
                self._record(cleanup_no, StepResult("테스트 세션 삭제", SKIP, 0.0, "만든 세션 없음"))
        finally:
            self.client.close()
        counts = {s: sum(1 for r in self.results if r.status == s) for s in (PASS, WARN, FAIL, SKIP)}
        self.out(
            f"== 결과: 통과 {counts[PASS]} · 경고 {counts[WARN]} · 실패 {counts[FAIL]} · 건너뜀 {counts[SKIP]}"
            f" (총 {self.clock() - total_started:.1f}s)"
        )
        return 1 if counts[FAIL] else 0

    # ------------------------------------------------------------------ 단계
    def step_health(self) -> str:
        deadline = self.clock() + self.config.first_wait_sec
        attempts, last = 0, ""
        while True:
            remaining = deadline - self.clock()
            if remaining <= 0:
                raise StepFailed(f"{self.config.first_wait_sec:.0f}초 안에 200 응답 없음(마지막: {last or '없음'})")
            attempts += 1
            try:
                r = self.client.get("/health", timeout=max(1.0, remaining))
                if r.status_code == 200:
                    return f"{attempts}번째 시도에 응답"
                last = f"HTTP {r.status_code}"
            except httpx.HTTPError as exc:
                last = type(exc).__name__
            self.sleep(HEALTH_RETRY_SEC)

    def step_ready(self) -> str | Warn:
        r = self.client.get("/ready")
        try:
            body = r.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        if r.status_code not in (200, 503):
            raise StepFailed(f"GET /ready: {describe_error(r)}")
        if r.status_code == 503 or body.get("db") is not True:
            raise StepFailed("DB 연결 실패(db=false) — Supabase 일시정지 여부, SUPABASE_URL·SUPABASE_SECRET_KEY 확인")
        self.redis_ok = body.get("redis") is True
        if not self.redis_ok:
            return Warn("Redis 연결 안 됨(redis=false) — 초안·캐시·실시간 로그가 멈춘다. 나머지는 계속 확인")
        return "db·redis 정상"

    def _login(self, email: str, password: str) -> dict:
        r = self._request("POST", "/auth/login", json_body={"email": email, "password": password})
        body = self._json(r)
        if not isinstance(body, dict) or not body.get("access_token"):
            raise StepFailed("POST /auth/login: access_token 없음")
        return body

    def step_login_user(self) -> str:
        body = self._login(self.config.user_email, self.config.user_password)
        self.user_token = body["access_token"]
        role = (body.get("profile") or {}).get("role", "?")
        return f"역할 {role}"

    def step_create_session(self) -> str:
        now = dt.datetime.now(KST)
        title = f"스모크 테스트 {now:%m-%d %H:%M}"
        r = self._request(
            "POST", "/sessions", token=self.user_token,
            json_body={"title": title, "visit_date": now.date().isoformat()}, expect=(200, 201),
        )
        body = self._json(r)
        if not isinstance(body, dict) or not body.get("id"):
            raise StepFailed("POST /sessions: id 없음")
        self.session_id, self.session_title = body["id"], title
        return f"'{title}'"

    def step_create_listings(self) -> str:
        for memo in SAMPLE_MEMOS:
            r = self._request(
                "POST", f"/sessions/{self.session_id}/listings", token=self.user_token,
                json_body={"memo_text": memo}, expect=(200, 201),
            )
            body = self._json(r)
            if not isinstance(body, dict) or not body.get("id"):
                raise StepFailed("POST /sessions/{id}/listings: id 없음")
            self.listings.append(body)
        return ", ".join(str(l.get("label") or l["id"]) for l in self.listings)

    def _analyze(self, listing: dict) -> httpx.Response:
        path = f"/listings/{listing['id']}/analyses"
        for attempt in range(RATE_LIMIT_RETRIES + 1):
            r = self.client.post(path, json={"use_cache": False}, headers=self._auth(self.user_token),
                                 timeout=ANALYSIS_TIMEOUT_SEC)
            if r.status_code == 429 and attempt < RATE_LIMIT_RETRIES:
                self.sleep(RATE_LIMIT_WAIT_SEC)
                continue
            if r.status_code not in (200, 201):
                raise StepFailed(f"POST /listings/{{id}}/analyses({listing.get('label', '')}): {describe_error(r)}")
            return r
        raise StepFailed("분석 요청이 계속 429")  # 도달하지 않음

    def step_analyze(self) -> str:
        for listing in self.listings:
            r = self._analyze(listing)
            body = self._json(r)
            if not isinstance(body, dict) or body.get("status") != "success":
                code = body.get("error_code") if isinstance(body, dict) else None
                raise StepFailed(f"{listing.get('label', '')} 분석 실패(error_code={code})")
            if self.analysis_request_id is None:
                rid = r.headers.get("x-request-id")
                if not rid:
                    raise StepFailed("분석 응답에 X-Request-ID 헤더가 없음")
                self.analysis_request_id = rid
            self.analyses.append(body)
        return f"{len(self.analyses)}건 성공, 첫 분석 요청 X-Request-ID={self.analysis_request_id}"

    def step_edit_and_rate(self) -> str:
        analysis, listing = self.analyses[0], self.listings[0]
        current = ((analysis.get("fields") or {}).get(EDIT_FIELD) or {}).get("value")
        new_value = current + 1 if isinstance(current, int) and not isinstance(current, bool) else 45
        aid = analysis["id"]
        self._request(
            "POST", f"/analyses/{aid}/feedback", token=self.user_token,
            json_body={"field_name": EDIT_FIELD, "corrected_value": new_value}, expect=(200, 201),
        )
        self._request(
            "POST", f"/analyses/{aid}/feedback", token=self.user_token,
            json_body={"rating": "down", "reason": "amount", "comment": "스모크 테스트 자동 평가"},
            expect=(200, 201),
        )
        latest = self._json(self._request("GET", f"/listings/{listing['id']}/analyses/latest", token=self.user_token))
        fv = ((latest.get("fields") if isinstance(latest, dict) else None) or {}).get(EDIT_FIELD) or {}
        if fv.get("value") != new_value or fv.get("edited") is not True:
            raise StepFailed(f"수정값이 최신 분석에 반영되지 않음({EDIT_FIELD}: 기대 {new_value}, 받은 값 {fv.get('value')})")
        if latest.get("rating") != "down":
            raise StepFailed(f"평가가 반영되지 않음(rating={latest.get('rating')})")
        self.edited_value = new_value
        return f"{EDIT_FIELD} {current} → {new_value}, rating=down"

    def step_comparison(self) -> str:
        body = self._json(self._request("GET", f"/sessions/{self.session_id}/comparison", token=self.user_token))
        if not isinstance(body, dict):
            raise StepFailed("비교표 응답 모양이 다름")
        rows = body.get("rows") or []
        if body.get("enough_listings") is not True or len(rows) != len(self.listings):
            raise StepFailed(f"비교표 행 수가 다름(enough_listings={body.get('enough_listings')}, rows={len(rows)})")
        first = next((row for row in rows if row.get("listing_id") == self.listings[0]["id"]), None)
        if first is None:
            raise StepFailed("비교표에 1번 매물이 없음")
        got = (first.get("values") or {}).get(EDIT_FIELD)
        if got != self.edited_value:
            raise StepFailed(f"비교표에 수정값이 반영되지 않음({EDIT_FIELD}: 기대 {self.edited_value}, 받은 값 {got})")
        return f"행 {len(rows)}개, 수정값 반영 확인"

    def step_login_admin(self) -> str:
        body = self._login(self.config.admin_email, self.config.admin_password)
        role = (body.get("profile") or {}).get("role")
        if role != "admin":
            raise StepFailed(f"운영자 계정의 role이 admin이 아님(role={role}) — docs/DEPLOY.md 2절 운영자 지정 SQL")
        self.admin_token = body["access_token"]
        return "role=admin"

    def step_admin_logs(self) -> str:
        rid = self.analysis_request_id
        deadline = self.clock() + self.config.log_wait_sec
        while True:
            body = self._json(self._request("GET", "/admin/logs", token=self.admin_token))
            if not isinstance(body, list):
                raise StepFailed("GET /admin/logs 응답이 목록(list)이 아님")
            row = next((x for x in body if isinstance(x, dict) and x.get("request_id") == rid), None)
            if row is not None:
                if row.get("method") != "POST" or "analyses" not in str(row.get("endpoint", "")):
                    raise StepFailed(f"찾은 로그가 분석 요청이 아님({row.get('method')} {row.get('endpoint')})")
                ai = row.get("ai_latency_ms")
                return (f"{row.get('method')} {row.get('endpoint')} → {row.get('status_code')}, "
                        f"{row.get('latency_ms')}ms (AI {ai if ai is not None else '-'}ms)")
            if self.clock() >= deadline:
                raise StepFailed(
                    f"최근 로그에 X-Request-ID={rid}가 없음 — 로그 저장 실패(서버 로그의 request_logs insert failed) "
                    "또는 목록이 최근 일부만 주는지 확인"
                )
            self.sleep(LOG_RETRY_SEC)

    def step_stream(self) -> str | Warn:
        if not self.redis_ok:
            return Warn("Redis가 꺼져 있어 건너뜀(/ready redis=false)")
        events: queue.Queue = queue.Queue()
        connected = threading.Event()
        stop = threading.Event()
        holder: dict[str, Any] = {}
        stream_client = self._new_client()
        timeout = httpx.Timeout(10.0, read=self.config.stream_wait_sec + 5)
        headers = {**self._auth(self.admin_token), "Accept": "text/event-stream"}

        def reader() -> None:
            try:
                with stream_client.stream("GET", "/admin/logs/stream", headers=headers, timeout=timeout) as r:
                    if r.status_code != 200:
                        r.read()
                        holder["error"] = describe_error(r)
                        return
                    holder["response"] = r
                    connected.set()
                    for ev in iter_sse(r.iter_lines()):
                        if stop.is_set():
                            break
                        events.put(ev)
            except Exception as exc:  # noqa: BLE001
                holder.setdefault("error", type(exc).__name__)
            finally:
                connected.set()
                events.put(None)  # 끝 표시

        thread = threading.Thread(target=reader, name="smoke-sse", daemon=True)
        thread.start()
        try:
            if not connected.wait(timeout=15):
                raise StepFailed("15초 안에 스트림 연결이 열리지 않음")
            if "response" not in holder:
                raise StepFailed(f"스트림 연결 실패: {holder.get('error', '알 수 없음')}")
            started = self.clock()
            deadline = started + self.config.stream_wait_sec
            trigger_ids: set[str] = set()
            next_trigger = started
            while self.clock() < deadline:
                if self.clock() >= next_trigger:
                    r = self._request("GET", "/me", token=self.user_token)
                    if r.headers.get("x-request-id"):
                        trigger_ids.add(r.headers["x-request-id"])
                    next_trigger = self.clock() + STREAM_TRIGGER_EVERY_SEC
                try:
                    ev = events.get(timeout=1.0)
                except queue.Empty:
                    continue
                if ev is None:
                    raise StepFailed(f"스트림이 끊김({holder.get('error', '서버가 연결을 닫음')})")
                data = ev.get("data")
                if isinstance(data, dict) and data.get("request_id") in trigger_ids:
                    return f"새 요청(GET /me) 이벤트 수신 {self.clock() - started:.1f}s"
            raise StepFailed(
                f"{self.config.stream_wait_sec:.0f}초 동안 새 요청 이벤트가 오지 않음 — REDIS_URL·Pub/Sub 확인"
            )
        finally:
            stop.set()
            resp = holder.get("response")
            if resp is not None:
                try:
                    resp.close()
                except Exception:  # noqa: BLE001
                    pass
            try:
                stream_client.close()
            except Exception:  # noqa: BLE001
                pass
            thread.join(timeout=2)

    def step_cleanup(self) -> str:
        if not self.user_token:
            raise StepFailed(f"토큰이 없어 지우지 못함 — 화면에서 '{self.session_title}' 세션을 직접 삭제")
        try:
            self._request("DELETE", f"/sessions/{self.session_id}", token=self.user_token)
        except StepFailed as exc:
            raise StepFailed(f"{exc} — 화면에서 '{self.session_title}' 세션을 직접 삭제") from None
        return f"'{self.session_title}' 삭제"


def main(env: Mapping[str, str] | None = None, *, transport: httpx.BaseTransport | None = None,
         sleep: Callable[[float], None] = time.sleep) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # Windows 콘솔·파일 리디렉션에서 한글 출력 오류 방지
        except (AttributeError, ValueError):
            pass
    config, missing = Config.from_env(os.environ if env is None else env)
    if config is None:
        print("환경변수가 비어 있습니다: " + ", ".join(missing))
        print("docs/DEPLOY.md 6절의 예시처럼 설정한 뒤 다시 실행하세요.")
        return 2
    return SmokeTest(config, transport=transport, sleep=sleep).run()


if __name__ == "__main__":
    sys.exit(main())
