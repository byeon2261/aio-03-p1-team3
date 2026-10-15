"""F2 집 보기 세션 API."""

from __future__ import annotations

import uuid

from app.core import events
from app.core.errors import AppError
from app.features.drafts.store import listing_draft_key, meta_key, new_draft_key
from tests.sessions.helpers import (
    create_listing,
    create_session,
    error_code,
    insert_analysis,
    insert_feedback,
    p1_client,
)


# ------------------------------------------------------------------ 인증·소유
def test_sessions_requires_token(client_as):
    c = p1_client(client_as, None)
    r = c.get("/sessions")
    assert r.status_code == 401 and error_code(r) == "AUTH_REQUIRED"
    assert c.post("/sessions", json={"title": "x"}).status_code == 401
    sid = str(uuid.uuid4())
    for method in ("get", "patch", "delete"):
        kwargs = {"json": {"title": "x"}} if method == "patch" else {}
        assert getattr(c, method)(f"/sessions/{sid}", **kwargs).status_code == 401


def test_sessions_list_only_mine(client_as, make_user, memory_db):
    alice, bob = make_user(), make_user()
    memory_db.insert("tour_sessions", {"profile_id": bob.profile_id, "title": "남의 것"})
    c = p1_client(client_as, alice)
    assert c.get("/sessions").json() == []
    mine = create_session(c, "내 세션")
    listed = c.get("/sessions").json()
    assert [s["id"] for s in listed] == [mine["id"]]


def test_sessions_other_users_session_is_404(client_as, make_user, memory_db):
    alice, bob = make_user(), make_user()
    other = memory_db.insert("tour_sessions", {"profile_id": bob.profile_id, "title": "남의 것"})[0]
    c = p1_client(client_as, alice)
    for r in (c.get(f"/sessions/{other['id']}"),
              c.patch(f"/sessions/{other['id']}", json={"title": "바꿈"}),
              c.delete(f"/sessions/{other['id']}")):
        assert r.status_code == 404 and error_code(r) == "SESSION_NOT_FOUND"
    assert memory_db.select("tour_sessions", {"id": other["id"]})[0]["title"] == "남의 것"


def test_sessions_bad_id_is_404(client_as, make_user):
    c = p1_client(client_as, make_user())
    r = c.get("/sessions/not-a-uuid")
    assert r.status_code == 404 and error_code(r) == "SESSION_NOT_FOUND"


# ------------------------------------------------------------------ 만들기·조회
def test_sessions_create_and_get(client_as, make_user):
    c = p1_client(client_as, make_user())
    s = create_session(c, "  토요일 집 보기  ", "2026-10-17")
    assert s["title"] == "토요일 집 보기"
    assert s["visit_date"] == "2026-10-17" and s["listing_count"] == 0
    got = c.get(f"/sessions/{s['id']}").json()
    assert got["id"] == s["id"] and got["title"] == "토요일 집 보기"


def test_sessions_create_without_visit_date(client_as, make_user):
    c = p1_client(client_as, make_user())
    r = c.post("/sessions", json={"title": "날짜 미정"})
    assert r.status_code == 200 and r.json()["visit_date"] is None


def test_sessions_create_blank_title_422(client_as, make_user):
    c = p1_client(client_as, make_user())
    for title in ("", "   "):
        r = c.post("/sessions", json={"title": title})
        assert r.status_code == 422 and error_code(r) == "VALIDATION_ERROR"
    assert c.get("/sessions").json() == []


def test_sessions_listing_count(client_as, make_user):
    c = p1_client(client_as, make_user())
    s1, s2 = create_session(c, "하나"), create_session(c, "둘")
    create_listing(c, s1["id"])
    create_listing(c, s1["id"])
    create_listing(c, s2["id"])
    counts = {s["id"]: s["listing_count"] for s in c.get("/sessions").json()}
    assert counts == {s1["id"]: 2, s2["id"]: 1}
    assert c.get(f"/sessions/{s1['id']}").json()["listing_count"] == 2


def test_sessions_list_newest_first(client_as, make_user):
    c = p1_client(client_as, make_user())
    old, new = create_session(c, "먼저"), create_session(c, "나중")
    assert [s["id"] for s in c.get("/sessions").json()] == [new["id"], old["id"]]


# ------------------------------------------------------------------ PATCH
def test_sessions_patch_title_only_keeps_visit_date(client_as, make_user):
    c = p1_client(client_as, make_user())
    s = create_session(c, "처음", "2026-10-17")
    r = c.patch(f"/sessions/{s['id']}", json={"title": "  바꾼 제목 "})
    assert r.status_code == 200
    assert r.json()["title"] == "바꾼 제목" and r.json()["visit_date"] == "2026-10-17"


def test_sessions_patch_visit_date_only_keeps_title(client_as, make_user):
    c = p1_client(client_as, make_user())
    s = create_session(c, "처음", "2026-10-17")
    r = c.patch(f"/sessions/{s['id']}", json={"visit_date": "2026-10-20"})
    assert r.status_code == 200
    assert r.json()["title"] == "처음" and r.json()["visit_date"] == "2026-10-20"


def test_sessions_patch_visit_date_null_clears(client_as, make_user):
    c = p1_client(client_as, make_user())
    s = create_session(c, "처음", "2026-10-17")
    r = c.patch(f"/sessions/{s['id']}", json={"visit_date": None})
    assert r.status_code == 200 and r.json()["visit_date"] is None


