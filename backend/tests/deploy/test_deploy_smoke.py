"""smoke_test.py 단계 함수 단위 테스트 — 가짜 HTTP 응답(httpx.MockTransport)으로 외부 서버 없이 돈다."""

from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from pathlib import Path

import httpx
import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "smoke_test.py"


def _load_smoke():
    name = "deploy_smoke_test_module"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


smoke = _load_smoke()

USER_TOKEN = "user-token-SECRET"
ADMIN_TOKEN = "admin-token-SECRET"
ENV = {
    "API_BASE_URL": "https://api.example.test/",
    "SMOKE_USER_EMAIL": "user@example.test",
    "SMOKE_USER_PASSWORD": "user-pass-SECRET",
    "SMOKE_ADMIN_EMAIL": "admin@example.test",
    "SMOKE_ADMIN_PASSWORD": "admin-pass-SECRET",
    "SMOKE_STREAM_WAIT_SEC": "3",
}
ME_REQUEST_ID = "rid-me"


class FakeApi:
    """계약(CONTRACT.md 4절)의 응답 모양만 흉내 내는 가짜 서버."""

    def __init__(self):
        self.ready = (200, {"db": True, "redis": True})
        self.health_failures = 0            # 앞의 N번은 연결 오류
        self.analysis_status = "success"
        self.analysis_429_times = 0
        self.log_visible_after = 0          # /admin/logs를 N번 부른 뒤부터 분석 로그가 보임
        self.log_present = True
        self.stream_status = 200
        self.stream_has_event = True
        self.apply_edit = True
        self.admin_role = "admin"
        self.calls: list[tuple[str, str]] = []
        self.analysis_request_ids: list[str] = []
        self.sessions: dict[str, dict] = {}
        self.listings: dict[str, dict] = {}
        self.analyses: dict[str, dict] = {}
        self.overrides: dict[str, dict] = {}
        self.ratings: dict[str, str] = {}
        self.deleted: list[str] = []
        self._log_calls = 0

    # ---------------------------------------------------------------- 도우미
    @staticmethod
    def _json(status, body, rid=None):
        return httpx.Response(status, json=body, headers={"x-request-id": rid or str(uuid.uuid4())})

    @staticmethod
    def _error(status, code, message="오류"):
        return httpx.Response(status, json={"error": {"code": code, "message": message, "detail": {}}},
                              headers={"x-request-id": str(uuid.uuid4())})

    def _token(self, request):
        auth = request.headers.get("authorization", "")
        return auth.removeprefix("Bearer ") if auth else None

    def _analysis_out(self, aid):
        a = self.analyses[aid]
        rent = self.overrides.get(aid, {}).get("monthly_rent_manwon", a["rent"])
        edited = "monthly_rent_manwon" in self.overrides.get(aid, {})
        return {
            "id": aid, "listing_id": a["listing_id"], "status": a["status"],
            "error_code": None if a["status"] == "success" else "AI_FORMAT_ERROR",
            "fields": {"monthly_rent_manwon": {"ai_value": a["rent"], "user_value": rent if edited else None,
                                               "value": rent, "edited": edited}},
            "rating": self.ratings.get(aid),
        }

    # ---------------------------------------------------------------- 처리기
    def __call__(self, request: httpx.Request) -> httpx.Response:
        method, path = request.method, request.url.path
        self.calls.append((method, path))
        body = json.loads(request.content) if request.content else None
        token = self._token(request)

        if path == "/health":
            if self.health_failures > 0:
                self.health_failures -= 1
                raise httpx.ConnectError("잠듦", request=request)
            return self._json(200, {"status": "ok"})
        if path == "/ready":
            return self._json(*self.ready)
        if path == "/auth/login":
            if body["email"] == ENV["SMOKE_ADMIN_EMAIL"]:
                return self._json(200, {"access_token": ADMIN_TOKEN, "refresh_token": "r", "expires_at": 1,
                                        "profile": {"id": "p-admin", "nickname": "운영자", "role": self.admin_role}})
            return self._json(200, {"access_token": USER_TOKEN, "refresh_token": "r", "expires_at": 1,
                                    "profile": {"id": "p-user", "nickname": "사용자", "role": "user"}})
        if path == "/me":
            assert token == USER_TOKEN
            return self._json(200, {"id": "p-user", "nickname": "사용자", "role": "user"}, rid=ME_REQUEST_ID)
        if path.startswith("/admin/"):
            if token != ADMIN_TOKEN:
                return self._error(403, "FORBIDDEN")
            return self._admin(request, path)

        assert token == USER_TOKEN, f"{method} {path}에 사용자 토큰이 없음"
        parts = path.strip("/").split("/")
        if method == "POST" and path == "/sessions":
            sid = str(uuid.uuid4())
            self.sessions[sid] = {"id": sid, "title": body["title"], "visit_date": body["visit_date"],
                                  "created_at": "2026-10-14T00:00:00Z", "listing_count": 0}
            return self._json(201, self.sessions[sid])
        if method == "DELETE" and parts[0] == "sessions":
            self.deleted.append(parts[1])
            return self._json(200, {"ok": True})
        if method == "POST" and parts[0] == "sessions" and parts[2] == "listings":
            no = sum(1 for l in self.listings.values() if l["session_id"] == parts[1]) + 1
            lid = str(uuid.uuid4())
            self.listings[lid] = {"id": lid, "session_id": parts[1], "listing_no": no, "label": f"{no}번 집",
                                  "memo_text": body["memo_text"]}
            return self._json(200, self.listings[lid])
        if method == "POST" and parts[0] == "listings" and parts[2] == "analyses":
            if self.analysis_429_times > 0:
                self.analysis_429_times -= 1
                return self._error(429, "AI_RATE_LIMITED")
            aid = str(uuid.uuid4())
            no = self.listings[parts[1]]["listing_no"]
            self.analyses[aid] = {"listing_id": parts[1], "status": self.analysis_status, "rent": 40 + no}
            rid = str(uuid.uuid4())
            self.analysis_request_ids.append(rid)
            return self._json(200, self._analysis_out(aid), rid=rid)
        if method == "GET" and parts[0] == "listings" and parts[2:] == ["analyses", "latest"]:
            aid = next(a for a, v in reversed(list(self.analyses.items())) if v["listing_id"] == parts[1])
            return self._json(200, self._analysis_out(aid))
        if method == "POST" and parts[0] == "analyses" and parts[2] == "feedback":
            aid = parts[1]
            if body.get("field_name") and self.apply_edit:
                self.overrides.setdefault(aid, {})[body["field_name"]] = body["corrected_value"]
            if body.get("rating"):
                self.ratings[aid] = body["rating"]
            return self._json(200, {"id": str(uuid.uuid4()), "analysis_id": aid, **body,
                                    "created_at": "2026-10-14T00:00:00Z"})
        if method == "GET" and parts[0] == "sessions" and parts[2] == "comparison":
            rows = []
            for lid, l in self.listings.items():
                if l["session_id"] != parts[1]:
                    continue
                aid = next(a for a, v in self.analyses.items() if v["listing_id"] == lid)
                rent = self._analysis_out(aid)["fields"]["monthly_rent_manwon"]["value"]
                rows.append({"listing_id": lid, "listing_no": l["listing_no"], "label": l["label"],
                             "analysis_status": "success", "needs_reanalysis": False,
                             "values": {"monthly_rent_manwon": rent}, "columns": {}})
            return self._json(200, {"session_id": parts[1], "enough_listings": len(rows) >= 2, "rows": rows,
                                    "fields": [], "providers": [], "lowest": {}, "hidden_count": {}})
        return self._error(404, "NOT_FOUND")

    def _admin(self, request, path):
        if path == "/admin/logs":
            self._log_calls += 1
            rows = [{"id": 1, "request_id": str(uuid.uuid4()), "endpoint": "/me", "method": "GET",
                     "status_code": 200, "latency_ms": 5, "created_at": "2026-10-14T00:00:00Z"}]
            if self.log_present and self._log_calls > self.log_visible_after and self.analysis_request_ids:
                rows.insert(0, {"id": 2, "request_id": self.analysis_request_ids[0],
                                "endpoint": "/listings/{listing_id}/analyses", "method": "POST",
                                "status_code": 200, "latency_ms": 900, "ai_latency_ms": 812,
                                "created_at": "2026-10-14T00:00:01Z"})
            return self._json(200, rows)
        if path == "/admin/logs/stream":
            if self.stream_status != 200:
                return self._error(self.stream_status, "KV_UNAVAILABLE")
            chunks = [": keep-alive\n\n",
                      "event: log\ndata: " + json.dumps({"request_id": "rid-other", "endpoint": "/sessions"}) + "\n\n"]
            if self.stream_has_event:
                chunks.append("event: log\nid: 7\ndata: " + json.dumps({"request_id": ME_REQUEST_ID,
                                                                       "endpoint": "/me"}) + "\n\n")
            return httpx.Response(200, content="".join(chunks).encode(),
                                  headers={"content-type": "text/event-stream"})
        return self._error(404, "NOT_FOUND")


