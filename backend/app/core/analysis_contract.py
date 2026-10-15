"""분석 계약. AI 출력 모델, 저장 모델, 파이프라인 등록.

P2가 AnalysisPipeline을 구현해 register_pipeline으로 등록한다. 다른 대화창은 get_pipeline()으로 쓴다.
AnalysisResult는 build_result(ai_output)로 만든다(서버가 네 목록을 계산).
"""

from __future__ import annotations

import hashlib
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field, model_validator

from app.core.errors import AppError

SCHEMA_VERSION = "1"

CHECKLIST = ("채광", "소음", "수압", "곰팡이", "난방", "층수", "옵션", "보안", "교통")
CHECK_STATUSES = ("confirmed", "unchecked", "ambiguous")

ChecklistItem = Literal[CHECKLIST]
CheckStatus = Literal[CHECK_STATUSES]


class CheckItem(BaseModel):
    item: ChecklistItem = Field(description="체크리스트 항목 이름. 정해진 9개 중 하나만 쓴다.")
    status: CheckStatus = Field(
        description=(
            "confirmed: 메모에 긍정이든 부정이든 분명히 적혀 있음('곰팡이 없음'도 confirmed). "
            "unchecked: 사용자가 '확인 못함', '못 봤음'처럼 확인하지 못했다고 씀. "
            "ambiguous: 적혀 있지만 해석을 확정하기 어려움."
        )
    )
    evidence: str = Field(description="판정 근거가 된 메모 원문 구절을 그대로 옮긴다. 지어내지 않는다.")


class AnalysisAIOutput(BaseModel):
    """AI가 채우는 모델. Gemini 응답 스키마로도 쓴다."""

    label: str = Field(description="메모 속 매물 이름(예: '역앞 원룸'). 이름이 없으면 '매물 N' 형식으로 쓴다.")
    deposit_manwon: int | None = Field(
        default=None,
        description="보증금, 만원 단위 정수. '500에 45'는 보증금 500·월세 45. 메모에 없으면 null. 추측하지 않는다.",
    )
    monthly_rent_manwon: int | None = Field(default=None, description="월세, 만원 단위 정수. 언급이 없으면 null.")
    maintenance_fee_manwon: int | None = Field(
        default=None, description="관리비, 만원 단위 정수. 언급이 없으면 null. '관리비 없음'이면 0."
    )
    maintenance_includes: list[str] = Field(
        default_factory=list, description="관리비에 포함된다고 메모에 적힌 항목(예: 수도, 인터넷). 없으면 빈 목록."
    )
    transit: str | None = Field(default=None, description="교통 정보(역·버스까지 거리 등) 원문 요약. 없으면 null.")
    floor: str | None = Field(default=None, description="층수(예: '3층', '반지하'). 없으면 null.")
    direction: str | None = Field(default=None, description="방향(예: '남향'). 없으면 null.")
    pros: list[str] = Field(default_factory=list, description="메모에 적힌 장점. 메모에 없는 내용은 넣지 않는다.")
    cons: list[str] = Field(
        default_factory=list,
        description="메모에 적힌 단점. '곰팡이 없음'처럼 나쁜 것이 없다는 부정 표현은 단점이 아니다.",
    )
    checks: list[CheckItem] = Field(
        default_factory=list,
        description="메모에 언급된 체크리스트 항목만 넣는다. 언급이 없는 항목은 넣지 않는다.",
    )
    ambiguous: list[str] = Field(
        default_factory=list, description="해석이 애매하거나 서로 충돌하는 메모 원문 구절 목록."
    )
    mixed_listings: bool = Field(
        default=False,
        description=(
            "메모에 집이 둘 이상 섞여 있으면 true. 이때 어느 집 값인지 갈리는 값(금액·교통·층수·방향)은 "
            "null로 두고 그 구절을 ambiguous에 넣는다."
        ),
    )


