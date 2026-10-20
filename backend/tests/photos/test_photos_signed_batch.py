"""사진 서명 URL을 한 번에 만들기: 응답은 한 장씩 만들 때와 같고, Storage는 묶음으로 한 번만 부른다."""

from __future__ import annotations

from app.core.storage import StorageError, SupabaseStorage
from app.features.photos import service

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 200


def _listing(db, user, title="토요일"):
    s = db.insert("tour_sessions", {"profile_id": user.profile_id, "title": title})[0]
    return db.insert("listings", {"session_id": s["id"], "memo_text": "메모"})[0]


def _upload(c, listing_id):
    r = c.post(f"/listings/{listing_id}/photos", files={"file": ("a.jpg", JPEG, "image/jpeg")})
    assert r.status_code == 200, r.text
    return r.json()


def _add_batch(storage, fail=False):
    """MemoryStorage에 묶음 기능을 붙인다. 한 장씩 만들 때와 같은 URL을 돌려준다."""
    batches: list[list[str]] = []

    def signed_urls(paths, ttl_sec, access_token):
        batches.append(list(paths))
        if fail:
            raise StorageError("signed_urls failed (fake)")
        return {p: (f"https://storage.test/listing-photos/{p}?ttl={int(ttl_sec)}" if p in storage.objects else None)
                for p in paths}

    storage.signed_urls = signed_urls
    return batches


def _without_expiry(body):
    return [{k: v for k, v in p.items() if k != "url_expires_at"} for p in body]


def _one_by_one(storage):
    return [c for c in storage.calls if c[0] == "signed_url"]


def test_my_photos_signs_all_in_one_batch_same_body(client_as, make_user, memory_db, memory_storage):
    alice = make_user()
    c = client_as(alice)
    for title in ("토요일", "일요일"):
        lid = _listing(memory_db, alice, title)["id"]
        _upload(c, lid)
        _upload(c, lid)

    before = c.get("/me/photos").json()                 # 묶음 기능이 없을 때(한 장씩)
    memory_storage.calls.clear()
    batches = _add_batch(memory_storage)
    after = c.get("/me/photos").json()

    assert len(batches) == 1 and len(batches[0]) == 4
    assert _one_by_one(memory_storage) == []
    assert _without_expiry(after) == _without_expiry(before)
    assert all(p["url"] and p["url_expires_at"] for p in after)


def test_listing_photos_signs_in_one_batch_same_body(client_as, make_user, memory_db, memory_storage):
    alice = make_user()
    c = client_as(alice)
    lid = _listing(memory_db, alice)["id"]
    for _ in range(3):
        _upload(c, lid)

    before = c.get(f"/listings/{lid}/photos").json()
    memory_storage.calls.clear()
    batches = _add_batch(memory_storage)
    after = c.get(f"/listings/{lid}/photos").json()

    assert len(batches) == 1 and len(batches[0]) == 3
    assert _one_by_one(memory_storage) == []
    assert _without_expiry(after) == _without_expiry(before)


def test_missing_file_in_batch_gives_no_url_like_before(client_as, make_user, memory_db, memory_storage):
    alice = make_user()
    c = client_as(alice)
    lid = _listing(memory_db, alice)["id"]
    _upload(c, lid)
    gone = _upload(c, lid)
    path = memory_db.select("photos", {"id": gone["id"]})[0]["storage_path"]
    memory_storage.objects.pop(path)                     # 파일만 사라진 사진

    before = c.get("/me/photos").json()
    _add_batch(memory_storage)
    after = c.get("/me/photos").json()

    missing = next(p for p in after if p["id"] == gone["id"])
    assert missing["url"] is None and missing["url_expires_at"] is None
    assert _without_expiry(after) == _without_expiry(before)


def test_batch_failure_falls_back_to_one_by_one(client_as, make_user, memory_db, memory_storage):
    alice = make_user()
    c = client_as(alice)
    lid = _listing(memory_db, alice)["id"]
    _upload(c, lid)
    _upload(c, lid)

    before = c.get("/me/photos").json()
    memory_storage.calls.clear()
    batches = _add_batch(memory_storage, fail=True)
    after = c.get("/me/photos").json()

    assert len(batches) == 1
    assert len(_one_by_one(memory_storage)) == 2
    assert _without_expiry(after) == _without_expiry(before)


def test_batch_is_split_into_chunks(client_as, make_user, memory_db, memory_storage, monkeypatch):
    monkeypatch.setattr(service, "SIGN_CHUNK", 2)
    alice = make_user()
    c = client_as(alice)
    lid = _listing(memory_db, alice)["id"]
    for _ in range(5):
        _upload(c, lid)
    batches = _add_batch(memory_storage)
    body = c.get("/me/photos").json()
    assert [len(b) for b in batches] == [2, 2, 1]
    assert len(body) == 5 and all(p["url"] for p in body)


def test_supabase_storage_signed_urls_reads_response(monkeypatch):
    calls = []

    class Bucket:
        def create_signed_urls(self, paths, expires_in):
            calls.append((paths, expires_in))
            return [{"path": "a/1.jpg", "error": None, "signedURL": "https://x/sign/a/1.jpg?token=t"},
                    {"path": "a/2.jpg", "error": "Either the object does not exist", "signedURL": None}]

    storage = SupabaseStorage()
    monkeypatch.setattr(storage, "_bucket", lambda token: Bucket())
    assert storage.signed_urls(["a/1.jpg", "a/2.jpg"], 60, "tok") == {
        "a/1.jpg": "https://x/sign/a/1.jpg?token=t", "a/2.jpg": None}
    assert calls == [(["a/1.jpg", "a/2.jpg"], 60)]
    assert storage.signed_urls([], 60, "tok") == {}


def test_supabase_storage_signed_urls_error_is_storage_error(monkeypatch):
    class Bucket:
        def create_signed_urls(self, paths, expires_in):
            raise RuntimeError("network")

    storage = SupabaseStorage()
    monkeypatch.setattr(storage, "_bucket", lambda token: Bucket())
    try:
        storage.signed_urls(["a/1.jpg"], 60, "tok")
    except StorageError as exc:
        assert "tok" not in str(exc)
    else:
        raise AssertionError("StorageError expected")
