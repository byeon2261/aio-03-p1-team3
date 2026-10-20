"""F2·F3 상세 화면 섹션.

- session_detail (order 10): 맨 위 요약 숫자 카드(본 집·예산 안·확인 필요·최저 월 고정비), 매물 카드 목록
  (사진 | 제목·한 줄 정보·상태 칩 | 월 고정비·[상세 보기 →]), 오른쪽 열에 'AI 정리' 제목 + '정리 안 된 매물 N곳' 배너
  ([AI로 정리하기])와 F13 매물 지도, 그 아래 '새 매물 메모 추가' 펼침 상자(매물이 없으면 펼친 상태).
- session_detail (order 90): 페이지 맨 아래 '세션 관리' 펼침 상자(아이콘 settings)(세션 제목·방문일 수정, 세션 삭제).
  요약 숫자·카드 숫자·예산 칩은 같은 화면의 비교표가 쓰는 GET /sessions/{id}/comparison 응답에서 만든다(summary.py).
- listing_detail (order 10): [⋯] 팝오버 안 [매물 삭제] → 같은 팝오버 안 삭제 확인(menu), 한 번짜리 안내(notice),
  '메모' 탭의 메모 편집·저장(memo)
"""

from __future__ import annotations

import html
import logging

import streamlit as st

from core import nav
from core.api import ApiError, api_delete, api_get, api_patch, api_post
from core.ui import empty_state, fmt_kst, icon_badge, icon_title, show_api_error
from features.sessions import analyze_all, summary
from features.sessions.common import flash, parse_date, show_flash, status_next_step
from features.sessions.memo_editor import render_memo_editor
from features.map.listing_map import render_session_map

TITLE_MAX_CHARS = 100
MEMO_PLACEHOLDER = "예: 보증금 500 / 월세 45 / 관리비 7(인터넷 포함). 3층, 남향. 채광 좋음, 수압 보통. 역까지 도보 8분."
CLEANUP_FAILED_MESSAGE = "사진 정리에 실패했습니다. 다시 삭제하세요"


def _confirm_key(kind: str, rid: str) -> str:
    return f"p1_confirm_delete:{kind}:{rid}"


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


def _session_comparison(session_id: str) -> dict | None:
    """요약 숫자·카드 숫자에 쓸 비교표 응답(예산 필터 없이 전체 매물). 못 불러오면 None(숫자 없이 목록만 표시).

    비교표 섹션(P3)도 같은 API를 부른다. 이 화면 안의 부가 정보라 실패해도 오류 상자는 띄우지 않는다.
    """
    try:
        return api_get(f"/sessions/{session_id}/comparison")
    except ApiError as e:
        logger.warning("session comparison unavailable: %s", e.code)
    except Exception as exc:  # 응답 형식이 예상과 달라도 매물 목록은 보여야 한다
        logger.warning("session comparison unavailable: %s", type(exc).__name__)
    return None


def _summary_card(m: dict) -> str:
    """요약 카드 한 장(HTML): 연한 색 원 아이콘 + 라벨, 큰 숫자. 설명은 마우스를 올리면(title)."""
    return (f'<div class="ht-summary-card" title="{html.escape(m["help"], quote=True)}" style="background:#fff;'
            'border:1px solid #E3E8F2;border-radius:16px;padding:1rem 1.25rem;box-shadow:0 1px 2px rgba(17,13,60,.04),'
            '0 4px 16px rgba(17,13,60,.06)"><div style="display:flex;align-items:center;gap:8px;color:#64636d;'
            f'font-size:14px;font-weight:600">{icon_badge(m["icon"], m["tone"], 28)}{html.escape(m["label"])}</div>'
            f'<div style="font-size:2rem;font-weight:800;color:#110D3C;letter-spacing:-.02em;margin-top:.4rem">'
            f'{html.escape(m["value"])}</div></div>')


def _render_summary(listings: list[dict], comparison: dict | None) -> None:
    cols = st.columns(4)
    for col, m in zip(cols, summary.summary_metrics(listings, comparison)):
        col.markdown(_summary_card(m), unsafe_allow_html=True)
    if comparison is None:
        st.caption("요약 숫자를 불러오지 못했습니다. 아래 매물 비교표에서 확인하거나 새로 고쳐 주세요.")


NO_PHOTO_ICON = (  # 집 아이콘(사진이 없는 매물 자리). 강조색, 선만
    '<svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="#3246d3" stroke-width="1.6" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V20h14V9.5"/><path d="M10 20v-5h4v5"/></svg>'
)
ONE_LINE = "white-space:nowrap;overflow:hidden;text-overflow:ellipsis"
MUTED = "#64636d"


