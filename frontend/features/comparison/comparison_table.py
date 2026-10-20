"""슬롯 session_detail(order 30): 매물 비교표."""

from __future__ import annotations

import streamlit as st

from core import nav, state
from core.api import ApiError, api_get
from core.ui import icon_title, show_api_error
from features.comparison.cells import (
    BUDGET_FILTER, COST_NOTE, comparison_markdown, hidden_message, needs_action,
)

TITLE_HELP = "관리비가 비싸도 **포함 내역**이 많으면 더 쌀 수 있어요.  \n'미기재'는 집주인에게 꼭 물어보세요."


def _action_hint(rows: list[dict]) -> None:
    todo = [r for r in rows if needs_action(r)]
    if not todo:
        return
    st.caption("분석 전·분석 실패·재분석 필요 매물은 매물 화면에서 분석을 실행하세요.")
    cols = st.columns(min(len(todo), 4))
    for i, r in enumerate(todo):
        with cols[i % len(cols)]:
            if st.button(f"{r['label']} 상세 보기 →", key=f"cmp_open:{r['listing_id']}", type="tertiary",
                         width="stretch"):
                nav.go_listing_detail(r["listing_id"])


def render_comparison(ctx: dict) -> None:
    session = ctx["session"]
    sid = session["id"]
    icon_title("table_chart", "매물 비교표", help=TITLE_HELP)

    filter_on = bool(st.session_state.get(state.budget_filter_key(sid)))
    params = {"filters": BUDGET_FILTER} if filter_on else None
    # 필터가 꺼져 있으면 위 매물 목록(F2, order 10)이 이번 화면에서 이미 받은 응답을 그대로 쓴다(같은 API 두 번 방지)
    data = None if filter_on else ctx.get("comparison")
    try:
        if data is None:
            with st.spinner("비교표를 불러오는 중…"):
                data = api_get(f"/sessions/{sid}/comparison", params=params)
    except ApiError as e:
        show_api_error(e)
        if st.button("다시 시도", key=f"cmp_retry:{sid}"):
            st.rerun()
        return

    if not data.get("enough_listings"):
        st.info(data.get("message") or "매물을 하나 더 추가하세요")
        return

    hidden = hidden_message(data) if filter_on else None
    if hidden:
        st.caption(f"예산 필터 적용 중 · {hidden}")

    rows = data.get("rows") or []
    if not rows:
        st.info("예산 안에 드는 매물이 없습니다. 예산 필터를 끄면 모든 매물을 볼 수 있습니다.")
        return

    st.markdown(comparison_markdown(data))
    st.caption("파란 글씨는 값이 적힌 매물 중 최저값입니다. 미기재 = 메모에 없음(0원 아님), — = 아직 분석 결과 없음.")
    st.caption(COST_NOTE)
    _action_hint(rows)
