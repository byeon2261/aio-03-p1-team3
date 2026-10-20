"""F3 메모 초안(KV) API."""

from __future__ import annotations

import datetime as dt
import json
import uuid

from app.core.config import settings
from app.core.schemas import MEMO_MAX_CHARS
from app.features.drafts.store import DRAFT_META_TTL_SEC, listing_draft_key, meta_key, new_draft_key
from tests.sessions.helpers import create_listing, create_session, error_code, p1_client


def _t(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


# ------------------------------------------------------------------ 인증·소유
def test_drafts_requires_token(client_as):
    c = p1_client(client_as, None)
    lid, sid = str(uuid.uuid4()), str(uuid.uuid4())
    r = c.get(f"/listings/{lid}/draft")
    assert r.status_code == 401 and error_code(r) == "AUTH_REQUIRED"
    assert c.put(f"/listings/{lid}/draft", json={"memo_text": "x"}).status_code == 401
    assert c.get(f"/sessions/{sid}/draft").status_code == 401
    assert c.put(f"/sessions/{sid}/draft", json={"memo_text": "x"}).status_code == 401
    assert c.delete(f"/sessions/{sid}/draft").status_code == 401


def test_drafts_other_users_resources_are_404(client_as, make_user, memory_kv):
    alice, bob = make_user(), make_user()
    cb = p1_client(client_as, bob)
    bs = create_session(cb)
    bl = create_listing(cb, bs["id"])
    assert cb.put(f"/listings/{bl['id']}/draft", json={"memo_text": "밥의 초안"}).status_code == 200

    ca = p1_client(client_as, alice)
    for r in (ca.get(f"/listings/{bl['id']}/draft"),
              ca.put(f"/listings/{bl['id']}/draft", json={"memo_text": "덮어쓰기"})):
        assert r.status_code == 404 and error_code(r) == "LISTING_NOT_FOUND"
    for r in (ca.get(f"/sessions/{bs['id']}/draft"),
              ca.put(f"/sessions/{bs['id']}/draft", json={"memo_text": "x"}),
              ca.delete(f"/sessions/{bs['id']}/draft")):
        assert r.status_code == 404 and error_code(r) == "SESSION_NOT_FOUND"
    assert cb.get(f"/listings/{bl['id']}/draft").json()["memo_text"] == "밥의 초안"


# ------------------------------------------------------------------ 저장·복원
def test_drafts_listing_draft_roundtrip(client_as, make_user, memory_kv):
    alice = make_user()
    c = p1_client(client_as, alice)
    s = create_session(c)
    lst = create_listing(c, s["id"], "원래 메모")

    r = c.put(f"/listings/{lst['id']}/draft", json={"memo_text": "고치는 중인 메모"})
    assert r.status_code == 200
    saved = r.json()
    assert saved["memo_text"] == "고치는 중인 메모"
    assert _t(saved["expires_at"]) - _t(saved["saved_at"]) == dt.timedelta(seconds=settings.DRAFT_TTL_SEC)

    # 새로고침(다시 들어옴) 후 복원
    got = c.get(f"/listings/{lst['id']}/draft")
    assert got.status_code == 200 and got.json() == saved

    # 키 모양·TTL
    key = listing_draft_key(alice.auth_user_id, lst["id"])
    assert key == f"draft:{alice.auth_user_id}:{lst['id']}"
    stored = json.loads(memory_kv.get(key))
    assert stored["text"] == "고치는 중인 메모" and "saved_at" in stored
    assert memory_kv.ttl(key) == settings.DRAFT_TTL_SEC
    assert memory_kv.ttl(meta_key(key)) == DRAFT_META_TTL_SEC == 7 * 24 * 3600

    # 초안은 정식 메모를 바꾸지 않는다
    assert c.get(f"/listings/{lst['id']}").json()["memo_text"] == "원래 메모"


def test_drafts_new_memo_draft_roundtrip_and_delete(client_as, make_user, memory_kv):
    alice = make_user()
    c = p1_client(client_as, alice)
    s = create_session(c)
    r = c.put(f"/sessions/{s['id']}/draft", json={"memo_text": "새 집 메모 쓰는 중"})
    assert r.status_code == 200
    key = new_draft_key(alice.auth_user_id, s["id"])
    assert key == f"draft:{alice.auth_user_id}:new:{s['id']}"
    assert memory_kv.ttl(key) == settings.DRAFT_TTL_SEC

    got = c.get(f"/sessions/{s['id']}/draft")
    assert got.status_code == 200 and got.json()["memo_text"] == "새 집 메모 쓰는 중"

    d = c.delete(f"/sessions/{s['id']}/draft")
    assert d.status_code == 200 and d.json() == {"ok": True}
    r = c.get(f"/sessions/{s['id']}/draft")
    assert r.status_code == 404 and error_code(r) == "DRAFT_NOT_FOUND"   # 버린 초안은 '만료'가 아니다


def test_drafts_overwrite_keeps_latest(client_as, make_user):
    c = p1_client(client_as, make_user())
    s = create_session(c)
    c.put(f"/sessions/{s['id']}/draft", json={"memo_text": "첫 번째"})
    c.put(f"/sessions/{s['id']}/draft", json={"memo_text": "두 번째"})
    assert c.get(f"/sessions/{s['id']}/draft").json()["memo_text"] == "두 번째"


def test_drafts_empty_text_allowed_too_long_422(client_as, make_user):
    c = p1_client(client_as, make_user())
    s = create_session(c)
    assert c.put(f"/sessions/{s['id']}/draft", json={"memo_text": ""}).status_code == 200
    r = c.put(f"/sessions/{s['id']}/draft", json={"memo_text": "가" * (MEMO_MAX_CHARS + 1)})
    assert r.status_code == 422 and error_code(r) == "VALIDATION_ERROR"


# ------------------------------------------------------------------ 만료·기록 없음
def test_drafts_not_found_when_never_saved(client_as, make_user):
    c = p1_client(client_as, make_user())
    s = create_session(c)
    lst = create_listing(c, s["id"])
    r = c.get(f"/listings/{lst['id']}/draft")
    assert r.status_code == 404 and error_code(r) == "DRAFT_NOT_FOUND"
    r = c.get(f"/sessions/{s['id']}/draft")
    assert r.status_code == 404 and error_code(r) == "DRAFT_NOT_FOUND"


def test_drafts_expired_returns_410_then_404(client_as, make_user, memory_kv):
    alice = make_user()
    c = p1_client(client_as, alice)
    s = create_session(c)
    lst = create_listing(c, s["id"])
    saved = c.put(f"/listings/{lst['id']}/draft", json={"memo_text": "곧 만료"}).json()
    c.put(f"/sessions/{s['id']}/draft", json={"memo_text": "곧 만료"})

    memory_kv.advance(settings.DRAFT_TTL_SEC - 1)
    assert c.get(f"/listings/{lst['id']}/draft").status_code == 200   # 아직 살아 있음

    memory_kv.advance(2)                                               # 24시간 지남
    key = listing_draft_key(alice.auth_user_id, lst["id"])
    assert not memory_kv.exists(key) and memory_kv.exists(meta_key(key))
    r = c.get(f"/listings/{lst['id']}/draft")
    assert r.status_code == 410 and error_code(r) == "DRAFT_EXPIRED"
    assert _t(r.json()["error"]["detail"]["saved_at"]) == _t(saved["saved_at"])   # 마지막 저장 시각 안내용
    assert "곧 만료" not in r.text                                      # 원문은 담지 않는다
    r = c.get(f"/sessions/{s['id']}/draft")
    assert r.status_code == 410 and error_code(r) == "DRAFT_EXPIRED"

    memory_kv.advance(DRAFT_META_TTL_SEC)                              # 기록(7일)도 지남
    r = c.get(f"/listings/{lst['id']}/draft")
    assert r.status_code == 404 and error_code(r) == "DRAFT_NOT_FOUND"


def test_drafts_resave_after_expiry_works(client_as, make_user, memory_kv):
    c = p1_client(client_as, make_user())
    s = create_session(c)
    c.put(f"/sessions/{s['id']}/draft", json={"memo_text": "옛 초안"})
    memory_kv.advance(settings.DRAFT_TTL_SEC + 1)
    assert c.get(f"/sessions/{s['id']}/draft").status_code == 410
    c.put(f"/sessions/{s['id']}/draft", json={"memo_text": "새 초안"})
    got = c.get(f"/sessions/{s['id']}/draft")
    assert got.status_code == 200 and got.json()["memo_text"] == "새 초안"


# ------------------------------------------------------------------ 정식 저장 뒤 초안 삭제
def test_drafts_cleared_after_listing_create(client_as, make_user, memory_kv):
    alice = make_user()
    c = p1_client(client_as, alice)
    s = create_session(c)
    c.put(f"/sessions/{s['id']}/draft", json={"memo_text": "새 집 메모"})
    create_listing(c, s["id"], "새 집 메모")
    key = new_draft_key(alice.auth_user_id, s["id"])
    assert not memory_kv.exists(key) and not memory_kv.exists(meta_key(key))
    r = c.get(f"/sessions/{s['id']}/draft")
    assert r.status_code == 404 and error_code(r) == "DRAFT_NOT_FOUND"


def test_drafts_cleared_after_listing_patch(client_as, make_user, memory_kv):
    alice = make_user()
    c = p1_client(client_as, alice)
    s = create_session(c)
    lst = create_listing(c, s["id"], "원래")
    c.put(f"/listings/{lst['id']}/draft", json={"memo_text": "고친 메모"})
    assert c.patch(f"/listings/{lst['id']}", json={"memo_text": "고친 메모"}).status_code == 200
    key = listing_draft_key(alice.auth_user_id, lst["id"])
    assert not memory_kv.exists(key) and not memory_kv.exists(meta_key(key))
    r = c.get(f"/listings/{lst['id']}/draft")
    assert r.status_code == 404 and error_code(r) == "DRAFT_NOT_FOUND"


def test_drafts_failed_save_keeps_draft(client_as, make_user, memory_kv):
    c = p1_client(client_as, make_user())
    s = create_session(c)
    lst = create_listing(c, s["id"], "원래")
    c.put(f"/listings/{lst['id']}/draft", json={"memo_text": "고치는 중"})
    assert c.patch(f"/listings/{lst['id']}", json={"memo_text": " "}).status_code == 422
    assert c.get(f"/listings/{lst['id']}/draft").json()["memo_text"] == "고치는 중"


def test_drafts_are_per_user(client_as, make_user, memory_kv):
    alice, bob = make_user(), make_user()
    ca, cb = p1_client(client_as, alice), p1_client(client_as, bob)
    sa, sb = create_session(ca), create_session(cb)
    ca.put(f"/sessions/{sa['id']}/draft", json={"memo_text": "앨리스"})
    cb.put(f"/sessions/{sb['id']}/draft", json={"memo_text": "밥"})
    assert ca.get(f"/sessions/{sa['id']}/draft").json()["memo_text"] == "앨리스"
    assert cb.get(f"/sessions/{sb['id']}/draft").json()["memo_text"] == "밥"


# ------------------------------------------------------------------ KV 장애
def test_drafts_kv_unavailable_503(client_as, make_user, memory_kv):
    c = p1_client(client_as, make_user())
    s = create_session(c)
    lst = create_listing(c, s["id"])
    memory_kv.available = False
    for r in (c.get(f"/listings/{lst['id']}/draft"),
              c.put(f"/listings/{lst['id']}/draft", json={"memo_text": "x"}),
              c.get(f"/sessions/{s['id']}/draft"),
              c.put(f"/sessions/{s['id']}/draft", json={"memo_text": "x"}),
              c.delete(f"/sessions/{s['id']}/draft")):
        assert r.status_code == 503 and error_code(r) == "KV_UNAVAILABLE"
    # 메모 저장은 그대로 동작
    assert c.post(f"/sessions/{s['id']}/listings", json={"name": "1번방", "memo_text": "저장"}).status_code == 200
