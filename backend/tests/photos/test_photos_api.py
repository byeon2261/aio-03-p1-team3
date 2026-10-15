"""F10 사진 API: 본인만 업로드·조회·삭제, 형식·크기 검사, 저장 경로, 서명 URL만 응답."""

from __future__ import annotations

import datetime as dt
import json

from app.core.config import settings

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 200
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 200
GIF = b"GIF89a" + b"\x00" * 200


def _listing(db, user, title="토요일"):
    s = db.insert("tour_sessions", {"profile_id": user.profile_id, "title": title})[0]
    l = db.insert("listings", {"session_id": s["id"], "memo_text": "메모"})[0]
    return s, l


def _upload(c, listing_id, content=JPEG, name="a.jpg", ctype="image/jpeg", **extra):
    return c.post(f"/listings/{listing_id}/photos", files={"file": (name, content, ctype)}, **extra)


def _err(r):
    return r.json()["error"]


# ------------------------------------------------------------------ 정상 흐름·저장 경로
def test_photos_upload_list_delete_own(client_as, make_user, memory_db, memory_storage):
    alice = make_user()
    _, l = _listing(memory_db, alice)
    c = client_as(alice)

    r = _upload(c, l["id"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["listing_id"] == l["id"]
    assert body["visibility"] == "private"
    assert body["content_type"] == "image/jpeg" and body["size_bytes"] == len(JPEG)

    rows = memory_db.select("photos")
    assert len(rows) == 1
    path = rows[0]["storage_path"]
    assert path == f"{alice.auth_user_id}/{l['id']}/{body['id']}.jpg"       # 저장 경로 규칙
    assert path in memory_storage.objects
    assert memory_storage.objects[path]["token"] == alice.access_token      # 사용자 토큰으로 업로드
    assert rows[0]["visibility"] == "private" and rows[0]["profile_id"] == alice.profile_id

    r = c.get(f"/listings/{l['id']}/photos")
    assert r.status_code == 200 and [p["id"] for p in r.json()] == [body["id"]]

    r = c.delete(f"/photos/{body['id']}")
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert memory_db.select("photos") == []
    assert memory_storage.objects == {}


def test_photos_extension_follows_real_format(client_as, make_user, memory_db, memory_storage):
    alice = make_user()
    _, l = _listing(memory_db, alice)
    c = client_as(alice)
    for data, ext, ctype in ((PNG, "png", "image/png"), (WEBP, "webp", "image/webp")):
        r = _upload(c, l["id"], content=data, name=f"x.{ext}", ctype=ctype)
        assert r.status_code == 200, r.text
        assert r.json()["content_type"] == ctype
        assert memory_db.select("photos", {"id": r.json()["id"]})[0]["storage_path"].endswith(f".{ext}")


def test_photos_visibility_is_always_private(client_as, make_user, memory_db):
    alice = make_user()
    _, l = _listing(memory_db, alice)
    r = _upload(client_as(alice), l["id"], data={"visibility": "public"})
    assert r.status_code == 200 and r.json()["visibility"] == "private"
    assert memory_db.select("photos")[0]["visibility"] == "private"


def test_photos_requires_login(client_as, make_user, memory_db):
    alice = make_user()
    _, l = _listing(memory_db, alice)
    r = _upload(client_as(None), l["id"])
    assert r.status_code == 401 and _err(r)["code"] == "AUTH_REQUIRED"


# ------------------------------------------------------------------ 남의 것 → 404
def test_photos_other_users_listing_upload_and_list_404(client_as, make_user, memory_db, memory_storage):
    alice, bob = make_user(), make_user()
    _, bob_listing = _listing(memory_db, bob)
    c = client_as(alice)

    r = _upload(c, bob_listing["id"])
    assert r.status_code == 404 and _err(r)["code"] == "LISTING_NOT_FOUND"
    assert memory_storage.calls == [] and memory_db.select("photos") == []

    r = c.get(f"/listings/{bob_listing['id']}/photos")
    assert r.status_code == 404 and _err(r)["code"] == "LISTING_NOT_FOUND"

    r = c.get("/listings/not-a-uuid/photos")
    assert r.status_code == 404


def test_photos_delete_other_users_photo_404(client_as, make_user, memory_db, memory_storage):
    alice, bob = make_user(), make_user()
    _, bob_listing = _listing(memory_db, bob)
    photo = _upload(client_as(bob), bob_listing["id"]).json()

    r = client_as(alice).delete(f"/photos/{photo['id']}")
    assert r.status_code == 404 and _err(r)["code"] == "PHOTO_NOT_FOUND"
    assert len(memory_db.select("photos")) == 1 and len(memory_storage.objects) == 1


def test_photos_list_shows_only_mine_and_no_other_urls(client_as, make_user, memory_db):
    alice, bob = make_user(), make_user()
    _, l = _listing(memory_db, alice)
    _, bl = _listing(memory_db, bob)
    _upload(client_as(bob), bl["id"])
    mine = _upload(client_as(alice), l["id"]).json()

    r = client_as(alice).get(f"/listings/{l['id']}/photos")
    assert [p["id"] for p in r.json()] == [mine["id"]]
    assert bob.auth_user_id not in r.text


# ------------------------------------------------------------------ 형식·크기 → 422
def test_photos_rejects_unsupported_type(client_as, make_user, memory_db, memory_storage):
    alice = make_user()
    _, l = _listing(memory_db, alice)
    c = client_as(alice)
    cases = [
        (GIF, "a.gif", "image/gif", "unsupported_type"),
        (b"just text, not an image", "fake.png", "image/png", "unsupported_type"),   # 확장자·형식 위장
        (b"%PDF-1.7 ...", "doc.jpg", "image/jpeg", "unsupported_type"),
        (b"", "empty.jpg", "image/jpeg", "empty_file"),
    ]
    for data, name, ctype, reason in cases:
        r = _upload(c, l["id"], content=data, name=name, ctype=ctype)
        assert r.status_code == 422, name
        err = _err(r)
        assert err["code"] == "VALIDATION_ERROR" and err["detail"]["reason"] == reason
        assert set(err["detail"]["allowed_types"]) == {"image/jpeg", "image/png", "image/webp"}
    assert memory_storage.objects == {} and memory_db.select("photos") == []


def test_photos_rejects_too_large(client_as, make_user, memory_db, memory_storage, monkeypatch):
    monkeypatch.setattr(settings, "MAX_PHOTO_MB", 1)
    limit = 1024 * 1024
    alice = make_user()
    _, l = _listing(memory_db, alice)
    c = client_as(alice)

    big = JPEG[:4] + b"\x00" * (limit - 4 + 1)
    r = _upload(c, l["id"], content=big)
    assert r.status_code == 422
    assert _err(r)["code"] == "VALIDATION_ERROR" and _err(r)["detail"]["reason"] == "too_large"
    assert _err(r)["detail"]["max_mb"] == 1
    assert memory_storage.objects == {}

    exact = JPEG[:4] + b"\x00" * (limit - 4)
    assert _upload(c, l["id"], content=exact).status_code == 200


def test_photos_default_limit_is_10mb():
    assert settings.MAX_PHOTO_MB == 10 and settings.SIGNED_URL_TTL_SEC == 600


def test_photos_missing_file_field_422(client_as, make_user, memory_db):
    alice = make_user()
    _, l = _listing(memory_db, alice)
    r = client_as(alice).post(f"/listings/{l['id']}/photos", data={"x": "1"})
    assert r.status_code == 422 and _err(r)["code"] == "VALIDATION_ERROR"


# ------------------------------------------------------------------ 서명 URL만
def test_photos_response_has_signed_url_only(client_as, make_user, memory_db):
    alice = make_user()
    _, l = _listing(memory_db, alice)
    c = client_as(alice)
    before = dt.datetime.now(dt.timezone.utc)
    up = _upload(c, l["id"]).json()
    listed = c.get(f"/listings/{l['id']}/photos").json()[0]

    for body in (up, listed):
        path = memory_db.select("photos")[0]["storage_path"]
        assert body["url"] == f"https://storage.test/listing-photos/{path}?ttl=600"   # 서명 URL(TTL 600초)
        exp = dt.datetime.fromisoformat(body["url_expires_at"].replace("Z", "+00:00"))
        assert before + dt.timedelta(seconds=590) <= exp <= before + dt.timedelta(seconds=660)
        raw = json.dumps(body)
        assert "storage_path" not in body
        assert "/object/public/" not in raw and "/public/" not in raw


def test_photos_signed_url_failure_keeps_list(client_as, make_user, memory_db, memory_storage):
    alice = make_user()
    _, l = _listing(memory_db, alice)
    c = client_as(alice)
    _upload(c, l["id"])
    memory_storage.fail_signed_urls = True
    r = c.get(f"/listings/{l['id']}/photos")
    assert r.status_code == 200
    assert r.json()[0]["url"] is None and r.json()[0]["url_expires_at"] is None


# ------------------------------------------------------------------ Storage 실패
def test_photos_delete_storage_failure_keeps_row(client_as, make_user, memory_db, memory_storage):
    alice = make_user()
    _, l = _listing(memory_db, alice)
    c = client_as(alice)
    photo = _upload(c, l["id"]).json()

    memory_storage.fail_deletes = True
    r = c.delete(f"/photos/{photo['id']}")
    assert r.status_code == 503 and _err(r)["code"] == "CLEANUP_FAILED"
    assert len(memory_db.select("photos")) == 1 and len(memory_storage.objects) == 1   # 행 유지 → 다시 삭제 가능

    memory_storage.fail_deletes = False
    assert c.delete(f"/photos/{photo['id']}").status_code == 200
    assert memory_db.select("photos") == [] and memory_storage.objects == {}


def test_photos_upload_storage_failure_creates_no_row(client_as, make_user, memory_db, memory_storage):
    alice = make_user()
    _, l = _listing(memory_db, alice)
    memory_storage.fail_uploads = True
    r = _upload(client_as(alice), l["id"])
    assert r.status_code == 503 and _err(r)["code"] == "STORAGE_UNAVAILABLE"
    assert memory_db.select("photos") == []


def test_photos_row_insert_failure_removes_uploaded_file(client_as, make_user, memory_db, memory_storage,
                                                         monkeypatch):
    alice = make_user()
    _, l = _listing(memory_db, alice)
    real_insert = memory_db.insert

    def failing_insert(table, rows):
        if table == "photos":
            raise ConnectionError("db down (test)")
        return real_insert(table, rows)

    monkeypatch.setattr(memory_db, "insert", failing_insert)
    r = _upload(client_as(alice), l["id"])
    assert r.status_code == 500
    assert memory_storage.objects == {}                     # 올린 파일을 되돌림
