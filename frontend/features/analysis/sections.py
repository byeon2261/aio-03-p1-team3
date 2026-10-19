"""F4·F5 매물 상세 화면의 'AI 정리' (슬롯 listing_detail, order 20~23). 자리(area)는 core/host_pages.py.

    actions   분석 완료일 때만 제목 오른쪽 버튼(key analysis_run_{lid}): 메모가 바뀌면 [✨ 다시 분석](primary),
              그대로면 [✨ 다시 정리](비활성, "메모를 고치면 다시 정리할 수 있어요")
    notice    정리 결과 안내·재분석 안내, 분석 전·실패면 가운데 빈 상태 카드(큰 [✨ AI로 정리하기], 같은 key)
    overview  분석 완료: 숫자 카드 4개(보증금·월세·관리비·월 고정비) + 교통·층·방향·관리비 포함 한 줄
    summary   '요약' 탭: 장점·단점 상자, 확인 상태 칩 한 줄, 다음 방문 때 물어볼 것(체크 목록, 저장 안 함)
최신 분석은 한 번만 불러와 ctx에 담아 네 자리가 같이 쓴다. import 시 st 함수를 부르지 않는다.
"""

from __future__ import annotations

import html

import streamlit as st

from core.api import ApiError, api_get, api_post
from core.ui import fmt_kst, fmt_manwon, show_api_error
from features.analysis import logic

_FLASH_KEY = "analysis_flash:{lid}"


def _flash_key(lid: str) -> str:
    return _FLASH_KEY.format(lid=lid)


def _load_latest(lid: str) -> tuple[dict | None, ApiError | None]:
    try:
        return api_get(f"/listings/{lid}/analyses/latest"), None
    except ApiError as e:
        if e.code == "ANALYSIS_NOT_FOUND":
            return None, None
        return None, e


def _run_analysis(lid: str) -> None:
    """분석 요청. 결과(성공 안내 또는 오류)를 세션 상태에 남기고 화면 전체를 다시 그린다."""
    try:
        with st.spinner("AI가 메모를 정리하는 중입니다(보통 몇 초, 최대 1분)…"):
            api_post(f"/listings/{lid}/analyses", json={"use_cache": True})
        st.session_state[_flash_key(lid)] = {"kind": "success"}
    except ApiError as e:
        st.session_state[_flash_key(lid)] = {"kind": "error", "status": e.status, "code": e.code,
                                             "message": e.message, "detail": e.detail}
    st.rerun()


def _show_flash(lid: str) -> None:
    flash = st.session_state.pop(_flash_key(lid), None)
    if not flash:
        return
    if flash["kind"] == "success":
        st.success("정리했습니다. 아래 결과를 확인하고, 틀린 값은 고쳐 주세요.")
    else:
        show_api_error(ApiError(flash["status"], flash["code"], flash["message"], flash.get("detail")))


# 안쪽 항목 아이콘: Material 아이콘, 색은 강조색 한 가지(:blue = 테마 강조색)
MONEY_FIELDS = (("deposit_manwon", "보증금", ":material/account_balance_wallet:"),
                ("monthly_rent_manwon", "월세", ":material/payments:"),
                ("maintenance_fee_manwon", "관리비", ":material/receipt_long:"))
COST_ICON = ":material/calendar_month:"
INFO_FIELDS = (("transit", ":material/directions_subway:"), ("floor", ":material/stairs:"),
               ("direction", ":material/explore:"))
# 확인 상태 칩 한 줄: 확인됨 → 모호함 → 미확인 → 미기재 (logic.STATUS_GROUPS의 key, 아이콘, 색)
STATUS_LINE = (("confirmed_checks", ":material/check_circle:", "green"),
               ("ambiguous_checks", ":material/help:", "orange"),
               ("unchecked", ":material/search:", "blue"),
               ("missing_checks", ":material/error:", "gray"))
QUESTIONS_SHOWN = 4
_CACHE = "_analysis_latest"
SPARKLE_ICON = (  # 빈 상태 카드 아이콘(강조색)
    '<svg width="44" height="44" viewBox="0 0 24 24" fill="#3246d3" aria-hidden="true">'
    '<path d="M10 2.5l1.6 4.9L16.5 9l-4.9 1.6L10 15.5l-1.6-4.9L3.5 9l4.9-1.6z"/>'
    '<path d="M18 13l.9 2.6 2.6.9-2.6.9L18 20l-.9-2.6-2.6-.9 2.6-.9z" opacity=".75"/>'
    '<path d="M18.5 2l.6 1.9 1.9.6-1.9.6-.6 1.9-.6-1.9-1.9-.6 1.9-.6z" opacity=".6"/></svg>'
)
# 장점·단점 상자. 선택자는 st.container(key=…)가 붙이는 공식 CSS 클래스 st-key-<key>(내부 클래스명 아님).
# 공통 카드 규칙(frontend/core/theme.css)보다 앞서도록 !important를 붙인다.
BOX_CSS = """<style>
[data-testid="stMain"] [class*="st-key-analysis_pros_"] {
  background: #EEF8F1 !important; border: 1px solid #D3EEDC !important; box-shadow: none !important;
  padding: 0.875rem 1.125rem !important;
}
[data-testid="stMain"] [class*="st-key-analysis_cons_"] {
  background: #FDF0F0 !important; border: 1px solid #F6D6D7 !important; box-shadow: none !important;
  padding: 0.875rem 1.125rem !important;
}
[data-testid="stMain"] [class*="st-key-analysis_empty_"] { text-align: center; padding: 2.5rem 1.5rem !important; }
</style>"""


