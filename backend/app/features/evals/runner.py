"""평가 실행: 사례 고르기 → eval_runs 'running' 행 → 사례를 차례로 돌려 저장 → 지표와 'done'.

라우터(BackgroundTasks)와 scripts/run_eval.py가 같은 함수를 쓴다.
- 파이프라인은 get_pipeline()으로 받고 use_cache=False, cache_scope=None으로 부른다.
- 호출 사이에 settings.GEMINI_MIN_INTERVAL_SEC만큼 쉰다(무료 등급 한도 대비).
- model·thinking_level·schema_version은 settings와 SCHEMA_VERSION에서 기록한다.
- 예외가 나면 'failed'와 error_message(메모 원문 없이 오류 종류와 사례 key만).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from typing import Any, Callable

from app.core.analysis_contract import SCHEMA_VERSION, AnalysisOutcome, get_pipeline
from app.core.config import settings
from app.core.errors import AppError
from app.features.evals.metrics import STATUS_SUCCESS, CaseScore, aggregate, score_case

logger = logging.getLogger("app.features.evals")

CASE_ORDER = "case_key"
# 이 시간보다 오래 'running'인 실행은 멈춘 것으로 보고 새 실행을 막지 않는다(서버 재시작 등)
STALE_RUNNING_MINUTES = 30
ERROR_MESSAGE_MAX_CHARS = 300


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _parse_ts(value: Any) -> dt.datetime | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        t = value
    else:
        t = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def select_cases(db: Any, case_keys: list[str] | None = None) -> list[dict]:
    """case_keys가 None이면 전체. 없는 key가 있으면 422, 고를 사례가 없으면 409."""
    if case_keys is not None:
        keys = sorted({k.strip() for k in case_keys if k and k.strip()})
        if not keys:
            raise AppError(422, "VALIDATION_ERROR", "실행할 사례 key를 하나 이상 고르세요.")
        cases = db.select("eval_cases", {"case_key": keys}, order_by=CASE_ORDER)
        unknown = sorted(set(keys) - {c["case_key"] for c in cases})
        if unknown:
            raise AppError(422, "VALIDATION_ERROR", "기준 세트에 없는 사례가 있습니다.", {"unknown_case_keys": unknown})
    else:
        cases = db.select("eval_cases", order_by=CASE_ORDER)
    if not cases:
        raise AppError(409, "EVAL_CASES_EMPTY",
                       "기준 세트가 비어 있습니다. scripts/load_eval_cases.py로 사례를 먼저 넣으세요.")
    return cases


def ensure_no_active_run(db: Any, now: dt.datetime | None = None) -> None:
    """최근에 시작해 아직 'running'인 실행이 있으면 409(무료 등급 한도 보호)."""
    now = now or utcnow()
    limit = now - dt.timedelta(minutes=STALE_RUNNING_MINUTES)
    for run in db.select("eval_runs", {"status": "running"}):
        started = _parse_ts(run.get("created_at"))
        if started is None or started >= limit:
            raise AppError(409, "EVAL_RUN_IN_PROGRESS", "이미 진행 중인 평가 실행이 있습니다. 끝난 뒤 다시 실행하세요.",
                           {"run_id": str(run.get("id"))})


def create_run(db: Any, prompt_version: str, cases: list[dict]) -> dict:
    return db.insert("eval_runs", {
        "prompt_version": prompt_version,
        "model": settings.GEMINI_MODEL,
        "thinking_level": settings.GEMINI_THINKING_LEVEL,
        "schema_version": SCHEMA_VERSION,
        "status": "running",
        "case_count": len(cases),
    })[0]


def outcome_to_output(outcome: AnalysisOutcome) -> tuple[str, dict | None]:
    """파이프라인 결과 → (eval_results.status, output_json).

    status: 성공이면 'success', 실패면 파이프라인 오류 코드(AI_FORMAT_ERROR·AI_TIMEOUT …).
    성공인데 result가 없으면 형식 실패로 본다.
    """
    if outcome.status == "success" and outcome.result is not None:
        return STATUS_SUCCESS, outcome.result.model_dump(mode="json")
    if outcome.status == "success":
        return "AI_FORMAT_ERROR", None
    code = outcome.error_code or "AI_FORMAT_ERROR"
    return code, None


def describe_error(exc: BaseException, case_key: str | None) -> str:
    """error_message. 예외 메시지에는 메모 원문이 섞일 수 있어 쓰지 않는다(AppError는 우리 문구라 씀)."""
    where = f" (사례 {case_key})" if case_key else ""
    if isinstance(exc, AppError):
        text = f"{exc.code}: {exc.message}{where}"
    else:
        text = f"{type(exc).__name__}{where}"
    return text[:ERROR_MESSAGE_MAX_CHARS]


def _expected_of(case: dict) -> dict:
    return case.get("expected_json") or {}


async def execute_run(
    db: Any,
    run_id: str,
    cases: list[dict],
    prompt_version: str,
    *,
    pipeline: Any = None,
    interval_sec: float | None = None,
    on_progress: Callable[[int, int, dict, CaseScore], None] | None = None,
) -> dict:
    """사례를 차례로 돌려 eval_results에 저장하고 실행 행을 마무리한다. 마지막 실행 행을 돌려준다."""
    interval = settings.GEMINI_MIN_INTERVAL_SEC if interval_sec is None else interval_sec
    current_key: str | None = None
    try:
        pipeline = pipeline or get_pipeline()
        scores: list[CaseScore] = []
        for i, case in enumerate(cases):
            current_key = case.get("case_key")
            if i > 0 and interval and interval > 0:
                await asyncio.sleep(interval)
            outcome = await pipeline.run(case["memo_text"], prompt_version, use_cache=False, cache_scope=None)
            status, output = outcome_to_output(outcome)
            score = score_case(_expected_of(case), output, status)
            db.insert("eval_results", {
                "run_id": run_id,
                "case_id": case["id"],
                "output_json": output,
                "status": status,
                "field_matches": score.field_matches,
                "failure_codes": score.failure_codes,
            })
            scores.append(score)
            if on_progress:
                on_progress(i + 1, len(cases), case, score)
        current_key = None
        values = {"status": "done", "finished_at": utcnow(), "case_count": len(cases), **aggregate(scores)}
        return db.update("eval_runs", {"id": run_id}, values)[0]
    except Exception as exc:  # noqa: BLE001 — 실행 실패는 행에 기록하고 끝낸다
        logger.warning("eval run failed run_id=%s error=%s case=%s", run_id, type(exc).__name__, current_key)
        try:
            rows = db.update("eval_runs", {"id": run_id}, {
                "status": "failed", "finished_at": utcnow(), "error_message": describe_error(exc, current_key),
            })
            return rows[0] if rows else {"id": run_id, "status": "failed"}
        except Exception as exc2:  # noqa: BLE001
            logger.error("eval run status update failed run_id=%s error=%s", run_id, type(exc2).__name__)
            return {"id": run_id, "status": "failed"}
