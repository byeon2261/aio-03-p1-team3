"""F14 발품 후기: /community/*

인수 조건(기획안 C1~C7, C9):
- 로그인한 사용자만 이용(get_current_user → 없으면 401).
- 필수 address·topic·title·body, 선택 floor·visit_date·사진 1장(JPG·PNG, 5MB).
- 주소는 부분 일치, 층수·주제는 같은 값으로 거른다. 처음 목록은 전체 최신순.
- 작성자만 고치고 지운다(남의 글 → 403 FORBIDDEN). 응답에는 닉네임만, 이메일·작성자 id는 없다.
- 좋아요(0141): PUT·DELETE /community/posts/{post_id}/like. 내 글에는 못 누른다(403). 목록 sort=likes는 좋아요 많은순.
- 요청 로그(C9)는 미들웨어가 경로 틀(/community/posts/{post_id})로 남긴다. 주소·본문은 로그에 남지 않는다.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, File, Query, UploadFile
from starlette.concurrency import run_in_threadpool

from app.core.auth import CurrentUser, get_current_user
from app.core.db import Database, get_admin_db, get_user_db
from app.core.errors import AppError
from app.core.schemas import OkOut
from app.core.storage import Storage, StorageError, get_storage
from app.features.community import service
from app.features.community.schemas import (
    FLOOR_MAX, FLOOR_MIN, TOPICS, PostIn, PostLikeOut, PostOut, PostSort, PostSummaryOut, PostUpdateIn, TopicsOut,
)

logger = logging.getLogger("app.features.community")
router = APIRouter(tags=["community"])


@router.get("/community/topics", response_model=TopicsOut)
def read_topics(user: CurrentUser = Depends(get_current_user)) -> TopicsOut:
    return TopicsOut(topics=list(TOPICS))


@router.get("/community/posts", response_model=list[PostSummaryOut])
def list_posts(
    address: str | None = Query(default=None, max_length=200, description="지번 주소 일부(부분 일치)"),
    floor: int | None = Query(default=None, ge=FLOOR_MIN, le=FLOOR_MAX),
    topic: str | None = Query(default=None),
    mine: bool = Query(default=False, description="true면 내가 쓴 후기만"),
    limit: int = Query(default=service.DEFAULT_LIMIT, ge=1, le=service.MAX_LIMIT),
    sort: PostSort = Query(default="latest", description="latest(최신순) · likes(좋아요 많은순, 같으면 최신순)"),
    user: CurrentUser = Depends(get_current_user),
    db: Database = Depends(get_user_db),
    admin_db: Database = Depends(get_admin_db),
) -> list[PostSummaryOut]:
    if topic is not None and topic not in TOPICS:
        raise AppError(422, "VALIDATION_ERROR", f"주제는 {', '.join(TOPICS)} 중 하나입니다.", {"reason": "topic"})
    rows = service.list_posts(db, user, address=address, floor=floor, topic=topic, mine=mine, limit=limit,
                              sort=sort)
    return service.to_summaries(db, admin_db, user, rows)


@router.post("/community/posts", response_model=PostOut)
def create_post(
    body: PostIn,
    user: CurrentUser = Depends(get_current_user),
    db: Database = Depends(get_user_db),
    admin_db: Database = Depends(get_admin_db),
    storage: Storage = Depends(get_storage),
) -> PostOut:
    row = service.create_post(db, user, body)
    return service.to_post_out(db, admin_db, user, row, storage)


@router.get("/community/posts/{post_id}", response_model=PostOut)
def read_post(
    post_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: Database = Depends(get_user_db),
    admin_db: Database = Depends(get_admin_db),
    storage: Storage = Depends(get_storage),
) -> PostOut:
    return service.to_post_out(db, admin_db, user, service.get_post(db, post_id), storage)


@router.patch("/community/posts/{post_id}", response_model=PostOut)
def update_post(
    post_id: str,
    body: PostUpdateIn,
    user: CurrentUser = Depends(get_current_user),
    db: Database = Depends(get_user_db),
    admin_db: Database = Depends(get_admin_db),
    storage: Storage = Depends(get_storage),
) -> PostOut:
    row = service.update_post(db, user, post_id, body)
    return service.to_post_out(db, admin_db, user, row, storage)


@router.delete("/community/posts/{post_id}", response_model=OkOut)
def delete_post(
    post_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: Database = Depends(get_user_db),
    storage: Storage = Depends(get_storage),
) -> OkOut:
    """사진 파일을 먼저 지운다. 실패하면 503 CLEANUP_FAILED이고 글은 남는다."""
    service.delete_post(db, user, post_id, storage)
    return OkOut()


@router.put("/community/posts/{post_id}/like", response_model=PostLikeOut)
def like_post(
    post_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: Database = Depends(get_user_db),
) -> PostLikeOut:
    """좋아요 누르기. 여러 번 보내도 1번만 센다. 내 글이면 403 FORBIDDEN."""
    return service.like_post(db, user, post_id)


@router.delete("/community/posts/{post_id}/like", response_model=PostLikeOut)
def unlike_post(
    post_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: Database = Depends(get_user_db),
) -> PostLikeOut:
    """좋아요 취소. 누른 적이 없어도 200으로 현재 상태를 준다."""
    return service.unlike_post(db, user, post_id)


@router.post("/community/posts/{post_id}/photo", response_model=PostOut)
async def upload_photo(
    post_id: str,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    db: Database = Depends(get_user_db),
    admin_db: Database = Depends(get_admin_db),
    storage: Storage = Depends(get_storage),
) -> PostOut:
    """글당 1장. 이미 있으면 새 사진으로 바꾼다(새 파일 저장 → 행 교체 → 옛 파일 삭제)."""
    post = await run_in_threadpool(service.get_own_post, db, user, post_id)
    data = await file.read(service.MAX_PHOTO_BYTES + 1)
    await file.close()
    content_type = service.validate_photo(data)

    photo_id = str(uuid.uuid4())
    path = service.build_storage_path(user.auth_user_id, str(post["id"]), photo_id, content_type)
    try:
        await run_in_threadpool(storage.upload, path, data, content_type, user.access_token)
    except StorageError as exc:
        logger.warning("community photo upload failed: %s", exc)
        raise AppError(503, "STORAGE_UNAVAILABLE", "사진을 저장하지 못했습니다. 잠시 후 다시 올려 주세요.") from None

    old = await run_in_threadpool(db.select, service.PHOTOS, {"post_id": str(post["id"])})
    try:
        if old:
            await run_in_threadpool(db.delete, service.PHOTOS, {"post_id": str(post["id"])})
        await run_in_threadpool(db.insert, service.PHOTOS, {
            "id": photo_id,
            "post_id": str(post["id"]),
            "profile_id": user.profile_id,
            "storage_path": path,
            "content_type": content_type,
            "size_bytes": len(data),
        })
    except Exception:
        try:   # 행을 못 만들면 올린 파일을 지운다(실패해도 원래 오류를 그대로 낸다)
            await run_in_threadpool(storage.delete, [path], user.access_token)
        except StorageError as exc:
            logger.warning("orphan community photo cleanup failed: %s", exc)
        raise
    if old:
        try:   # 옛 파일 정리는 실패해도 새 사진 등록은 유지한다
            await run_in_threadpool(storage.delete, [r["storage_path"] for r in old], user.access_token)
        except StorageError as exc:
            logger.warning("old community photo cleanup failed: %s", exc)
    return await run_in_threadpool(service.to_post_out, db, admin_db, user, post, storage)


@router.delete("/community/posts/{post_id}/photo", response_model=PostOut)
def delete_photo(
    post_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: Database = Depends(get_user_db),
    admin_db: Database = Depends(get_admin_db),
    storage: Storage = Depends(get_storage),
) -> PostOut:
    post = service.get_own_post(db, user, post_id)
    photos = db.select(service.PHOTOS, {"post_id": str(post["id"])})
    service.delete_files(storage, [p["storage_path"] for p in photos], user.access_token)
    db.delete(service.PHOTOS, {"post_id": str(post["id"])})
    return service.to_post_out(db, admin_db, user, post, storage)
