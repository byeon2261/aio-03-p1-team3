"""Supabase Storage 어댑터. 버킷은 비공개 `listing-photos` 하나.

경로 규칙: "{auth_user_id}/{listing_id}/{파일이름}" — 첫 폴더가 auth.uid()여야 RLS를 통과한다.
사용자 토큰(access_token)으로 부르므로 남의 폴더는 읽기·쓰기·삭제할 수 없다.
실패는 모두 StorageError로 던진다(삭제 정리 실패는 기능에서 503 CLEANUP_FAILED로 바꾼다).
"""

from __future__ import annotations

from typing import Protocol

from app.core.config import settings

BUCKET = "listing-photos"


class StorageError(Exception):
    """Storage 호출 실패. 메시지에 토큰을 넣지 않는다."""


class Storage(Protocol):
    def upload(self, path: str, data: bytes, content_type: str, access_token: str) -> None: ...
    def signed_url(self, path: str, ttl_sec: int, access_token: str) -> str: ...
    def delete(self, paths: list[str], access_token: str) -> None: ...


class SupabaseStorage:
    def _bucket(self, access_token: str):
        settings.require("SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY")
        from app.core.db import _make_client

        return _make_client(settings.SUPABASE_PUBLISHABLE_KEY, access_token).storage.from_(BUCKET)

    def upload(self, path: str, data: bytes, content_type: str, access_token: str) -> None:
        try:
            self._bucket(access_token).upload(path, data, {"content-type": content_type, "upsert": "false"})
        except StorageError:
            raise
        except Exception as exc:
            raise StorageError(f"upload failed: {type(exc).__name__}") from None

    def signed_url(self, path: str, ttl_sec: int, access_token: str) -> str:
        try:
            res = self._bucket(access_token).create_signed_url(path, int(ttl_sec))
        except Exception as exc:
            raise StorageError(f"signed_url failed: {type(exc).__name__}") from None
        url = (res or {}).get("signedURL") or (res or {}).get("signedUrl")
        if not url:
            raise StorageError("signed_url failed: empty")
        return url

    def delete(self, paths: list[str], access_token: str) -> None:
        if not paths:
            return
        try:
            self._bucket(access_token).remove(list(paths))
        except Exception as exc:
            raise StorageError(f"delete failed: {type(exc).__name__}") from None


_storage: SupabaseStorage | None = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        _storage = SupabaseStorage()
    return _storage
