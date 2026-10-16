"""실제 주소·건물 대표 좌표에 가상 조건을 붙인 샘플의 반경 검색."""

import json
import math
from pathlib import Path


EARTH_RADIUS_M = 6_371_008.8
SEOUL_STATION = {
    "label": "서울역 데모 기준점",
    "latitude": 37.5547,
    "longitude": 126.9706,
}
DATA_PATH = Path(__file__).with_name("data") / "listings.json"


def distance_m(latitude: float, longitude: float, other_latitude: float, other_longitude: float) -> float:
    """WGS84 위경도 두 점 사이의 구면 직선거리를 미터로 반환한다."""
    lat1, lat2 = math.radians(latitude), math.radians(other_latitude)
    dlat = lat2 - lat1
    dlon = math.radians(other_longitude - longitude)
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(min(1.0, max(0.0, value))))


def search_listings(origin: dict | None, radius_m: int) -> list[dict]:
    """기준점에서 반경 이내인 가상 매물을 가까운 순서로 조회한다."""
    if origin is None:
        return []
    if radius_m not in (300, 500, 1000):
        raise ValueError("검색 반경은 300m, 500m, 1km 중 하나여야 합니다.")
    listings = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    results = []
    for listing in listings:
        distance = distance_m(
            origin["latitude"], origin["longitude"], listing["latitude"], listing["longitude"]
        )
        if distance <= radius_m:
            results.append({**listing, "distance_m": distance})
    return sorted(results, key=lambda listing: (listing["distance_m"], listing["id"]))


def price_text(listing: dict) -> str:
    if listing["lease_type"] == "월세":
        return f"보증금 {listing['deposit_manwon']:,} / 월 {listing['monthly_rent_manwon']:,}만원"
    return f"전세 {listing['deposit_manwon']:,}만원"