def make_runner(api: FakeApi, *, out=None, env=None):
    config, missing = smoke.Config.from_env(env or ENV)
    assert not missing
    lines = out if out is not None else []
    return smoke.SmokeTest(config, transport=httpx.MockTransport(api), sleep=lambda s: None,
                           out=lines.append), lines


def statuses(runner):
    return {r.name: r.status for r in runner.results}


# -------------------------------------------------------------------- 전체 흐름
def test_deploy_full_flow_passes_and_cleans_up():
    api = FakeApi()
    runner, lines = make_runner(api)
    assert runner.run() == 0
    assert all(r.status == smoke.PASS for r in runner.results), lines
    assert len(runner.results) == 12
    assert api.deleted == [runner.session_id]
    assert lines[-1].startswith("== 결과: 통과 12")
    # 각 줄에 상태와 걸린 시간이 찍힌다
    assert any(l.startswith("[PASS]  6. 메모 분석 2건 (") and "s)" in l for l in lines)


def test_deploy_output_has_no_secrets_or_memo_text():
    api = FakeApi()
    runner, lines = make_runner(api)
    runner.run()
    text = "\n".join(lines)
    for secret in (USER_TOKEN, ADMIN_TOKEN, ENV["SMOKE_USER_PASSWORD"], ENV["SMOKE_ADMIN_PASSWORD"]):
        assert secret not in text
    for memo in smoke.SAMPLE_MEMOS:
        assert memo[:20] not in text


