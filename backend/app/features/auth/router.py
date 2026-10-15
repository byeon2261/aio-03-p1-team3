"""F1 인증: /auth/signup · /auth/login · /auth/logout · /auth/refresh · GET /me"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool

from app.core.auth import CurrentUser, ensure_profile, get_current_user, mark_request_user
from app.core.auth_provider import AuthProvider, AuthSession, get_auth_provider
from app.core.db import Database, get_admin_db
from app.core.errors import AppError
from app.core.schemas import AuthTokensOut, LoginIn, OkOut, ProfileOut, RefreshIn, SignupIn, SignupOut

router = APIRouter(tags=["auth"])
_bearer = HTTPBearer(auto_error=False)


def _profile_out(row: dict) -> ProfileOut:
    return ProfileOut(id=str(row["id"]), nickname=row.get("nickname") or "사용자", role=row.get("role") or "user")


def _tokens(session: AuthSession, profile: dict) -> AuthTokensOut:
    return AuthTokensOut(access_token=session.access_token, refresh_token=session.refresh_token,
                         expires_at=session.expires_at, profile=_profile_out(profile))


def _remember(request: Request, profile: dict) -> None:
    request.scope.setdefault("state", {})["profile_id"] = str(profile["id"])


@router.post("/auth/signup", response_model=SignupOut)
async def signup(body: SignupIn, request: Request, provider: AuthProvider = Depends(get_auth_provider),
                 admin_db: Database = Depends(get_admin_db)) -> SignupOut:
    result = await run_in_threadpool(provider.sign_up, body.email, body.password)
    if result.needs_email_confirm or result.session is None:
        return SignupOut(needs_email_confirm=True)
    profile = await run_in_threadpool(ensure_profile, admin_db, result.session.auth_user_id, result.session.email)
    _remember(request, profile)
    t = _tokens(result.session, profile)
    return SignupOut(needs_email_confirm=False, **t.model_dump())


@router.post("/auth/login", response_model=AuthTokensOut)
async def login(body: LoginIn, request: Request, provider: AuthProvider = Depends(get_auth_provider),
                admin_db: Database = Depends(get_admin_db)) -> AuthTokensOut:
    session = await run_in_threadpool(provider.sign_in, body.email, body.password)
    profile = await run_in_threadpool(ensure_profile, admin_db, session.auth_user_id, session.email)
    _remember(request, profile)
    return _tokens(session, profile)


@router.post("/auth/refresh", response_model=AuthTokensOut)
async def refresh(body: RefreshIn, request: Request, provider: AuthProvider = Depends(get_auth_provider),
                  admin_db: Database = Depends(get_admin_db)) -> AuthTokensOut:
    session = await run_in_threadpool(provider.refresh, body.refresh_token)
    profile = await run_in_threadpool(ensure_profile, admin_db, session.auth_user_id, session.email)
    _remember(request, profile)
    return _tokens(session, profile)


@router.post("/auth/logout", response_model=OkOut)
async def logout(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
                 provider: AuthProvider = Depends(get_auth_provider)) -> OkOut:
    """토큰이 없거나 만료돼도 성공으로 답한다. 화면은 응답과 상관없이 토큰을 지운다."""
    if credentials and credentials.credentials:
        try:
            await run_in_threadpool(provider.sign_out, credentials.credentials)
        except AppError:
            pass
    return OkOut()


@router.get("/me", response_model=ProfileOut)
async def me(request: Request, user: CurrentUser = Depends(get_current_user),
             admin_db: Database = Depends(get_admin_db)) -> ProfileOut:
    rows = await run_in_threadpool(admin_db.select, "profiles", {"id": user.profile_id}, limit=1)
    if not rows:
        raise AppError(401, "AUTH_REQUIRED", "로그인이 필요합니다.")
    mark_request_user(request, user)
    return _profile_out(rows[0])
