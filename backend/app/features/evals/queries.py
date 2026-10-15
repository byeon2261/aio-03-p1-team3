"""조회: 실행 목록 집계, 사례별 결과와 compare_to 짝짓기."""

from __future__ import annotations

from typing import Any

from app.core.db import is_valid_uuid
from app.core.errors import AppError
from app.features.evals.metrics import (
    FORMAT_ERROR_CODES,
    STATUS_SUCCESS,
    condition_mismatches,
    failure_counts,
    mixed_listings_match,
    split_expected,
)
from app.features.evals.schemas import EvalCompareOut, EvalResultDetailOut, EvalRunSummaryOut

RUN_LIST_LIMIT = 50
STATUS_MISSING = "missing"   # compare_to 실행에만 있는 사례(이 실행에는 결과 없음)


def _is_ai_error(status: str | None) -> bool:
    return bool(status) and status != STATUS_SUCCESS and status not in FORMAT_ERROR_CODES


def summarize_run(run: dict, results: list[dict]) -> EvalRunSummaryOut:
    return EvalRunSummaryOut(
        **run,
        failure_counts=failure_counts(r.get("failure_codes") for r in results),
        result_count=len(results),
        error_case_count=sum(1 for r in results if _is_ai_error(r.get("status"))),
    )


def list_runs(db: Any, limit: int = RUN_LIST_LIMIT) -> list[EvalRunSummaryOut]:
    runs = db.select("eval_runs", order_by="created_at", desc=True, limit=limit)
    if not runs:
        return []
    results = db.select("eval_results", {"run_id": [r["id"] for r in runs]})
    by_run: dict[str, list[dict]] = {}
    for r in results:
        by_run.setdefault(str(r["run_id"]), []).append(r)
    return [summarize_run(run, by_run.get(str(run["id"]), [])) for run in runs]


def get_run(db: Any, run_id: str) -> dict:
    if not is_valid_uuid(run_id):
        raise AppError(404, "EVAL_RUN_NOT_FOUND", "평가 실행을 찾을 수 없습니다.")
    rows = db.select("eval_runs", {"id": run_id}, limit=1)
    if not rows:
        raise AppError(404, "EVAL_RUN_NOT_FOUND", "평가 실행을 찾을 수 없습니다.")
    return rows[0]


def _results_of(db: Any, run_id: str) -> list[dict]:
    return db.select("eval_results", {"run_id": run_id}, order_by="created_at")


def run_results(db: Any, run_id: str, compare_to: str | None = None) -> EvalCompareOut:
    run = get_run(db, run_id)
    results = _results_of(db, run_id)

    compare_run = None
    compare_results: list[dict] = []
    if compare_to:
        compare_run = get_run(db, compare_to)
        compare_results = _results_of(db, compare_to)

    case_ids = {str(r["case_id"]) for r in results} | {str(r["case_id"]) for r in compare_results}
    cases = {str(c["id"]): c for c in db.select("eval_cases", {"id": sorted(case_ids)})} if case_ids else {}
    compare_by_case = {str(r["case_id"]): r for r in compare_results}

    def detail(case_id: str, mine: dict | None, other: dict | None) -> EvalResultDetailOut:
        case = cases.get(case_id) or {}
        expected, criteria = split_expected(case.get("expected_json"))
        out = (mine or {}).get("output_json")
        item = EvalResultDetailOut(
            case_id=case_id,
            case_key=case.get("case_key") or "(삭제된 사례)",
            tags=list(case.get("tags") or []),
            memo_text=case.get("memo_text"),
            criteria=criteria,
            expected_json=expected,
            status=(mine or {}).get("status") or STATUS_MISSING,
            field_matches=(mine or {}).get("field_matches") or {},
            failure_codes=list((mine or {}).get("failure_codes") or []),
            output_json=out,
            mixed_listings_match=mixed_listings_match(expected, out),
        )
        if compare_run is not None:
            other_out = (other or {}).get("output_json")
            item.compare_status = (other or {}).get("status") or STATUS_MISSING
            item.compare_field_matches = (other or {}).get("field_matches") or ({} if other else None)
            item.compare_failure_codes = list((other or {}).get("failure_codes") or []) if other else None
            item.compare_output_json = other_out
            item.compare_mixed_listings_match = mixed_listings_match(expected, other_out)
        return item

    items: list[EvalResultDetailOut] = []
    seen: set[str] = set()
    for r in results:
        cid = str(r["case_id"])
        seen.add(cid)
        items.append(detail(cid, r, compare_by_case.get(cid)))
    for r in compare_results:   # 비교 실행에만 있는 사례도 보여 준다(사례 목록 차이)
        cid = str(r["case_id"])
        if cid not in seen:
            seen.add(cid)
            items.append(detail(cid, None, r))
    items.sort(key=lambda x: x.case_key)

    mismatches: list[str] = []
    if compare_run is not None:
        mismatches = condition_mismatches(run, compare_run,
                                          [r["case_id"] for r in results], [r["case_id"] for r in compare_results])

    return EvalCompareOut(
        run=summarize_run(run, results),
        compare_run=summarize_run(compare_run, compare_results) if compare_run is not None else None,
        results=items,
        condition_mismatches=mismatches,
    )
