"""소유 확인. 없거나 남의 것이면 404를 던진다(남의 리소스가 있다는 사실도 알리지 않는다).

    session = get_owned_session(db, user, session_id)
    listing = get_owned_listing(db, user, listing_id)      # listing["session"]에 세션 행
    analysis = get_owned_analysis(db, user, analysis_id)   # analysis["listing"]["session"]
    photo = get_owned_photo(db, user, photo_id)            # photo["listing"]["session"]

RLS가 걸린 user db에서도, admin db에서도 같은 결과가 나오도록 profile_id를 직접 비교한다.
"""

from __future__ import annotations

from typing import Any

from app.core.db import is_valid_uuid
from app.core.errors import AppError


def _nf(code: str, message: str) -> AppError:
    return AppError(404, code, message)


def _one(db: Any, table: str, row_id: Any) -> dict | None:
    if not is_valid_uuid(row_id):
        return None
    rows = db.select(table, {"id": str(row_id)}, limit=1)
    return rows[0] if rows else None


def get_owned_session(db: Any, user: Any, session_id: Any) -> dict:
    row = _one(db, "tour_sessions", session_id)
    if row is None or str(row.get("profile_id")) != str(user.profile_id):
        raise _nf("SESSION_NOT_FOUND", "세션을 찾을 수 없습니다.")
    return row


def get_owned_listing(db: Any, user: Any, listing_id: Any) -> dict:
    row = _one(db, "listings", listing_id)
    if row is None:
        raise _nf("LISTING_NOT_FOUND", "매물을 찾을 수 없습니다.")
    try:
        session = get_owned_session(db, user, row["session_id"])
    except AppError:
        raise _nf("LISTING_NOT_FOUND", "매물을 찾을 수 없습니다.") from None
    return {**row, "session": session}


def get_owned_analysis(db: Any, user: Any, analysis_id: Any) -> dict:
    row = _one(db, "analyses", analysis_id)
    if row is None:
        raise _nf("ANALYSIS_NOT_FOUND", "분석 결과를 찾을 수 없습니다.")
    try:
        listing = get_owned_listing(db, user, row["listing_id"])
    except AppError:
        raise _nf("ANALYSIS_NOT_FOUND", "분석 결과를 찾을 수 없습니다.") from None
    return {**row, "listing": listing}


def get_owned_photo(db: Any, user: Any, photo_id: Any) -> dict:
    row = _one(db, "photos", photo_id)
    if row is None or str(row.get("profile_id")) != str(user.profile_id):
        raise _nf("PHOTO_NOT_FOUND", "사진을 찾을 수 없습니다.")
    try:
        listing = get_owned_listing(db, user, row["listing_id"])
    except AppError:
        raise _nf("PHOTO_NOT_FOUND", "사진을 찾을 수 없습니다.") from None
    return {**row, "listing": listing}
