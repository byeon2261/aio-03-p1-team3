"""마이페이지: PATCH /me · POST /me/password · GET /me/photos · GET /me/summary

GET /me는 R(features/auth)이 만들었다. 여기서는 같은 경로에 PATCH만 더한다.
"""

from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends, Request
from pydantic import ConfigDict, Field, field_validator

from app.core.auth import CurrentUser, get_current_user, mark_request_user
from app.core.auth_provider import AuthProvider, get_auth_provider
from app.core.db import Database, get_admin_db, get_user_db
from app.core.errors import AppError
from app.core.schemas import (
    PASSWORD_MIN_CHARS,
    MeUpdateIn,
    MyPhotoOut,
    MySummaryOut,
    OkOut,
    PasswordChangeIn,
    ProfileOut,
    SessionOut,
)
from app.core.storage import Storage, get_storage
from app.features.photos.service import to_my_photo_out

router = APIRouter(tags=["mypage"])

NICKNAME_MAX = 20          # 단계 파일 기준(계약 MeUpdateIn은 30) — REPORT 참고
RECENT_SESSIONS = 5


# ------------------------------------------------------------------ 요청·응답 모델(계약 모델 상속)
class NicknameUpdateIn(MeUpdateIn):
    """닉네임만 받는다. role 등 다른 값은 무시한다(extra=ignore)."""

    model_config = ConfigDict(extra="ignore")

    nickname: str = Field(min_length=1, max_length=NICKNAME_MAX)

    @field_validator("nickname", mode="before")
    @classmethod
    def _strip(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v

    @field_validator("nickname")
    @classmethod
    def _printable(cls, v: str) -> str:
        if not v.isprintable():
            raise ValueError("줄바꿈·제어 문자는 쓸 수 없습니다.")
        return v


class PasswordChangeWithCurrentIn(PasswordChangeIn):
    """현재 비밀번호 확인을 위해 current_password를 더했다."""

    current_password: str = Field(min_length=1, max_length=72)
    new_password: str = Field(min_length=PASSWORD_MIN_CHARS, max_length=72)


class MySummaryWithRecentOut(MySummaryOut):
    """최근 세션 5개를 더했다."""

    recent_sessions: list[SessionOut] = Field(default_factory=list)


# ------------------------------------------------------------------ 닉네임
@router.patch("/me", response_model=ProfileOut)
def update_me(
    body: NicknameUpdateIn,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    admin_db: Database = Depends(get_admin_db),
) -> ProfileOut:
    # 사용자 토큰은 profiles를 고칠 수 없으므로 admin db로 본인 행의 nickname 열만 고친다
    rows = admin_db.update("profiles", {"id": user.profile_id}, {"nickname": body.nickname})
    if not rows:
        raise AppError(401, "AUTH_REQUIRED", "로그인이 필요합니다.")
    mark_request_user(request, user)
    row = rows[0]
    return ProfileOut(id=str(row["id"]), nickname=row.get("nickname") or body.nickname,
                      role=row.get("role") or "user")


# ------------------------------------------------------------------ 비밀번호
@router.post("/me/password", response_model=OkOut)
def change_password(
    body: PasswordChangeWithCurrentIn,
    user: CurrentUser = Depends(get_current_user),
    provider: AuthProvider = Depends(get_auth_provider),
) -> OkOut:
    if body.new_password == body.current_password:
        raise AppError(422, "VALIDATION_ERROR", "새 비밀번호가 지금 비밀번호와 같습니다. 다른 비밀번호를 정하세요.",
                       {"reason": "same_password"})
    email = provider.verify(user.access_token).get("email")
    if not email:
        raise AppError(422, "VALIDATION_ERROR", "이메일로 가입한 계정만 비밀번호를 바꿀 수 있습니다.",
                       {"reason": "no_email"})

    # 현재 비밀번호 확인. 틀리면 provider가 401 INVALID_CREDENTIALS를 던진다
    check = provider.sign_in(email, body.current_password)
    try:
        provider.sign_out(check.access_token)   # 확인용으로 생긴 세션은 바로 끝낸다
    except AppError:
        pass

    provider.update_password(user.access_token, body.new_password)
    return OkOut()


# ------------------------------------------------------------------ 내 사진
@router.get("/me/photos", response_model=list[MyPhotoOut])
def my_photos(
    user: CurrentUser = Depends(get_current_user),
    db: Database = Depends(get_user_db),
    storage: Storage = Depends(get_storage),
) -> list[MyPhotoOut]:
    photos = db.select("photos", {"profile_id": user.profile_id}, order_by="created_at", desc=True)
    if not photos:
        return []
    listing_ids = sorted({str(p["listing_id"]) for p in photos})
    listings = {str(r["id"]): r for r in db.select("listings", {"id": listing_ids})}
    session_ids = sorted({str(r["session_id"]) for r in listings.values()})
    sessions = {
        str(r["id"]): r
        for r in db.select("tour_sessions", {"id": session_ids})
        if str(r.get("profile_id")) == str(user.profile_id)
    }
    out: list[MyPhotoOut] = []
    for p in photos:
        listing = listings.get(str(p["listing_id"]))
        session = sessions.get(str(listing["session_id"])) if listing else None
        if listing is None or session is None:
            continue  # 삭제 중인 매물 등
        out.append(to_my_photo_out(p, listing, session, storage, user.access_token))
    return out


# ------------------------------------------------------------------ 요약
@router.get("/me/summary", response_model=MySummaryWithRecentOut)
def my_summary(
    user: CurrentUser = Depends(get_current_user),
    db: Database = Depends(get_user_db),
) -> MySummaryWithRecentOut:
    sessions = db.select("tour_sessions", {"profile_id": user.profile_id}, order_by="created_at", desc=True)
    session_ids = [str(s["id"]) for s in sessions]
    listings = db.select("listings", {"session_id": session_ids}) if session_ids else []
    listing_ids = [str(r["id"]) for r in listings]
    analyses = db.select("analyses", {"listing_id": listing_ids}) if listing_ids else []
    photos = db.select("photos", {"profile_id": user.profile_id})
    feedback = db.select("feedback", {"profile_id": user.profile_id})

    per_session = Counter(str(r["session_id"]) for r in listings)
    recent = [
        SessionOut(id=str(s["id"]), title=s["title"], visit_date=s.get("visit_date"),
                   created_at=s["created_at"], listing_count=per_session.get(str(s["id"]), 0))
        for s in sessions[:RECENT_SESSIONS]
    ]
    return MySummaryWithRecentOut(
        session_count=len(sessions),
        listing_count=len(listings),
        analysis_count=len(analyses),
        photo_count=len(photos),
        feedback_count=len(feedback),
        recent_sessions=recent,
    )
