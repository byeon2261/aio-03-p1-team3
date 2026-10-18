"""F13 지도 탐색 응답 모델."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


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
