"""F11 예산 판정 상세 응답 모델. 공통 core/schemas.py는 건드리지 않고 이 폴더에 둔다(F12·F14와 같은 방식).

GET /sessions/{session_id}/budget/evaluations 응답에 쓴다.
판정(status·reason)은 service.evaluate 결과 그대로이고, next_action은 안내 문구일 뿐 판정을 바꾸지 않는다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

BudgetStatus = Literal["within", "over", "unknown"]


class BudgetCountsOut(BaseModel):
    """판정별 매물 수. 예산 미설정이면 모두 0."""

    within: int = Field(0, examples=[1])
    over: int = Field(0, examples=[2])
    unknown: int = Field(0, examples=[2])


class BudgetEvaluationOut(BaseModel):
    """매물 하나의 예산 판정과 다음 행동."""

    listing_id: str
    listing_no: int = Field(examples=[2])
    label: str = Field(examples=["2번 집"])
    status: BudgetStatus | None = Field(None, description="예산 미설정이면 null", examples=["unknown"])
    status_label: str = Field(examples=["판단 불가"], description="예산 안·예산 초과·판단 불가, 미설정이면 '-'")
    reason: str = Field(examples=["관리비 미기재"])
    missing: list[str] = Field(default_factory=list, description="unknown일 때 미기재 항목(보증금·월세·관리비)",
                               examples=[["관리비"]])
    next_action: str | None = Field(None, description="unknown일 때만. 무엇을 하면 판정되는지",
                                    examples=["관리비 17만원 이하면 예산 안"])


class BudgetEvaluationsOut(BaseModel):
    session_id: str
    budget_set: bool = Field(description="상한이 하나라도 있으면 true")
    counts: BudgetCountsOut
    items: list[BudgetEvaluationOut] = Field(default_factory=list, description="listing_no 오름차순")
