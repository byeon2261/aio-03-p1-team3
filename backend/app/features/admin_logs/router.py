"""F8 운영 API. 모두 require_admin(일반 사용자 403).

GET /admin/logs           요청 로그 조회(최신순, after_id가 있으면 id 오름차순). profile_id는 앞 4자리만.
GET /admin/logs/stream    SSE(event "log", id = 로그 id). Last-Event-ID 뒤의 DB 로그를 먼저 보낸다.
GET /admin/metrics        지표(MetricsOut, 상세는 extra. docs/METRICS.md)
GET /admin/feedback       낮은 평가 사례(분석별 최신 평가 기준)
"""

from __future__ import annotations

import datetime as dt
from collections.abc import AsyncIterable
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.core.auth import CurrentUser, require_admin
from app.core.broker import get_broker
from app.core.db import Database, get_admin_db
from app.core.errors import AppError
from app.core.schemas import MetricsOut, RequestLogOut
from app.features.admin_logs.common import now_utc, parse_ts, to_log_out
from app.features.admin_logs.feedback_cases import DEFAULT_LIMIT as FB_DEFAULT, MAX_LIMIT as FB_MAX
from app.features.admin_logs.feedback_cases import FeedbackCaseOut, list_feedback_cases
from app.features.admin_logs.metrics import compute_metrics
from app.features.admin_logs.queries import DEFAULT_LIMIT, MAX_LIMIT, list_logs
from app.features.admin_logs.stream import log_event_stream

router = APIRouter(prefix="/admin", tags=["admin"])

DEFAULT_METRIC_WINDOW = dt.timedelta(hours=24)

FromQ = Annotated[dt.datetime | None, Query(alias="from", description="시작 시각(ISO 8601, 시간대 없으면 UTC)")]
ToQ = Annotated[dt.datetime | None, Query(description="끝 시각(ISO 8601, 시간대 없으면 UTC)")]


def _range_error() -> AppError:
    return AppError(422, "VALIDATION_ERROR", "시작 시각이 끝 시각보다 늦습니다. 기간을 다시 고르세요.",
                    {"fields": [{"loc": ["query", "from"], "type": "value_error", "msg": "from > to"}]})


def _normalize(from_: dt.datetime | None, to: dt.datetime | None) -> tuple[dt.datetime | None, dt.datetime | None]:
    f, t = parse_ts(from_), parse_ts(to)
    if f is not None and t is not None and f > t:
        raise _range_error()
    return f, t


def require_live_broker() -> None:
    """실시간 저장소가 없으면 스트림을 열기 전에 503(스트림이 시작된 뒤에는 상태 코드를 바꿀 수 없다)."""
    if get_broker() is None:
        raise AppError(503, "KV_UNAVAILABLE", "실시간 로그를 받을 수 없습니다(임시 저장소 없음).")


@router.get("/logs", response_model=list[RequestLogOut])
def get_logs(
    from_: FromQ = None,
    to: ToQ = None,
    status: Annotated[str | None, Query(description="success·error·4xx·5xx 또는 숫자 코드")] = None,
    prompt_version: str | None = None,
    after_id: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    include_admin: bool = False,
    admin: CurrentUser = Depends(require_admin),
    db: Database = Depends(get_admin_db),
) -> list[RequestLogOut]:
    f, t = _normalize(from_, to)
    rows = list_logs(db, from_=f, to=t, status=status, prompt_version=prompt_version or None,
                     after_id=after_id, limit=limit, include_admin=include_admin)
    return [to_log_out(r) for r in rows]


@router.get("/logs/stream", response_class=EventSourceResponse)
async def stream_logs(
    last_event_id: Annotated[int | None, Header()] = None,
    admin: CurrentUser = Depends(require_admin),
    db: Database = Depends(get_admin_db),
    _live: None = Depends(require_live_broker),
) -> AsyncIterable[ServerSentEvent]:
    # 1) last_event_id 뒤의 DB 로그 → 2) 새 로그. 15초 연결 유지 신호는 FastAPI가 보낸다.
    async for event in log_event_stream(db, last_event_id):
        yield event


@router.get("/metrics", response_model=MetricsOut)
def get_metrics(
    from_: FromQ = None,
    to: ToQ = None,
    prompt_version: str | None = None,
    include_admin: bool = False,
    admin: CurrentUser = Depends(require_admin),
    db: Database = Depends(get_admin_db),
) -> MetricsOut:
    f, t = _normalize(from_, to)
    t = t or now_utc()
    f = f or (t - DEFAULT_METRIC_WINDOW)
    if f > t:
        raise _range_error()
    return compute_metrics(db, from_=f, to=t, prompt_version=prompt_version or None, include_admin=include_admin)


@router.get("/feedback", response_model=list[FeedbackCaseOut])
def get_feedback(
    rating: Literal["up", "down"] = "down",
    limit: Annotated[int, Query(ge=1, le=FB_MAX)] = FB_DEFAULT,
    admin: CurrentUser = Depends(require_admin),
    db: Database = Depends(get_admin_db),
) -> list[FeedbackCaseOut]:
    return list_feedback_cases(db, rating=rating, limit=limit)
