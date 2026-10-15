"""F10 사진 공통 처리. photos 라우터·hooks와 mypage가 함께 쓴다.

- 형식 검사: 파일 앞부분(매직 바이트)으로 실제 형식을 판단한다. 브라우저가 보낸 Content-Type은 믿지 않는다.
- 저장 경로: "{auth_user_id}/{listing_id}/{photo_id}.{ext}" (첫 폴더 = auth.uid(), Storage RLS 조건)
- 응답에는 서명 URL만 담는다. storage_path·공개 주소는 내보내지 않는다.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from app.core.config import settings
from app.core.errors import AppError
from app.core.schemas import MyPhotoOut, PhotoOut
from app.core.storage import Storage, StorageError

logger = logging.getLogger("app.features.photos")

# 실제 형식 → 확장자
ALLOWED_TYPES: dict[str, str] = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
# Storage 삭제 한 번에 보낼 경로 수
DELETE_CHUNK = 100


def max_photo_bytes() -> int:
    return int(settings.MAX_PHOTO_MB) * 1024 * 1024


def sniff_content_type(data: bytes) -> str | None:
    """파일 앞부분으로 jpeg·png·webp를 가린다. 그 밖의 형식이면 None."""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _invalid(reason: str, message: str) -> AppError:
    return AppError(422, "VALIDATION_ERROR", message, {
        "reason": reason,
        "allowed_types": list(ALLOWED_TYPES),
        "max_mb": int(settings.MAX_PHOTO_MB),
    })


def validate_photo(data: bytes) -> str:
    """검사를 통과하면 실제 content_type을 돌려준다. 어기면 422 VALIDATION_ERROR(detail.reason)."""
    if not data:
        raise _invalid("empty_file", "빈 파일입니다. 사진 파일을 다시 고르세요.")
    if len(data) > max_photo_bytes():
        raise _invalid("too_large", f"사진은 한 장에 {int(settings.MAX_PHOTO_MB)}MB 이하만 올릴 수 있습니다.")
    content_type = sniff_content_type(data)
    if content_type is None:
        raise _invalid("unsupported_type", "JPG·PNG·WEBP 사진만 올릴 수 있습니다.")
    return content_type


def build_storage_path(auth_user_id: str, listing_id: str, photo_id: str, content_type: str) -> str:
    return f"{auth_user_id}/{listing_id}/{photo_id}.{ALLOWED_TYPES[content_type]}"


def _signed(storage: Storage, path: str, access_token: str) -> tuple[str | None, dt.datetime | None]:
    """서명 URL과 만료 시각. 만들지 못하면 (None, None) — 목록 전체를 실패시키지 않는다."""
    ttl = int(settings.SIGNED_URL_TTL_SEC)
    expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=ttl)  # 호출 전 시각 기준(보수적)
    try:
        return storage.signed_url(path, ttl, access_token), expires_at
    except StorageError as exc:
        logger.warning("signed_url failed: %s", exc)
        return None, None


def to_photo_out(row: dict[str, Any], storage: Storage, access_token: str) -> PhotoOut:
    url, expires_at = _signed(storage, row["storage_path"], access_token)
    return PhotoOut(
        id=str(row["id"]),
        listing_id=str(row["listing_id"]),
        content_type=row["content_type"],
        size_bytes=int(row["size_bytes"]),
        visibility=row.get("visibility") or "private",
        created_at=row["created_at"],
        url=url,
        url_expires_at=expires_at,
    )


def to_my_photo_out(row: dict[str, Any], listing: dict[str, Any], session: dict[str, Any],
                    storage: Storage, access_token: str) -> MyPhotoOut:
    base = to_photo_out(row, storage, access_token)
    return MyPhotoOut(
        **base.model_dump(),
        session_id=str(session["id"]),
        session_title=session.get("title") or "",
        listing_no=int(listing["listing_no"]),
    )


def delete_files(storage: Storage, paths: list[str], access_token: str) -> None:
    """Storage 파일 삭제. 실패하면 503 CLEANUP_FAILED(호출한 쪽은 DB 행을 지우지 않는다)."""
    paths = [p for p in paths if p]
    for i in range(0, len(paths), DELETE_CHUNK):
        try:
            storage.delete(paths[i:i + DELETE_CHUNK], access_token)
        except StorageError as exc:
            logger.warning("photo cleanup failed: %s (count=%d)", exc, len(paths))
            raise AppError(503, "CLEANUP_FAILED",
                           "사진 파일을 지우지 못해 삭제를 멈췄습니다. 잠시 후 다시 삭제해 주세요.") from None
