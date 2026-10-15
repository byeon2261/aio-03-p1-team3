"""세션·매물 삭제 이벤트에서 Storage 파일 삭제, 실패 시 CLEANUP_FAILED(행 유지).

처리기는 이벤트 인자 storage(삭제 엔드포인트가 Depends(get_storage)로 받은 것)를 쓴다(I2).
그래서 dependency_overrides로 바꾼 memory_storage를 그대로 따르고, 전역 get_storage()는 부르지 않는다.
"""

from __future__ import annotations

import pytest
from fastapi import Depends

from app.core import events
from app.core import storage as storage_module
from app.core.auth import CurrentUser, get_current_user
from app.core.db import get_user_db
from app.core.errors import AppError
from app.core.ownership import get_owned_listing
from app.core.schemas import OkOut
from app.core.storage import get_storage

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


class _BoomStorage:
    """어떤 메서드를 불러도 실패한다. 부르면 안 되는 저장소 자리에 둔다."""

    def __getattr__(self, name):
        raise AssertionError(f"이 저장소를 부르면 안 된다: {name}")


@pytest.fixture
def global_storage(memory_storage, monkeypatch):
    """이름은 예전 그대로 둔다. 전역 get_storage()가 돌려줄 저장소를 _BoomStorage로 바꿔, 처리기가 전역이 아니라
    이벤트 인자 storage를 쓰는지 확인한다. 반환값은 dependency_overrides로 엔드포인트에 들어가는 memory_storage다."""
    monkeypatch.setattr(storage_module, "_storage", _BoomStorage())
    return memory_storage


def _listing(db, user, session=None):
    s = session or db.insert("tour_sessions", {"profile_id": user.profile_id, "title": "세션"})[0]
    l = db.insert("listings", {"session_id": s["id"], "memo_text": "메모"})[0]
    return s, l


def _photo(c, listing_id):
    r = c.post(f"/listings/{listing_id}/photos", files={"file": ("a.jpg", JPEG, "image/jpeg")})
    assert r.status_code == 200, r.text
    return r.json()


def test_photos_hooks_registered_once(client_as, make_user):
    client_as(make_user())
    client_as(make_user())          # 앱을 다시 만들어도 처리기는 하나
    assert len(events.handlers("listing.before_delete")) == 1
    assert len(events.handlers("session.before_delete")) == 1


def test_photos_listing_delete_event_removes_files(client_as, make_user, memory_db, global_storage):
    alice, bob = make_user(), make_user()
    _, l = _listing(memory_db, alice)
    _, other = _listing(memory_db, alice)
    _, bl = _listing(memory_db, bob)
    c = client_as(alice)
    _photo(c, l["id"]); _photo(c, l["id"]); _photo(c, other["id"])
    _photo(client_as(bob), bl["id"])

    listing = get_owned_listing(memory_db, alice, l["id"])
    events.emit("listing.before_delete", db=memory_db, user=alice, listing=listing, storage=global_storage)

    left = set(global_storage.objects)
    assert not any(p.startswith(f"{alice.auth_user_id}/{l['id']}/") for p in left)
    assert sum(p.startswith(f"{alice.auth_user_id}/{other['id']}/") for p in left) == 1   # 다른 매물은 그대로
    assert sum(p.startswith(f"{bob.auth_user_id}/") for p in left) == 1                   # 남의 파일 그대로
    deletes = [args for name, args in global_storage.calls if name == "delete"]
    assert deletes and all(len(a) == 2 for a in deletes)


def test_photos_session_delete_event_removes_files(client_as, make_user, memory_db, global_storage):
    alice = make_user()
    s, l1 = _listing(memory_db, alice)
    _, l2 = _listing(memory_db, alice, session=s)
    _, keep = _listing(memory_db, alice)          # 다른 세션
    c = client_as(alice)
    _photo(c, l1["id"]); _photo(c, l2["id"]); _photo(c, keep["id"])

    events.emit("session.before_delete", db=memory_db, user=alice, session=s, listing_ids=[l1["id"], l2["id"]],
                storage=global_storage)
    assert list(global_storage.objects) == [memory_db.select("photos", {"listing_id": keep["id"]})[0]["storage_path"]]


def test_photos_hook_failure_raises_cleanup_failed(client_as, make_user, memory_db, global_storage):
    alice = make_user()
    s, l = _listing(memory_db, alice)
    _photo(client_as(alice), l["id"])
    global_storage.fail_deletes = True

    for event, payload in (("listing.before_delete", {"listing": l}),
                           ("session.before_delete", {"session": s, "listing_ids": [l["id"]]})):
        with pytest.raises(AppError) as ei:
            events.emit(event, db=memory_db, user=alice, storage=global_storage, **payload)
        assert ei.value.status == 503 and ei.value.code == "CLEANUP_FAILED"
    assert len(memory_db.select("photos")) == 1 and len(global_storage.objects) == 1