def _no_photo() -> None:
    st.markdown(
        '<div role="img" aria-label="사진 없음" style="width:100%;aspect-ratio:4/3;max-height:120px;'
        'border-radius:12px;background:linear-gradient(135deg,#eef2fb 0%,#e3e9fb 100%);display:flex;'
        f'align-items:center;justify-content:center;opacity:.9">{NO_PHOTO_ICON}</div>',
        unsafe_allow_html=True,
    )


def _card_title(label: str, info: str) -> None:
    """제목(크고 굵게) + 한 줄 정보(작은 회색, 넘치면 …)."""
    st.markdown(
        f'<div style="font-size:1.15rem;font-weight:800;line-height:1.3;color:#110d3c">{html.escape(label)}</div>'
        f'<div title="{html.escape(info, quote=True)}" style="font-size:13px;color:{MUTED};margin-top:2px;'
        f'{ONE_LINE}">{html.escape(info)}</div>',
        unsafe_allow_html=True,
    )


def _price(row: dict | None, hint: str = "") -> None:
    """오른쪽 위: 월 고정비(파란 큰 숫자)와 보조 줄. 분석 값이 없으면 짧은 안내 한 줄."""
    lines = summary.price_lines(row)
    if lines:
        main, sub = lines
        sub_html = "<br>".join(html.escape(part) for part in sub.split(" · "))   # 좁은 칸에서 한 줄씩
        body = (f'<div style="font-size:1.4rem;font-weight:800;color:#3246d3;letter-spacing:-.01em">'
                f'{html.escape(main)}</div><div style="font-size:12px;color:{MUTED}">{sub_html}</div>')
    elif hint:
        body = f'<div style="font-size:13px;color:{MUTED};{ONE_LINE}">{html.escape(hint)}</div>'
    else:
        return
    st.markdown(f'<div style="text-align:right;line-height:1.35">{body}</div>', unsafe_allow_html=True)


def _listing_card(lst: dict, photos: list[dict] | None = None, row: dict | None = None) -> None:
    with st.container(border=True):
        thumb, left, right = st.columns([1.1, 3, 1.4], vertical_alignment="center")
        with thumb:
            if photos:
                _thumbnail(photos, lst["label"])
            else:
                _no_photo()
        with left:
            _card_title(lst["label"], summary.info_line(lst, row))
            st.markdown(" ".join(summary.chips(lst, row)))
        with right:
            hint = analyze_all.CARD_HINT if analyze_all.needs_analysis(lst) else status_next_step(lst)
            _price(row, hint)
            if st.button("상세 보기 →", key=f"p1_open_listing:{lst['id']}", type="tertiary", width="stretch"):
                nav.go_listing_detail(lst["id"])


def _render_listings(session: dict) -> None:
    sid = session["id"]
    try:
        with st.spinner("매물을 불러오는 중…"):
            listings = api_get(f"/sessions/{sid}/listings")
    except ApiError as e:
        icon_title("home", "매물")
        show_api_error(e)
        if st.button("다시 시도", key=f"p1_listings_retry:{sid}"):
            st.rerun()
        return
    if not listings:
        icon_title("home", "매물")
        empty_state("home", "아직 매물이 없어요. 본 집 메모를 적으면 AI가 비교표로 정리해 드려요.",
                    button="첫 집 메모 적기", link="#new-memo", key="p1_empty_listings")
        return
    comparison = _session_comparison(sid)
    _render_summary(listings, comparison)
    icon_title("home", "매물")
    photos = _session_photos(sid)
    rows = summary.rows_by_listing(comparison)
    cards, side = st.columns([3, 2])
    with cards:
        for lst in listings:
            _listing_card(lst, photos.get(str(lst["id"])), rows.get(str(lst["id"])))
        if len(listings) == 1:
            st.caption("매물을 하나 더 추가하면 비교할 수 있습니다.")
    with side:
        icon_title("auto_awesome", "AI 정리")
        analyze_all.render_banner(listings, sid)
        icon_title("location_on", "지도")
        # F13: 위치를 넣은 매물을 지도에 찍는다(features/map/listing_map.py)
        render_session_map(session, listings)


NEW_MEMO_LABEL = "새 매물 메모 추가"     # 아이콘은 expander icon=
MANAGE_LABEL = "세션 관리"


def _render_new_memo(session: dict) -> None:
    """매물 목록 바로 아래 펼침 상자. 매물이 없으면 처음부터 펼쳐 둔다."""
    sid = session["id"]

    def save(text: str) -> str:
        created = api_post(f"/sessions/{sid}/listings", json={"memo_text": text})
        return f"{created['label']}을(를) 저장했습니다. 매물을 눌러 분석을 실행하거나 다음 집 메모를 적으세요."

    # 빈 화면 카드의 [첫 집 메모 적기 →]가 이 자리로 온다
    st.markdown('<div id="new-memo"></div>', unsafe_allow_html=True)
    with st.expander(NEW_MEMO_LABEL, icon=":material/edit_note:", expanded=not session.get("listing_count")):
        render_memo_editor(scope=f"new:{sid}", draft_path=f"/sessions/{sid}/draft", initial_text="",
                           label="이번 집 메모", placeholder=MEMO_PLACEHOLDER, save_label="메모 저장",
                           on_save=save, clear_after_save=True)


