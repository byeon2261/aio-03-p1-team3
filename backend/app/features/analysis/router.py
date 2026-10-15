"""F4·F5 분석 API.

POST /listings/{listing_id}/analyses         분석 실행 → AnalysisOut (실패도 analyses에 저장 후 오류 응답)
GET  /listings/{listing_id}/analyses/latest  최신 분석(성공·실패 무관) + 사용자 수정값 → AnalysisOut
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Body, Depends, Request
from starlette.concurrency import run_in_threadpool

from app.core.analysis_contract import get_pipeline
from app.core.auth import CurrentUser, get_current_user
from app.core.config import settings
from app.core.db import Database, get_user_db
from app.core.errors import AppError
from app.core.ownership import get_owned_listing
from app.core.repo import latest_analysis
from app.core.request_log import set_log_fields
from app.core.schemas import AnalysisCreateIn, AnalysisOut
from app.features.analysis.service import analysis_row, build_analysis_out, failure_error, stored_error_code

router = APIRouter(tags=["analysis"])


def _empty_memo_error() -> AppError:
    return AppError(422, "VALIDATION_ERROR", "메모가 비어 있습니다. 메모를 먼저 저장하세요.",
                    {"fields": [{"loc": ["memo_text"], "type": "empty", "msg": "메모가 비어 있음"}]})


@router.post("/listings/{listing_id}/analyses", response_model=AnalysisOut)
async def create_analysis(
    listing_id: str,
    request: Request,
    body: AnalysisCreateIn | None = Body(default=None),
    user: CurrentUser = Depends(get_current_user),
    db: Database = Depends(get_user_db),
) -> AnalysisOut:
    started = time.perf_counter()
    options = body or AnalysisCreateIn()
    listing = await run_in_threadpool(get_owned_listing, db, user, listing_id)
    memo_text = listing.get("memo_text") or ""
    if not memo_text.strip():
        raise _empty_memo_error()

    pipeline = get_pipeline()
    outcome = await pipeline.run(memo_text, settings.ACTIVE_PROMPT_VERSION,
                                 use_cache=options.use_cache, cache_scope=user.auth_user_id)

    error_code = stored_error_code(outcome)
    set_log_fields(request, ai_latency_ms=outcome.ai_latency_ms, prompt_version=outcome.prompt_version,
                   cache_hit=outcome.cache_hit)
    if error_code:
        set_log_fields(request, error_code=error_code)

    row = analysis_row(listing["id"], memo_text, outcome, int((time.perf_counter() - started) * 1000))
    saved = (await run_in_threadpool(db.insert, "analyses", row))[0]

    if outcome.status != "success":
        raise failure_error(error_code or "FMT", str(saved["id"]))
    return await run_in_threadpool(build_analysis_out, db, listing, saved)


@router.get("/listings/{listing_id}/analyses/latest", response_model=AnalysisOut)
async def get_latest_analysis(
    listing_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: Database = Depends(get_user_db),
) -> AnalysisOut:
    def _load() -> AnalysisOut:
        listing = get_owned_listing(db, user, listing_id)
        row = latest_analysis(db, listing["id"], status=None)
        if row is None:
            raise AppError(404, "ANALYSIS_NOT_FOUND", "분석 결과가 없습니다. 분석을 먼저 실행하세요.")
        return build_analysis_out(db, listing, row)

    return await run_in_threadpool(_load)
