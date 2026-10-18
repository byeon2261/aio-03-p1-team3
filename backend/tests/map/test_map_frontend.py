"""F13 지도 탐색 화면: 순수 함수, 페이지 등록, AppTest로 목록·반경·오류 표시. 서버는 가짜."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"
if str(FRONTEND_DIR) not in sys.path:
    sys.path.append(str(FRONTEND_DIR))

from features.map import logic  # noqa: E402

REAL = {"id": "map-03", "title": "서계동 실제 주소 샘플 A", "area_name": "서울특별시 용산구 서계동",
        "property_type": "원룸", "lease_type": "월세", "deposit_manwon": 1000, "monthly_rent_manwon": 60,
        "area_m2": 19.0, "floor": 2, "latitude": 37.5542693, "longitude": 126.9685446,
        "road_address": "서울특별시 용산구 청파로93길 5", "parcel_address": "서울특별시 용산구 서계동 223-8",
        "postal_code": "04300", "building_name": None, "address_source_url": "https://example.com/source",
        "address_verified_on": "2026-10-16", "distance_m": 187.2}
VIRTUAL = {**REAL, "id": "map-01", "title": "동자동 가상 원룸 01", "area_name": "서울특별시 용산구 동자동",
           "lease_type": "전세", "deposit_manwon": 18000, "monthly_rent_manwon": None, "road_address": None,
           "parcel_address": None, "postal_code": None, "address_source_url": None, "address_verified_on": None,
           "distance_m": 158.0}

HEADER = f"""
import sys
sys.path.insert(0, {str(FRONTEND_DIR)!r})
import _map_fake as fake
import streamlit as st
from core.api import ApiError
from features.map import logic, pages

def _get(path, params=None, **kw):
    fake.calls.append((path, params))
    if fake.error:
        raise ApiError(503, "DB_UNAVAILABLE", "잠시 후 다시 시도해 주세요.")
    return {{"origin": {{}}, "radius_m": params["radius_m"], "count": len(fake.listings), "listings": fake.listings}}

pages.api_get = _get
logic.configured_api_key = lambda *a, **kw: ""
st.session_state.setdefault("auth", {{"access_token": "t", "refresh_token": "r", "expires_at": None,
                                      "profile": {{"id": "me", "nickname": "테스터", "role": "user"}}}})
pages.render_map_explorer()
"""


@pytest.fixture
def ui_fake(monkeypatch):
    monkeypatch.delenv(logic.KEY_NAME, raising=False)
    mod = types.ModuleType("_map_fake")
    mod.calls, mod.listings, mod.error = [], [VIRTUAL, REAL], False
    sys.modules["_map_fake"] = mod
    yield mod
    sys.modules.pop("_map_fake", None)


def _app():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_string(HEADER, default_timeout=10)
    at.run()
    assert not at.exception, at.exception
    return at


def _text(at) -> str:
    return "\n".join(str(x.value) for x in [*at.markdown, *at.subheader, *at.caption, *at.text, *at.info, *at.error])


# ------------------------------------------------------------------ 순수 함수
def test_map_logic_helpers(tmp_path):
    assert logic.price_text(REAL) == "보증금 1,000 / 월 60만원"
    assert logic.price_text(VIRTUAL) == "전세 18,000만원"
    assert logic.radius_label(1000) == "1km" and logic.radius_label(300) == "300m"
    assert logic.coordinate_text(None) == "—"
    assert logic.coordinate_text({"latitude": 37.5, "longitude": 127}) == "37.500000, 127.000000"
    assert logic.next_command({"id": 4}, "reset") == {"id": 5, "type": "reset"}
    assert logic.search_params(logic.DEMO_ORIGIN, 500) == {"latitude": 37.5547, "longitude": 126.9706, "radius_m": 500}
    assert logic.map_payload(None, 300, [VIRTUAL])["listings"][0]["price"] == "전세 18,000만원"
    assert "실제 위치" in logic.data_note(REAL) and "가상" in logic.data_note(VIRTUAL)


def test_map_api_key_sources(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    monkeypatch.delenv(logic.KEY_NAME, raising=False)
    assert logic.configured_api_key(None, env) == ""                           # 파일 없음
    env.write_text('# 주석\nOTHER=1\nKAKAO_JAVASCRIPT_KEY="file-key"\n', encoding="utf-8")
    assert logic.configured_api_key(None, env) == "file-key"                   # frontend/.env
    monkeypatch.setenv(logic.KEY_NAME, "env-key")
    assert logic.configured_api_key(None, env) == "env-key"                    # 환경변수가 우선
    assert logic.configured_api_key({"KAKAO_JAVASCRIPT_KEY": " secret-key "}, env) == "secret-key"


def test_map_page_registered():
    from core.loader import load_pages

    page = next(p for p in load_pages() if p["key"] == "map")
    assert page["order"] == 70 and page["admin_only"] is False and page["feature"] == "map"


# ------------------------------------------------------------------ 화면
def test_map_page_lists_demo_origin_listings(ui_fake):
    at = _app()
    assert at.title[0].value == "동네 지도 탐색"
    assert ui_fake.calls[0] == ("/map/listings", {"latitude": 37.5547, "longitude": 126.9706, "radius_m": 300})
    assert [e.label for e in at.expander if e.label[0].isdigit()] == [
        "1. 동자동 가상 원룸 01 · 158m", "2. 서계동 실제 주소 샘플 A · 187m"]
    text = _text(at)
    assert "주변 매물 2개" in text and "서울특별시 용산구 청파로93길 5" in text and "동자동 일대" in text
    assert "카카오 JavaScript 키를 입력하면 지도가 표시됩니다." in text      # 키가 없으면 지도 대신 안내


def test_map_page_radius_change_calls_api(ui_fake):
    at = _app()
    at.segmented_control[0].set_value(1000).run()
    assert not at.exception, at.exception
    assert ui_fake.calls[-1][1]["radius_m"] == 1000


def test_map_page_select_listing_shows_detail(ui_fake):
    at = _app()
    next(b for b in at.button if b.key == "map_focus_map-03").click().run()
    assert not at.exception, at.exception
    assert at.session_state[logic.SELECTED] == "map-03"
    assert any(s.value == "선택한 매물" for s in at.subheader)


def test_map_page_api_error(ui_fake):
    ui_fake.error = True
    at = _app()
    assert any("주변 매물을 불러오지 못했습니다" in str(e.value) for e in at.error)
    assert "주변 매물 0개" in _text(at) and "반경 안에 더미 매물이 없습니다" not in _text(at)
