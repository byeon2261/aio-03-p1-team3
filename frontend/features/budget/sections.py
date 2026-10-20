"""F11 예산 섹션: 세션 상세(session_detail) 슬롯 order 20.

- 보증금 상한·월 고정비 상한(만원) 입력, 저장, 비우기.
- "예산 안만 보기" 토글 → st.session_state[budget_filter_key(sid)]에 쓴다. 비교표(P3, order 30)가 읽는다.
- 상한이 없으면 토글을 끄고 "예산을 먼저 입력하세요"를 보여 준다.
- 토글이 켜져 있으면 숨긴 매물을 사유별로 세어 보여 주고(예산 초과 n건 · 판단 불가 n건 숨김),
  그 아래 판단 불가 매물마다 사유·다음 행동·[열기]를 한 줄씩 보여 준다(GET /sessions/{sid}/budget/evaluations).
import 시 st 함수를 부르지 않는다.
"""

from __future__ import annotations

import streamlit as st

from core import nav
from core.api import ApiError, api_get, api_put
from core.state import budget_filter_key
from core.ui import fmt_kst, icon_title, notify, show_api_error
from features.budget.view import (
    budget_body, budget_summary, has_budget, hidden_summary, unknown_items, unknown_line,
)


def _cache_key(sid: str) -> str:
    return f"budget_cache:{sid}"


def _flash_key(sid: str) -> str:
    return f"budget_flash:{sid}"


def _form_ver_key(sid: str) -> str:
    return f"budget_form_ver:{sid}"


def _load(sid: str) -> dict | None:
    """세션 예산. 한 번 받으면 저장할 때까지 화면 상태에 둔다. 실패하면 None."""
    key = _cache_key(sid)
    if key not in st.session_state:
        try:
            with st.spinner("예산을 불러오는 중…"):
                st.session_state[key] = api_get(f"/sessions/{sid}/budget")
        except ApiError as e:
            show_api_error(e)
            if st.button("다시 시도", key=f"budget_retry:{sid}"):
                st.rerun()
            return None
    return st.session_state[key]


def _save(sid: str, body: dict, done_message: str) -> None:
    try:
        with st.spinner("저장하는 중…"):
            saved = api_put(f"/sessions/{sid}/budget", json=body)
    except ApiError as e:
        show_api_error(e)
        return
    st.session_state[_cache_key(sid)] = saved
    st.session_state[_flash_key(sid)] = done_message
    st.session_state[_form_ver_key(sid)] = st.session_state.get(_form_ver_key(sid), 0) + 1  # 입력칸 새로 그림
    if not has_budget(saved):
        st.session_state[budget_filter_key(sid)] = False
    st.rerun()


def _render_form(sid: str, budget: dict) -> None:
    ver = st.session_state.get(_form_ver_key(sid), 0)
    with st.form(f"budget_form:{sid}:{ver}", border=False):
        c1, c2 = st.columns(2)
        deposit = c1.number_input("보증금 상한 (만원)", min_value=0, step=100,
                                  value=budget.get("deposit_max_manwon"), placeholder="비우면 제한 없음")
        monthly = c2.number_input("월 고정비 상한 (만원)", min_value=0, step=5,
                                  value=budget.get("monthly_max_manwon"), placeholder="비우면 제한 없음",
                                  help="월세 + 관리비 기준")
        b1, b2 = st.columns(2)
        save = b1.form_submit_button("저장", type="primary", width="stretch")
        clear = b2.form_submit_button("비우기", width="stretch")
    if save:
        _save(sid, budget_body(deposit, monthly), "예산을 저장했습니다.")
    elif clear:
        _save(sid, budget_body(None, None), "예산을 비웠습니다.")


def _render_toggle(sid: str, budget: dict) -> None:
    key = budget_filter_key(sid)
    if not has_budget(budget):
        st.session_state[key] = False
        st.toggle("예산 안만 보기", value=False, disabled=True, key=f"budget_toggle_off:{sid}")
        st.caption("예산을 먼저 입력하세요. 상한을 저장하면 예산 안 매물만 골라 볼 수 있습니다.")
        return
    on = st.toggle("예산 안만 보기", value=bool(st.session_state.get(key, False)), key=f"budget_toggle:{sid}",
                   help="'판단 불가'(금액 미기재) 매물도 숨깁니다.")
    st.session_state[key] = on
    if on:
        st.caption("비교표에 예산 안 매물만 보여 줍니다. 숨긴 매물을 보려면 토글을 끄세요.")
        _render_hidden(sid)


def _render_hidden(sid: str) -> None:
    """숨긴 매물 사유별 개수 + 판단 불가 매물의 다음 행동. 판정은 서버 결과 그대로 보여 준다."""
    try:
        with st.spinner("숨긴 매물을 확인하는 중…"):
            data = api_get(f"/sessions/{sid}/budget/evaluations")
    except ApiError as e:
        show_api_error(e)
        if st.button("다시 시도", key=f"budget_eval_retry:{sid}"):
            st.rerun()
        return
    summary = hidden_summary(data)
    if not summary:
        return
    st.markdown(f"예산 필터 적용 중 · **{summary}**")
    for item in unknown_items(data):
        c1, c2 = st.columns([5, 1], vertical_alignment="center")
        c1.markdown(unknown_line(item))
        if c2.button("열기", key=f"budget_open:{item['listing_id']}", width="stretch"):
            nav.go_listing_detail(item["listing_id"])


def render_budget(ctx: dict) -> None:
    session = ctx.get("session") or {}
    sid = session.get("id")
    if not sid:
        return
    with st.container(border=True):
        icon_title("account_balance_wallet", "예산")
        flash = st.session_state.pop(_flash_key(sid), None)
        if flash:
            st.success(flash)
            notify(flash)
        budget = _load(sid)
        if budget is None:
            st.session_state[budget_filter_key(sid)] = False
            return
        if has_budget(budget):
            st.caption(f"{budget_summary(budget)} · 마지막 저장 {fmt_kst(budget.get('updated_at'))}")
        _render_form(sid, budget)
        _render_toggle(sid, budget)


SECTIONS = [{"slot": "session_detail", "order": 20, "render": render_budget}]