# -------------------------------------------------------------------- /health
def test_deploy_health_waits_for_sleeping_server():
    api = FakeApi()
    api.health_failures = 3
    runner, _ = make_runner(api)
    assert runner.step_health() == "4번째 시도에 응답"


def test_deploy_health_gives_up_after_first_wait():
    api = FakeApi()
    api.health_failures = 10_000
    runner, _ = make_runner(api)
    now = [0.0]
    runner.clock = lambda: now[0]
    runner.sleep = lambda s: now.__setitem__(0, now[0] + s)
    with pytest.raises(smoke.StepFailed, match="90초 안에 200 응답 없음"):
        runner.step_health()
    assert now[0] >= 90


# -------------------------------------------------------------------- /ready
def test_deploy_ready_db_false_fails_and_stops():
    api = FakeApi()
    api.ready = (503, {"db": False, "redis": True})
    runner, lines = make_runner(api)
    assert runner.run() == 1
    st = statuses(runner)
    assert st["준비 상태 /ready"] == smoke.FAIL
    assert st["로그인(테스트 계정)"] == smoke.SKIP
    assert st["테스트 세션 삭제"] == smoke.SKIP          # 만든 세션이 없다
    assert ("POST", "/auth/login") not in api.calls
    assert any("DB 연결 실패" in l for l in lines)


def test_deploy_ready_db_false_even_with_200_fails():
    api = FakeApi()
    api.ready = (200, {"db": False, "redis": True})
    runner, _ = make_runner(api)
    with pytest.raises(smoke.StepFailed, match="db=false"):
        runner.step_ready()


def test_deploy_ready_redis_false_warns_and_continues():
    api = FakeApi()
    api.ready = (200, {"db": True, "redis": False})
    runner, lines = make_runner(api)
    assert runner.run() == 0                               # 경고는 실패가 아니다
    st = statuses(runner)
    assert st["준비 상태 /ready"] == smoke.WARN
    assert st["실시간 로그 스트림(Pub/Sub)"] == smoke.WARN   # Redis 없으면 스트림 확인은 건너뜀
    assert st["메모 분석 2건"] == smoke.PASS
    assert ("GET", "/admin/logs/stream") not in api.calls
    assert any(l.startswith("[WARN]  2.") and "redis=false" in l for l in lines)


