"""마이페이지: 닉네임 검증·role 무시, 비밀번호 변경, 내 사진, 요약 숫자."""

from __future__ import annotations

import json

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def _err(r):
    return r.json()["error"]


def _profile(db, user):
    return db.select("profiles", {"id": user.profile_id})[0]


# ------------------------------------------------------------------ 닉네임
def test_mypage_nickname_trimmed_and_saved(client_as, make_user, memory_db):
    alice, bob = make_user(nickname="앨리스"), make_user(nickname="밥")
    c = client_as(alice)
    r = c.patch("/me", json={"nickname": "  새 닉네임  "})
    assert r.status_code == 200, r.text
    assert r.json() == {"id": alice.profile_id, "nickname": "새 닉네임", "role": "user"}
    assert _profile(memory_db, alice)["nickname"] == "새 닉네임"
    assert _profile(memory_db, bob)["nickname"] == "밥"                     # 남의 행은 그대로
    assert c.get("/me").json()["nickname"] == "새 닉네임"


def test_mypage_nickname_length_rules(client_as, make_user, memory_db):
    alice = make_user(nickname="앨리스")
    c = client_as(alice)
    assert c.patch("/me", json={"nickname": "가" * 20}).status_code == 200
    assert c.patch("/me", json={"nickname": "a"}).status_code == 200
    for bad in ("", "   ", "가" * 21, "줄\n바꿈", 123, None):
        r = c.patch("/me", json={"nickname": bad})
        assert r.status_code == 422, bad
        assert _err(r)["code"] == "VALIDATION_ERROR"
    assert c.patch("/me", json={}).status_code == 422
    assert _profile(memory_db, alice)["nickname"] == "a"


def test_mypage_nickname_ignores_role(client_as, make_user, memory_db):
    alice = make_user()
    r = client_as(alice).patch("/me", json={"nickname": "운영자인척", "role": "admin", "id": "x"})
    assert r.status_code == 200 and r.json()["role"] == "user"
    row = _profile(memory_db, alice)
    assert row["role"] == "user" and row["id"] == alice.profile_id and row["nickname"] == "운영자인척"


def test_mypage_nickname_requires_login(client_as):
    assert client_as(None).patch("/me", json={"nickname": "x"}).status_code == 401


# ------------------------------------------------------------------ 비밀번호
def _password_user(make_user, fake_auth, password="oldpass1"):
    email = "pw@example.com"
    user = make_user(email=email)
    fake_auth.add_user(email, password, auth_user_id=user.auth_user_id)
    return user, email


def test_mypage_password_wrong_current_is_401(client_as, make_user, fake_auth):
    user, email = _password_user(make_user, fake_auth)
    r = client_as(user).post("/me/password", json={"current_password": "wrong!!", "new_password": "newpass1"})
    assert r.status_code == 401 and _err(r)["code"] == "INVALID_CREDENTIALS"
    assert fake_auth.users[email]["password"] == "oldpass1"
    assert "wrong!!" not in r.text and "newpass1" not in r.text


