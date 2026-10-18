"""F13 지도 탐색: GET /map/listings

- 로그인한 사용자만 쓴다(없으면 401). 더미 매물은 모두가 같은 데이터를 읽는다(RLS: 로그인 사용자 읽기 전용).
- 반경은 300·500·1000m 중 하나(그 밖은 422 VALIDATION_ERROR). 위도·경도는 한국 근처 범위만 받는다.
- 기준점 좌표는 요청 로그 경로에 남지 않는다(미들웨어는 경로 틀만 기록한다).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.core.auth import CurrentUser, get_current_user
from app.core.db import Database, get_user_db
from app.core.errors import AppError
from app.features.map import service
from app.features.map.schemas import MapListingOut, MapOriginOut, MapSearchOut

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
