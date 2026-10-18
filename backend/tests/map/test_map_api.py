"""F13 지도 탐색 API: 반경 조회·정렬·입력 검사, 더미 데이터와 마이그레이션 일치."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.features.map import service
from app.features.map.seed import DUMMY_MAP_LISTINGS

MIGRATION = Path(__file__).resolve().parents[3] / "supabase" / "migrations" / "0130_map_listings.sql"
ORIGIN = service.DEMO_ORIGIN


@pytest.fixture
def seeded(memory_db):
    memory_db.insert("map_listings", [dict(row) for row in DUMMY_MAP_LISTINGS])
    return memory_db


def search(client, radius_m=300, **kw):
    params = {"latitude": ORIGIN["latitude"], "longitude": ORIGIN["longitude"], "radius_m": radius_m, **kw}
    return client.get("/map/listings", params=params)


# ------------------------------------------------------------------ 인증
def test_map_requires_login(client_as, seeded):
    assert search(client_as(None)).status_code == 401


# ------------------------------------------------------------------ 반경 조회
@pytest.mark.parametrize(("radius_m", "count"), [(300, 8), (500, 18), (1000, 30)])
def test_map_radius_counts(client_as, make_user, seeded, radius_m, count):
    r = search(client_as(make_user()), radius_m)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["radius_m"] == radius_m and body["count"] == count == len(body["listings"])
    assert body["origin"] == {"latitude": ORIGIN["latitude"], "longitude": ORIGIN["longitude"]}
    assert all(item["distance_m"] <= radius_m for item in body["listings"])


def test_map_sorted_by_distance_and_fields(client_as, make_user, seeded):
    items = search(client_as(make_user()), 1000).json()["listings"]
    distances = [item["distance_m"] for item in items]
    assert distances == sorted(distances)
    assert [item["id"] for item in items] == [f"map-{i:02d}" for i in range(1, 31)]   # id는 가까운 순
    assert set(items[0]) == {"id", "title", "area_name", "property_type", "lease_type", "deposit_manwon",
                             "monthly_rent_manwon", "area_m2", "floor", "latitude", "longitude", "road_address",
                             "parcel_address", "postal_code", "building_name", "address_source_url",
                             "address_verified_on", "distance_m"}
    real = [item for item in items if item["road_address"]]
    assert len(real) == 9
    assert all(item["address_verified_on"] == "2026-10-16" and item["address_source_url"].startswith("https://")
               for item in real)
    for item in items:
        if item["lease_type"] == "전세":
            assert item["monthly_rent_manwon"] is None
        else:
            assert item["monthly_rent_manwon"] is not None


def test_map_wider_radius_includes_inner(client_as, make_user, seeded):
    c = client_as(make_user())
    ids = {r: {i["id"] for i in search(c, r).json()["listings"]} for r in (300, 500, 1000)}
    assert ids[300] <= ids[500] <= ids[1000]


def test_map_far_origin_returns_empty(client_as, make_user, seeded):
    r = client_as(make_user()).get("/map/listings",
                                   params={"latitude": 35.1796, "longitude": 129.0756, "radius_m": 1000})
    assert r.status_code == 200 and r.json()["count"] == 0 and r.json()["listings"] == []


def test_map_empty_table(client_as, make_user):
    r = search(client_as(make_user()), 1000)
    assert r.status_code == 200 and r.json()["count"] == 0


# ------------------------------------------------------------------ 입력 검사
@pytest.mark.parametrize("radius_m", [0, 100, 750, 5000])
def test_map_rejects_other_radius(client_as, make_user, seeded, radius_m):
    r = search(client_as(make_user()), radius_m)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert r.json()["error"]["detail"]["reason"] == "radius_m"


def test_map_rejects_bad_coordinates(client_as, make_user, seeded):
    c = client_as(make_user())
    assert c.get("/map/listings", params={"latitude": 91, "longitude": 126.97}).status_code == 422
    assert c.get("/map/listings", params={"latitude": 37.55, "longitude": 0}).status_code == 422
    assert c.get("/map/listings", params={"latitude": 37.55}).status_code == 422


# ------------------------------------------------------------------ 계산·데이터
def test_distance_m_known_value():
    assert service.distance_m(37.0, 127.0, 37.0, 127.0) == 0
    # 위도 0.001도 ≈ 111.2m
    assert 110 < service.distance_m(37.0, 127.0, 37.001, 127.0) < 112


def test_seed_real_and_virtual_rows():
    """실제 주소 샘플 9개는 주소·출처가 모두 있고, 가상 매물 21개는 주소가 동 단위뿐이다."""
    assert len(DUMMY_MAP_LISTINGS) == 30
    assert len({row["id"] for row in DUMMY_MAP_LISTINGS}) == 30
    real = [row for row in DUMMY_MAP_LISTINGS if row["road_address"]]
    virtual = [row for row in DUMMY_MAP_LISTINGS if not row["road_address"]]
    assert len(real) == 9 and len(virtual) == 21
    for row in real:
        assert "실제 주소 샘플" in row["title"]
        assert row["parcel_address"] and re.fullmatch(r"\d{5}", row["postal_code"])
        assert row["address_source_url"].startswith("https://") and row["address_verified_on"]
        assert row["parcel_address"].startswith(row["area_name"])
    for row in virtual:
        assert "가상" in row["title"]
        assert not re.search(r"\d", row["area_name"]), "가상 매물은 동 단위까지만 둔다(번지·도로명 번호 없음)"
        assert all(row[field] is None for field in ("parcel_address", "postal_code", "building_name",
                                                    "address_source_url", "address_verified_on"))


def _migration_rows() -> dict[str, tuple[float, float]]:
    sql = MIGRATION.read_text(encoding="utf-8")
    # 값 순서: id, ..., floor, latitude, longitude, road_address, ...
    rows = re.findall(r"\('(map-\d+)', .*?, -?\d+, (\d+\.\d+), (\d+\.\d+), (?:null|')", sql)
    return {rid: (float(lat), float(lng)) for rid, lat, lng in rows}


def test_seed_matches_migration():
    """seed.py와 0130 마이그레이션의 INSERT가 같은 매물·좌표인지."""
    from_sql = _migration_rows()
    from_seed = {row["id"]: (row["latitude"], row["longitude"]) for row in DUMMY_MAP_LISTINGS}
    assert from_sql == from_seed
