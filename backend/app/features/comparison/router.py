"""F6 매물 비교표: GET /sessions/{session_id}/comparison?filters=a,b"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from starlette.concurrency import run_in_threadpool

from app.core.auth import CurrentUser, get_current_user
from app.core.db import Database, get_user_db
from app.core.schemas import ComparisonOut
from app.features.comparison.service import build_comparison, parse_filters

router = APIRouter(tags=["comparison"])


@router.get("/sessions/{session_id}/comparison", response_model=ComparisonOut)
async def get_comparison(
    session_id: str,
    filters: str | None = Query(default=None, max_length=200, description="쉼표로 구분한 행 필터 이름(예: within_budget)"),
    user: CurrentUser = Depends(get_current_user),
    db: Database = Depends(get_user_db),
) -> ComparisonOut:
    return await run_in_threadpool(build_comparison, db, user, session_id, parse_filters(filters))