def _icon(name: str) -> str:
    return f":blue[{name}]"


def _mark(a: dict, name: str) -> str:
    return " ✎" if logic.field_edited(a, name) else ""


def _latest(ctx: dict) -> tuple[dict | None, ApiError | None]:
    """최신 분석을 이 화면 실행 동안 한 번만 부른다(ctx에 담아 actions·notice·overview·summary가 같이 쓴다)."""
    if _CACHE not in ctx:
        ctx[_CACHE] = _load_latest(ctx["listing"]["id"])
    return ctx[_CACHE]


# ------------------------------------------------------------------ actions: 제목 오른쪽 버튼
RERUN_DONE_HELP = "메모를 고치면 다시 정리할 수 있어요"


def render_actions(ctx: dict) -> None:
    """분석 완료일 때만. 분석 전·실패면 빈 상태 카드 안의 큰 버튼 하나만 둔다(같은 key, 같은 동작)."""
    listing = ctx["listing"]
    lid = listing["id"]
    analysis, load_error = _latest(ctx)
    if load_error is not None or analysis is None or analysis.get("status") != "success":
        return
    state = logic.button_state(listing, analysis)
    if state["needs_reanalysis"]:
        clicked = st.button("✨ 다시 분석", key=f"analysis_run_{lid}", type="primary", disabled=state["disabled"],
                            width="stretch")
    else:
        clicked = st.button("✨ 다시 정리", key=f"analysis_run_{lid}", disabled=True, help=RERUN_DONE_HELP,
                            width="stretch")
    if clicked:
        _run_analysis(lid)


# ------------------------------------------------------------------ notice: 안내·빈 상태 카드
def _empty_card(listing: dict, analysis: dict | None) -> None:
    lid = listing["id"]
    memo = (listing.get("memo_text") or "").strip()
    if analysis is not None and analysis.get("status") == "failed":
        title = "정리하지 못했어요"
        desc = " ".join(logic.failure_text(analysis.get("error_code")))
    elif not memo:
        title, desc = "아직 정리 전이에요", "메모가 비어 있어요. 아래 '메모 고치기' 탭에서 메모를 적고 저장한 뒤 정리하세요."
    else:
        title, desc = "아직 정리 전이에요", "메모를 AI가 금액·확인 항목·물어볼 것으로 정리해 드려요."
    with st.container(border=True, key=f"analysis_empty_{lid}"):
        st.markdown(
            f'<div style="display:flex;flex-direction:column;align-items:center;gap:.5rem;margin-bottom:1rem">'
            f'{SPARKLE_ICON}<div style="font-size:1.25rem;font-weight:800;color:#110d3c">{html.escape(title)}</div>'
            f'<div style="color:#64636d">{html.escape(desc)}</div></div>',
            unsafe_allow_html=True,
        )
        if st.button("✨ AI로 정리하기", key=f"analysis_run_{lid}", type="primary", width="stretch",
                     disabled=logic.button_state(listing, analysis)["disabled"]):
            _run_analysis(lid)


def render_notice(ctx: dict) -> None:
    listing = ctx["listing"]
    lid = listing["id"]
    st.html(BOX_CSS)
    _show_flash(lid)
    analysis, load_error = _latest(ctx)
    if load_error is not None:
        show_api_error(load_error)
        return
    if analysis is None or analysis.get("status") == "failed":
        _empty_card(listing, analysis)
        return
    if logic.button_state(listing, analysis)["needs_reanalysis"]:
        st.warning("메모가 바뀌었습니다. 아래 결과는 이전 메모 기준이에요. 오른쪽 위 ‘다시 분석’을 누르세요.")
    if analysis.get("mixed_listings"):
        st.warning(logic.MIXED_LISTINGS_MESSAGE)


# ------------------------------------------------------------------ overview: 숫자 카드 + 한 줄 정보
def _success(ctx: dict) -> dict | None:
    analysis, _ = _latest(ctx)
    return analysis if analysis is not None and analysis.get("status") == "success" else None


