"""F13 내 매물 위치 화면: 세션 상세 매물 목록 옆 지도, 매물 상세 '위치' 섹션(AppTest, 서버는 가짜)."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"
if str(FRONTEND_DIR) not in sys.path:
    sys.path.append(str(FRONTEND_DIR))

from features.map import logic  # noqa: E402

SID, LID1, LID2 = "s-1", "l-1", "l-2"
LOC = {"road_address": "가상시 예시구 샘플로 1", "parcel_address": "가상시 예시구 샘플동 1-1", "postal_code": "00000",
       "building_name": "샘플빌라", "latitude": 37.55, "longitude": 126.97, "updated_at": "2026-10-18T05:00:00Z"}
LISTINGS = [
    {"id": LID1, "label": "1번 집", "listing_no": 1, "memo_text": "첫 집", "latest_analysis_status": "none",
     "needs_reanalysis": False},
    {"id": LID2, "label": "2번 집", "listing_no": 2, "memo_text": "둘째 집", "latest_analysis_status": "none",
     "needs_reanalysis": False},
]

HEADER = f"""
import sys
sys.path.insert(0, {str(FRONTEND_DIR)!r})
import _map_loc_fake as fake
import streamlit as st
from core.api import ApiError
from features.map import components, listing_map
from features.sessions import sections

def _get(path, params=None, **kw):
    fake.calls.append(("GET", path))
    if path in fake.errors:
        raise ApiError(503, "DB_UNAVAILABLE", "잠시 후 다시 시도해 주세요.")
    return fake.responses[path]

def _write(method):
    def f(path, json=None, **kw):
        fake.calls.append((method, path, json))
        return {{"ok": True}}
    return f

for m in (listing_map, sections):
    m.api_get = _get
listing_map.api_put, listing_map.api_delete = _write("PUT"), _write("DELETE")
components.current_api_key = lambda: fake.api_key
st.session_state.setdefault("auth", {{"access_token": "t", "refresh_token": "r", "expires_at": None,
                                      "profile": {{"id": "me", "nickname": "테스터", "role": "user"}}}})
