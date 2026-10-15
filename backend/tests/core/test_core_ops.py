"""/health, /ready, 요청 로그 미들웨어, 오류 형식."""

from fastapi import Request
from fastapi.testclient import TestClient

from app.core.errors import AppError
from app.core.request_log import set_log_fields


def test_core_health_ok_without_db_or_redis(monkeypatch):
    from app.core import config, db, kv
    from app.main import create_app

    monkeypatch.setattr(config.settings, "SUPABASE_URL", None)
    monkeypatch.setattr(config.settings, "REDIS_URL", None)
    monkeypatch.setattr(db, "_admin_db", None)
    monkeypatch.setattr(kv, "_redis_kv", None)
    c = TestClient(create_app())
    r = c.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    # 설정이 전혀 없으면 /ready는 db false → 503
    r = c.get("/ready")
    assert r.status_code == 503 and r.json() == {"db": False, "redis": False}


def test_core_ready_db_failure_is_503(client_as, memory_db):
    memory_db.fail_all = True
    r = client_as(None).get("/ready")
    assert r.status_code == 503
    assert r.json() == {"db": False, "redis": True}


def test_core_ready_redis_only_failure_is_200(client_as, memory_kv):
    memory_kv.available = False
    r = client_as(None).get("/ready")
    assert r.status_code == 200
    assert r.json() == {"db": True, "redis": False}


def test_core_middleware_saves_request_log_and_publishes(client_as, make_user, memory_db, memory_broker):
    alice = make_user()
    r = client_as(alice).get("/me")
    assert r.status_code == 200
    rid = r.headers["X-Request-ID"]
    logs = memory_db.select("request_logs")
    assert len(logs) == 1
    row = logs[0]
    assert row["request_id"] == rid
    assert row["profile_id"] == alice.profile_id
    assert row["endpoint"] == "/me" and row["method"] == "GET" and row["status_code"] == 200
    assert isinstance(row["latency_ms"], int)
    assert memory_broker.published and memory_broker.published[-1]["id"] == row["id"]


def test_core_middleware_skips_health_ready(client_as, memory_db, memory_broker):
    c = client_as(None)
    c.get("/health")
    c.get("/ready")
    assert memory_db.select("request_logs") == []
    assert memory_broker.published == []


def test_core_middleware_records_error_code_and_route_template(client_as, make_user, memory_db):
    c = client_as(make_user())

    def boom(item_id: str, request: Request):
        set_log_fields(request, ai_latency_ms=321, prompt_version="v9", cache_hit=True, error_code="FMT")
        raise AppError(502, "AI_FORMAT_ERROR", "형식 오류")

    c.app.add_api_route("/_t/items/{item_id}", boom, methods=["POST"])
    r = c.post("/_t/items/abc")
    assert r.status_code == 502
    body = r.json()["error"]
    assert body["code"] == "AI_FORMAT_ERROR"
    assert body["detail"]["request_id"] == r.headers["X-Request-ID"]
    row = memory_db.select("request_logs")[-1]
    assert row["endpoint"] == "/_t/items/{item_id}"
    assert (row["error_code"], row["ai_latency_ms"], row["prompt_version"], row["cache_hit"]) == ("FMT", 321, "v9", True)


def test_core_app_error_code_is_logged_by_default(client_as, memory_db):
    r = client_as(None).get("/me")       # 토큰 없음
    assert r.status_code == 401
    assert memory_db.select("request_logs")[-1]["error_code"] == "AUTH_REQUIRED"


def test_core_unhandled_exception_is_500_internal_error(client_as, memory_db, caplog):
    c = client_as(None)

    def crash():
        raise RuntimeError("비밀 메모 원문")

    c.app.add_api_route("/_t/crash", crash)
    r = c.get("/_t/crash")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "INTERNAL_ERROR"
    assert r.headers.get("X-Request-ID")
    row = memory_db.select("request_logs")[-1]
    assert row["status_code"] == 500 and row["error_code"] == "INTERNAL_ERROR"
    assert "비밀 메모 원문" not in caplog.text          # 예외 메시지를 로그에 남기지 않는다


def test_core_log_store_failure_does_not_block_response(client_as, memory_db, memory_broker):
    c = client_as(None)
    c.app.add_api_route("/_t/ok", lambda: {"ok": True})
    memory_db.fail_all = True
    r = c.get("/_t/ok")
    assert r.status_code == 200
    assert memory_broker.published[-1]["endpoint"] == "/_t/ok"   # 저장 실패해도 발행은 한다


def test_core_validation_error_does_not_echo_input(client_as, make_user):
    c = client_as(None)
    r = c.post("/auth/login", json={"email": "not-an-email", "password": "비밀번호원문"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "비밀번호원문" not in r.text and "not-an-email" not in r.text
