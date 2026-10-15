"""F4·F5 매물 상세 화면의 'AI 정리' 섹션 (슬롯 listing_detail, order 20).

분석 버튼 · 로딩 · 결과 카드(금액·교통·층·방향·장단점·애매한 구절) · 확인 상태 4묶음 · 문의 질문.
import 시 st 함수를 부르지 않는다.
"""

from __future__ import annotations

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


def _money_row(a: dict) -> None:
    cols = st.columns(3)
    for col, (name, title) in zip(cols, (("deposit_manwon", "보증금"), ("monthly_rent_manwon", "월세"),
                                         ("maintenance_fee_manwon", "관리비"))):
        mark = " ✎" if logic.field_edited(a, name) else ""
        col.metric(title + mark, fmt_manwon(logic.field_value(a, name)))
    includes = logic.field_value(a, "maintenance_includes") or []
    st.caption("관리비 포함: " + (", ".join(includes) if includes else "미기재"))


def _info_row(a: dict) -> None:
    cols = st.columns(3)
    for col, (name, title) in zip(cols, (("transit", "교통"), ("floor", "층"), ("direction", "방향"))):
        mark = " ✎" if logic.field_edited(a, name) else ""
        col.markdown(f"**{title}{mark}**  \n{logic.text_or_missing(logic.field_value(a, name))}")


def _pros_cons(a: dict) -> None:
    left, right = st.columns(2)
    with left:
        st.markdown("**장점**")
        pros = logic.field_value(a, "pros") or []
        if pros:
            st.markdown("\n".join(f"- {p}" for p in pros))
        else:
            st.caption("메모에 적힌 장점이 없습니다.")
    with right:
        st.markdown("**단점**")
        cons = logic.field_value(a, "cons") or []
        if cons:
            st.markdown("\n".join(f"- {c}" for c in cons))
        else:
            st.caption("메모에 적힌 단점이 없습니다.")
    if a.get("ambiguous"):
        st.markdown("**애매한 구절** (값을 정하지 않았어요. 직접 확인하세요)")
        st.markdown("\n".join(f"- “{x}”" for x in a["ambiguous"]))


def _check_status(a: dict) -> None:
    st.markdown("**확인 상태**")
    groups = logic.status_groups(a)
    cols = st.columns(len(groups))
    for col, g in zip(cols, groups):
        with col:
            st.markdown(f"**{g['title']}** · {len(g['items'])}")
            if not g["items"]:
                st.caption("없음")
                continue
            for it in g["items"]:
                st.markdown(f"- {it['item']}")
                if g["show_evidence"] and it["evidence"]:
                    st.caption(f"“{it['evidence']}”")

    questions = logic.inquiry_questions(a)
    if questions:
        st.markdown("**물어볼 것** (미확인·모호함·미기재 항목)")
        st.markdown("\n".join(f"- **{item}**: {q}" for item, q in questions))
    else:
        st.caption("체크리스트 항목을 모두 확인했어요.")


def _result_card(a: dict) -> None:
    with st.container(border=True):
        if a.get("mixed_listings"):
            st.warning(logic.MIXED_LISTINGS_MESSAGE)
        label = logic.field_value(a, "label")
        if label:
            st.markdown(f"#### {label}")
        _money_row(a)
        _info_row(a)
        _pros_cons(a)
        st.divider()
        _check_status(a)
        st.caption(f"분석 {fmt_kst(a.get('created_at'))} · 프롬프트 {a.get('prompt_version')} · "
                   "✎ 표시는 직접 고친 값입니다.")


def render_analysis_section(ctx: dict) -> None:
    listing = ctx["listing"]
    lid = listing["id"]
    st.subheader("AI 정리")
    _show_flash(lid)

    analysis, load_error = _load_latest(lid)
    if load_error is not None:
        show_api_error(load_error)

    state = logic.button_state(listing, analysis)

    if analysis is None and load_error is None:
        if state["memo_empty"]:
            st.info("메모가 비어 있습니다. 위에서 메모를 입력하고 저장한 뒤 정리하세요.")
        else:
            st.info("아직 정리하지 않았습니다. ‘AI로 정리하기’를 누르면 금액·확인 항목을 표로 정리해 드려요.")
    elif analysis is not None and analysis.get("status") == "failed":
        msg, next_step = logic.failure_text(analysis.get("error_code"))
        st.error(f"{msg} {next_step}")
    elif state["needs_reanalysis"]:
        st.warning("메모가 바뀌었습니다. 아래 결과는 이전 메모 기준이에요. ‘다시 분석’을 누르세요.")

    if state["show"]:
        if st.button(state["label"], key=f"analysis_run_{lid}", type="primary", disabled=state["disabled"]):
            _run_analysis(lid)

    if analysis is not None and analysis.get("status") == "success":
        _result_card(analysis)


SECTIONS = [{"slot": "listing_detail", "order": 20, "render": render_analysis_section}]
