"""Supabase Auth 어댑터. 서버만 Supabase Auth를 부른다(publishable key).

테스트에서는 tests.fakes.FakeAuthProvider로 바꾼다(`app.dependency_overrides[get_auth_provider]`).
모든 메서드는 실패 시 AppError를 던진다.
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx
from pydantic import BaseModel

from app.core.config import settings
from app.core.errors import AppError


class AuthSession(BaseModel):
    access_token: str
    refresh_token: str
    expires_at: int          # Unix 초(UTC)
    auth_user_id: str
    email: str | None = None


class SignUpResult(BaseModel):
    needs_email_confirm: bool
    auth_user_id: str | None = None
    email: str | None = None
    session: AuthSession | None = None


class AuthProvider(Protocol):
    def sign_up(self, email: str, password: str) -> SignUpResult: ...
    def sign_in(self, email: str, password: str) -> AuthSession: ...
    def sign_out(self, access_token: str) -> None: ...
    def refresh(self, refresh_token: str) -> AuthSession: ...
    def verify(self, access_token: str) -> dict[str, Any]:
        """유효하면 JWT claims(sub, email, role, exp …). 아니면 401 AUTH_REQUIRED."""
        ...
    def update_password(self, access_token: str, new_password: str) -> None: ...


def _invalid_token() -> AppError:
    return AppError(401, "AUTH_REQUIRED", "로그인이 필요합니다. 다시 로그인해 주세요.")


def _map_auth_error(exc: Exception) -> AppError:
    code = getattr(exc, "code", None)
    status = getattr(exc, "status", None)
    if code == "invalid_credentials":
        return AppError(401, "INVALID_CREDENTIALS", "이메일 또는 비밀번호가 맞지 않습니다.")
    if code == "email_not_confirmed":
        return AppError(403, "EMAIL_NOT_CONFIRMED", "메일 확인 후 로그인하세요.")
    if code in ("refresh_token_not_found", "refresh_token_already_used", "session_not_found",
                "bad_jwt", "session_expired"):
        return _invalid_token()
    if code in ("user_already_exists", "email_exists"):
        return AppError(422, "VALIDATION_ERROR", "이미 가입된 이메일입니다. 로그인해 주세요.", {"reason": code})
    if code == "weak_password":
        return AppError(422, "VALIDATION_ERROR", "비밀번호가 너무 약합니다. 더 길게 정해 주세요.", {"reason": code})
    if code and "rate_limit" in str(code):
        return AppError(422, "VALIDATION_ERROR", "요청이 많습니다. 잠시 후 다시 시도해 주세요.", {"reason": code})
    if status and 400 <= int(status) < 500:
        return AppError(422, "VALIDATION_ERROR", "입력값을 확인해 주세요.", {"reason": code})
    return AppError(503, "CONFIG_MISSING", "인증 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.")


def _to_session(session: Any, user: Any = None) -> AuthSession:
    u = user or getattr(session, "user", None)
    return AuthSession(
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        expires_at=int(session.expires_at or 0),
        auth_user_id=str(u.id) if u else "",
        email=getattr(u, "email", None) if u else None,
    )


class SupabaseAuthProvider:
    """요청마다 새 클라이언트를 만든다(서버 쪽 세션 상태를 남기지 않기 위해)."""

    def _client(self):
        settings.require("SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY")
        from supabase import ClientOptions, create_client

        return create_client(
            settings.SUPABASE_URL,
            settings.SUPABASE_PUBLISHABLE_KEY,
            options=ClientOptions(auto_refresh_token=False, persist_session=False),
        )

    def sign_up(self, email: str, password: str) -> SignUpResult:
        try:
            res = self._client().auth.sign_up({"email": email, "password": password})
        except AppError:
            raise
        except Exception as exc:  # supabase_auth.errors.AuthError 등
            raise _map_auth_error(exc) from None
        user = res.user
        if res.session is None:
            return SignUpResult(needs_email_confirm=True, auth_user_id=str(user.id) if user else None,
                                email=getattr(user, "email", None))
        return SignUpResult(needs_email_confirm=False, auth_user_id=str(user.id), email=user.email,
                            session=_to_session(res.session, user))

    def sign_in(self, email: str, password: str) -> AuthSession:
        try:
            res = self._client().auth.sign_in_with_password({"email": email, "password": password})
        except AppError:
            raise
        except Exception as exc:
            raise _map_auth_error(exc) from None
        return _to_session(res.session, res.user)

    def sign_out(self, access_token: str) -> None:
        try:
            # POST /auth/v1/logout (사용자 JWT). scope=local: 이 기기의 세션만 끝낸다
            self._client().auth.admin.sign_out(access_token, scope="local")
        except AppError:
            raise
        except Exception:
            pass  # 이미 만료된 토큰이어도 로그아웃은 성공으로 본다

    def refresh(self, refresh_token: str) -> AuthSession:
        try:
            res = self._client().auth.refresh_session(refresh_token)
        except AppError:
            raise
        except Exception as exc:
            mapped = _map_auth_error(exc)
            raise (_invalid_token() if mapped.status != 503 else mapped) from None
        if res.session is None:
            raise _invalid_token()
        return _to_session(res.session, res.user)

    def verify(self, access_token: str) -> dict[str, Any]:
        try:
            res = self._client().auth.get_claims(access_token)
        except AppError:
            raise
        except Exception:
            raise _invalid_token() from None
        if not res or not res.get("claims") or not res["claims"].get("sub"):
            raise _invalid_token()
        return dict(res["claims"])

    def update_password(self, access_token: str, new_password: str) -> None:
        # Supabase Auth REST: PUT /auth/v1/user (사용자 JWT로 본인 비밀번호 변경)
        settings.require("SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY")
        url = settings.SUPABASE_URL.rstrip("/") + "/auth/v1/user"
        try:
            r = httpx.put(
                url,
                headers={"apikey": settings.SUPABASE_PUBLISHABLE_KEY, "Authorization": f"Bearer {access_token}"},
                json={"password": new_password},
                timeout=15,
            )
        except httpx.HTTPError:
            raise AppError(503, "CONFIG_MISSING", "인증 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.") from None
        if r.status_code == 401:
            raise _invalid_token()
        if r.status_code >= 400:
            try:
                body = r.json()
            except ValueError:
                body = {}

            class _E(Exception):
                pass

            e = _E()
            e.code = body.get("error_code") or body.get("code")
            e.status = r.status_code
            raise _map_auth_error(e)


_provider: AuthProvider | None = None


def get_auth_provider() -> AuthProvider:
    global _provider
    if _provider is None:
        _provider = SupabaseAuthProvider()
    return _provider
