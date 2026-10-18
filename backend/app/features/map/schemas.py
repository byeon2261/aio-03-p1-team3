"""F13 내 매물 위치 모델."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


# ------------------------------------------------------------------ 내 매물 위치
_POSTAL_RE = r"^[0-9]{5}$"


class LocationIn(BaseModel):
    """매물 위치 저장. 도로명·지번 중 하나는 있어야 한다. 좌표는 화면의 카카오 지도 SDK가 바꾼 값."""

    road_address: str | None = Field(default=None, max_length=200, examples=["서울특별시 용산구 한강대로 366"])
    parcel_address: str | None = Field(default=None, max_length=200, examples=["서울특별시 용산구 동자동 56"])
    postal_code: str | None = Field(default=None, examples=["04323"])
    building_name: str | None = Field(default=None, max_length=100, examples=["트윈시티남산"])
    latitude: float = Field(ge=33.0, le=39.0, examples=[37.5511247])
    longitude: float = Field(ge=124.0, le=132.0, examples=[126.9729133])

    @field_validator("road_address", "parcel_address", "postal_code", "building_name", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("postal_code")
    @classmethod
    def _postal(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(_POSTAL_RE, value):
            raise ValueError("우편번호는 숫자 5자리입니다.")
        return value

    @model_validator(mode="after")
    def _has_address(self) -> "LocationIn":
        if not self.road_address and not self.parcel_address:
            raise ValueError("도로명주소나 지번주소 중 하나는 있어야 합니다.")
        return self


class LocationOut(BaseModel):
    road_address: str | None = None
    parcel_address: str | None = None
    postal_code: str | None = None
    building_name: str | None = None
    latitude: float
    longitude: float
    updated_at: datetime | None = None


class ListingLocationOut(BaseModel):
    listing_id: str
    location: LocationOut | None = Field(default=None, description="저장한 위치. 없으면 null")


class SessionPinOut(BaseModel):
    """세션 지도 핀. 금액은 최신 성공 분석 + 사용자 수정값(비교표와 같은 값), 없거나 미기재면 null."""

    listing_id: str
    listing_no: int = Field(examples=[1])
    label: str = Field(examples=["1번 집"])
    location: LocationOut
    deposit_manwon: int | None = Field(default=None, description="보증금(만원)", examples=[1000])
    monthly_rent_manwon: int | None = Field(default=None, description="월세(만원)", examples=[40])
    maintenance_fee_manwon: int | None = Field(default=None, description="관리비(만원)", examples=[7])
    analyzed: bool = Field(default=False, description="성공한 AI 분석이 있는지(없으면 금액이 모두 null)")


class MyPinOut(SessionPinOut):
    """전체 매물 지도 핀: 세션 핀 + 어느 세션의 매물인지."""

    session_id: str
    session_title: str = Field(examples=["토요일 집 보기"])
    memo_text: str = Field(default="", description="매물 메모(목록 미리보기용, 본인 것만)")
    analysis_status: Literal["none", "success", "failed"] = Field(default="none", description="최신 분석 상태")
    needs_reanalysis: bool = Field(default=False, description="분석 뒤 메모가 바뀌었는지")


class MyPinsOut(BaseModel):
    pins: list[MyPinOut]
    listing_count: int = Field(description="내 매물 전체 수(위치가 없는 매물 포함)", examples=[5])