def render_overview(ctx: dict) -> None:
    a = _success(ctx)
    if a is None:
        return
    cols = st.columns(4)
    for col, (name, title, icon) in zip(cols, MONEY_FIELDS):
        col.metric(f"{_icon(icon)} {title}{_mark(a, name)}", fmt_manwon(logic.field_value(a, name)))
    row_values = (ctx.get("comparison_row") or {}).get("values") or {}
    cost = fmt_manwon(row_values.get("monthly_cost_manwon")) if ctx.get("comparison_row") else "—"
    cols[3].metric(f"{_icon(COST_ICON)} 월 고정비", cost, help="월세 + 관리비(비교표와 같은 값)")
    parts = [f"{_icon(icon)} {logic.text_or_missing(logic.field_value(a, name))}{_mark(a, name)}"
             for name, icon in INFO_FIELDS]
    includes = logic.field_value(a, "maintenance_includes") or []
    parts.append(":gray[관리비 포함: " + (", ".join(includes) if includes else "미기재") + "]")
    st.markdown(" &nbsp;·&nbsp; ".join(parts))


# ------------------------------------------------------------------ summary: '요약' 탭
def _box(kind: str, lid: str, title: str, icon: str, items: list, empty: str) -> None:
    with st.container(border=True, key=f"analysis_{kind}_{lid}"):
        st.markdown(f"{icon} **{title}**")
        if items:
            st.markdown("\n".join(f"- {x}" for x in items))
        else:
            st.caption(empty)


def _status_line(a: dict) -> None:
    st.markdown("**확인 상태**")
    groups = {g["key"]: g for g in logic.status_groups(a)}
    parts = []
    for key, icon, color in STATUS_LINE:
        g = groups.get(key)
        if not g:
            continue
        chips = " ".join(f":{color}-badge[{it['item']}]" for it in g["items"]) or ":gray[없음]"
        parts.append(f":{color}[{icon} {g['title']}] {chips}")
    st.markdown(" &nbsp;&nbsp; ".join(parts))
    evidence = [(it["item"], it["evidence"]) for g in groups.values() for it in g["items"]
                if g["show_evidence"] and it["evidence"]]
    if evidence:
        with st.expander(":material/format_quote: 근거 문장 보기"):
            st.markdown("\n".join(f"- **{item}** :gray[“{ev}”]" for item, ev in evidence))


def _questions(a: dict, lid: str) -> None:
    questions = logic.inquiry_questions(a)
    with st.container(border=True):
        st.markdown(f"{_icon(':material/forum:')} **다음 방문 때 물어볼 것** :gray[{len(questions)}개]")
        if not questions:
            st.caption("체크리스트 항목을 모두 확인했어요.")
        else:
            # 체크는 화면 표시용(저장하지 않음)
            for item, q in questions[:QUESTIONS_SHOWN]:
                st.checkbox(f"**{item}** · {q}", key=f"analysis_ask:{lid}:{item}")
            rest = questions[QUESTIONS_SHOWN:]
            if rest:
                with st.expander(f"+{len(rest)}개 더 보기"):
                    for item, q in rest:
                        st.checkbox(f"**{item}** · {q}", key=f"analysis_ask:{lid}:{item}")
        st.caption(f"분석 {fmt_kst(a.get('created_at'))} · 프롬프트 {a.get('prompt_version')} · "
                   "✎ 표시는 직접 고친 값입니다. 체크는 저장되지 않습니다.")


def render_summary(ctx: dict) -> None:
    a = _success(ctx)
    if a is None:
        return
    lid = ctx["listing"]["id"]
    with st.container(border=True):
        left, right = st.columns(2)
        with left:
            _box("pros", lid, "장점", ":green[:material/thumb_up:]", logic.field_value(a, "pros") or [],
                 "메모에 적힌 장점이 없어요")
        with right:
            _box("cons", lid, "단점", ":red[:material/thumb_down:]", logic.field_value(a, "cons") or [],
                 "메모에 적힌 단점이 없어요")
        if a.get("ambiguous"):
            st.markdown(f"{_icon(':material/format_quote:')} **애매한 구절** :gray[(값을 정하지 않았어요. 직접 확인하세요)]")
            st.markdown("\n".join(f"- “{x}”" for x in a["ambiguous"]))
        _status_line(a)
    _questions(a, lid)


SECTIONS = [
    {"slot": "listing_detail", "order": 20, "area": "actions", "render": render_actions},
    {"slot": "listing_detail", "order": 21, "area": "notice", "render": render_notice},
    {"slot": "listing_detail", "order": 22, "area": "overview", "render": render_overview},
    {"slot": "listing_detail", "order": 23, "area": "summary", "render": render_summary},
]
