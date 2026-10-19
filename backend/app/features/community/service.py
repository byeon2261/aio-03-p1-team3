"""F14 발품 후기 저장·조회.

테이블(0140): community_posts, community_post_photos. (0141): community_post_likes.
- 읽기는 로그인한 사용자 모두(RLS), 쓰기·고치기·지우기는 작성자만. 남의 글을 고치거나 지우려 하면 403.
- 작성자 닉네임은 profiles가 본인 행만 읽히므로 admin db(secret key)로 닉네임만 읽는다.
- 주소 검색은 부분 일치라 DB 필터 대신 최근 글을 읽어 서버에서 거른다(SEARCH_SCAN 개까지).
- 좋아요는 남의 글에만, 한 사람이 한 글에 1번. 좋아요 많은순은 최근 글(SEARCH_SCAN 개)을 읽어 서버에서 정렬한다.
- 사진 파일은 Storage "{auth_user_id}/community/{post_id}/{photo_id}.{ext}". 응답에는 서명 URL만 준다.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from app.core.config import settings
from app.core.db import UniqueViolation, is_valid_uuid
from app.core.errors import AppError
from app.core.storage import Storage, StorageError
from app.features.community.address import address_key, address_matches, normalize_address
from app.features.community.privacy import contact_reason
from app.features.community.schemas import (
    PostIn, PostLikeOut, PostOut, PostPhotoOut, PostSummaryOut, PostUpdateIn,
)
from app.features.photos.service import sniff_content_type

logger = logging.getLogger("app.features.community")

POSTS = "community_posts"
PHOTOS = "community_post_photos"
LIKES = "community_post_likes"
DEFAULT_LIMIT = 50
MAX_LIMIT = 200
SEARCH_SCAN = 1000                      # 주소 검색 때 서버에서 훑는 최근 글 수
MAX_PHOTO_BYTES = 5 * 1024 * 1024       # 5MB
ALLOWED_TYPES: dict[str, str] = {"image/jpeg": "jpg", "image/png": "png"}
UNKNOWN_NICKNAME = "알 수 없음"


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def post_not_found() -> AppError:
    return AppError(404, "POST_NOT_FOUND", "발품 후기를 찾을 수 없습니다.")


def not_author() -> AppError:
    return AppError(403, "FORBIDDEN", "내가 쓴 후기만 고치거나 지울 수 있습니다.")


def own_post_like() -> AppError:
    return AppError(403, "FORBIDDEN", "내가 쓴 후기에는 좋아요를 누를 수 없습니다.")


# ------------------------------------------------------------------ 입력 검사
def check_contact(title: str | None, body: str | None) -> None:
    """제목·본문에 전화번호·이메일 모양이 있으면 422."""
    for field, text in (("title", title), ("body", body)):
        if text is None:
            continue
        reason = contact_reason(text)
        if reason:
            what = "이메일" if reason == "email" else "전화번호"
            raise AppError(422, "VALIDATION_ERROR",
                           f"{'제목' if field == 'title' else '내용'}에 {what}로 보이는 글자가 있습니다. "
                           "연락처는 적지 말아 주세요.",
                           {"reason": "contact_info", "field": field})


def validate_photo(data: bytes) -> str:
    """JPG·PNG, 5MB 이하만. 통과하면 실제 content_type, 아니면 422(detail.reason)."""
    def invalid(reason: str, message: str) -> AppError:
        return AppError(422, "VALIDATION_ERROR", message,
                        {"reason": reason, "allowed_types": list(ALLOWED_TYPES), "max_mb": 5})

    if not data:
        raise invalid("empty_file", "빈 파일입니다. 사진 파일을 다시 고르세요.")
    if len(data) > MAX_PHOTO_BYTES:
        raise invalid("too_large", "사진은 5MB 이하만 올릴 수 있습니다.")
    content_type = sniff_content_type(data)
    if content_type not in ALLOWED_TYPES:
        raise invalid("unsupported_type", "JPG·PNG 사진만 올릴 수 있습니다.")
    return content_type


# ------------------------------------------------------------------ 조회
def get_post(db: Any, post_id: Any) -> dict:
    if not is_valid_uuid(post_id):
        raise post_not_found()
    rows = db.select(POSTS, {"id": str(post_id)}, limit=1)
    if not rows:
        raise post_not_found()
    return rows[0]


def get_own_post(db: Any, user: Any, post_id: Any) -> dict:
    post = get_post(db, post_id)
    if str(post.get("profile_id")) != str(user.profile_id):
        raise not_author()
    return post


def list_posts(db: Any, user: Any, *, address: str | None = None, floor: int | None = None,
               topic: str | None = None, mine: bool = False, limit: int = DEFAULT_LIMIT,
               sort: str = "latest") -> list[dict]:
    """최신순(sort=latest) 또는 좋아요 많은순(sort=likes, 같으면 최신순).
    address는 부분 일치, floor·topic은 같은 값만(층수를 비운 글은 층 필터에 안 걸린다)."""
    filters: dict[str, Any] = {}
    if floor is not None:
        filters["floor"] = int(floor)
    if topic:
        filters["topic"] = topic
    if mine:
        filters["profile_id"] = user.profile_id
    query = (address or "").strip()
    if not query and sort != "likes":
        return db.select(POSTS, filters, order_by="created_at", desc=True, limit=limit)
    rows = db.select(POSTS, filters, order_by="created_at", desc=True, limit=SEARCH_SCAN)
    if query:
        rows = [r for r in rows if address_matches(query, r.get("address_key") or "")]
    if sort == "likes":
        counts = like_counts(db, [str(r["id"]) for r in rows])
        rows = sorted(rows, key=lambda r: counts.get(str(r["id"]), 0), reverse=True)   # 안정 정렬: 같으면 최신순 유지
    return rows[:limit]


def like_counts(db: Any, post_ids: list[str]) -> dict[str, int]:
    if not post_ids:
        return {}
    counts: dict[str, int] = {}
    for r in db.select(LIKES, {"post_id": [str(p) for p in post_ids]}):
        key = str(r["post_id"])
        counts[key] = counts.get(key, 0) + 1
    return counts


def liked_post_ids(db: Any, user: Any, post_ids: list[str]) -> set[str]:
    if not post_ids:
        return set()
    rows = db.select(LIKES, {"post_id": [str(p) for p in post_ids], "profile_id": user.profile_id})
    return {str(r["post_id"]) for r in rows}


def nicknames(admin_db: Any, profile_ids: list[str]) -> dict[str, str]:
    ids = sorted({str(p) for p in profile_ids if p})
    if not ids:
        return {}
    try:
        rows = admin_db.select("profiles", {"id": ids})
    except Exception as exc:   # 닉네임을 못 읽어도 목록은 보여 준다
        logger.warning("nickname lookup failed: %s", type(exc).__name__)
        return {}
    return {str(r["id"]): r.get("nickname") or UNKNOWN_NICKNAME for r in rows}


def photos_by_post(db: Any, post_ids: list[str]) -> dict[str, dict]:
    if not post_ids:
        return {}
    rows = db.select(PHOTOS, {"post_id": [str(p) for p in post_ids]})
    return {str(r["post_id"]): r for r in rows}


def _summary_fields(row: dict, user: Any, names: dict[str, str], has_photo: bool,
                    like_count: int = 0, liked_by_me: bool = False) -> dict:
    pid = str(row.get("profile_id"))
    return {
        "id": str(row["id"]),
        "address": row["address"],
        "floor": row.get("floor"),
        "topic": row["topic"],
        "visit_date": row.get("visit_date"),
        "title": row["title"],
        "nickname": names.get(pid, UNKNOWN_NICKNAME),
        "is_mine": pid == str(user.profile_id),
        "has_photo": has_photo,
        "like_count": like_count,
        "liked_by_me": liked_by_me,
        "created_at": row["created_at"],
        "updated_at": row.get("updated_at") or row["created_at"],
    }


def to_summaries(db: Any, admin_db: Any, user: Any, rows: list[dict]) -> list[PostSummaryOut]:
    names = nicknames(admin_db, [r.get("profile_id") for r in rows])
    ids = [str(r["id"]) for r in rows]
    photos = photos_by_post(db, ids)
    counts = like_counts(db, ids)
    liked = liked_post_ids(db, user, ids)
    return [PostSummaryOut(**_summary_fields(r, user, names, str(r["id"]) in photos,
                                             counts.get(str(r["id"]), 0), str(r["id"]) in liked))
            for r in rows]


def to_photo_out(row: dict, storage: Storage, access_token: str) -> PostPhotoOut:
    ttl = int(settings.SIGNED_URL_TTL_SEC)
    expires_at = _now() + dt.timedelta(seconds=ttl)
    try:
        url = storage.signed_url(row["storage_path"], ttl, access_token)
    except StorageError as exc:
        logger.warning("community signed_url failed: %s", exc)
        url, expires_at = None, None
    return PostPhotoOut(id=str(row["id"]), content_type=row["content_type"], size_bytes=int(row["size_bytes"]),
                        url=url, url_expires_at=expires_at)


def to_post_out(db: Any, admin_db: Any, user: Any, row: dict, storage: Storage) -> PostOut:
    pid = str(row["id"])
    names = nicknames(admin_db, [row.get("profile_id")])
    photo = photos_by_post(db, [pid]).get(pid)
    return PostOut(
        **_summary_fields(row, user, names, photo is not None,
                          like_count_of(db, pid), pid in liked_post_ids(db, user, [pid])),
        body=row["body"],
        photo=to_photo_out(photo, storage, user.access_token) if photo else None,
    )


# ------------------------------------------------------------------ 쓰기
def create_post(db: Any, user: Any, body: PostIn) -> dict:
    check_contact(body.title, body.body)
    address = normalize_address(body.address)
    now = _now()
    row = {
        "profile_id": user.profile_id,
        "address": address,
        "address_key": address_key(address),
        "floor": body.floor,
        "topic": body.topic,
        "visit_date": body.visit_date,
        "title": body.title,
        "body": body.body,
        "created_at": now,
        "updated_at": now,
    }
    return db.insert(POSTS, row)[0]


def update_post(db: Any, user: Any, post_id: Any, body: PostUpdateIn) -> dict:
    post = get_own_post(db, user, post_id)
    fields = body.model_fields_set
    check_contact(body.title if "title" in fields else None, body.body if "body" in fields else None)
    values: dict[str, Any] = {}
    for name in ("topic", "title", "body", "floor", "visit_date"):
        if name in fields:
            values[name] = getattr(body, name)
    if "address" in fields:
        values["address"] = normalize_address(body.address or "")
        values["address_key"] = address_key(values["address"])
    if not values:
        return post
    values["updated_at"] = _now()
    rows = db.update(POSTS, {"id": str(post["id"])}, values)
    return rows[0] if rows else {**post, **values}


def delete_files(storage: Storage, paths: list[str], access_token: str) -> None:
    """실패하면 503 CLEANUP_FAILED(호출한 쪽은 DB 행을 지우지 않는다)."""
    paths = [p for p in paths if p]
    if not paths:
        return
    try:
        storage.delete(paths, access_token)
    except StorageError as exc:
        logger.warning("community photo cleanup failed: %s", exc)
        raise AppError(503, "CLEANUP_FAILED",
                       "사진 파일을 지우지 못해 삭제를 멈췄습니다. 잠시 후 다시 삭제해 주세요.") from None


def delete_post(db: Any, user: Any, post_id: Any, storage: Storage) -> None:
    post = get_own_post(db, user, post_id)
    photos = db.select(PHOTOS, {"post_id": str(post["id"])})
    delete_files(storage, [p["storage_path"] for p in photos], user.access_token)
    db.delete(PHOTOS, {"post_id": str(post["id"])})
    db.delete(POSTS, {"id": str(post["id"])})   # 좋아요는 DB의 ON DELETE CASCADE로 함께 지워진다


# ------------------------------------------------------------------ 좋아요
def like_count_of(db: Any, post_id: str) -> int:
    return like_counts(db, [post_id]).get(str(post_id), 0)


def _like_out(db: Any, user: Any, post_id: str) -> PostLikeOut:
    return PostLikeOut(post_id=post_id, like_count=like_count_of(db, post_id),
                       liked_by_me=post_id in liked_post_ids(db, user, [post_id]))


def like_post(db: Any, user: Any, post_id: Any) -> PostLikeOut:
    """누르기. 이미 눌렀으면 그대로 둔다(여러 번 보내도 1번). 내 글이면 403."""
    post = get_post(db, post_id)
    if str(post.get("profile_id")) == str(user.profile_id):
        raise own_post_like()
    pid = str(post["id"])
    if not liked_post_ids(db, user, [pid]):
        try:
            db.insert(LIKES, {"post_id": pid, "profile_id": user.profile_id})
        except UniqueViolation:   # 동시에 두 번 눌러 이미 들어간 경우
            pass
    return _like_out(db, user, pid)


def unlike_post(db: Any, user: Any, post_id: Any) -> PostLikeOut:
    """취소. 누른 적이 없어도 오류 없이 현재 상태를 준다."""
    post = get_post(db, post_id)
    pid = str(post["id"])
    db.delete(LIKES, {"post_id": pid, "profile_id": user.profile_id})
    return _like_out(db, user, pid)


def build_storage_path(auth_user_id: str, post_id: str, photo_id: str, content_type: str) -> str:
    return f"{auth_user_id}/community/{post_id}/{photo_id}.{ALLOWED_TYPES[content_type]}"