def test_mypage_password_change_ok(client_as, make_user, fake_auth):
    user, email = _password_user(make_user, fake_auth)
    r = client_as(user).post("/me/password", json={"current_password": "oldpass1", "new_password": "newpass1"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert fake_auth.users[email]["password"] == "newpass1"
    assert len(fake_auth.signed_out) == 1                 # 확인용 세션은 바로 끝냄
    assert user.access_token not in fake_auth.signed_out  # 지금 쓰는 세션은 유지


def test_mypage_password_validation(client_as, make_user, fake_auth):
    user, email = _password_user(make_user, fake_auth)
    c = client_as(user)
    r = c.post("/me/password", json={"current_password": "oldpass1", "new_password": "12345"})   # 6자 미만
    assert r.status_code == 422 and _err(r)["code"] == "VALIDATION_ERROR"
    r = c.post("/me/password", json={"current_password": "oldpass1", "new_password": "oldpass1"})
    assert r.status_code == 422 and _err(r)["detail"]["reason"] == "same_password"
    r = c.post("/me/password", json={"new_password": "newpass1"})                                # 현재 비번 없음
    assert r.status_code == 422
    assert fake_auth.users[email]["password"] == "oldpass1"


# ------------------------------------------------------------------ 데이터 만들기
def _session(db, user, title):
    return db.insert("tour_sessions", {"profile_id": user.profile_id, "title": title})[0]


def _listing(db, session):
    return db.insert("listings", {"session_id": session["id"], "memo_text": "메모"})[0]


def _photo(c, listing_id):
    r = c.post(f"/listings/{listing_id}/photos", files={"file": ("a.jpg", JPEG, "image/jpeg")})
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ 내 사진
def test_mypage_my_photos_newest_first_with_names(client_as, make_user, memory_db):
    alice, bob = make_user(), make_user()
    s1, s2 = _session(memory_db, alice, "토요일"), _session(memory_db, alice, "일요일")
    l1, l2 = _listing(memory_db, s1), _listing(memory_db, s2)
    bob_l = _listing(memory_db, _session(memory_db, bob, "밥의 세션"))
    c = client_as(alice)
    p1 = _photo(c, l1["id"])
    p2 = _photo(c, l2["id"])
    _photo(client_as(bob), bob_l["id"])

    r = c.get("/me/photos")
    assert r.status_code == 200
    body = r.json()
    assert [p["id"] for p in body] == [p2["id"], p1["id"]]                 # 최신순
    assert body[0]["session_title"] == "일요일" and body[0]["session_id"] == s2["id"]
    assert body[1]["session_title"] == "토요일" and body[1]["listing_no"] == l1["listing_no"]
    assert all(p["url"] and p["url"].startswith("https://storage.test/") for p in body)
    assert "storage_path" not in json.dumps(body) and "밥의 세션" not in r.text


def test_mypage_my_photos_empty(client_as, make_user):
    r = client_as(make_user()).get("/me/photos")
    assert r.status_code == 200 and r.json() == []


# ------------------------------------------------------------------ 요약
def test_mypage_summary_counts(client_as, make_user, memory_db):
    alice, bob = make_user(), make_user()
    sessions = [_session(memory_db, alice, f"세션{i}") for i in range(6)]
    l_a = _listing(memory_db, sessions[5])
    l_b = _listing(memory_db, sessions[5])
    l_c = _listing(memory_db, sessions[0])
    a1 = memory_db.insert("analyses", {"listing_id": l_a["id"], "status": "success"})[0]
    memory_db.insert("analyses", {"listing_id": l_a["id"], "status": "failed"})
    memory_db.insert("analyses", {"listing_id": l_c["id"], "status": "success"})
    memory_db.insert("feedback", {"analysis_id": a1["id"], "profile_id": alice.profile_id, "rating": "up"})
    c = client_as(alice)
    _photo(c, l_b["id"])

    # 남의 데이터는 세지 않는다
    bs = _session(memory_db, bob, "밥")
    bl = _listing(memory_db, bs)
    ba = memory_db.insert("analyses", {"listing_id": bl["id"], "status": "success"})[0]
    memory_db.insert("feedback", {"analysis_id": ba["id"], "profile_id": bob.profile_id, "rating": "down"})
    _photo(client_as(bob), bl["id"])

    r = c.get("/me/summary")
    assert r.status_code == 200, r.text
    body = r.json()
    assert {k: body[k] for k in ("session_count", "listing_count", "analysis_count", "photo_count",
                                 "feedback_count")} == {
        "session_count": 6, "listing_count": 3, "analysis_count": 3, "photo_count": 1, "feedback_count": 1}
    recent = body["recent_sessions"]
    assert [s["title"] for s in recent] == ["세션5", "세션4", "세션3", "세션2", "세션1"]   # 최신 5개
    assert recent[0]["listing_count"] == 2 and recent[1]["listing_count"] == 0


def test_mypage_summary_empty(client_as, make_user):
    body = client_as(make_user()).get("/me/summary").json()
    assert body == {"session_count": 0, "listing_count": 0, "analysis_count": 0, "photo_count": 0,
                    "feedback_count": 0, "recent_sessions": []}
