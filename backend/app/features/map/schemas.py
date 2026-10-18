"""F13 지도 탐색·내 매물 위치 모델."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class MapOriginOut(BaseModel):
    latitude: float = Field(examples=[37.5547])
    longitude: float = Field(examples=[126.9706])


class MapListingOut(BaseModel):
    id: str = Field(examples=["map-01"])
    title: str = Field(examples=["회현동 가상 투룸 01"])
    area_name: str = Field(description="동 단위 지역", examples=["서울특별시 중구 회현동"])
    property_type: str = Field(examples=["투룸"])
    lease_type: Literal["월세", "전세"]
    deposit_manwon: int = Field(description="보증금(만원)", examples=[1000])
    monthly_rent_manwon: int | None = Field(default=None, description="월세(만원). 전세면 null", examples=[80])
    area_m2: float = Field(description="전용면적(㎡)", examples=[43.0])
    floor: int = Field(examples=[14])
    latitude: float
    longitude: float
    road_address: str | None = Field(default=None, description="도로명주소(실제 주소 샘플만, 가상 매물은 null)",
                                     examples=["서울특별시 용산구 청파로93길 5"])
    parcel_address: str | None = Field(default=None, description="지번주소(실제 주소 샘플만)")
    postal_code: str | None = Field(default=None, description="우편번호(실제 주소 샘플만)", examples=["04300"])
    building_name: str | None = Field(default=None, description="건물명(있을 때만)")
    address_source_url: str | None = Field(default=None, description="주소·좌표 출처(실제 주소 샘플만)")
    address_verified_on: date | None = Field(default=None, description="주소 확인일(실제 주소 샘플만)")
    distance_m: float = Field(description="기준점에서의 직선거리(m, 소수 첫째 자리)", examples=[233.4])


class MapSearchOut(BaseModel):
    origin: MapOriginOut
    radius_m: int = Field(examples=[300])
    count: int = Field(examples=[8])
    listings: list[MapListingOut]


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
    listing_id: str
    listing_no: int = Field(examples=[1])
    label: str = Field(examples=["1번 집"])
    location: LocationOut
