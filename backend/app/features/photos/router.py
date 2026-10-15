"""F10 사진: POST·GET /listings/{listing_id}/photos · DELETE /photos/{photo_id}

인수 조건: 본인만 조회·삭제, 파일 주소로도 남의 비공개 사진에 접근할 수 없다.
- 소유 확인은 core.ownership(남의 것 → 404).
- 파일은 비공개 버킷에 사용자 토큰으로 올리고, 응답에는 서명 URL(SIGNED_URL_TTL_SEC)만 준다.
- visibility는 항상 private. 바꾸는 API는 없다(public은 F14 예약).
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, File, UploadFile
from starlette.concurrency import run_in_threadpool

from app.core.auth import CurrentUser, get_current_user
from app.core.db import Database, get_user_db
from app.core.errors import AppError
from app.core.ownership import get_owned_listing, get_owned_photo
from app.core.schemas import OkOut, PhotoOut
from app.core.storage import Storage, StorageError, get_storage
from app.features.photos.service import (
    build_storage_path,
    delete_files,
    max_photo_bytes,
    to_photo_out,
    validate_photo,
)

logger = logging.getLogger("app.features.photos")
router = APIRouter(tags=["photos"])


@router.post("/listings/{listing_id}/photos", response_model=PhotoOut)
async def upload_photo(
    listing_id: str,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    db: Database = Depends(get_user_db),
    storage: Storage = Depends(get_storage),
) -> PhotoOut:
    listing = await run_in_threadpool(get_owned_listing, db, user, listing_id)   # 남의 매물 → 404

    # 최대 크기 + 1바이트까지만 읽어 넘침을 판단한다
    data = await file.read(max_photo_bytes() + 1)
    await file.close()
    content_type = validate_photo(data)

    photo_id = str(uuid.uuid4())
    path = build_storage_path(user.auth_user_id, str(listing["id"]), photo_id, content_type)
    try:
        await run_in_threadpool(storage.upload, path, data, content_type, user.access_token)
    except StorageError as exc:
        logger.warning("photo upload failed: %s", exc)
        raise AppError(503, "STORAGE_UNAVAILABLE", "사진을 저장하지 못했습니다. 잠시 후 다시 올려 주세요.") from None

    row_in = {
        "id": photo_id,
        "listing_id": str(listing["id"]),
        "profile_id": user.profile_id,
        "storage_path": path,
        "content_type": content_type,
        "size_bytes": len(data),
        "visibility": "private",
    }
    try:
        rows = await run_in_threadpool(db.insert, "photos", row_in)
    except Exception:
        # 행을 못 만들면 올린 파일을 지운다(실패해도 원래 오류를 그대로 낸다)
        try:
            await run_in_threadpool(storage.delete, [path], user.access_token)
        except StorageError as exc:
            logger.warning("orphan photo cleanup failed: %s photo_id=%s", exc, photo_id)
        raise
    row = rows[0] if rows else row_in
    return await run_in_threadpool(to_photo_out, row, storage, user.access_token)


@router.get("/listings/{listing_id}/photos", response_model=list[PhotoOut])
def list_photos(
    listing_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: Database = Depends(get_user_db),
    storage: Storage = Depends(get_storage),
) -> list[PhotoOut]:
    listing = get_owned_listing(db, user, listing_id)
    rows = db.select("photos", {"listing_id": str(listing["id"]), "profile_id": user.profile_id},
                     order_by="created_at")
    return [to_photo_out(r, storage, user.access_token) for r in rows]


@router.delete("/photos/{photo_id}", response_model=OkOut)
def delete_photo(
    photo_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: Database = Depends(get_user_db),
    storage: Storage = Depends(get_storage),
) -> OkOut:
    photo = get_owned_photo(db, user, photo_id)                       # 남의 사진 → 404
    delete_files(storage, [photo["storage_path"]], user.access_token)  # 실패 → 503, 행 유지
    db.delete("photos", {"id": str(photo["id"])})
    return OkOut()
