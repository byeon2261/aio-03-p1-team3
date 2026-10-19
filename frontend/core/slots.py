"""상세 화면의 슬롯. 각 기능의 sections.py SECTIONS를 order 순으로 그린다.

슬롯
    session_detail  ctx = {"session": SessionOut dict}
                    P1 매물 목록·새 메모 10 · P5 예산 20 · F12 가중치 25 · P3 비교표 30 · F12 순위 35 · P1 세션 관리 90
    listing_detail  ctx = {"listing": ListingOut dict, "session": SessionOut dict, "comparison_row": dict | None}
                    섹션의 "area"로 자리를 정한다(없으면 "main" = 탭 아래):
                    actions 제목 오른쪽 버튼 · menu [⋯] 팝오버 · notice 제목 아래 안내 · overview 숫자 카드
                    탭: summary 요약 · memo 메모 · review 수정·평가 · media 사진·위치 · score 내 점수
                    P1 메모 편집 10 · P2 분석 결과 20 · P3 수정·피드백 30 · P4 사진 40
한 섹션이 예외를 내도 나머지 섹션은 그린다(st.rerun·st.switch_page·st.stop은 그대로 통과).
"""

from __future__ import annotations

import logging

import streamlit as st

try:
    from streamlit.runtime.scriptrunner_utils.exceptions import ScriptControlException
except Exception:  # 버전 차이 대비
    ScriptControlException = None  # type: ignore[assignment]

logger = logging.getLogger("frontend.slots")
_sections: list[dict] = []


def register_sections(sections: list[dict]) -> None:
    _sections[:] = list(sections)


DEFAULT_AREA = "main"


def sections_for(slot: str, area: str | None = None) -> list[dict]:
    """slot의 섹션(order 순). area를 주면 그 자리("area" 키, 없으면 "main")의 섹션만."""
    return sorted((s for s in _sections if s["slot"] == slot
                   and (area is None or s.get("area", DEFAULT_AREA) == area)), key=lambda s: s["order"])


def _is_control_flow(exc: BaseException) -> bool:
    if ScriptControlException is not None and isinstance(exc, ScriptControlException):
        return True
    return type(exc).__name__ in ("RerunException", "StopException")


def render_slot(slot: str, ctx: dict, area: str | None = None) -> None:
    for sec in sections_for(slot, area):
        try:
            sec["render"](ctx)
        except Exception as exc:
            if _is_control_flow(exc):
                raise
            logger.error("section %s/%s failed: %s", slot, sec.get("feature"), type(exc).__name__)
            st.error("이 영역을 불러오지 못했습니다. 새로 고침하거나 잠시 후 다시 시도하세요.")