def test_sessions_patch_empty_body_changes_nothing(client_as, make_user):
    c = p1_client(client_as, make_user())
    s = create_session(c, "처음", "2026-10-17")
    r = c.patch(f"/sessions/{s['id']}", json={})
    assert r.status_code == 200
    assert r.json()["title"] == "처음" and r.json()["visit_date"] == "2026-10-17"


def test_sessions_patch_blank_title_422(client_as, make_user):
    c = p1_client(client_as, make_user())
    s = create_session(c, "처음")
    for body in ({"title": ""}, {"title": "   "}, {"title": None}):
        r = c.patch(f"/sessions/{s['id']}", json=body)
        assert r.status_code == 422 and error_code(r) == "VALIDATION_ERROR", body
    assert c.get(f"/sessions/{s['id']}").json()["title"] == "처음"


# ------------------------------------------------------------------ DELETE
def _seed_session_with_children(c, memory_db, user):
    s = create_session(c)
    l1 = create_listing(c, s["id"], "첫 집 메모")
    l2 = create_listing(c, s["id"], "둘째 집 메모")
    a1 = insert_analysis(memory_db, l1["id"], "첫 집 메모")
    insert_feedback(memory_db, a1["id"], user.profile_id)
    # 초안: 매물 수정 초안 + 새 메모 초안
    assert c.put(f"/listings/{l1['id']}/draft", json={"memo_text": "수정 중"}).status_code == 200
    assert c.put(f"/sessions/{s['id']}/draft", json={"memo_text": "새로 쓰는 중"}).status_code == 200
    return s, [l1, l2]


def test_sessions_delete_removes_children_drafts_and_emits(client_as, make_user, memory_db, memory_kv, memory_storage):
    alice, bob = make_user(), make_user()
    c = p1_client(client_as, alice)
    s, listings = _seed_session_with_children(c, memory_db, alice)
    keep = memory_db.insert("tour_sessions", {"profile_id": bob.profile_id, "title": "남의 것"})[0]

    calls = []

    def on_session_delete(**payload):
        calls.append(payload)

    events.on("session.before_delete", on_session_delete)
    r = c.delete(f"/sessions/{s['id']}")
    assert r.status_code == 200 and r.json() == {"ok": True}

    # 이벤트: 키워드 인자 db, user, session, listing_ids, storage(엔드포인트의 Depends(get_storage))
    assert len(calls) == 1
    assert set(calls[0]) == {"db", "user", "session", "listing_ids", "storage"}
    assert calls[0]["storage"] is memory_storage
    assert calls[0]["session"]["id"] == s["id"]
    assert sorted(calls[0]["listing_ids"]) == sorted(lst["id"] for lst in listings)
    assert calls[0]["user"].profile_id == alice.profile_id

    # 행: 세션·매물·분석·피드백 모두 삭제, 남의 세션은 그대로
    assert memory_db.select("tour_sessions", {"id": s["id"]}) == []
    assert memory_db.select("listings", {"session_id": s["id"]}) == []
    assert memory_db.select("analyses") == []
    assert memory_db.select("feedback") == []
    assert memory_db.select("tour_sessions", {"id": keep["id"]})

    # 초안 키와 draftmeta 삭제
    for key in (listing_draft_key(alice.auth_user_id, listings[0]["id"]),
                new_draft_key(alice.auth_user_id, s["id"])):
        assert not memory_kv.exists(key)
        assert not memory_kv.exists(meta_key(key))
    assert c.get(f"/sessions/{s['id']}").status_code == 404


def test_sessions_delete_handler_error_keeps_rows(client_as, make_user, memory_db, memory_kv):
    alice = make_user()
    c = p1_client(client_as, alice)
    s, listings = _seed_session_with_children(c, memory_db, alice)

    def failing_cleanup(**_):
        raise AppError(503, "CLEANUP_FAILED", "사진 정리에 실패했습니다.")

    events.on("session.before_delete", failing_cleanup)
    r = c.delete(f"/sessions/{s['id']}")
    assert r.status_code == 503 and error_code(r) == "CLEANUP_FAILED"

    # 아무것도 지우지 않았다(행·초안 그대로)
    assert memory_db.select("tour_sessions", {"id": s["id"]})
    assert len(memory_db.select("listings", {"session_id": s["id"]})) == 2
    assert len(memory_db.select("analyses")) == 1 and len(memory_db.select("feedback")) == 1
    assert memory_kv.exists(new_draft_key(alice.auth_user_id, s["id"]))

    # 처리기가 나아지면 다시 삭제할 수 있다
    events.reset_events()
    assert c.delete(f"/sessions/{s['id']}").status_code == 200
    assert memory_db.select("tour_sessions", {"id": s["id"]}) == []


def test_sessions_delete_unexpected_handler_error_keeps_rows(client_as, make_user, memory_db):
    alice = make_user()
    c = p1_client(client_as, alice)
    s = create_session(c)
    create_listing(c, s["id"])

    def broken(**_):
        raise RuntimeError("boom")

    events.on("session.before_delete", broken)
    r = c.delete(f"/sessions/{s['id']}")
    assert r.status_code == 500 and error_code(r) == "INTERNAL_ERROR"
    assert memory_db.select("tour_sessions", {"id": s["id"]})
    assert memory_db.select("listings", {"session_id": s["id"]})


def test_sessions_delete_ignores_draft_cleanup_failure(client_as, make_user, memory_db, memory_kv):
    alice = make_user()
    c = p1_client(client_as, alice)
    s = create_session(c)
    create_listing(c, s["id"])
    memory_kv.available = False
    r = c.delete(f"/sessions/{s['id']}")
    assert r.status_code == 200
    assert memory_db.select("tour_sessions", {"id": s["id"]}) == []
