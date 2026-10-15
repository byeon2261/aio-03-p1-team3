"""F1 인증: 401·403·가입·로그인·갱신·로그아웃."""

from fastapi import Depends

from app.core.auth import require_admin


def test_auth_no_token_is_401(client_as):
    r = client_as(None).get("/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "AUTH_REQUIRED"


def test_auth_invalid_token_is_401(client_as):
    r = client_as(None).get("/me", headers={"Authorization": "Bearer forged"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "AUTH_REQUIRED"


def test_auth_valid_token_returns_me(client_as, make_user):
    alice = make_user(nickname="앨리스")
    # client_as(None) + 헤더: get_current_user를 바꾸지 않고 실제 검증 경로를 탄다
    r = client_as(None).get("/me", headers={"Authorization": f"Bearer {alice.access_token}"})
    assert r.status_code == 200
    assert r.json() == {"id": alice.profile_id, "nickname": "앨리스", "role": "user"}


def test_auth_profile_created_when_missing(client_as, fake_auth, memory_db):
    token = fake_auth.issue_token("auth-only-user", "newbie@example.com")
    r = client_as(None).get("/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and r.json()["nickname"] == "newbie"
    assert len(memory_db.select("profiles", {"auth_user_id": "auth-only-user"})) == 1


def test_auth_non_admin_is_403(client_as, make_user):
    def admin_only():
        return {"ok": True}

    for user, expected in ((make_user(), 403), (make_user(role="admin"), 200)):
        c = client_as(user)
        c.app.add_api_route("/_t/admin", admin_only, dependencies=[Depends(require_admin)])
        r = c.get("/_t/admin")
        assert r.status_code == expected
        if expected == 403:
            assert r.json()["error"]["code"] == "FORBIDDEN"


def test_auth_signup_login_refresh_logout(client_as, fake_auth, memory_db):
    c = client_as(None)
    r = c.post("/auth/signup", json={"email": "kim@example.com", "password": "secret123"})
    assert r.status_code == 200
    body = r.json()
    assert body["needs_email_confirm"] is False and body["profile"]["nickname"] == "kim"

    r = c.post("/auth/login", json={"email": "kim@example.com", "password": "secret123"})
    assert r.status_code == 200
    tokens = r.json()
    assert set(tokens) == {"access_token", "refresh_token", "expires_at", "profile"}
    assert len(memory_db.select("profiles")) == 1        # 같은 사용자 → profile 하나

    r = c.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200
    new_access = r.json()["access_token"]
    assert c.get("/me", headers={"Authorization": f"Bearer {new_access}"}).status_code == 200
    assert c.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401  # 재사용 불가

    r = c.post("/auth/logout", headers={"Authorization": f"Bearer {new_access}"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert c.get("/me", headers={"Authorization": f"Bearer {new_access}"}).status_code == 401
    assert c.post("/auth/logout").status_code == 200     # 토큰 없어도 성공


def test_auth_login_failures(client_as, fake_auth):
    c = client_as(None)
    fake_auth.add_user("a@example.com", "pw123456")
    fake_auth.add_user("b@example.com", "pw123456", confirmed=False)
    r = c.post("/auth/login", json={"email": "a@example.com", "password": "wrong-pw"})
    assert (r.status_code, r.json()["error"]["code"]) == (401, "INVALID_CREDENTIALS")
    r = c.post("/auth/login", json={"email": "b@example.com", "password": "pw123456"})
    assert (r.status_code, r.json()["error"]["code"]) == (403, "EMAIL_NOT_CONFIRMED")


def test_auth_signup_needs_email_confirm(client_as, fake_auth):
    fake_auth.require_email_confirm = True
    r = client_as(None).post("/auth/signup", json={"email": "c@example.com", "password": "pw123456"})
    assert r.status_code == 200
    assert r.json() == {"needs_email_confirm": True, "access_token": None, "refresh_token": None,
                        "expires_at": None, "profile": None}
