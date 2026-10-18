"""F13 내 매물 위치 API: 저장·고치기·지우기, 세션 핀 목록, 소유 확인, 입력 검사, 마이그레이션 문법."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from tests.sessions.helpers import create_listing, create_session, error_code, insert_analysis

MIGRATION = Path(__file__).resolve().parents[3] / "supabase" / "migrations" / "0131_listing_locations.sql"
# 테스트용 가짜 주소(좌표는 서울 안의 아무 점)
LOC = {"road_address": "가상시 예시구 샘플로 1", "parcel_address": "가상시 예시구 샘플동 1-1",
       "postal_code": "00000", "building_name": "샘플빌라", "latitude": 37.55, "longitude": 126.97}


@pytest.fixture
def owner(client_as, make_user):
    c = client_as(make_user())
    session = create_session(c)
    first = create_listing(c, session["id"])
    second = create_listing(c, session["id"], memo="두 번째 집 메모")
    return c, session, first, second


# ------------------------------------------------------------------ 인증·소유
def test_location_requires_login(client_as):
    c = client_as(None)
    lid, sid = str(uuid.uuid4()), str(uuid.uuid4())
    assert c.get(f"/listings/{lid}/location").status_code == 401
    assert c.put(f"/listings/{lid}/location", json=LOC).status_code == 401
    assert c.get(f"/sessions/{sid}/locations").status_code == 401


def test_location_other_users_listing_is_404(client_as, make_user, owner):
    _, session, first, _ = owner
    other = client_as(make_user())
    for r in (other.get(f"/listings/{first['id']}/location"),
              other.put(f"/listings/{first['id']}/location", json=LOC),
              other.delete(f"/listings/{first['id']}/location")):
        assert r.status_code == 404 and error_code(r) == "LISTING_NOT_FOUND"
    r = other.get(f"/sessions/{session['id']}/locations")
    assert r.status_code == 404 and error_code(r) == "SESSION_NOT_FOUND"


# ------------------------------------------------------------------ 저장·조회·지우기
def test_location_empty_then_save_update_delete(owner):
    c, _, first, _ = owner
    url = f"/listings/{first['id']}/location"
    assert c.get(url).json() == {"listing_id": first["id"], "location": None}

    saved = c.put(url, json=LOC).json()["location"]
    assert saved["road_address"] == LOC["road_address"] and saved["latitude"] == 37.55
    assert saved["updated_at"]

    moved = c.put(url, json={"parcel_address": "가상시 예시구 견본동 2", "latitude": 37.56, "longitude": 126.98}).json()
    loc = moved["location"]
    assert loc["parcel_address"] == "가상시 예시구 견본동 2" and loc["road_address"] is None   # 통째로 바꾼다
    assert c.get(url).json()["location"]["latitude"] == 37.56

    assert c.delete(url).json() == {"ok": True}
    assert c.get(url).json()["location"] is None
    assert c.delete(url).status_code == 200   # 없어도 성공


def test_session_pins_include_money_from_analysis(owner, memory_db, make_user):
    """핀 금액 = 최신 성공 분석 + 사용자 수정값(비교표와 같은 값). 분석이 없으면 analyzed False·금액 null."""
    c, session, first, second = owner
    c.put(f"/listings/{first['id']}/location", json=LOC)
    c.put(f"/listings/{second['id']}/location", json=LOC)
    analysis = insert_analysis(memory_db, first["id"], first["memo_text"])
    memory_db.update("analyses", {"id": analysis["id"]}, {"result_json": {
        "deposit_manwon": 1000, "monthly_rent_manwon": 40, "maintenance_fee_manwon": None}})
    memory_db.insert("feedback", {"analysis_id": analysis["id"], "profile_id": make_user().profile_id,
                                  "field_name": "monthly_rent_manwon", "corrected_value": 45, "action": "set"})
    pins = {p["label"]: p for p in c.get(f"/sessions/{session['id']}/locations").json()}
    assert pins["1번 집"]["analyzed"] is True
    assert (pins["1번 집"]["deposit_manwon"], pins["1번 집"]["monthly_rent_manwon"]) == (1000, 45)
    assert pins["1번 집"]["maintenance_fee_manwon"] is None
    assert pins["2번 집"]["analyzed"] is False and pins["2번 집"]["deposit_manwon"] is None


def test_session_pins_only_listings_with_location(owner):
    c, session, first, second = owner
    url = f"/sessions/{session['id']}/locations"
    assert c.get(url).json() == []
    c.put(f"/listings/{second['id']}/location", json=LOC)
    c.put(f"/listings/{first['id']}/location", json={**LOC, "latitude": 37.56})
    pins = c.get(url).json()
    assert [p["label"] for p in pins] == ["1번 집", "2번 집"]
    assert pins[0]["listing_id"] == first["id"] and pins[0]["location"]["latitude"] == 37.56
    assert pins[1]["listing_no"] == 2


# ------------------------------------------------------------------ 입력 검사
@pytest.mark.parametrize("body", [
    {"latitude": 37.55, "longitude": 126.97},                                   # 주소 없음
    {"road_address": "   ", "parcel_address": "", "latitude": 37.55, "longitude": 126.97},
    {**LOC, "latitude": 0},
    {**LOC, "longitude": 200},
    {**LOC, "postal_code": "12ab"},
    {**LOC, "road_address": "가" * 201},
])
def test_location_rejects_bad_input(owner, body):
    c, _, first, _ = owner
    r = c.put(f"/listings/{first['id']}/location", json=body)
    assert r.status_code == 422 and error_code(r) == "VALIDATION_ERROR"
    assert "가상시" not in r.text   # 오류 응답에 주소 원문을 돌려주지 않는다


def test_location_blank_optional_fields_become_null(owner):
    c, _, first, _ = owner
    body = {"road_address": " 가상시 예시구 샘플로 1 ", "postal_code": "", "building_name": " ",
            "latitude": 37.55, "longitude": 126.97}
    loc = c.put(f"/listings/{first['id']}/location", json=body).json()["location"]
    assert loc["road_address"] == "가상시 예시구 샘플로 1"
    assert loc["postal_code"] is None and loc["building_name"] is None and loc["parcel_address"] is None


def test_migration_parses():
    pglast = pytest.importorskip("pglast")
    assert len(pglast.parse_sql(MIGRATION.read_text(encoding="utf-8"))) > 5
