"""R의 상세 페이지 2개. 내용은 슬롯(session_detail, listing_detail)에 붙는 섹션이 그린다.

매물 상세 배치(위에서 아래로):
    [← 세션 이름]
    N번 집 (분석 상태·예산 판정 칩)                 [actions 버튼] [⋯ menu]
    세션 이름 · 메모 수정 시각
    notice(안내·삭제 확인·빈 상태 카드) → overview(분석 완료일 때 숫자 카드)
    탭: 분석 완료 = 요약 / 메모 / 수정·평가 / 사진·위치 / 내 점수
        분석 전·실패 = 메모 고치기 / 사진·위치 / 내 점수
    main(자리를 정하지 않은 섹션)
"""

from __future__ import annotations

import html
import logging

import streamlit as st

from core import nav, state
from core.api import ApiError, api_get
from core.slots import render_slot, sections_for
from core.ui import fmt_kst, show_api_error

logger = logging.getLogger("frontend.host_pages")

# 분석 상태(ListingOut.latest_analysis_status) · 예산 판정(비교표 응답의 columns.budget.status) → 칩
STATUS_CHIPS = {"success": ("green", "분석 완료"), "none": ("gray", "분석 전"), "failed": ("red", "분석 실패")}
REANALYSIS_CHIP = ("orange", "재분석 필요")
BUDGET_CHIPS = {"within": ("green", "예산 안"), "over": ("red", "예산 초과"), "unknown": ("gray", "판단 불가")}
# 제목 옆 칩 색(바탕, 글자). 테마 초록·빨강·회색과 같은 계열
CHIP_COLORS = {"green": ("#E7F6EC", "#15803D"), "red": ("#FDECEC", "#C93C40"),
               "gray": ("#EEF0F4", "#55596A"), "orange": ("#FFF1E0", "#B45309")}
# (area, 탭 이름). 분석 완료 여부에 따라 탭 묶음이 다르다
TABS_ANALYZED = (("summary", ":material/description: 요약"), ("memo", ":material/edit_note: 메모"),
                 ("review", ":material/rate_review: 수정·평가"), ("media", ":material/photo_camera: 사진·위치"),
                 ("score", ":material/tune: 내 점수"))
TABS_NOT_ANALYZED = (("memo", ":material/edit_note: 메모 고치기"), ("media", ":material/photo_camera: 사진·위치"),
                     ("score", ":material/tune: 내 점수"))


def _back_to_sessions(label: str = "← 세션") -> None:
    if st.button(label, key="host_back_sessions"):
        nav.go_sessions()


def render_session_detail() -> None:
    sid = st.session_state.get(state.SELECTED_SESSION_ID)
    if not sid:
        st.subheader("세션 상세")
        st.info("볼 세션을 아직 고르지 않았습니다. 사이드바의 '세션'에서 세션을 고르세요.")
        _back_to_sessions()
        return
    try:
        with st.spinner("세션을 불러오는 중…"):
            session = api_get(f"/sessions/{sid}")
    except ApiError as e:
        show_api_error(e)
        _back_to_sessions()
        return

    _back_to_sessions()
    st.title(session["title"])
    visit = session.get("visit_date") or "날짜 미정"
    st.caption(f"방문일 {visit} · 매물 {session.get('listing_count', 0)}곳 · 만든 시각 {fmt_kst(session.get('created_at'))}")
    if not sections_for("session_detail"):
        st.info("아직 이 화면에 붙은 기능이 없습니다.")
    render_slot("session_detail", {"session": session})


def _comparison_row(session_id: str, listing_id: str) -> dict | None:
    """이 매물의 비교표 행(예산 판정·월 고정비). 세션 화면과 같은 GET /sessions/{id}/comparison. 실패하면 None."""
    try:
        data = api_get(f"/sessions/{session_id}/comparison") or {}
    except ApiError as e:
        logger.warning("listing comparison unavailable: %s", e.code)
        return None
    except Exception as exc:  # 부가 정보: 형식이 달라도 화면은 그린다
        logger.warning("listing comparison unavailable: %s", type(exc).__name__)
        return None
    return next((r for r in data.get("rows") or [] if str(r.get("listing_id")) == str(listing_id)), None)


def _title_chips(listing: dict, row: dict | None) -> list[tuple[str, str]]:
    """[(색, 문구)]: 분석 상태 → 재분석 필요 → 예산 판정(예산을 정했고 매물이 2곳 이상일 때)."""
    chips = [STATUS_CHIPS.get(listing.get("latest_analysis_status") or "none", STATUS_CHIPS["none"])]
    if listing.get("needs_reanalysis"):
        chips.append(REANALYSIS_CHIP)
    budget = BUDGET_CHIPS.get((((row or {}).get("columns") or {}).get("budget") or {}).get("status") or "")
    if budget:
        chips.append(budget)
    return chips


def _title_html(label: str, chips: list[tuple[str, str]]) -> str:
    """제목(h1) 옆에 작은 칩. 사용자 입력이 들어가므로 escape한다."""
    spans = "".join(
        f'<span style="display:inline-block;padding:2px 9px;border-radius:6px;font-size:13px;font-weight:700;'
        f'background:{CHIP_COLORS[c][0]};color:{CHIP_COLORS[c][1]};vertical-align:middle">{html.escape(text)}</span>'
        for c, text in chips)
    return (f'<div style="display:flex;align-items:center;gap:.5rem;flex-wrap:wrap">'
            f'<h1 style="margin:0;padding:0">{html.escape(label)}</h1>{spans}</div>')


def render_listing_detail() -> None:
    lid = st.session_state.get(state.SELECTED_LISTING_ID)
    if not lid:
        st.subheader("매물 상세")
        st.caption("볼 매물을 아직 고르지 않았습니다. 세션 화면에서 매물을 고르세요.")
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

    if st.button(f"← {session['title']}", key="host_back_session", type="tertiary"):
        nav.go_session_detail(session["id"])
    row = _comparison_row(session["id"], lid)
    ctx = {"listing": listing, "session": session, "comparison_row": row}
    label = listing.get("label") or f"{listing.get('listing_no')}번 집"

    head, actions, menu = st.columns([5, 1.6, 0.5], vertical_alignment="bottom")
    with head:
        st.markdown(_title_html(label, _title_chips(listing, row)), unsafe_allow_html=True)
        st.caption(f"{session['title']} · 메모 수정 {fmt_kst(listing.get('memo_updated_at'))}")
    with actions:
        render_slot("listing_detail", ctx, area="actions")
    with menu:
        with st.popover(":material/more_horiz:", help="매물 관리", width="stretch"):
            render_slot("listing_detail", ctx, area="menu")

    if not sections_for("listing_detail"):
        st.caption("아직 이 화면에 붙은 기능이 없습니다.")
    render_slot("listing_detail", ctx, area="notice")
    analyzed = (listing.get("latest_analysis_status") or "none") == "success"
    if analyzed:
        render_slot("listing_detail", ctx, area="overview")
    tab_specs = TABS_ANALYZED if analyzed else TABS_NOT_ANALYZED
    # key + on_change="rerun": 고른 탭을 서버가 기억해서, 탭 안 버튼으로 화면을 다시 그려도 첫 탭으로 돌아가지 않는다.
    # 숨은 탭의 내용도 그대로 그린다(입력 중인 값이 사라지지 않게)
    tabs = st.tabs([title for _, title in tab_specs], key=f"listing_tabs:{lid}:{int(analyzed)}", on_change="rerun")
    for tab, (area, _) in zip(tabs, tab_specs):
        with tab:
            render_slot("listing_detail", ctx, area=area)
    render_slot("listing_detail", ctx, area="main")
