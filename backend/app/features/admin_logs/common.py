"""admin_logs 공통 도우미: 시각 처리, profile_id 가림, 운영자 요청 판별, 로그 행 변환."""

from __future__ import annotations

import datetime as dt
from typing import Any, Iterable

from app.core.schemas import RequestLogOut

UTC = dt.timezone.utc
ADMIN_PREFIX = "/admin"
MASK_VISIBLE = 4  # profile_id 앞 4자리만 보인다


def parse_ts(value: Any) -> dt.datetime | None:
    """ISO 문자열·datetime → UTC aware datetime. 시간대가 없으면 UTC로 본다."""
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        t = value
    else:
        t = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    return t.astimezone(UTC)


def now_utc() -> dt.datetime:
    return dt.datetime.now(UTC)


def mask_profile_id(profile_id: Any) -> str | None:
    """'1a2b3c4d-…' → '1a2b****'. None은 그대로."""
    if profile_id is None:
        return None
    s = str(profile_id)
    return s[:MASK_VISIBLE] + "****"


def is_admin_endpoint(endpoint: Any) -> bool:
    """`/admin`으로 시작하는 요청(운영자 화면이 부른 요청)인지."""
    e = str(endpoint or "")
    return e == ADMIN_PREFIX or e.startswith(ADMIN_PREFIX + "/")


def to_log_out(row: dict) -> RequestLogOut:
    """request_logs 행 → 응답 모델(profile_id 가림)."""
    data = {k: row.get(k) for k in RequestLogOut.model_fields}
    data["profile_id"] = mask_profile_id(row.get("profile_id"))
    if data.get("created_at") is None:
        data["created_at"] = now_utc()
    if data.get("request_id") is None:
        data["request_id"] = ""
    return RequestLogOut.model_validate(data)


def log_payload(row: dict) -> dict:
    """SSE data로 보낼 JSON 사전."""
    return to_log_out(row).model_dump(mode="json")


ID_CHUNK = 200   # IN 조건 한 번에 넣는 id 수(요청 URL 길이 제한 대비)


def chunks(items: list[str], n: int = ID_CHUNK) -> Iterable[list[str]]:
    for i in range(0, len(items), n):
        yield items[i:i + n]


def select_in(db: Any, table: str, column: str, ids: list[str], extra: dict | None = None) -> list[dict]:
    """column IN ids 조회를 ID_CHUNK개씩 나눠서. ids가 비면 []."""
    out: list[dict] = []
    for part in chunks(ids):
        out.extend(db.select(table, {column: part, **(extra or {})}))
    return out
