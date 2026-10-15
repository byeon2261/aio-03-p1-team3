"""F9 개선 전후 비교 페이지(운영자 전용). import할 때 st 함수를 부르지 않는다."""

from __future__ import annotations

import streamlit as st

from core import state
from features.evals import components


def render_eval_compare() -> None:
    st.title("개선 전후 비교")
    st.caption("같은 기준 세트·모델·설정으로 프롬프트 버전만 바꿔 돌리고, 지표와 사례별 결과를 나란히 봅니다. "
               "실패 유형을 고르고 v2를 쓰는 일은 사람이 합니다.")
    if not state.is_admin():
        st.error("운영자만 볼 수 있습니다. 다른 메뉴를 이용하세요.")
        return

    runs = components.load_runs()
    if runs is None:
        return
    components.run_section(runs)
    st.divider()
    components.runs_table(runs)
    st.divider()
    components.compare_section(runs)


PAGES = [
    {"key": "evals", "title": "개선 전후 비교", "order": 95, "admin_only": True, "render": render_eval_compare},
]
