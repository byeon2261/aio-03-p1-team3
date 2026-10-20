"""F13 내 매물 위치 화면 부품. import할 때 st 함수를 부르지 않는다.

- render_session_map(session, listings): 세션 상세 '매물' 목록 옆 지도(P1 sessions/sections.py가 부름).
  위치를 넣은 매물만 핀으로 찍고, 핀을 누르면 이름·주소·보증금·월세 카드가 열리며 '매물 상세 보기'로 이동한다.
- render_listing_location(ctx): 매물 상세 슬롯 listing_detail order 50 '위치'.
  카카오 주소 검색으로 주소를 고르면 지도 SDK가 좌표로 바꾸고, 확인 후 저장한다.
주소는 메모와 따로 저장되고 본인만 본다. AI 분석에는 보내지 않는다.
"""

from __future__ import annotations

import streamlit as st

from core import nav
from core.api import ApiError, api_delete, api_get, api_put
from core.ui import icon_badge, icon_title, show_api_error
from features.map import components, logic

PRIVACY_NOTE = "주소는 메모와 따로 저장되고 나만 볼 수 있습니다. AI 분석에는 보내지 않습니다."
NO_KEY_NOTE = ("카카오 JavaScript 키가 없어 지도를 표시할 수 없습니다. "
               "frontend/.env·Streamlit secrets의 KAKAO_JAVASCRIPT_KEY를 설정하거나 '전체 매물'에서 키를 입력하세요.")


# ------------------------------------------------------------------ 세션 상세: 매물 목록 옆 지도
def render_session_map(session: dict, listings: list[dict]) -> None:
    sid = session["id"]
    try:
        pins = api_get(f"/sessions/{sid}/locations")
    except ApiError as e:
        show_api_error(e)
        return
    missing = len(listings) - len(pins)
    if not pins:
        st.caption("아직 위치를 넣은 매물이 없습니다. 매물을 열고 '위치'에서 주소를 검색해 저장하면 여기에 표시됩니다.")
        return
    api_key = components.current_api_key()
    if not api_key:
        st.info(NO_KEY_NOTE)
    else:
        result = components.pins_map(api_key, logic.session_pins(pins), key=f"map_session_pins:{sid}", height=400)
        opened = getattr(result, "open", None)
        if opened and any(p["listing_id"] == opened for p in pins):
            nav.go_listing_detail(opened)   # 카드의 '매물 상세 보기'
    if missing > 0:
        st.caption(f"위치가 없는 매물 {missing}곳은 지도에 없습니다.")


# ------------------------------------------------------------------ 매물 상세: 위치
def _pending_key(lid: str) -> str:
    return f"map_loc_pending:{lid}"


def _geocode_id_key(lid: str) -> str:
    return f"map_loc_geocode_id:{lid}"


def _show_saved(location: dict) -> None:
    if location.get("road_address"):
        st.caption("도로명주소")
        st.text(location["road_address"])
    if location.get("parcel_address"):
        st.caption("지번주소")
        st.text(location["parcel_address"])
    if location.get("building_name"):
        st.caption("건물명")
        st.text(location["building_name"])


def render_listing_location(ctx: dict) -> None:
    listing = ctx["listing"]
    lid = listing["id"]
    icon_title("location_on", "위치")
    st.caption(PRIVACY_NOTE)
    try:
        location = api_get(f"/listings/{lid}/location").get("location")
    except ApiError as e:
        show_api_error(e)
        return

    api_key = components.current_api_key()
    pending = st.session_state.get(_pending_key(lid))
    label = listing.get("label") or "이 매물"

    if pending:
        _render_pending(lid, label, pending, api_key)
        return

    if location:
        _show_saved(location)
        if api_key:
            pin = {"id": lid, "label": label, "detail": logic.address_text(location),
                   "latitude": location["latitude"], "longitude": location["longitude"], "link": False}
            components.pins_map(api_key, [pin], key=f"map_loc_saved:{lid}", height=280)
    else:
        st.markdown(
            '<div style="display:flex;align-items:center;gap:.75rem;padding:.5rem 0">'
            f'{icon_badge("location_on", "blue", 44)}<div style="color:#3d4152">'
            '아직 위치가 없습니다. 주소를 검색해 저장하면 세션 화면의 매물 지도에 표시됩니다.</div></div>',
            unsafe_allow_html=True)

    if not api_key:
        st.caption(NO_KEY_NOTE)
    left, right = st.columns(2)
    with left:
        if st.button("주소 검색" if not location else "주소 바꾸기", icon=":material/location_on:",
                     key=f"map_loc_search:{lid}", disabled=not api_key):
            components.pick_address(_pending_key(lid), f"map_loc_postcode:{lid}")
    with right:
        if location and st.button("위치 지우기", key=f"map_loc_delete:{lid}"):
            try:
                api_delete(f"/listings/{lid}/location")
            except ApiError as e:
                show_api_error(e)
                return
            st.rerun()


def _render_pending(lid: str, label: str, pending: dict, api_key: str) -> None:
    """주소를 고른 뒤: 지도로 좌표를 확인하고 저장하거나 취소한다."""
    st.text(pending.get("query") or "")
    if not api_key:
        st.warning(NO_KEY_NOTE)
        geocoded = None
    else:
        st.session_state.setdefault(_geocode_id_key(lid), 0)
        request = {"id": st.session_state[_geocode_id_key(lid)], "query": pending.get("query"), "address": pending}
        result = components.pins_map(api_key, [], key=f"map_loc_pick:{lid}", geocode=request, height=280)
        geocoded = getattr(result, "geocoded", None)
        if not geocoded or geocoded.get("id") != request["id"]:
            geocoded = None   # 아직 변환 중

    save_col, cancel_col = st.columns(2)
    with save_col:
        can_save = bool(geocoded and geocoded.get("ok"))
        if st.button("이 위치로 저장", type="primary", key=f"map_loc_save:{lid}", disabled=not can_save):
            try:
                api_put(f"/listings/{lid}/location", json=logic.location_body(geocoded))
            except ApiError as e:
                show_api_error(e)
                return
            _clear_pending(lid)
            st.toast(f"{label} 위치를 저장했습니다.")
            st.rerun()
    with cancel_col:
        if st.button("취소", key=f"map_loc_cancel:{lid}"):
            _clear_pending(lid)
            st.rerun()


def _clear_pending(lid: str) -> None:
    st.session_state.pop(_pending_key(lid), None)
    # 다음에 같은 주소를 다시 골라도 새 요청으로 보이게 번호를 올린다
    st.session_state[_geocode_id_key(lid)] = st.session_state.get(_geocode_id_key(lid), 0) + 1
