"""P1 화면 공통: 한 번만 보이는 안내(flash), 분석 상태 문구, 방문일 표시."""

from __future__ import annotations

import datetime as dt

import streamlit as st

from core.ui import notify

_FLASH_PREFIX = "p1_flash:"

# latest_analysis_status → (표시, 다음에 할 일)
ANALYSIS_STATUS: dict[str, tuple[str, str]] = {
    "none": (":gray[분석 전]", "매물 화면에서 분석을 실행하세요."),
    "success": (":green[분석 완료]", ""),
    "failed": (":red[분석 실패]", "매물 화면에서 다시 시도하세요."),
}
REANALYSIS_BADGE = ":orange[**재분석 필요**]"


def flash(where: str, message: str, kind: str = "success") -> None:
    """다음 실행(같은 화면 또는 이동한 화면)에서 한 번 보여 줄 안내를 남긴다."""
    st.session_state[_FLASH_PREFIX + where] = (kind, message)


def show_flash(where: str) -> None:
    item = st.session_state.pop(_FLASH_PREFIX + where, None)
    if not item:
        return
    kind, message = item
    {"success": st.success, "info": st.info, "warning": st.warning}.get(kind, st.info)(message)
    if kind == "success":
        notify(message)


def status_text(listing: dict) -> str:
    label, _ = ANALYSIS_STATUS.get(listing.get("latest_analysis_status") or "none", ANALYSIS_STATUS["none"])
    if listing.get("needs_reanalysis"):
        label += " · " + REANALYSIS_BADGE
    return label


def status_next_step(listing: dict) -> str:
    if listing.get("needs_reanalysis"):
        return "메모가 분석 뒤에 바뀌었습니다. 분석을 다시 실행하세요."
    return ANALYSIS_STATUS.get(listing.get("latest_analysis_status") or "none", ANALYSIS_STATUS["none"])[1]


def parse_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def visit_text(value: str | None) -> str:
    d = parse_date(value)
    return f"방문일 {d.isoformat()}" if d else "방문일 미정"