# -------------------------------------------------------------------- 분석·수정·비교
def test_deploy_analysis_failure_skips_rest_but_deletes_session():
    api = FakeApi()
    api.analysis_status = "failed"
    runner, _ = make_runner(api)
    assert runner.run() == 1
    st = statuses(runner)
    assert st["메모 분석 2건"] == smoke.FAIL
    assert st["비교표 조회"] == smoke.SKIP
    assert st["테스트 세션 삭제"] == smoke.PASS
    assert api.deleted == [runner.session_id]


def test_deploy_analysis_retries_rate_limit():
    api = FakeApi()
    api.analysis_429_times = 2
    runner, _ = make_runner(api)
    assert runner.run() == 0
    assert sum(1 for c in api.calls if c[0] == "POST" and c[1].endswith("/analyses")) == 4


def test_deploy_edit_not_applied_fails():
    api = FakeApi()
    api.apply_edit = False
    runner, _ = make_runner(api)
    assert runner.run() == 1
    assert statuses(runner)["필드 수정 + 비추천(down) 평가"] == smoke.FAIL


def test_deploy_edit_uses_ai_value_plus_one():
    api = FakeApi()
    runner, _ = make_runner(api)
    runner.run()
    aid = next(iter(api.analyses))
    assert api.overrides[aid]["monthly_rent_manwon"] == 42      # AI 값 41 + 1
    assert api.ratings[aid] == "down"


# -------------------------------------------------------------------- 운영 로그
def test_deploy_admin_logs_waits_until_row_saved():
    api = FakeApi()
    api.log_visible_after = 2           # 로그 저장이 응답보다 늦는 경우
    runner, _ = make_runner(api)
    assert runner.run() == 0
    assert sum(1 for c in api.calls if c == ("GET", "/admin/logs")) == 3


def test_deploy_admin_logs_missing_request_id_fails():
    api = FakeApi()
    api.log_present = False
    runner, lines = make_runner(api)
    now = [0.0]
    runner.clock = lambda: now[0]
    runner.sleep = lambda s: now.__setitem__(0, now[0] + s)
    assert runner.run() == 1
    assert statuses(runner)["운영 로그에서 분석 요청 찾기"] == smoke.FAIL
    assert any("X-Request-ID=" in l and "없음" in l for l in lines)


def test_deploy_admin_role_required():
    api = FakeApi()
    api.admin_role = "user"
    runner, _ = make_runner(api)
    assert runner.run() == 1
    assert statuses(runner)["운영자 로그인"] == smoke.FAIL


# -------------------------------------------------------------------- 실시간 스트림
def test_deploy_stream_without_matching_event_fails():
    api = FakeApi()
    api.stream_has_event = False
    runner, _ = make_runner(api)
    assert runner.run() == 1
    assert statuses(runner)["실시간 로그 스트림(Pub/Sub)"] == smoke.FAIL
    assert api.deleted == [runner.session_id]


def test_deploy_stream_error_status_fails():
    api = FakeApi()
    api.stream_status = 503
    runner, lines = make_runner(api)
    assert runner.run() == 1
    assert any("스트림 연결 실패" in l and "KV_UNAVAILABLE" in l for l in lines)


def test_deploy_iter_sse_parses_events_and_skips_comments():
    lines = [": ping", "", "event: log", "id: 3", 'data: {"request_id": "a"}', "", "data: 평문", ""]
    events = list(smoke.iter_sse(lines))
    assert events == [{"event": "log", "data": {"request_id": "a"}, "id": "3"},
                      {"event": "message", "data": "평문", "id": None}]


# -------------------------------------------------------------------- 입력
def test_deploy_missing_env_exits_2(capsys):
    assert smoke.main(env={"API_BASE_URL": "https://x.test"}) == 2
    out = capsys.readouterr().out
    assert "SMOKE_USER_EMAIL" in out and "SMOKE_ADMIN_PASSWORD" in out


def test_deploy_main_runs_with_transport(capsys):
    api = FakeApi()
    assert smoke.main(env=ENV, transport=httpx.MockTransport(api), sleep=lambda s: None) == 0
    assert "== 결과: 통과 12" in capsys.readouterr().out


def test_deploy_describe_error_uses_contract_shape():
    r = httpx.Response(429, json={"error": {"code": "AI_RATE_LIMITED", "message": "잠시 후 다시"}},
                       headers={"x-request-id": "rid-1"})
    assert smoke.describe_error(r) == "HTTP 429 AI_RATE_LIMITED — 잠시 후 다시 (request_id=rid-1)"
