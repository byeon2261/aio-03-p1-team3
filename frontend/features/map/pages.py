"""F13 지도 탐색 페이지(key map, order 70). import할 때 st 함수를 부르지 않는다.

서울역 주변 더미 매물(실제 주소 샘플 9개 + 가상 21개, 서버 GET /map/listings)을 반경 300m·500m·1km로 찾아 카카오 지도와 목록에 보여 준다.
카카오 JavaScript 키: st.secrets / 환경변수 / frontend/.env 의 KAKAO_JAVASCRIPT_KEY, 없으면 화면에서 입력.
"""

from __future__ import annotations

import streamlit as st

from core.api import ApiError, api_get
from features.map import components, logic


def _init_state() -> None:
    st.session_state.setdefault(logic.COMMAND, {"id": 0, "type": "none"})
    st.session_state.setdefault(logic.ORIGIN, logic.DEMO_ORIGIN.copy())
    st.session_state.setdefault(logic.SELECTED, None)


def _send(type_: str, **fields: object) -> None:
    st.session_state[logic.COMMAND] = logic.next_command(st.session_state[logic.COMMAND], type_, **fields)


def _load_listings(origin: dict | None, radius_m: int) -> list[dict] | None:
    """서버에서 반경 안의 더미 매물을 가져온다. 실패하면 오류를 보여 주고 None."""
    if origin is None:
        return []
    try:
        return api_get("/map/listings", params=logic.search_params(origin, radius_m))["listings"]
    except ApiError as exc:
        st.error(f"주변 매물을 불러오지 못했습니다. {exc.message}")
        return None


def _show_area(listing: dict) -> None:
    if listing.get("road_address"):
        st.caption("도로명주소")
        st.text(listing["road_address"])
        st.caption("지번주소")
        st.text(listing["parcel_address"])
        if listing.get("building_name"):
            st.caption("건물명")
            st.text(listing["building_name"])
        st.caption(f"우편번호 {listing['postal_code']} · 건물 대표 좌표 기준")
    else:
        st.caption("지역")
        st.text(f"{listing['area_name']} 일대")
        st.caption("가상 매물 · 가상 좌표")
    st.caption(f"{listing['property_type']} · {listing['area_m2']}㎡ · {listing['floor']}층")


def _controls(api_key: str) -> int:
    if st.button("주소 검색", icon=":material/location_on:", type="primary", disabled=not api_key,
                 key="map_address_search"):
        components.open_address_search()
    st.caption("카카오 주소 검색창에서 도로명·지번·건물명을 검색하고 주소를 선택해 주세요.")

    if st.button("서울역 더미 매물 보기", icon=":material/home_work:", key="map_demo_origin"):
        st.session_state[logic.ORIGIN] = logic.DEMO_ORIGIN.copy()
        st.session_state[logic.SELECTED] = None
        _send("set_origin", origin=logic.DEMO_ORIGIN.copy())

    radius_m = st.segmented_control(
        "검색 반경", options=logic.RADIUS_OPTIONS, default=logic.RADIUS_OPTIONS[0],
        format_func=logic.radius_label, required=True, key=logic.RADIUS,
    )

    with st.form("map_station_search"):
        input_column, button_column = st.columns([4, 1], vertical_alignment="bottom")
        with input_column:
            query = st.text_input("검색할 역 이름", placeholder="역 이름을 입력하세요 (예: 강남역)",
                                  key="map_station_query")
        with button_column:
            submitted = st.form_submit_button("역 검색", type="primary", disabled=not api_key)
    if submitted:
        if query.strip():
            _send("search", query=query.strip())
        else:
            st.warning("검색할 역 이름을 입력해 주세요.")

    if st.button("서울 중심으로", icon=":material/my_location:", key="map_reset", disabled=not api_key):
        st.session_state[logic.ORIGIN] = None
        st.session_state[logic.SELECTED] = None
        _send("reset")
    return int(radius_m)


