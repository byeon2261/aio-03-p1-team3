"""현재 사용자.

    @router.get("/x")
    def x(user: CurrentUser = Depends(get_current_user)): ...
    def y(user: CurrentUser = Depends(require_admin)): ...

토큰 없음·무효 → 401 AUTH_REQUIRED, 관리자 아님 → 403 FORBIDDEN.
profiles 행이 없으면 admin db로 만든다(사용자 토큰에는 profiles 쓰기 권한이 없다).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.auth_provider import AuthProvider, get_auth_provider
from app.core.deps import resolve
from app.core.errors import AppError

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    auth_user_id: str
    profile_id: str
    role: str
    access_token: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def default_nickname(email: str | None) -> str:
    head = (email or "").split("@", 1)[0].strip()
    return head or "사용자"


def ensure_profile(admin_db: Any, auth_user_id: str, email: str | None) -> dict:
    """auth_user_id의 profiles 행을 돌려준다. 없으면 만든다(동시 생성은 unique 위반 후 다시 읽음)."""
    from app.core.db import UniqueViolation

    rows = admin_db.select("profiles", {"auth_user_id": auth_user_id}, limit=1)
    if rows:
        return rows[0]
    try:
        created = admin_db.insert("profiles", {"auth_user_id": auth_user_id, "nickname": default_nickname(email)})
        if created:
            return created[0]
    except UniqueViolation:
        pass
    rows = admin_db.select("profiles", {"auth_user_id": auth_user_id}, limit=1)
    if not rows:
        raise AppError(500, "INTERNAL_ERROR", "사용자 정보를 만들지 못했습니다. 잠시 후 다시 시도해 주세요.")
    return rows[0]


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    provider: AuthProvider = Depends(get_auth_provider),
) -> CurrentUser:
    if credentials is None or not credentials.credentials:
        raise AppError(401, "AUTH_REQUIRED", "로그인이 필요합니다.")
    token = credentials.credentials
    claims = provider.verify(token)
    auth_user_id = str(claims.get("sub") or "")
    if not auth_user_id:
        raise AppError(401, "AUTH_REQUIRED", "로그인이 필요합니다.")

    from app.core.db import get_admin_db

    admin_db = resolve(request.app, get_admin_db)
    profile = ensure_profile(admin_db, auth_user_id, claims.get("email"))
    user = CurrentUser(
        auth_user_id=auth_user_id,
        profile_id=str(profile["id"]),
        role=profile.get("role") or "user",
        access_token=token,
    )
    mark_request_user(request, user)
    return user


def mark_request_user(request: Request, user: CurrentUser) -> None:
    """요청 로그에 profile_id를 남기기 위해 요청 상태에 적는다."""
    request.scope.setdefault("state", {})["profile_id"] = user.profile_id


def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.role != "admin":
        raise AppError(403, "FORBIDDEN", "운영자만 볼 수 있습니다.")
    return user