def _render_session_edit(session: dict) -> None:
    sid = session["id"]
    st.markdown("**세션 제목·방문일 수정**")
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
    _render_new_memo(session)


def render_session_manage(ctx: dict) -> None:
    """페이지 맨 아래(order 90): 세션 제목·방문일 수정과 세션 삭제를 접힌 펼침 상자 하나로.

    삭제 확인 중에는 펼친 채로 둔다(확인 문구와 [삭제]/[취소]가 상자 안에 있다).
    """
    session = ctx["session"]
    confirming = bool(st.session_state.get(_confirm_key("session", session["id"])))
    with st.expander(MANAGE_LABEL, icon=":material/settings:", expanded=confirming):
        _render_session_edit(session)
        st.divider()
        _render_session_delete(session)


# ------------------------------------------------------------------ listing_detail
# [삭제] 버튼만 빨간 글씨(테두리 버튼). 선택자는 st.button(key=…)이 붙이는 공식 CSS 클래스 st-key-<key>
DELETE_BUTTON_CSS = """<style>
[class*="st-key-p1_delete_listing_ok"] button { color: #E5484D; border-color: #F2B8BA; }
[class*="st-key-p1_delete_listing_ok"] button:hover { color: #C93C40; border-color: #E5484D; background: #FDF0F0; }
[class*="st-key-p1_delete_listing_ok"] button p { color: inherit; font-weight: 700; }
</style>"""


def render_listing_menu(ctx: dict) -> None:
    """매물 상세 [⋯] 팝오버 안: [매물 삭제] → 같은 팝오버 안에 확인 문구 + [삭제]/[취소]. 흐름·key는 예전과 같다."""
    listing, session = ctx["listing"], ctx["session"]
    lid = listing["id"]
    key = _confirm_key("listing", lid)
    if not st.session_state.get(key):
        if st.button("매물 삭제", key=f"p1_delete_listing:{lid}", icon=":material/delete:", type="tertiary"):
            st.session_state[key] = True
            st.rerun()
        return
    st.html(DELETE_BUTTON_CSS)
    st.markdown(f"**{listing['label']}을(를) 삭제할까요?**")
    st.caption("메모·분석·사진이 모두 삭제됩니다. 지운 번호는 다시 쓰지 않습니다. 되돌릴 수 없습니다.")
    ok_col, cancel_col = st.columns(2)
    with cancel_col:
        if st.button("취소", key=f"p1_delete_listing_cancel:{lid}", width="stretch"):
            st.session_state.pop(key, None)
            st.rerun()
    with ok_col:
        confirmed = st.button("삭제", key=f"p1_delete_listing_ok:{lid}", width="stretch")
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


def render_listing_flash(ctx: dict) -> None:
    """제목 아래(notice): 이 매물 화면에 남긴 한 번짜리 안내."""
    show_flash("listing_detail")


def render_listing_memo(ctx: dict) -> None:
    """매물 상세 '메모' 탭: 메모 편집·저장(분석 상태 문구는 제목 옆 칩으로 옮김)."""
    listing = ctx["listing"]
    lid = listing["id"]

    def save(text: str) -> str:
        updated = api_patch(f"/listings/{lid}", json={"memo_text": text})
        if updated.get("needs_reanalysis"):
            return "메모를 저장했습니다. 분석 뒤에 메모가 바뀌었으니 분석을 다시 실행하세요."
        return f"메모를 저장했습니다({fmt_kst(updated.get('memo_updated_at'))})."

    render_memo_editor(scope=f"listing:{lid}", draft_path=f"/listings/{lid}/draft",
                       initial_text=listing.get("memo_text") or "", label="메모 편집",
                       placeholder=MEMO_PLACEHOLDER, save_label="메모 저장", on_save=save)


SECTIONS = [
    {"slot": "session_detail", "order": 10, "render": render_session_section},
    {"slot": "session_detail", "order": 90, "render": render_session_manage},
    # 매물 상세: 자리(area)는 core/host_pages.py 참고. order는 check_merge 중복 점검 때문에 자리마다 다르게
    {"slot": "listing_detail", "order": 10, "area": "menu", "render": render_listing_menu},
    {"slot": "listing_detail", "order": 11, "area": "notice", "render": render_listing_flash},
    {"slot": "listing_detail", "order": 12, "area": "memo", "render": render_listing_memo},
]
