"""F12 요청·응답 모델. 공통 core/schemas.py는 건드리지 않고 이 폴더에 둔다.

항목별 값은 {item_key, 값} 목록(nested 모델)으로 주고받는다.
- 요청: SCORE_ITEMS에 없는 항목·같은 항목 두 번은 422 VALIDATION_ERROR.
- 응답: 항상 SCORE_ITEMS 전체를 그 순서로 준다(가중치 행 없음 = 0, 만족도 행 없음 = null).
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field, field_validator

from app.features.scoring.items import SCORE_ITEMS

NAME_MAX_CHARS = 30


def _check_item_keys(items: list) -> list:
    seen: set[str] = set()
    for it in items:
        if it.item_key not in SCORE_ITEMS:
            raise ValueError(f"알 수 없는 항목입니다. 쓸 수 있는 항목: {', '.join(SCORE_ITEMS)}")
        if it.item_key in seen:
            raise ValueError("같은 항목이 두 번 들어 있습니다.")
        seen.add(it.item_key)
    return items


# ------------------------------------------------------------------ 평가 항목
class ScoreItemsOut(BaseModel):
    items: list[str] = Field(examples=[list(SCORE_ITEMS)])   # SCORE_ITEMS 순서


# ------------------------------------------------------------------ 가중치 프로필
class WeightItemIn(BaseModel):
    item_key: str = Field(examples=["채광"])
    weight: int = Field(ge=0, le=100, examples=[50])


class WeightItemOut(BaseModel):
    item_key: str
    weight: int


class WeightProfileIn(BaseModel):
    """만들기·고치기 공통. weights에 빠진 항목은 가중치 0. 고치기는 통째로 바꾼다."""

    name: str = Field(min_length=1, max_length=NAME_MAX_CHARS, examples=["여름 6개월"])
    weights: list[WeightItemIn] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("프로필 이름을 입력하세요.")
        return v

    @field_validator("weights")
    @classmethod
    def _keys(cls, v: list[WeightItemIn]) -> list[WeightItemIn]:
        return _check_item_keys(v)


class WeightProfileOut(BaseModel):
    id: str
    name: str
    weights: list[WeightItemOut]
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None


# ------------------------------------------------------------------ 매물 만족도
class SatisfactionItemIn(BaseModel):
    item_key: str = Field(examples=["채광"])
    satisfaction: int = Field(ge=0, le=100, examples=[90])


class SatisfactionItemOut(BaseModel):
    item_key: str
    satisfaction: int | None = None   # None = 미입력


class SatisfactionIn(BaseModel):
    """통째로 바꾼다. items에 빠진 항목은 미입력이 된다. 빈 목록 = 전부 비우기."""

    items: list[SatisfactionItemIn] = Field(default_factory=list)

    @field_validator("items")
    @classmethod
    def _keys(cls, v: list[SatisfactionItemIn]) -> list[SatisfactionItemIn]:
        return _check_item_keys(v)


class SatisfactionOut(BaseModel):
    listing_id: str
    items: list[SatisfactionItemOut]
    entered_count: int
    updated_at: dt.datetime | None = None   # 입력한 적 없으면 None


# ------------------------------------------------------------------ 세션 설정
class ScoringSettingIn(BaseModel):
    enabled: bool = Field(examples=[True])
    weight_profile_id: str | None = Field(default=None, description="null = 동일 가중치")


class ScoringSettingOut(BaseModel):
    session_id: str
    enabled: bool = True
    weight_profile_id: str | None = None
    weight_profile_name: str | None = None
    updated_at: dt.datetime | None = None   # 설정한 적 없으면 None
    items: list[str] = Field(default_factory=lambda: list(SCORE_ITEMS))   # 평가 항목(화면이 입력칸을 그릴 때 씀)


# ------------------------------------------------------------------ 점수·순위
class ScoreRow(BaseModel):
    listing_id: str
    listing_no: int
    label: str
    score: int | None = None        # None = 만족도 미입력
    rank: int | None = None         # 이 응답의 rows 안에서의 순위
    entered_count: int = 0
    total_items: int = 0


class ScoresOut(BaseModel):
    session_id: str
    setting: ScoringSettingOut
    items: list[str]
    rows: list[ScoreRow]           # 꺼져 있으면 빈 목록. 순위 → 매물 번호 순
    hidden_count: dict[str, int] = Field(default_factory=dict)   # 필터별 숨긴 매물 수


__all__ = [
    "ScoreItemsOut", "WeightItemIn", "WeightItemOut", "WeightProfileIn", "WeightProfileOut",
    "SatisfactionItemIn", "SatisfactionItemOut", "SatisfactionIn", "SatisfactionOut",
    "ScoringSettingIn", "ScoringSettingOut", "ScoreRow", "ScoresOut", "NAME_MAX_CHARS",
]
