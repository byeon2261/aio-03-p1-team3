"""P3 화면 섹션. import 시 Streamlit 함수를 부르지 않는다(함수 정의만).

    session_detail 30  매물 비교표
    listing_detail 30  AI 결과 수정·피드백
"""

from __future__ import annotations

from features.comparison.comparison_table import render_comparison
from features.comparison.feedback_form import render_feedback

SECTIONS = [
    {"slot": "session_detail", "order": 30, "render": render_comparison},
    {"slot": "listing_detail", "order": 30, "area": "review", "render": render_feedback},   # '수정·평가' 탭
]
