"""F2·F3 상세 화면 섹션.

- session_detail (order 10): 매물 목록(사진이 있으면 카드에 대표 사진, 오른쪽에 F13 매물 지도), 새 메모 입력,
  세션 제목·방문일 수정, 세션 삭제
- listing_detail (order 10): 분석 상태 안내, 메모 편집·저장, 매물 삭제
"""

from __future__ import annotations

import html
import logging

import streamlit as st

from core import nav
from core.api import ApiError, api_delete, api_get, api_patch, api_post
from core.ui import fmt_kst, show_api_error
from features.sessions.common import flash, parse_date, show_flash, status_next_step, status_text
from features.sessions.memo_editor import render_memo_editor
from features.map.listing_map import render_session_map

TITLE_MAX_CHARS = 100
MEMO_PLACEHOLDER = "예: 보증금 500 / 월세 45 / 관리비 7(인터넷 포함). 3층, 남향. 채광 좋음, 수압 보통. 역까지 도보 8분."
CLEANUP_FAILED_MESSAGE = "사진 정리에 실패했습니다. 다시 삭제하세요"


def _confirm_key(kind: str, rid: str) -> str:
    return f"p1_confirm_delete:{kind}:{rid}"


def _preview(text: str, n: int = 60) -> str:
    one_line = " ".join((text or "").split())
    return one_line if len(one_line) <= n else one_line[:n] + "…"


logger = logging.getLogger("frontend.sessions")


# ------------------------------------------------------------------ session_detail
def _session_photos(session_id: str) -> dict[str, list[dict]]:
    """이 세션 매물의 사진 {listing_id: [사진, …]}(올린 순). GET /me/photos(P4) 한 번으로 모은다.

    사진을 못 불러와도 매물 목록은 그대로 보여야 하므로 실패하면 빈 dict(사진 없이 표시).
    """
    try:
        photos = api_get("/me/photos") or []
    except ApiError as e:
        logger.warning("session photos unavailable: %s", e.code)
        return {}
    by_listing: dict[str, list[dict]] = {}
    for photo in reversed(photos):          # 응답은 최신순 → 올린 순으로
        if str(photo.get("session_id")) == str(session_id) and photo.get("url"):
            by_listing.setdefault(str(photo["listing_id"]), []).append(photo)
    return by_listing


def _thumbnail(photos: list[dict], label: str) -> None:
    """대표 사진(처음 올린 사진) 한 장. 여러 장이면 오른쪽 아래에 '+N'."""
    url = html.escape(photos[0]["url"], quote=True)
    more = (f'<span style="position:absolute;right:6px;bottom:6px;padding:1px 7px;border-radius:999px;'
            f'background:rgba(15,23,42,.72);color:#fff;font-size:12px;font-weight:600">+{len(photos) - 1}</span>'
            if len(photos) > 1 else "")
    st.markdown(
        f'<div style="position:relative;width:100%;aspect-ratio:4/3;border-radius:10px;overflow:hidden;'
        f'background:#f1f5f9"><img src="{url}" alt="{html.escape(label)} 사진" loading="lazy" '
        f'style="width:100%;height:100%;object-fit:cover;display:block">{more}</div>',
        unsafe_allow_html=True,
    )


def _listing_card(lst: dict, photos: list[dict] | None = None) -> None:
    with st.container(border=True):
        if photos:
            thumb, left, right = st.columns([1.3, 3, 1], vertical_alignment="center")
            with thumb:
                _thumbnail(photos, lst["label"])
        else:
            left, right = st.columns([4, 1], vertical_alignment="center")
        with left:
            st.markdown(f"**{lst['label']}** · {status_text(lst)}")
            st.caption(_preview(lst.get("memo_text", "")))
            hint = status_next_step(lst)
            if hint:
                st.caption(hint)
        with right:
            if st.button("열기", key=f"p1_open_listing:{lst['id']}", width="stretch"):
                nav.go_listing_detail(lst["id"])


def _render_listings(session: dict) -> None:
    sid = session["id"]
    st.subheader("매물")
    try:
        with st.spinner("매물을 불러오는 중…"):
            listings = api_get(f"/sessions/{sid}/listings")
    except ApiError as e:
        show_api_error(e)
        if st.button("다시 시도", key=f"p1_listings_retry:{sid}"):
            st.rerun()
        return
    if not listings:
        st.info("아직 매물이 없습니다. 아래 '새 메모'에 첫 집 메모를 적고 저장하세요.")
        return
    photos = _session_photos(sid)
    cards, map_area = st.columns([3, 2])
    with cards:
        for lst in listings:
            _listing_card(lst, photos.get(str(lst["id"])))
        if len(listings) == 1:
            st.caption("매물을 하나 더 추가하면 비교할 수 있습니다.")
    with map_area:
        # F13: 위치를 넣은 매물을 지도에 찍는다(features/map/listing_map.py)
        render_session_map(session, listings)


def _render_new_memo(session: dict) -> None:
    sid = session["id"]
    st.subheader("새 메모")

    def save(text: str) -> str:
        created = api_post(f"/sessions/{sid}/listings", json={"memo_text": text})
        return f"{created['label']}을(를) 저장했습니다. 매물을 눌러 분석을 실행하거나 다음 집 메모를 적으세요."

    render_memo_editor(scope=f"new:{sid}", draft_path=f"/sessions/{sid}/draft", initial_text="",
                       label="이번 집 메모", placeholder=MEMO_PLACEHOLDER, save_label="메모 저장",
                       on_save=save, clear_after_save=True)


