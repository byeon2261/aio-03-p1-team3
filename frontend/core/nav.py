"""페이지 이동. 선택 값을 저장한 뒤 st.switch_page로 넘어간다.

버튼 콜백(on_click) 안이 아니라 `if st.button(...): go_session_detail(sid)`처럼 본문에서 부른다.
페이지 key: sessions(P1) · session_detail · listing_detail(R) · mypage(P4) · admin_logs(P6) · evals(P7)
"""

from __future__ import annotations

import streamlit as st

from core import state

_PAGES_KEY = "_nav_pages"


def register_pages(pages: dict) -> None:
    """app.py가 매 실행마다 {key: st.Page}를 넣는다."""
    st.session_state[_PAGES_KEY] = pages


def _switch(key: str) -> None:
    page = (st.session_state.get(_PAGES_KEY) or {}).get(key)
    if page is None:
        st.warning("아직 준비되지 않은 화면입니다.")
        return
    st.switch_page(page)


def go_page(key: str) -> None:
    _switch(key)


def go_sessions() -> None:
    _switch("sessions")


def go_session_detail(session_id: str) -> None:
    st.session_state[state.SELECTED_SESSION_ID] = session_id
    _switch("session_detail")


def go_listing_detail(listing_id: str) -> None:
    st.session_state[state.SELECTED_LISTING_ID] = listing_id
    _switch("listing_detail")
