"""request_logs 조회 (GET /admin/logs, 스트림 재전송, 지표 계산용 기간 조회)."""

from __future__ import annotations

import datetime as dt
from typing import Any

from app.core.errors import AppError
from app.features.admin_logs.common import is_admin_endpoint, parse_ts

LOG_TABLE = "request_logs"
DEFAULT_LIMIT = 100
MAX_LIMIT = 500
MAX_PAGES = 10                 # /admin 요청을 걸러 내느라 부족할 때 더 가져오는 최대 횟수
METRIC_ROW_CAP = 50_000        # 지표 계산 때 한 번에 가져오는 최대 행 수
STATUS_CHOICES = ("success", "error", "4xx", "5xx")


def status_filter(status: str | None) -> Any:
    """status 질의값 → status_code 필터. 없으면 None.

    success: < 400, error: ≥ 400, 4xx: 400~499, 5xx: ≥ 500, 숫자: 그 코드만.
    """
    if status is None or status == "" or status == "all":
        return None
    s = status.strip().lower()
    if s == "success":
        return ("lt", 400)
    if s == "error":
        return ("gte", 400)
    if s == "4xx":
        return list(range(400, 500))
    if s == "5xx":
        return ("gte", 500)
    if s.isdigit() and 100 <= int(s) <= 599:
        return int(s)
    raise AppError(422, "VALIDATION_ERROR", "status는 success·error·4xx·5xx 또는 숫자 상태 코드로 주세요.",
                   {"fields": [{"loc": ["query", "status"], "type": "value_error", "msg": "허용하지 않는 값"}]})


def _base_filters(*, status: str | None, prompt_version: str | None) -> dict:
    filters: dict = {}
    sf = status_filter(status)
    if sf is not None:
        filters["status_code"] = sf
    if prompt_version:
        filters["prompt_version"] = prompt_version
    return filters


def list_logs(db: Any, *, from_: dt.datetime | None = None, to: dt.datetime | None = None,
              status: str | None = None, prompt_version: str | None = None, after_id: int | None = None,
              limit: int = DEFAULT_LIMIT, include_admin: bool = False) -> list[dict]:
    """조건에 맞는 로그 행. after_id가 없으면 최신순(id 내림차순), 있으면 id 오름차순.

    - 필터 사전은 열마다 조건 하나라서 created_at은 읽는 방향 쪽 경계만 DB에 걸고
      반대쪽 경계는 Python에서 본다(id 순서 ≈ 시각 순서이므로 경계를 넘으면 멈춘다).
    - /admin 요청은 DB 필터로 뺄 수 없어(접두어 불일치 조건 없음) Python에서 거르고,
      모자라면 id 커서로 더 가져온다(최대 MAX_PAGES번).
    """
    limit = max(1, min(int(limit), MAX_LIMIT))
    ascending = after_id is not None
    base = _base_filters(status=status, prompt_version=prompt_version)
    if ascending and from_ is not None:
        base["created_at"] = ("gte", from_)
    if not ascending and to is not None:
        base["created_at"] = ("lte", to)
    out: list[dict] = []
    cursor: int | None = after_id
    for _ in range(MAX_PAGES):
        filters = dict(base)
        if cursor is not None:
            filters["id"] = ("gt", cursor) if ascending else ("lt", cursor)
        batch = db.select(LOG_TABLE, filters, order_by="id", desc=not ascending, limit=limit)
        for row in batch:
            t = parse_ts(row.get("created_at"))
            if t is not None:
                if ascending and to is not None and t > to:
                    return out
                if not ascending and from_ is not None and t < from_:
                    return out
            if not include_admin and is_admin_endpoint(row.get("endpoint")):
                continue
            out.append(row)
            if len(out) >= limit:
                return out
        if len(batch) < limit:
            break
        ids = [r["id"] for r in batch if r.get("id") is not None]
        if not ids:
            break
        cursor = max(ids) if ascending else min(ids)
    return out


def logs_after(db: Any, after_id: int, *, before_id: int | None = None, limit: int = MAX_LIMIT) -> list[dict]:
    """after_id < id (< before_id) 인 로그를 id 오름차순으로(스트림 재전송·빈 구간 채우기)."""
    rows = db.select(LOG_TABLE, {"id": ("gt", after_id)}, order_by="id", limit=limit)
    if before_id is not None:
        rows = [r for r in rows if r.get("id") is not None and r["id"] < before_id]
    return rows


def logs_in_period(db: Any, *, from_: dt.datetime, to: dt.datetime, prompt_version: str | None = None,
                   include_admin: bool = False, cap: int = METRIC_ROW_CAP) -> tuple[list[dict], bool]:
    """지표 계산용 기간 행 (행 목록, 잘렸는지)."""
    filters: dict = {"created_at": ("gte", from_)}
    if prompt_version:
        filters["prompt_version"] = prompt_version
    rows = db.select(LOG_TABLE, filters, order_by="created_at", limit=cap + 1)
    truncated = len(rows) > cap
    rows = rows[:cap]
    rows = [r for r in rows if (parse_ts(r.get("created_at")) or to) <= to]
    if not include_admin:
        rows = [r for r in rows if not is_admin_endpoint(r.get("endpoint"))]
    return rows, truncated