"""


@pytest.fixture
def fake():
    mod = types.ModuleType("_map_loc_fake")
    mod.calls, mod.errors, mod.api_key = [], set(), ""
    mod.responses = {
        f"/sessions/{SID}/listings": LISTINGS,
        f"/sessions/{SID}/locations": [{"listing_id": LID1, "listing_no": 1, "label": "1번 집", "location": LOC}],
        f"/listings/{LID1}/location": {"listing_id": LID1, "location": LOC},
        f"/listings/{LID2}/location": {"listing_id": LID2, "location": None},
    }
    sys.modules["_map_loc_fake"] = mod
    yield mod
    sys.modules.pop("_map_loc_fake", None)


def _app(body: str):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_string(HEADER + body, default_timeout=10)
    at.run()
    assert not at.exception, at.exception
    return at


def _text(at) -> str:
    return "\n".join(str(x.value) for x in [*at.markdown, *at.subheader, *at.caption, *at.text, *at.info,
                                              *at.warning, *at.error])


SESSION_BODY = f'sections._render_listings({{"id": "{SID}", "title": "토요일"}})'


# ------------------------------------------------------------------ 순수 함수
def test_location_logic_helpers():
    assert logic.address_text(None) == ""
    assert logic.address_text(LOC) == "가상시 예시구 샘플로 1 (샘플빌라)"
    assert logic.address_text({"parcel_address": "가상시 예시구 샘플동 1-1"}) == "가상시 예시구 샘플동 1-1"
    pins = logic.session_pins([{"listing_id": LID1, "listing_no": 1, "label": "1번 집", "location": LOC}])
    assert pins == [{"id": LID1, "label": "1번 집", "detail": "가상시 예시구 샘플로 1 (샘플빌라)",
                     "latitude": 37.55, "longitude": 126.97, "clickable": True}]
    body = logic.location_body({"id": 0, "ok": True, "latitude": 37.5, "longitude": 127.0, "roadAddress": "도로",
                                "parcelAddress": "", "zonecode": "04323", "buildingName": ""})
    assert body == {"road_address": "도로", "parcel_address": None, "postal_code": "04323", "building_name": None,
                    "latitude": 37.5, "longitude": 127.0}


def test_listing_location_section_registered():
    from core.loader import load_sections

    sec = next(s for s in load_sections() if s["feature"] == "map")
    assert sec["slot"] == "listing_detail" and sec["order"] == 50


# ------------------------------------------------------------------ 세션 상세: 매물 목록 옆 지도
def test_session_listings_with_map_column(fake):
    at = _app(SESSION_BODY)
    text = _text(at)
    assert "1번 집" in text and "2번 집" in text and "매물 지도" in text
    assert ("GET", f"/sessions/{SID}/locations") in fake.calls
    assert "위치가 없는 매물 1곳은 지도에 없습니다." in text
    assert "카카오 JavaScript 키가 없어" in text            # 키가 없으면 지도 대신 안내
    assert not at.error


def test_session_map_with_key_renders_without_error(fake):
    fake.api_key = "dummy-key"
    at = _app(SESSION_BODY)
    assert not at.error and "카카오 JavaScript 키가 없어" not in _text(at)


def test_session_map_no_locations_yet(fake):
    fake.responses[f"/sessions/{SID}/locations"] = []
    at = _app(SESSION_BODY)
    assert "아직 위치를 넣은 매물이 없습니다" in _text(at)


def test_session_map_error_keeps_cards(fake):
    fake.errors.add(f"/sessions/{SID}/locations")
    at = _app(SESSION_BODY)
    assert "1번 집" in _text(at) and at.error       # 지도만 실패하고 매물 카드는 남는다


# ------------------------------------------------------------------ 매물 상세: 위치
def _listing_body(lid: str) -> str:
    return f'listing_map.render_listing_location({{"listing": {{"id": "{lid}", "label": "x번 집"}}, "session": {{}}}})'


def test_listing_location_empty(fake):
    fake.api_key = "dummy-key"
    at = _app(_listing_body(LID2))
    assert "아직 위치가 없습니다" in _text(at)
    labels = [b.label for b in at.button]
    assert "주소 검색" in labels and "위치 지우기" not in labels


def test_listing_location_saved_and_delete(fake):
    fake.api_key = "dummy-key"
    at = _app(_listing_body(LID1))
    text = _text(at)
    assert "가상시 예시구 샘플로 1" in text and "샘플빌라" in text
    next(b for b in at.button if b.label == "위치 지우기").click().run()
    assert ("DELETE", f"/listings/{LID1}/location", None) in fake.calls


def test_listing_location_without_key_disables_search(fake):
    at = _app(_listing_body(LID2))
    assert next(b for b in at.button if b.label == "주소 검색").disabled
    assert "카카오 JavaScript 키가 없어" in _text(at)


def test_listing_location_pending_waits_for_geocode_then_cancel(fake):
    fake.api_key = "dummy-key"
    pending = '{"query": "가상시 예시구 샘플로 1", "roadAddress": "가상시 예시구 샘플로 1"}'
    seed = (f'if not st.session_state.get("seeded"):\n'
            f'    st.session_state["seeded"] = True\n'
            f'    st.session_state["map_loc_pending:{LID2}"] = {pending}\n')
    at = _app(seed + _listing_body(LID2))
    save = next(b for b in at.button if b.label == "이 위치로 저장")
    assert save.disabled                                    # 좌표 변환 결과가 오기 전에는 저장 못 함
    next(b for b in at.button if b.label == "취소").click().run()
    assert f"map_loc_pending:{LID2}" not in at.session_state
    assert "아직 위치가 없습니다" in _text(at)