def test_photos_hook_without_photos_does_not_touch_storage(client_as, make_user, memory_db, global_storage):
    boom = _BoomStorage()
    alice = make_user()
    client_as(alice)
    s, l = _listing(memory_db, alice)
    events.emit("listing.before_delete", db=memory_db, user=alice, listing=l, storage=boom)
    events.emit("session.before_delete", db=memory_db, user=alice, session=s, listing_ids=[l["id"]], storage=boom)
    events.emit("session.before_delete", db=memory_db, user=alice, session=s, listing_ids=[], storage=boom)


def test_photos_hook_stops_p1_style_delete(client_as, make_user, memory_db, global_storage):
    """P1처럼 emit → DB 삭제 순서로 지우는 임시 경로로, 실패 시 행이 남고 다시 지울 수 있는지 본다."""
    alice = make_user()
    _, l = _listing(memory_db, alice)
    c = client_as(alice)
    _photo(c, l["id"])

    def fake_p1_delete(listing_id: str, user: CurrentUser = Depends(get_current_user), db=Depends(get_user_db),
                       storage=Depends(get_storage)):
        listing = get_owned_listing(db, user, listing_id)
        events.emit("listing.before_delete", db=db, user=user, listing=listing, storage=storage)
        db.delete("listings", {"id": listing["id"]})
        return OkOut()

    c.app.add_api_route("/_t/listings/{listing_id}", fake_p1_delete, methods=["DELETE"])

    global_storage.fail_deletes = True
    r = c.delete(f"/_t/listings/{l['id']}")
    assert r.status_code == 503 and r.json()["error"]["code"] == "CLEANUP_FAILED"
    assert len(memory_db.select("listings")) == 1 and len(memory_db.select("photos")) == 1

    global_storage.fail_deletes = False
    assert c.delete(f"/_t/listings/{l['id']}").status_code == 200
    assert memory_db.select("listings") == [] and memory_db.select("photos") == []   # CASCADE
    assert global_storage.objects == {}


# ------------------------------------------------------------------ I2: 실제 P1 삭제 엔드포인트 + dependency_overrides
def test_photos_real_listing_delete_uses_overridden_storage(client_as, make_user, memory_db, global_storage):
    """DELETE /listings/{id}(P1)가 Depends(get_storage)로 받은 memory_storage를 이벤트로 넘기고,
    P4 처리기가 그것으로 사진 파일을 지운다(전역 get_storage()는 막아 둠)."""
    alice = make_user()
    s, l = _listing(memory_db, alice)
    _, keep = _listing(memory_db, alice, session=s)
    c = client_as(alice)
    _photo(c, l["id"]); _photo(c, l["id"]); _photo(c, keep["id"])

    r = c.delete(f"/listings/{l['id']}")
    assert r.status_code == 200, r.text
    left = list(global_storage.objects)
    assert len(left) == 1 and left[0].startswith(f"{alice.auth_user_id}/{keep['id']}/")
    assert memory_db.select("photos", {"listing_id": l["id"]}) == []


def test_photos_real_session_delete_uses_overridden_storage(client_as, make_user, memory_db, global_storage):
    alice = make_user()
    s, l1 = _listing(memory_db, alice)
    _, l2 = _listing(memory_db, alice, session=s)
    _, other = _listing(memory_db, alice)          # 다른 세션
    c = client_as(alice)
    _photo(c, l1["id"]); _photo(c, l2["id"]); _photo(c, other["id"])

    r = c.delete(f"/sessions/{s['id']}")
    assert r.status_code == 200, r.text
    left = list(global_storage.objects)
    assert len(left) == 1 and left[0].startswith(f"{alice.auth_user_id}/{other['id']}/")
    assert memory_db.select("tour_sessions", {"id": s["id"]}) == []


def test_photos_real_delete_storage_failure_keeps_rows(client_as, make_user, memory_db, global_storage):
    alice = make_user()
    s, l = _listing(memory_db, alice)
    c = client_as(alice)
    _photo(c, l["id"])
    global_storage.fail_deletes = True

    for path in (f"/listings/{l['id']}", f"/sessions/{s['id']}"):
        r = c.delete(path)
        assert r.status_code == 503 and r.json()["error"]["code"] == "CLEANUP_FAILED"
    assert len(memory_db.select("listings")) == 1 and len(memory_db.select("photos")) == 1
    assert len(global_storage.objects) == 1
