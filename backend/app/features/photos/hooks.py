"""세션·매물 삭제 전에 그 안의 사진 파일을 Storage에서 지운다.

DB의 CASCADE는 photos 행만 지우고 Storage 파일은 남기므로 여기서 먼저 지운다.
Storage 삭제가 실패하면 AppError(503, CLEANUP_FAILED)를 던진다 → P1이 DB 삭제를 멈추고(행이 남음)
사용자는 다시 삭제할 수 있다.

Storage는 이벤트 인자 storage(삭제 엔드포인트가 Depends(get_storage)로 받은 것)를 쓴다.
그래서 테스트의 dependency_overrides(memory_storage)를 그대로 따른다.
사진이 하나도 없으면 Storage를 부르지 않는다(사진 없는 삭제는 Storage 설정과 무관하게 진행).
"""

from __future__ import annotations

from typing import Any

from app.core import events
from app.features.photos.service import delete_files


def _photo_paths(db: Any, listing_ids: list[str]) -> list[str]:
    if not listing_ids:
        return []
    rows = db.select("photos", {"listing_id": listing_ids})
    return [r["storage_path"] for r in rows if r.get("storage_path")]


def _cleanup(db: Any, user: Any, storage: Any, listing_ids: list[Any]) -> None:
    paths = _photo_paths(db, [str(x) for x in listing_ids if x])
    if not paths:
        return
    delete_files(storage, paths, user.access_token)


def on_session_before_delete(*, db: Any, user: Any, storage: Any, session: Any = None,
                             listing_ids: list[Any] | None = None, **_: Any) -> None:
    if listing_ids is None and session:  # 계약상 listing_ids가 오지만, 없으면 직접 찾는다
        listing_ids = [r["id"] for r in db.select("listings", {"session_id": str(session["id"])})]
    _cleanup(db, user, storage, list(listing_ids or []))


def on_listing_before_delete(*, db: Any, user: Any, listing: dict, storage: Any, **_: Any) -> None:
    _cleanup(db, user, storage, [listing.get("id")])


events.on("session.before_delete", on_session_before_delete)
events.on("listing.before_delete", on_listing_before_delete)
