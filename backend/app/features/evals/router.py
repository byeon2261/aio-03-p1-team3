"""F9 개선 전후 비교 API. 모두 require_admin, admin db(eval_* 테이블은 secret key 전용).

    POST /admin/eval-runs                         EvalRunCreateIn → EvalRunSummaryOut('running')
    GET  /admin/eval-runs                         → list[EvalRunSummaryOut]
    GET  /admin/eval-runs/{run_id}/results        ?compare_to=<run_id> → EvalCompareOut
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request

from app.core.analysis_contract import get_pipeline
from app.core.auth import CurrentUser, require_admin
from app.core.db import get_admin_db
from app.core.errors import AppError
from app.core.request_log import set_log_fields
from app.core.schemas import EvalRunCreateIn
from app.features.evals import queries, runner
from app.features.evals.schemas import EvalCompareOut, EvalRunSummaryOut

router = APIRouter(prefix="/admin/eval-runs", tags=["evals"])


@router.post("", response_model=EvalRunSummaryOut)
async def create_eval_run(
    body: EvalRunCreateIn,
    request: Request,
    background_tasks: BackgroundTasks,
    admin: CurrentUser = Depends(require_admin),
    db: Any = Depends(get_admin_db),
) -> EvalRunSummaryOut:
    pipeline = get_pipeline()                       # 등록 전이면 503 CONFIG_MISSING(실행 행을 만들지 않음)
    prompt_version = body.prompt_version.strip()
    if not prompt_version:
        raise AppError(422, "VALIDATION_ERROR", "프롬프트 버전을 고르세요.")
    set_log_fields(request, prompt_version=prompt_version)
    cases = runner.select_cases(db, body.case_keys)
    runner.ensure_no_active_run(db)
    run = runner.create_run(db, prompt_version, cases)
    background_tasks.add_task(runner.execute_run, db, str(run["id"]), cases, prompt_version, pipeline=pipeline)
    return queries.summarize_run(run, [])


@router.get("", response_model=list[EvalRunSummaryOut])
def list_eval_runs(
    admin: CurrentUser = Depends(require_admin),
    db: Any = Depends(get_admin_db),
) -> list[EvalRunSummaryOut]:
    return queries.list_runs(db)


@router.get("/{run_id}/results", response_model=EvalCompareOut)
def get_eval_results(
    run_id: str,
    compare_to: str | None = Query(default=None),
    admin: CurrentUser = Depends(require_admin),
    db: Any = Depends(get_admin_db),
) -> EvalCompareOut:
    return queries.run_results(db, run_id, compare_to or None)
