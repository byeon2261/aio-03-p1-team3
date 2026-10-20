"""F2 세션 목록 페이지 (key sessions, order 10, 사이드바 이름 '세션')."""

from __future__ import annotations

import streamlit as st

from core import nav
from core.api import ApiError, api_get, api_post
from core.ui import fmt_kst, icon_badge, icon_title, show_api_error
from features.sessions.common import flash, show_flash, visit_text

TITLE_MAX_CHARS = 100
EMPTY_TEXT = "아직 집 보기 세션이 없어요. 제목을 적고 첫 세션을 만들어 보세요."
FLASH_WHERE = "sessions"
NEW_SESSION_LABEL = ":blue[**새 집 보기 세션 만들기**]"   # 강조색 글자(테마 blueColor = 강조색), 아이콘은 icon=


def _create_fields() -> tuple[str, object, bool]:
    with st.form("p1_new_session", clear_on_submit=False):
        title = st.text_input("제목", max_chars=TITLE_MAX_CHARS, placeholder="예: 10월 셋째 주 토요일 신촌")
        visit_date = st.date_input("방문일 (선택)", value=None, format="YYYY-MM-DD")
        submitted = st.form_submit_button("세션 만들기", type="primary")
    return title, visit_date, submitted


def _create_form(empty: bool) -> None:
    """세션이 있으면 접힌 펼침 상자, 없으면 빈 화면 카드(아이콘 + 한 줄 + 만들기 폼의 [세션 만들기] 하나)."""
    if empty:
        with st.container(border=True, key="ht_empty_sessions"):
            st.markdown(
                '<div style="display:flex;flex-direction:column;align-items:center;gap:.6rem;padding:.5rem 0">'
                f'{icon_badge("home_work", "blue", 44)}<div style="color:#3d4152">{EMPTY_TEXT}</div></div>',
                unsafe_allow_html=True)
            title, visit_date, submitted = _create_fields()
    else:
        with st.expander(NEW_SESSION_LABEL, icon=":material/add_circle:"):
            title, visit_date, submitted = _create_fields()
    if not submitted:
        return
    if not title.strip():
        st.warning("세션 제목을 입력하세요.")
        return
    body = {"title": title.strip(), "visit_date": visit_date.isoformat() if visit_date else None}
    try:
        with st.spinner("세션을 만드는 중…"):
            created = api_post("/sessions", json=body)
    except ApiError as e:
        show_api_error(e)
        return
    flash("session_detail", "세션을 만들었습니다. 아래에 첫 집 메모를 적어 보세요.")
    nav.go_session_detail(created["id"])


def _session_card(s: dict) -> None:
    with st.container(border=True):
        st.markdown(f"**{s['title']}**")
        st.caption(f"{visit_text(s.get('visit_date'))} · 매물 {s.get('listing_count', 0)}곳")
        st.caption(f"만든 시각 {fmt_kst(s.get('created_at'))}")
        if st.button("상세 보기 →", key=f"p1_open_session:{s['id']}", type="tertiary", width="stretch"):
            nav.go_session_detail(s["id"])


def render_sessions() -> None:
    st.title("집 보기 세션")
    st.caption("하루 동안 본 집들을 한 세션에 모아 메모하고 비교하세요.")
    show_flash(FLASH_WHERE)

    try:
        with st.spinner("세션을 불러오는 중…"):
            sessions = api_get("/sessions")
    except ApiError as e:
        show_api_error(e)
        if st.button("다시 시도", key="p1_sessions_retry"):
            st.rerun()
        return

    _create_form(empty=not sessions)
    if not sessions:
        return

    icon_title("home_work", f"내 세션 {len(sessions)}개")
    cols = st.columns(3)
    for i, s in enumerate(sessions):
        with cols[i % 3]:
            _session_card(s)


PAGES = [
    {"key": "sessions", "title": "세션", "order": 10, "admin_only": False, "render": render_sessions},
]
