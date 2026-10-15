"""MemoryDatabase·MemoryKV가 실제 DB·Redis의 규칙을 흉내 내는지."""

import pytest

from app.core.db import UniqueViolation
from tests.fakes import MemoryDatabase


@pytest.fixture
def seeded(memory_db: MemoryDatabase):
    p = memory_db.insert("profiles", {"auth_user_id": "u1", "nickname": "a"})[0]
    s = memory_db.insert("tour_sessions", {"profile_id": p["id"], "title": "토요일"})[0]
    return memory_db, p, s


def test_core_listing_no_auto_increments_and_never_reuses(seeded):
    db, _, s = seeded
    l1 = db.insert("listings", {"session_id": s["id"], "memo_text": "1"})[0]
    l2 = db.insert("listings", {"session_id": s["id"], "memo_text": "2", "listing_no": 99})[0]
    assert (l1["listing_no"], l2["listing_no"]) == (1, 2)  # 보낸 번호는 무시
    db.delete("listings", {"id": l2["id"]})                  # 마지막 번호를 지운 뒤
    l3 = db.insert("listings", {"session_id": s["id"]})[0]
    assert l3["listing_no"] == 3                             # 새 번호
    assert db.select("tour_sessions", {"id": s["id"]})[0]["last_listing_no"] == 3


def test_core_listing_no_is_per_session(seeded):
    db, p, s = seeded
    s2 = db.insert("tour_sessions", {"profile_id": p["id"], "title": "일요일"})[0]
    db.insert("listings", {"session_id": s["id"]})
    assert db.insert("listings", {"session_id": s2["id"]})[0]["listing_no"] == 1


def test_core_cascade_chain(seeded):
    db, p, s = seeded
    l = db.insert("listings", {"session_id": s["id"]})[0]
    a = db.insert("analyses", {"listing_id": l["id"], "status": "success", "memo_hash": "h",
                               "schema_version": "1", "prompt_version": "v1", "model": "m"})[0]
    db.insert("feedback", {"analysis_id": a["id"], "profile_id": p["id"], "rating": "up"})
    db.insert("photos", {"listing_id": l["id"], "profile_id": p["id"], "storage_path": "x/y/z.jpg",
                         "content_type": "image/jpeg", "size_bytes": 1})
    db.insert("session_budgets", {"session_id": s["id"], "monthly_max_manwon": 60})
    db.insert("request_logs", {"request_id": "r", "profile_id": p["id"], "endpoint": "/x", "method": "GET",
                               "status_code": 200, "latency_ms": 1})
    db.delete("profiles", {"id": p["id"]})
    for t in ("tour_sessions", "listings", "analyses", "feedback", "photos", "session_budgets"):
        assert db.select(t) == [], t
    logs = db.select("request_logs")
    assert len(logs) == 1 and logs[0]["profile_id"] is None   # 로그는 남고 profile_id만 null


def test_core_unique_constraints(seeded):
    db, p, s = seeded
    with pytest.raises(UniqueViolation):
        db.insert("profiles", {"auth_user_id": "u1"})
    db.insert("photos", {"listing_id": db.insert("listings", {"session_id": s["id"]})[0]["id"],
                         "profile_id": p["id"], "storage_path": "a", "content_type": "c", "size_bytes": 1})
    with pytest.raises(UniqueViolation):
        db.insert("photos", {"listing_id": db.select("listings")[0]["id"], "profile_id": p["id"],
                             "storage_path": "a", "content_type": "c", "size_bytes": 1})
    db.insert("session_budgets", {"session_id": s["id"]})
    with pytest.raises(UniqueViolation):
        db.insert("session_budgets", {"session_id": s["id"]})
    db.insert("eval_cases", {"case_key": "k1", "memo_text": "m", "expected_json": {}})
    with pytest.raises(UniqueViolation):
        db.insert("eval_cases", {"case_key": "k1", "memo_text": "m", "expected_json": {}})


def test_core_trigger_columns_cannot_be_updated(seeded):
    db, _, s = seeded
    l = db.insert("listings", {"session_id": s["id"], "memo_text": "a"})[0]
    with pytest.raises(PermissionError):
        db.update("tour_sessions", {"id": s["id"]}, {"last_listing_no": 0})
    with pytest.raises(PermissionError):
        db.update("listings", {"id": l["id"]}, {"memo_updated_at": "2020-01-01T00:00:00+00:00"})
    before = l["memo_updated_at"]
    after = db.update("listings", {"id": l["id"]}, {"memo_text": "b"})[0]["memo_updated_at"]
    assert after > before


def test_core_filters_and_order(seeded):
    db, p, _ = seeded
    for i in range(3):
        db.insert("request_logs", {"request_id": str(i), "endpoint": "/x", "method": "GET",
                                   "status_code": 200 + i, "latency_ms": i})
    rows = db.select("request_logs", {"status_code": ("gte", 201)}, order_by="id", desc=True)
    assert [r["status_code"] for r in rows] == [202, 201]
    assert len(db.select("request_logs", {"request_id": ["0", "2"]})) == 2
    assert db.select("request_logs", {"request_id": []}) == []
    assert len(db.select("request_logs", {"error_code": ("is", None)}, limit=2)) == 2
    first = db.select("request_logs", order_by="created_at")[0]
    assert len(db.select("request_logs", {"created_at": ("gt", first["created_at"])})) == 2


def test_core_memory_kv_ttl_and_outage(memory_kv):
    from app.core.errors import AppError

    memory_kv.set("k", "v", 10)
    assert memory_kv.get("k") == "v" and memory_kv.exists("k")
    memory_kv.advance(9)
    assert memory_kv.get("k") == "v"
    memory_kv.advance(1)
    assert memory_kv.get("k") is None
    memory_kv.available = False
    with pytest.raises(AppError) as e:
        memory_kv.get("k")
    assert e.value.code == "KV_UNAVAILABLE"