def _render_session_edit(session: dict) -> None:
    sid = session["id"]
    with st.expander("세션 제목·방문일 수정"):
        with st.form(f"p1_edit_session:{sid}"):
            title = st.text_input("제목", value=session.get("title") or "", max_chars=TITLE_MAX_CHARS)
            visit = st.date_input("방문일", value=parse_date(session.get("visit_date")), format="YYYY-MM-DD")
            clear_visit = st.checkbox("방문일 비우기")
            submitted = st.form_submit_button("수정 저장")
    if not submitted:
        return
    if not title.strip():
        st.warning("세션 제목을 입력하세요. 빈 제목은 저장할 수 없습니다.")
        return
    body = {"title": title.strip(), "visit_date": None if (clear_visit or not visit) else visit.isoformat()}
    try:
        with st.spinner("저장하는 중…"):
            api_patch(f"/sessions/{sid}", json=body)
    except ApiError as e:
        show_api_error(e)
        return
    flash("session_detail", "세션 정보를 수정했습니다.")
    st.rerun()


def _render_session_delete(session: dict) -> None:
    sid = session["id"]
    key = _confirm_key("session", sid)
    if not st.session_state.get(key):
        if st.button("세션 삭제", key=f"p1_delete_session:{sid}"):
            st.session_state[key] = True
            st.rerun()
        return
    n = session.get("listing_count", 0)
    st.warning(f"'{session['title']}' 세션과 매물 {n}곳의 메모·분석·사진이 모두 삭제됩니다. 되돌릴 수 없습니다.")
    ok_col, cancel_col = st.columns(2)
    with cancel_col:
        if st.button("취소", key=f"p1_delete_session_cancel:{sid}", width="stretch"):
            st.session_state.pop(key, None)
            st.rerun()
    with ok_col:
        confirmed = st.button("삭제", key=f"p1_delete_session_ok:{sid}", type="primary", width="stretch")
    if not confirmed:
        return
    try:
        with st.spinner("삭제하는 중…"):
            api_delete(f"/sessions/{sid}")
    except ApiError as e:
        if e.code == "CLEANUP_FAILED":
            st.error(CLEANUP_FAILED_MESSAGE)
        else:
            show_api_error(e)
        return
    st.session_state.pop(key, None)
    flash("sessions", f"'{session['title']}' 세션을 삭제했습니다.")
    nav.go_sessions()


def render_session_section(ctx: dict) -> None:
    session = ctx["session"]
    show_flash("session_detail")
    _render_listings(session)
    st.divider()
    _render_new_memo(session)
    st.divider()
    _render_session_edit(session)
    _render_session_delete(session)


# ------------------------------------------------------------------ listing_detail
def _render_listing_delete(listing: dict, session: dict) -> None:
    lid = listing["id"]
    key = _confirm_key("listing", lid)
    if not st.session_state.get(key):
        if st.button("매물 삭제", key=f"p1_delete_listing:{lid}"):
            st.session_state[key] = True
            st.rerun()
        return
    st.warning(f"{listing['label']}의 메모·분석·사진이 모두 삭제됩니다. "
               "지운 번호는 다시 쓰지 않습니다. 되돌릴 수 없습니다.")
    ok_col, cancel_col = st.columns(2)
    with cancel_col:
        if st.button("취소", key=f"p1_delete_listing_cancel:{lid}", width="stretch"):
            st.session_state.pop(key, None)
            st.rerun()
    with ok_col:
        confirmed = st.button("삭제", key=f"p1_delete_listing_ok:{lid}", type="primary", width="stretch")
    if not confirmed:
        return
    try:
        with st.spinner("삭제하는 중…"):
            api_delete(f"/listings/{lid}")
    except ApiError as e:
        if e.code == "CLEANUP_FAILED":
            st.error(CLEANUP_FAILED_MESSAGE)
        else:
            show_api_error(e)
        return
    st.session_state.pop(key, None)
    flash("session_detail", f"{listing['label']}을(를) 삭제했습니다.")
    nav.go_session_detail(session["id"])


def render_listing_section(ctx: dict) -> None:
    listing, session = ctx["listing"], ctx["session"]
    lid = listing["id"]
    show_flash("listing_detail")

    st.markdown(f"분석 상태: {status_text(listing)}")
    hint = status_next_step(listing)
    if hint:
        st.caption(hint)

    def save(text: str) -> str:
        updated = api_patch(f"/listings/{lid}", json={"memo_text": text})
        if updated.get("needs_reanalysis"):
            return "메모를 저장했습니다. 분석 뒤에 메모가 바뀌었으니 분석을 다시 실행하세요."
        return f"메모를 저장했습니다({fmt_kst(updated.get('memo_updated_at'))})."

    render_memo_editor(scope=f"listing:{lid}", draft_path=f"/listings/{lid}/draft",
                       initial_text=listing.get("memo_text") or "", label="메모 편집",
                       placeholder=MEMO_PLACEHOLDER, save_label="메모 저장", on_save=save)
    _render_listing_delete(listing, session)


SECTIONS = [
    {"slot": "session_detail", "order": 10, "render": render_session_section},
    {"slot": "listing_detail", "order": 10, "render": render_listing_section},
]