def _listing_list(origin: dict | None, radius_m: int, listings: list[dict], *, failed: bool = False) -> None:
    st.subheader(f"주변 매물 {len(listings)}개")
    if origin:
        st.caption(f"기준: {origin['label']} · 반경 {radius_m:,}m · 직선거리 가까운 순")
        st.caption("반경을 넓히면 안쪽 매물도 포함됩니다. 지도 이동은 검색 기준점을 바꾸지 않습니다.")
        if not listings and not failed:
            st.info("선택한 반경 안에 더미 매물이 없습니다. 반경을 넓히거나 서울역 더미 매물 보기를 눌러 보세요.")
    else:
        st.info("주소나 역을 검색하거나 서울역 더미 매물 보기를 눌러 검색 기준을 선택해 주세요.")
    for index, listing in enumerate(listings, 1):
        with st.expander(f"{index}. {listing['title']} · {listing['distance_m']:.0f}m"):
            st.text(f"{listing['lease_type']} · {logic.price_text(listing)}")
            _show_area(listing)
            st.caption(logic.data_note(listing))
            if st.button("매물 선택 · 지도에서 보기", key=f"map_focus_{listing['id']}"):
                st.session_state[logic.SELECTED] = listing["id"]
                _send("focus_listing", listingId=listing["id"])
                st.rerun()


def _side_panel(origin: dict | None, radius_m: int, listings: list[dict], view: dict | None) -> None:
    selected = next((x for x in listings if x["id"] == st.session_state[logic.SELECTED]), None)
    if selected:
        with st.container(border=True):
            st.subheader("선택한 매물")
            st.text(selected["title"])
            _show_area(selected)
            st.text(logic.price_text(selected))
            st.caption(logic.data_note(selected))
            if selected.get("address_source_url"):
                st.link_button("주소 정보 출처", selected["address_source_url"])

    with st.container(border=True):
        st.subheader("매물 검색 기준")
        st.text(origin["label"] if origin else "기준점 없음")
        st.metric("검색 결과", f"{len(listings)}개")
        st.caption(f"반경 {radius_m:,}m · 더미 매물 총 30개")

    if view and view.get("selectedAddress"):
        with st.container(border=True):
            st.subheader("검색한 주소")
            address = view["selectedAddress"]
            for field, label in (("zonecode", "우편번호"), ("roadAddress", "도로명주소"),
                                 ("parcelAddress", "지번주소"), ("buildingName", "건물명")):
                if address.get(field):
                    st.caption(label)
                    st.text(address[field])

    with st.container(border=True):
        st.subheader("현재 지도 영역")
        st.caption("아래 좌표 범위를 매물 검색 API에 전달하면 현재 화면 안의 매물을 조회할 수 있습니다.")
        for name, label in (("center", "지도 중심 (위도, 경도)"), ("southwest", "남서쪽 (위도, 경도)"),
                            ("northeast", "북동쪽 (위도, 경도)")):
            st.caption(label)
            st.code(logic.coordinate_text(view.get(name) if view else None), language=None)


def render_map_explorer() -> None:
    _init_state()
    st.title("동네 지도 탐색")
    st.caption("지도를 드래그하거나 확대해 보세요. 지도 이동이 끝나면 현재 화면의 좌표 범위가 업데이트됩니다.")
    st.caption("서울역 주변 더미 매물 30개입니다(실제 주소 샘플 9개 + 가상 매물 21개). 가격·면적·층수·임대 조건은 모두 가상입니다.")

    configured = logic.configured_api_key(st.secrets)
    with st.expander("카카오 지도 설정", expanded=not configured):
        api_key = st.text_input(
            "카카오 JavaScript 키", value=configured, type="password", key=logic.KEY_INPUT,
            help="frontend/.env, 환경 변수 또는 Streamlit secrets의 KAKAO_JAVASCRIPT_KEY로도 설정할 수 있습니다.",
        ).strip()
        st.caption("카카오 개발자 콘솔의 Web 도메인에 접속 주소(예: http://localhost:8501)를 등록해 주세요.")

    map_column, side_column = st.columns([3, 1])
    view = None
    with map_column:
        with st.container(border=True):
            radius_m = _controls(api_key)
            origin = st.session_state[logic.ORIGIN]
            loaded = _load_listings(origin, radius_m)
            listings = loaded or []
            if st.session_state[logic.SELECTED] not in {x["id"] for x in listings}:
                st.session_state[logic.SELECTED] = None
            if api_key:
                result = components.kakao_map(api_key, st.session_state[logic.COMMAND],
                                              logic.map_payload(origin, radius_m, listings))
                view = result.view
                if view and view.get("error"):
                    st.error(view["status"])
                else:
                    st.caption(view["status"] if view else "지도를 불러오는 중입니다.")
            else:
                st.info("카카오 JavaScript 키를 입력하면 지도가 표시됩니다.")
        _listing_list(origin, radius_m, listings, failed=loaded is None)

    with side_column:
        _side_panel(origin, radius_m, listings, view)


PAGES = [
    {"key": "map", "title": "동네 지도 탐색", "order": 70, "admin_only": False, "render": render_map_explorer},
]
