"""analyses 행 → AnalysisOut 조립, previous_overrides 계산, 실패 코드 → HTTP 오류 변환."""

from __future__ import annotations

import json
from typing import Any

from app.core.analysis_contract import EDITABLE_FIELDS, SCHEMA_VERSION, AnalysisOutcome, CheckItem, memo_hash
from app.core.analysis_contract import needs_reanalysis as _needs_reanalysis
from app.core.errors import AppError
from app.core.repo import field_overrides, latest_rating
from app.core.schemas import AnalysisOut, FieldValue

DISPLAY_FIELDS = ("label",) + EDITABLE_FIELDS
FORMAT_CODES = {"FMT", "AI_FORMAT_ERROR"}
PREVIOUS_SCAN_LIMIT = 50

# outcome.error_code → (HTTP 상태, 응답 code, 메시지)
_FAILURE_HTTP = {
    "FMT": (502, "AI_FORMAT_ERROR", "AI 응답을 정리하지 못했습니다. 다시 시도해 주세요."),
    "AI_TIMEOUT": (504, "AI_TIMEOUT", "AI 응답이 늦습니다. 잠시 후 다시 시도해 주세요."),
    "AI_RATE_LIMITED": (429, "AI_RATE_LIMITED", "분석 요청이 많습니다. 잠시 후 다시 시도해 주세요."),
    "AI_UPSTREAM_ERROR": (502, "AI_UPSTREAM_ERROR", "AI 서비스에서 문제가 생겼습니다. 잠시 후 다시 시도해 주세요."),
}


def stored_error_code(outcome: AnalysisOutcome) -> str | None:
    """저장·로그용 오류 코드. 형식 실패는 FMT로 맞춘다."""
    if outcome.status == "success":
        return None
    code = outcome.error_code or "FMT"
    return "FMT" if code in FORMAT_CODES else code


def failure_error(code: str, analysis_id: str | None) -> AppError:
    status, http_code, message = _FAILURE_HTTP.get(code, (502, code, "AI 분석에 실패했습니다. 다시 시도해 주세요."))
    detail = {"analysis_id": analysis_id} if analysis_id else None
    return AppError(status, http_code, message, detail)


def analysis_row(listing_id: str, memo_text: str, outcome: AnalysisOutcome, latency_ms: int) -> dict:
    return {
        "listing_id": str(listing_id),
        "result_json": outcome.result.model_dump(mode="json") if outcome.result is not None else None,
        "schema_version": SCHEMA_VERSION,
        "prompt_version": outcome.prompt_version,
        "model": outcome.model,
        "thinking_level": outcome.thinking_level,
        "memo_hash": memo_hash(memo_text),
        "latency_ms": latency_ms,
        "ai_latency_ms": outcome.ai_latency_ms,
        "status": outcome.status,
        "error_code": stored_error_code(outcome),
        "raw_output": outcome.raw_output,
    }


def same_value(a: Any, b: Any) -> bool:
    """목록은 순서를 무시하고 비교한다."""
    if isinstance(a, list) and isinstance(b, list):
        key = lambda x: json.dumps(x, ensure_ascii=False, sort_keys=True)  # noqa: E731
        return sorted(a, key=key) == sorted(b, key=key)
    return a == b


def previous_overrides(db: Any, row: dict, current_overrides: dict, result: dict) -> dict[str, Any]:
    """같은 매물의 이전 성공 분석 중 수정값이 있는 가장 최근 분석의 수정값에서,
    이 분석에 이미 수정값이 있는 필드와 이 분석의 AI 값과 같은 필드를 뺀 것."""
    if row.get("status") != "success" or not row.get("created_at"):
        return {}
    earlier = db.select("analyses", {"listing_id": str(row["listing_id"]), "status": "success",
                                     "created_at": ("lt", row["created_at"])},
                        order_by="created_at", desc=True, limit=PREVIOUS_SCAN_LIMIT)
    source: dict[str, Any] = {}
    for prev in earlier:
        ov = field_overrides(db, prev["id"])
        if any(k in EDITABLE_FIELDS for k in ov):
            source = ov
            break
    return {
        k: v for k, v in source.items()
        if k in EDITABLE_FIELDS and k not in current_overrides and not same_value(v, result.get(k))
    }


def build_analysis_out(db: Any, listing: dict, row: dict) -> AnalysisOut:
    result = row.get("result_json") or {}
    success = row.get("status") == "success"
    overrides = field_overrides(db, row["id"]) if success else {}

    fields: dict[str, FieldValue] = {}
    if success:
        for name in DISPLAY_FIELDS:
            ai_value = result.get(name)
            edited = name in EDITABLE_FIELDS and name in overrides
            user_value = overrides[name] if edited else None
            fields[name] = FieldValue(ai_value=ai_value, user_value=user_value,
                                      value=user_value if edited else ai_value, edited=edited)

    return AnalysisOut(
        id=str(row["id"]),
        listing_id=str(row["listing_id"]),
        status=row["status"],
        error_code=row.get("error_code"),
        prompt_version=row["prompt_version"],
        model=row["model"],
        thinking_level=row.get("thinking_level"),
        schema_version=row["schema_version"],
        created_at=row["created_at"],
        fields=fields,
        checks=[CheckItem.model_validate(c) for c in result.get("checks") or []],
        confirmed_checks=list(result.get("confirmed_checks") or []),
        unchecked=list(result.get("unchecked") or []),
        ambiguous_checks=list(result.get("ambiguous_checks") or []),
        missing_checks=list(result.get("missing_checks") or []),
        ambiguous=list(result.get("ambiguous") or []),
        mixed_listings=bool(result.get("mixed_listings", False)),
        rating=latest_rating(db, row["id"]),
        needs_reanalysis=_needs_reanalysis(listing, row),
        previous_overrides=previous_overrides(db, row, overrides, result) if success else {},
    )
