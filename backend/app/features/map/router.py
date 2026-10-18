"""F13 지도 탐색: GET /map/listings · 내 매물 위치: GET·PUT·DELETE /listings/{listing_id}/location,
GET /sessions/{session_id}/locations

- 로그인한 사용자만 쓴다(없으면 401). 더미 매물은 모두가 같은 데이터를 읽는다(RLS: 로그인 사용자 읽기 전용).
- 반경은 300·500·1000m 중 하나(그 밖은 422 VALIDATION_ERROR). 위도·경도는 한국 근처 범위만 받는다.
- 기준점 좌표는 요청 로그 경로에 남지 않는다(미들웨어는 경로 틀만 기록한다).
- 내 매물 위치는 본인 매물만(남의 매물·세션은 404 LISTING_NOT_FOUND·SESSION_NOT_FOUND).
  주소는 메모와 따로 저장하고 AI 분석에 보내지 않는다. 요청 본문(주소)은 로그에 남지 않는다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.core.auth import CurrentUser, get_current_user
from app.core.db import Database, get_user_db
from app.core.errors import AppError
from app.core.ownership import get_owned_listing, get_owned_session
from app.core.schemas import OkOut
from app.features.map import locations, service
from app.features.map.schemas import (
    ListingLocationOut, LocationIn, MapListingOut, MapOriginOut, MapSearchOut, SessionPinOut,
)

router = APIRouter(tags=["map"])


@router.get("/map/listings", response_model=MapSearchOut)
def search_map_listings(
    latitude: float = Query(ge=33.0, le=39.0, description="기준점 위도(WGS84)"),
    longitude: float = Query(ge=124.0, le=132.0, description="기준점 경도(WGS84)"),
    radius_m: int = Query(default=300, description="검색 반경(m): 300, 500, 1000"),
    user: CurrentUser = Depends(get_current_user),
    db: Database = Depends(get_user_db),
) -> MapSearchOut:
    if radius_m not in service.RADIUS_OPTIONS:
        raise AppError(422, "VALIDATION_ERROR", "검색 반경은 300m, 500m, 1km 중 하나입니다.", {"reason": "radius_m"})
    rows = service.search_nearby(db, latitude, longitude, radius_m)
    return MapSearchOut(
        origin=MapOriginOut(latitude=latitude, longitude=longitude),
        radius_m=radius_m,
        count=len(rows),
        listings=[MapListingOut.model_validate(row) for row in rows],
    )


@router.get("/listings/{listing_id}/location", response_model=ListingLocationOut)
def read_listing_location(listing_id: str, user: CurrentUser = Depends(get_current_user),
                          db: Database = Depends(get_user_db)) -> ListingLocationOut:
    listing = get_owned_listing(db, user, listing_id)
    return locations.to_out(listing["id"], locations.get_row(db, listing["id"]))


@router.put("/listings/{listing_id}/location", response_model=ListingLocationOut)
def save_listing_location(listing_id: str, body: LocationIn, user: CurrentUser = Depends(get_current_user),
                          db: Database = Depends(get_user_db)) -> ListingLocationOut:
    listing = get_owned_listing(db, user, listing_id)
    return locations.save(db, listing["id"], body)


@router.delete("/listings/{listing_id}/location", response_model=OkOut)
def delete_listing_location(listing_id: str, user: CurrentUser = Depends(get_current_user),
                            db: Database = Depends(get_user_db)) -> OkOut:
    listing = get_owned_listing(db, user, listing_id)
    locations.delete(db, listing["id"])
    return OkOut()


@router.get("/sessions/{session_id}/locations", response_model=list[SessionPinOut])
def list_session_locations(session_id: str, user: CurrentUser = Depends(get_current_user),
                           db: Database = Depends(get_user_db)) -> list[SessionPinOut]:
    session = get_owned_session(db, user, session_id)
    return locations.session_pins(db, session["id"])
