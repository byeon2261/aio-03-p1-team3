"""F9 응답 모델. core/schemas.py의 모델을 상속해 필드를 더한다(공통 2절, REPORT에 적음)."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from app.core.schemas import EvalResultOut, EvalResultsOut, EvalRunOut


class EvalRunSummaryOut(EvalRunOut):
    """실행 한 건 + 집계. failure_counts는 NUM·HAL·MIS·CHK·FMT별 사례 수."""

    failure_counts: dict[str, int] = Field(default_factory=dict)
    result_count: int = 0          # 지금까지 저장된 사례 결과 수(진행 상태 표시용)
    error_case_count: int = 0      # 형식 실패가 아닌 AI 오류(시간 초과·한도 등)로 끝난 사례 수


class EvalResultDetailOut(EvalResultOut):
    """사례 한 건의 결과. compare_* 는 compare_to 실행의 같은 사례(case_id로 짝지음)."""

    case_id: str
    memo_text: str | None = None
    criteria: str | None = None
    expected_json: dict[str, Any] | None = None
    mixed_listings_match: bool | None = None
    compare_output_json: dict[str, Any] | None = None
    compare_mixed_listings_match: bool | None = None


class EvalCompareOut(EvalResultsOut):
    run: EvalRunSummaryOut
    compare_run: EvalRunSummaryOut | None = None
    results: list[EvalResultDetailOut] = Field(default_factory=list)
    condition_mismatches: list[str] = Field(default_factory=list)
