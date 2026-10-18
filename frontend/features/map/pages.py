"""F13 전체 매물 페이지(key map, order 70). import할 때 st 함수를 부르지 않는다.

내 모든 세션에서 위치를 넣은 매물을 사이드바를 뺀 화면 전체 지도에 핀으로 찍는다(GET /me/locations).
핀을 누르면 정보 카드(N번 집·세션·주소·보증금·월세·관리비)가 열리고, [매물 상세 보기]는 그 매물 상세로 간다.
왼쪽 위 패널에 매물 목록(세션 상세 매물 카드처럼 사진·이름·분석 상태·메모)을 두고, 누르면 지도가 그 매물로 옮겨 간다.
카카오 JavaScript 키: st.secrets / 환경변수 / frontend/.env 의 KAKAO_JAVASCRIPT_KEY, 없으면 화면에서 입력.
"""

from __future__ import annotations

import streamlit as st

from core import nav
from core.api import ApiError, api_get
from core.ui import show_api_error
from features.map import components, logic

# 이 페이지에서만 본문 여백·최대 폭을 없애 지도를 사이드바 오른쪽 전체에 채운다
FULL_BLEED_CSS = """
<style>
[data-testid="stMainBlockContainer"], .block-container {
  padding: 0 !important;
  max-width: 100% !important;
}
[data-testid="stMain"] [data-testid="stVerticalBlock"] { gap: 0 !important; }
[data-testid="stHeader"] { background: transparent !important; }
</style>
"""


def _ask_key() -> str:
    """키가 없을 때만: 화면에서 입력받는다(이 세션 동안 매물 지도·위치에도 쓰인다)."""
    st.title("전체 매물")
    st.info("카카오 JavaScript 키를 입력하면 지도가 표시됩니다. "
            "frontend/.env·Streamlit secrets의 KAKAO_JAVASCRIPT_KEY로도 설정할 수 있습니다.")
    # 입력칸은 지도가 뜨면 사라져 위젯 값도 지워지므로, 일반 상태 키(KEY_INPUT)에 옮겨 둔다
    st.text_input("카카오 JavaScript 키", type="password", key="map_key_field",
                  on_change=lambda: st.session_state.update(
                      {logic.KEY_INPUT: str(st.session_state.get("map_key_field") or "").strip()}))
    st.caption("카카오 개발자 콘솔의 Web 도메인에 접속 주소(예: http://localhost:8501)를 등록해 주세요.")
    return str(st.session_state.get(logic.KEY_INPUT) or "")


def _photos() -> dict[str, str]:
    """목록 썸네일: 매물별 처음 올린 사진. 못 불러와도 목록은 사진 없이 보인다."""
    try:
        return logic.first_photos(api_get("/me/photos") or [])
    except ApiError:
        return {}


def render_all_listings() -> None:
    try:
        data = api_get("/me/locations")
    except ApiError as e:
        st.title("전체 매물")
        show_api_error(e)
        if st.button("다시 시도", key="map_all_retry"):
            st.rerun()
        return

    pins = data.get("pins") or []
    if not pins:
        st.title("전체 매물")
        if data.get("listing_count"):
            st.info("아직 위치를 넣은 매물이 없습니다. 매물을 열고 '위치'에서 주소를 검색해 저장하면 여기에 표시됩니다.")
        else:
            st.info("아직 매물이 없습니다. 세션 목록에서 세션을 만들고 집 메모를 저장한 뒤 위치를 넣어 보세요.")
        if st.button("세션 목록으로", key="map_all_to_sessions"):
            nav.go_sessions()
        return

    api_key = components.current_api_key() or _ask_key()
    if not api_key:
        return

    st.markdown(FULL_BLEED_CSS, unsafe_allow_html=True)
    result = components.pins_map(
        api_key, logic.my_pins(pins), key="map_all_pins", fullscreen=True,
        panel=logic.panel_text(pins, int(data.get("listing_count") or 0), _photos()),
    )
    opened = getattr(result, "open", None)
    if opened and any(p["listing_id"] == opened for p in pins):
        nav.go_listing_detail(opened)   # 카드의 '매물 상세 보기'


PAGES = [
    {"key": "map", "title": "전체 매물", "order": 70, "admin_only": False, "render": render_all_listings},
]