class AnalysisResult(AnalysisAIOutput):
    """저장 모델(analyses.result_json). 아래 네 목록은 서버가 계산한다(AI는 채우지 않는다).
    네 목록은 서로 겹치지 않고, 합치면 CHECKLIST 전체다."""

    confirmed_checks: list[str] = Field(default_factory=list)
    unchecked: list[str] = Field(default_factory=list)
    ambiguous_checks: list[str] = Field(default_factory=list)
    missing_checks: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _partition(self) -> "AnalysisResult":
        groups = [self.confirmed_checks, self.unchecked, self.ambiguous_checks, self.missing_checks]
        flat = [x for g in groups for x in g]
        if len(flat) != len(set(flat)) or set(flat) != set(CHECKLIST):
            raise ValueError("confirmed_checks·unchecked·ambiguous_checks·missing_checks는 CHECKLIST를 겹침 없이 나눠야 합니다")
        return self


def classify_checks(checks: list[CheckItem]) -> dict[str, list[str]]:
    """CheckItem 목록 → 네 목록. 한 항목에 상태가 여럿이면 ambiguous. 순서는 CHECKLIST 순."""
    by_item: dict[str, set[str]] = {}
    for c in checks:
        by_item.setdefault(c.item, set()).add(c.status)
    out = {"confirmed_checks": [], "unchecked": [], "ambiguous_checks": [], "missing_checks": []}
    for name in CHECKLIST:
        statuses = by_item.get(name)
        if not statuses:
            out["missing_checks"].append(name)
        elif len(statuses) > 1 or "ambiguous" in statuses:
            out["ambiguous_checks"].append(name)
        elif "confirmed" in statuses:
            out["confirmed_checks"].append(name)
        else:
            out["unchecked"].append(name)
    return out


def build_result(ai: AnalysisAIOutput) -> AnalysisResult:
    return AnalysisResult(**ai.model_dump(), **classify_checks(ai.checks))


SCHEMA_REGISTRY: dict[str, type[BaseModel]] = {SCHEMA_VERSION: AnalysisResult}

EDITABLE_FIELDS = (
    "deposit_manwon", "monthly_rent_manwon", "maintenance_fee_manwon",
    "maintenance_includes", "transit", "floor", "direction", "pros", "cons",
)
EVAL_FIELDS = (
    "deposit_manwon", "monthly_rent_manwon", "maintenance_fee_manwon",
    "maintenance_includes", "unchecked", "missing_checks", "floor", "direction",
)


def memo_hash(text: str | None) -> str:
    return hashlib.sha256(((text or "").strip() + SCHEMA_VERSION).encode("utf-8")).hexdigest()


def needs_reanalysis(listing: dict | None, analysis: dict | None) -> bool:
    """최신 분석이 있고 그 memo_hash가 지금 메모의 해시와 다르면 True. 분석이 없으면 False."""
    if not listing or not analysis:
        return False
    return analysis.get("memo_hash") != memo_hash(listing.get("memo_text"))


class AnalysisOutcome(BaseModel):
    result: AnalysisResult | None = None
    raw_output: str | None = None          # AI 응답 원문. 재시도했으면 시도별로 이어 붙인다
    ai_latency_ms: int | None = None
    status: Literal["success", "failed"]
    error_code: str | None = None          # 실패 시 AI_FORMAT_ERROR / AI_TIMEOUT / AI_RATE_LIMITED 등
    cache_hit: bool = False
    prompt_version: str
    model: str
    thinking_level: str | None = None


@runtime_checkable
class AnalysisPipeline(Protocol):
    async def run(self, memo_text: str, prompt_version: str, *, use_cache: bool = True,
                  cache_scope: str | None = None) -> AnalysisOutcome:
        """cache_scope는 캐시를 나누는 값(P2 라우터가 auth_user_id). None이면 캐시를 읽지도 쓰지도 않는다."""
        ...


_pipeline: Any = None


def register_pipeline(pipeline: Any) -> None:
    global _pipeline
    _pipeline = pipeline


def get_pipeline() -> AnalysisPipeline:
    if _pipeline is None:
        raise AppError(503, "CONFIG_MISSING", "분석 기능이 아직 준비되지 않았습니다.")
    return _pipeline


def reset_pipeline() -> None:
    """테스트용."""
    global _pipeline
    _pipeline = None
