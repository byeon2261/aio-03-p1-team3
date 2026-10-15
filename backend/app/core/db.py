"""DB 어댑터 (Supabase PostgREST).

    db.select("listings", {"session_id": sid}, order_by="listing_no")
    db.insert("tour_sessions", {"profile_id": pid, "title": "토요일"})   # dict 또는 list[dict]
    db.update("listings", {"id": lid}, {"memo_text": text})
    db.delete("listings", {"id": lid})

filters 값 규칙
    값             → 같음(eq)
    list/tuple(값들) → IN   (빈 리스트는 결과 없음)
    ("gte"|"lte"|"gt"|"lt", v) → 비교
    ("is", None) 또는 None → IS NULL
모든 메서드는 list[dict]를 돌려준다. date·datetime·UUID 값은 ISO 문자열로 바꿔 보낸다.

get_user_db  : 사용자 토큰 + publishable key → RLS 적용
get_admin_db : secret key → RLS 무시. profiles 생성·닉네임, request_logs, eval_*에만 쓴다.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any, Protocol

from fastapi import Depends

from app.core.auth import CurrentUser, get_current_user
from app.core.config import settings
from app.core.errors import AppError

COMPARE_OPS = ("gte", "lte", "gt", "lt")


class UniqueViolation(Exception):
    """unique 제약 위반(Postgres 23505)."""


class Database(Protocol):
    def select(self, table: str, filters: dict | None = None, *, order_by: str | None = None,
               desc: bool = False, limit: int | None = None) -> list[dict]: ...
    def insert(self, table: str, rows: dict | list[dict]) -> list[dict]: ...
    def update(self, table: str, filters: dict, values: dict) -> list[dict]: ...
    def delete(self, table: str, filters: dict) -> list[dict]: ...


def to_json_value(v: Any) -> Any:
    """DB로 보내기 전에 값을 JSON 친화 형태로 바꾼다(MemoryDatabase도 같은 규칙을 쓴다)."""
    if isinstance(v, dt.datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=dt.timezone.utc)
        return v.isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, dict):
        return {k: to_json_value(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [to_json_value(x) for x in v]
    if hasattr(v, "model_dump"):
        return to_json_value(v.model_dump(mode="json"))
    return v


def classify_filter(value: Any) -> tuple[str, Any]:
    """filters 값 하나를 (연산, 값)으로 바꾼다. 연산: eq / in / gte·lte·gt·lt / is."""
    if value is None:
        return "is", None
    if isinstance(value, tuple) and len(value) == 2 and value[0] in COMPARE_OPS + ("is",):
        op, v = value
        return op, to_json_value(v)
    if isinstance(value, (list, tuple, set)):
        return "in", [to_json_value(x) for x in value]
    return "eq", to_json_value(value)


class SupabaseDatabase:
    def __init__(self, client: Any):
        self._client = client

    def _apply(self, q: Any, filters: dict | None) -> tuple[Any, bool]:
        for col, raw in (filters or {}).items():
            op, v = classify_filter(raw)
            if op == "eq":
                q = q.eq(col, v)
            elif op == "in":
                if not v:
                    return q, True  # 빈 IN → 결과 없음
                q = q.in_(col, v)
            elif op == "is":
                q = q.is_(col, "null")
            else:
                q = getattr(q, op)(col, v)
        return q, False

    def _run(self, q: Any) -> list[dict]:
        from postgrest.exceptions import APIError

        try:
            res = q.execute()
        except APIError as exc:
            if getattr(exc, "code", None) == "23505":
                raise UniqueViolation(getattr(exc, "message", "unique violation")) from None
            raise
        return list(res.data or [])

    def select(self, table, filters=None, *, order_by=None, desc=False, limit=None):
        q, empty = self._apply(self._client.table(table).select("*"), filters)
        if empty:
            return []
        if order_by:
            q = q.order(order_by, desc=desc)
        if limit is not None:
            q = q.limit(limit)
        return self._run(q)

    def insert(self, table, rows):
        payload = to_json_value(rows if isinstance(rows, list) else [rows])
        if not payload:
            return []
        return self._run(self._client.table(table).insert(payload))

    def update(self, table, filters, values):
        if not filters:
            raise ValueError("update에는 filters가 필요합니다")
        q, empty = self._apply(self._client.table(table).update(to_json_value(values)), filters)
        return [] if empty else self._run(q)

    def delete(self, table, filters):
        if not filters:
            raise ValueError("delete에는 filters가 필요합니다")
        q, empty = self._apply(self._client.table(table).delete(), filters)
        return [] if empty else self._run(q)


def _make_client(key: str, access_token: str | None = None):
    from supabase import ClientOptions, create_client

    headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}
    return create_client(
        settings.SUPABASE_URL,
        key,
        options=ClientOptions(headers=headers, auto_refresh_token=False, persist_session=False,
                              postgrest_client_timeout=15, storage_client_timeout=30),
    )


_admin_db: SupabaseDatabase | None = None


def get_admin_db() -> Database:
    global _admin_db
    settings.require("SUPABASE_URL", "SUPABASE_SECRET_KEY")
    if _admin_db is None:
        _admin_db = SupabaseDatabase(_make_client(settings.SUPABASE_SECRET_KEY))
    return _admin_db


def get_user_db(user: CurrentUser = Depends(get_current_user)) -> Database:
    settings.require("SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY")
    return SupabaseDatabase(_make_client(settings.SUPABASE_PUBLISHABLE_KEY, user.access_token))


def is_valid_uuid(value: Any) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, TypeError, AttributeError):
        return False


__all__ = [
    "Database", "SupabaseDatabase", "UniqueViolation", "get_user_db", "get_admin_db",
    "to_json_value", "classify_filter", "is_valid_uuid", "AppError",
]
