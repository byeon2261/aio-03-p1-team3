"""GET /admin/logs·/admin/logs/stream·/admin/metrics·/admin/feedback 권한과 로그 조회 필터."""

from __future__ import annotations

import pytest

from app.core import broker
from tests.admin_logs.helpers import add_analysis_request, add_log, at

ADMIN_PATHS = ["/admin/logs", "/admin/logs/stream", "/admin/metrics", "/admin/feedback"]


@pytest.mark.parametrize("path", ADMIN_PATHS)
def test_admin_logs_regular_user_gets_403(client_as, make_user, path):
    r = client_as(make_user()).get(path)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.parametrize("path", ADMIN_PATHS)
def test_admin_logs_anonymous_gets_401(client_as, path):
    r = client_as(None).get(path)
    assert r.status_code == 401


def test_admin_logs_list_latest_first_and_masked(client_as, make_user, memory_db):
    admin, alice = make_user("admin"), make_user()
    first = add_log(memory_db, profile_id=alice.profile_id, created_at=at(0))
    second = add_log(memory_db, endpoint="/sessions/{session_id}", created_at=at(1))
    r = client_as(admin).get("/admin/logs")
    assert r.status_code == 200
    body = r.json()
    assert [x["id"] for x in body] == [second["id"], first["id"]]
    assert body[1]["profile_id"] == alice.profile_id[:4] + "****"
    assert alice.profile_id not in r.text


def test_admin_logs_excludes_admin_requests_by_default(client_as, make_user, memory_db):
    admin = make_user("admin")
    add_log(memory_db, endpoint="/admin/metrics", created_at=at(0))
    user_req = add_log(memory_db, endpoint="/sessions", created_at=at(1))
    c = client_as(admin)
    default = c.get("/admin/logs").json()
    assert [x["id"] for x in default] == [user_req["id"]]
    included = c.get("/admin/logs", params={"include_admin": "true"}).json()
    assert any(x["endpoint"].startswith("/admin") for x in included)


def test_admin_logs_filter_period_status_version(client_as, make_user, memory_db):
    admin = make_user("admin")
    add_log(memory_db, created_at=at(0))                                        # 기간 밖(이전)
    ok = add_analysis_request(memory_db, created_at=at(10), prompt_version="v1")
    bad = add_analysis_request(memory_db, created_at=at(20), status_code=502, error_code="AI_FORMAT_ERROR",
                               prompt_version="v2")
    nf = add_log(memory_db, status_code=404, error_code="LISTING_NOT_FOUND", created_at=at(30))
    add_log(memory_db, created_at=at(60))                                       # 기간 밖(이후)
    c = client_as(admin)
    period = {"from": at(5).isoformat(), "to": at(40).isoformat()}

    ids = [x["id"] for x in c.get("/admin/logs", params=period).json()]
    assert ids == [nf["id"], bad["id"], ok["id"]]

    errors = c.get("/admin/logs", params={**period, "status": "error"}).json()
    assert [x["id"] for x in errors] == [nf["id"], bad["id"]]
    five = c.get("/admin/logs", params={**period, "status": "5xx"}).json()
    assert [x["id"] for x in five] == [bad["id"]]
    four = c.get("/admin/logs", params={**period, "status": "4xx"}).json()
    assert [x["id"] for x in four] == [nf["id"]]
    success = c.get("/admin/logs", params={**period, "status": "success"}).json()
    assert [x["id"] for x in success] == [ok["id"]]
    exact = c.get("/admin/logs", params={**period, "status": "404"}).json()
    assert [x["id"] for x in exact] == [nf["id"]]

    v2 = c.get("/admin/logs", params={**period, "prompt_version": "v2"}).json()
    assert [x["id"] for x in v2] == [bad["id"]]


def test_admin_logs_after_id_returns_ascending(client_as, make_user, memory_db):
    admin = make_user("admin")
    rows = [add_log(memory_db, created_at=at(i)) for i in range(5)]
    body = client_as(admin).get("/admin/logs", params={"after_id": rows[1]["id"], "limit": 2}).json()
    assert [x["id"] for x in body] == [rows[2]["id"], rows[3]["id"]]


def test_admin_logs_limit_fills_past_admin_rows(client_as, make_user, memory_db):
    """/admin 요청이 많아도 limit만큼 업무 요청을 채운다(커서로 더 가져옴)."""
    admin = make_user("admin")
    user_rows = [add_log(memory_db, created_at=at(i)) for i in range(3)]
    for i in range(10):
        add_log(memory_db, endpoint="/admin/logs", created_at=at(10 + i))
    body = client_as(admin).get("/admin/logs", params={"limit": 3}).json()
    assert [x["id"] for x in body] == [r["id"] for r in reversed(user_rows)]


def test_admin_logs_rejects_bad_status_and_reversed_period(client_as, make_user):
    c = client_as(make_user("admin"))
    r = c.get("/admin/logs", params={"status": "weird"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    r = c.get("/admin/logs", params={"from": at(10).isoformat(), "to": at(0).isoformat()})
    assert r.status_code == 422
    r = c.get("/admin/metrics", params={"from": at(10).isoformat(), "to": at(0).isoformat()})
    assert r.status_code == 422


def test_admin_logs_stream_without_broker_is_503(client_as, make_user):
    c = client_as(make_user("admin"))
    broker.use_broker(None)          # REDIS_URL 없음(테스트 환경) → 브로커 없음
    r = c.get("/admin/logs/stream")
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "KV_UNAVAILABLE"


def test_admin_logs_requests_are_logged_but_hidden(client_as, make_user, memory_db):
    """운영자 화면 요청도 R 미들웨어가 기록한다. 기본 조회에서는 빠지고 include_admin=true면 보인다."""
    c = client_as(make_user("admin"))
    c.get("/admin/metrics")
    logged = memory_db.select("request_logs", {"endpoint": "/admin/metrics"})
    assert len(logged) == 1
    assert c.get("/admin/logs").json() == []
    shown = c.get("/admin/logs", params={"include_admin": "true"}).json()
    assert any(x["endpoint"] == "/admin/metrics" for x in shown)
