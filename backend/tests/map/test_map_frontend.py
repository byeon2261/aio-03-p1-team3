"""F13 전체 매물 페이지(key map): 키 읽기, 페이지 등록, AppTest로 빈 상태·키 입력·오류·지도 표시. 서버는 가짜."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"
if str(FRONTEND_DIR) not in sys.path:
    sys.path.append(str(FRONTEND_DIR))

from features.map import logic  # noqa: E402

LOC = {"road_address": "가상시 예시구 샘플로 1", "parcel_address": None, "postal_code": None,
       "building_name": None, "latitude": 37.55, "longitude": 126.97, "updated_at": "2026-10-18T05:00:00Z"}
PIN = {"listing_id": "l-1", "listing_no": 1, "label": "1번 집", "location": LOC, "session_id": "s-1",
       "session_title": "토요일 집 보기", "analyzed": True, "deposit_manwon": 1000, "monthly_rent_manwon": 40,
       "maintenance_fee_manwon": None, "memo_text": "보증금 1000 월세 40  채광 좋음", "analysis_status": "success",
       "needs_reanalysis": False}

HEADER = f"""
import sys
sys.path.insert(0, {str(FRONTEND_DIR)!r})
import _map_all_fake as fake
import streamlit as st
from core.api import ApiError
from features.map import components, pages

def _get(path, params=None, **kw):
    fake.calls.append(path)
    if fake.error:
        raise ApiError(503, "DB_UNAVAILABLE", "잠시 후 다시 시도해 주세요.")
    return fake.photos if path == "/me/photos" else fake.response

pages.api_get = _get
components.logic.configured_api_key = lambda *a, **kw: fake.configured_key
st.session_state.setdefault("auth", {{"access_token": "t", "refresh_token": "r", "expires_at": None,
                                      "profile": {{"id": "me", "nickname": "테스터", "role": "user"}}}})
pages.render_all_listings()
"""


@pytest.fixture
def fake():
    mod = types.ModuleType("_map_all_fake")
    mod.calls, mod.error, mod.configured_key = [], False, "dummy-key"
    mod.response = {"pins": [PIN], "listing_count": 3}
    mod.photos = [{"listing_id": "l-1", "url": "https://example.com/new.png"},
                  {"listing_id": "l-1", "url": "https://example.com/first.png"}]
    sys.modules["_map_all_fake"] = mod
    yield mod
    sys.modules.pop("_map_all_fake", None)


def _app():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_string(HEADER, default_timeout=10)
    at.run()
    assert not at.exception, at.exception
    return at


def _text(at) -> str:
    return "\n".join(str(x.value) for x in [*at.title, *at.markdown, *at.caption, *at.info, *at.error])


# ------------------------------------------------------------------ 순수 함수
def test_map_api_key_sources(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    monkeypatch.delenv(logic.KEY_NAME, raising=False)
    assert logic.configured_api_key(None, env) == ""                           # 파일 없음
    env.write_text('# 주석\nOTHER=1\nKAKAO_JAVASCRIPT_KEY="file-key"\n', encoding="utf-8")
    assert logic.configured_api_key(None, env) == "file-key"                   # frontend/.env
    monkeypatch.setenv(logic.KEY_NAME, "env-key")
    assert logic.configured_api_key(None, env) == "env-key"                    # 환경변수가 우선
    assert logic.configured_api_key({"KAKAO_JAVASCRIPT_KEY": " secret-key "}, env) == "secret-key"


def test_all_listings_logic():
    pin = logic.my_pins([PIN])[0]
    assert pin["detail"] == "토요일 집 보기 · 가상시 예시구 샘플로 1"
    assert pin["link"] is True and [r["value"] for r in pin["rows"]] == ["1,000만원", "40만원"]
    panel = logic.panel_text([PIN, {**PIN, "listing_id": "l-2"}], 5, {"l-1": "https://example.com/a.png"})
    assert panel["title"] == "전체 매물" and panel["subtitle"] == "위치를 넣은 매물 2곳 · 위치 없는 매물 3곳"
    assert panel["items"][0] == {
        "id": "l-1", "label": "1번 집", "status": "분석 완료", "tone": "success",
        "meta": "토요일 집 보기 · 보증금 1,000만원 · 월세 40만원", "memo": "보증금 1000 월세 40 채광 좋음",
        "hint": "", "thumb": "https://example.com/a.png"}
    assert panel["items"][1]["thumb"] is None
    assert logic.panel_text([PIN], 1)["subtitle"] == "위치를 넣은 매물 1곳"
    none = logic.list_item({**PIN, "analysis_status": "none", "analyzed": False})
    assert (none["status"], none["tone"], none["meta"]) == ("분석 전", "none", "토요일 집 보기")
    assert none["hint"] == "매물 화면에서 분석을 실행하세요."
    stale = logic.list_item({**PIN, "needs_reanalysis": True})
    assert stale["status"] == "분석 완료 · 재분석 필요" and stale["tone"] == "stale"
    jeonse = logic.list_item({**PIN, "deposit_manwon": 25000, "monthly_rent_manwon": None})
    assert jeonse["meta"] == "토요일 집 보기 · 보증금 2억 5,000만원"
    assert logic.memo_preview("가" * 70).endswith("…") and len(logic.memo_preview("가" * 70)) == 61
    assert logic.first_photos([{"listing_id": "l-1", "url": "new"}, {"listing_id": "l-1", "url": "old"},
                               {"listing_id": "l-2", "url": None}]) == {"l-1": "old"}


def test_map_page_registered_as_all_listings():
    from core.loader import load_pages

    page = next(p for p in load_pages() if p["key"] == "map")
    assert page["title"] == "전체 매물" and page["order"] == 70 and page["admin_only"] is False


# ------------------------------------------------------------------ 화면
def test_all_listings_shows_full_map(fake):
    at = _app()
    assert fake.calls == ["/me/locations", "/me/photos"]
    md = "\n".join(str(m.value) for m in at.markdown)
    assert "max-width: 100% !important" in md               # 본문 여백을 없애 지도를 화면 전체에
    assert not at.title and not at.error                     # 지도만 보인다


def test_all_listings_asks_key_when_missing(fake):
    fake.configured_key = ""
    at = _app()
    assert "카카오 JavaScript 키를 입력하면 지도가 표시됩니다" in _text(at)
    at.text_input(key="map_key_field").set_value("typed-key").run()
    assert not at.exception, at.exception
    assert at.session_state[logic.KEY_INPUT] == "typed-key"
    assert not at.text_input                                 # 입력 후에는 지도만


def test_all_listings_empty_states(fake):
    fake.response = {"pins": [], "listing_count": 2}
    assert "아직 위치를 넣은 매물이 없습니다" in _text(_app())
    fake.response = {"pins": [], "listing_count": 0}
    assert "아직 매물이 없습니다" in _text(_app())


def test_all_listings_api_error(fake):
    fake.error = True
    at = _app()
    assert at.error and any(b.label == "다시 시도" for b in at.button)


def test_all_listings_photo_error_keeps_map(fake):
    fake.photos = None   # /me/photos가 비어 와도
    at = _app()
    assert not at.error
