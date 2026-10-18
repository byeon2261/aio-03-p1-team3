"""F13 지도 탐색: 기준점에서 반경 안의 더미 매물을 가까운 순으로 찾는다.

거리는 WGS84 위경도 두 점의 구면 직선거리(미터)다. 도보 거리가 아니다.
더미 매물은 30개뿐이라 DB에서 전부 읽고 Python에서 거른다.
매물이 많아지면 DB 쪽 반경 조회(PostGIS 등)로 바꾼다.
"""

from __future__ import annotations

import math

from app.core.db import Database

TABLE = "map_listings"
EARTH_RADIUS_M = 6_371_008.8
RADIUS_OPTIONS = (300, 500, 1000)
MAX_ROWS = 500
# 화면이 처음 보여 주는 서울역 데모 기준점
DEMO_ORIGIN = {"label": "서울역 데모 기준점", "latitude": 37.5547, "longitude": 126.9706}


def distance_m(latitude: float, longitude: float, other_latitude: float, other_longitude: float) -> float:
    """WGS84 위경도 두 점 사이의 구면 직선거리를 미터로 반환한다."""
    lat1, lat2 = math.radians(latitude), math.radians(other_latitude)
    dlat = lat2 - lat1
    dlon = math.radians(other_longitude - longitude)
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(min(1.0, max(0.0, value))))


def search_nearby(db: Database, latitude: float, longitude: float, radius_m: int) -> list[dict]:
    """반경 안의 매물을 (거리, id) 순으로 돌려준다. 각 행에 distance_m을 붙인다."""
    results = []
    for row in db.select(TABLE, order_by="id", limit=MAX_ROWS):
        distance = distance_m(latitude, longitude, float(row["latitude"]), float(row["longitude"]))
        if distance <= radius_m:
            results.append({**row, "distance_m": round(distance, 1)})
    return sorted(results, key=lambda row: (row["distance_m"], row["id"]))
