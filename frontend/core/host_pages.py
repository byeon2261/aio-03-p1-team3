"""R의 상세 페이지 2개. 내용은 슬롯(session_detail, listing_detail)에 붙는 섹션이 그린다."""

from __future__ import annotations

import streamlit as st

from core import nav, state
from core.api import ApiError, api_get
from core.slots import render_slot, sections_for
from core.ui import fmt_kst, show_api_error


def _back_to_sessions(label: str = "세션 목록으로") -> None:
    if st.button(label, key="host_back_sessions"):
        nav.go_sessions()


def render_session_detail() -> None:
    sid = st.session_state.get(state.SELECTED_SESSION_ID)
    if not sid:
        st.subheader("세션 상세")
        st.info("볼 세션을 아직 고르지 않았습니다. 세션 목록에서 세션을 고르세요.")
        _back_to_sessions()
        return
    try:
        with st.spinner("세션을 불러오는 중…"):
            session = api_get(f"/sessions/{sid}")
    except ApiError as e:
        show_api_error(e)
        _back_to_sessions()
        return

    st.title(session["title"])
    visit = session.get("visit_date") or "날짜 미정"
    st.caption(f"방문일 {visit} · 매물 {session.get('listing_count', 0)}곳 · 만든 시각 {fmt_kst(session.get('created_at'))}")
    if not sections_for("session_detail"):
        st.info("아직 이 화면에 붙은 기능이 없습니다.")
    render_slot("session_detail", {"session": session})


def render_listing_detail() -> None:
    lid = st.session_state.get(state.SELECTED_LISTING_ID)
    if not lid:
        st.subheader("매물 상세")
        st.info("볼 매물을 아직 고르지 않았습니다. 세션 화면에서 매물을 고르세요.")
        _back_to_sessions()
        return
    try:
        with st.spinner("매물을 불러오는 중…"):
            listing = api_get(f"/listings/{lid}")
            session = api_get(f"/sessions/{listing['session_id']}")
    except ApiError as e:
        show_api_error(e)
        _back_to_sessions()
        return

    if st.button(f"← {session['title']}", key="host_back_session"):
        nav.go_session_detail(session["id"])
    st.title(listing.get("label") or f"{listing.get('listing_no')}번 집")
    st.caption(f"메모 수정 {fmt_kst(listing.get('memo_updated_at'))}")
    if not sections_for("listing_detail"):
        st.info("아직 이 화면에 붙은 기능이 없습니다.")
    render_slot("listing_detail", {"listing": listing, "session": session})
