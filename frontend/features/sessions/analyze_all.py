"""세션 화면의 [AI로 정리하기] 버튼: 아직 정리되지 않은 매물만 한 번에 분석한다.

버튼은 매물 목록 오른쪽 열 맨 위의 '✨ 정리 안 된 매물 N곳' 배너(render_banner) 안에 있다.
정리할 매물이 없으면 배너 대신 한 줄 안내만 보여 준다. 버튼의 key·라벨·동작은 render_button 그대로.

대상 = 메모가 있고 (분석 전 · 최신 분석 실패 · 메모가 바뀌어 재분석 필요)인 매물.
요청은 매물 화면과 같은 POST /listings/{id}/analyses(use_cache=True)를 매물마다 차례로 보낸다.
결과는 flash로 남기고 화면 전체를 다시 그려 아래 비교표·적합도 순위에 바로 반영한다.
"""

from __future__ import annotations

import streamlit as st

from core.api import ApiError, api_post
from features.sessions.common import flash

BUTTON_LABEL = "AI로 정리하기"
BUTTON_HELP = "아직 정리하지 않은 매물(분석 전·실패·메모가 바뀐 매물)만 한 번에 정리합니다."
DONE_HELP = "모든 매물이 정리되어 있습니다. 메모를 고치거나 매물을 추가하면 다시 누를 수 있어요."
CARD_HINT = "금액 정리 전"   # 분석 전·실패 매물 카드 오른쪽 회색 한 줄
BANNER_KEY = "p1_ai_banner"
BANNER_NOTE = "분석 전·실패·메모가 바뀐 매물만 한 번에 정리합니다."
# 배너만의 모양: 연파랑 바탕 + 왼쪽 강조색 세로 줄. 버튼은 기본 primary(강조색 바탕·흰 글자).
# 선택자는 st.container(key=…)가 붙이는 공식 CSS 클래스 st-key-<key>를 쓴다(내부 클래스명 아님).
# 공통 카드 규칙(frontend/core/theme.css)보다 앞서도록 !important를 붙인다.
BANNER_CSS = """<style>
[data-testid="stMain"] .st-key-p1_ai_banner {
  background: #EEF2FB !important;
  border: 1px solid #E3E8F2 !important;
  border-left: 4px solid #3246D3 !important;
  box-shadow: none !important;
}
[data-testid="stMain"] .st-key-p1_ai_banner [data-testid="stMarkdownContainer"] strong {
  color: #110D3C; font-size: 1.1rem; font-weight: 800;
}
</style>"""


def banner_title(count: int) -> str:
    return f"✨ 정리 안 된 매물 {count}곳"


def needs_analysis(listing: dict) -> bool:
    if not (listing.get("memo_text") or "").strip():
        return False
    if listing.get("needs_reanalysis"):
        return True
    return (listing.get("latest_analysis_status") or "none") in ("none", "failed")


def analysis_targets(listings: list[dict]) -> list[dict]:
    return [x for x in listings if needs_analysis(x)]


def result_message(ok: int, failed: int) -> tuple[str, str]:
    """(flash 종류, 문구)."""
    if failed == 0:
        return "success", f"{ok}곳을 정리했습니다. 아래 매물 비교표에 바로 반영됐어요."
    if ok == 0:
        return "warning", f"{failed}곳 모두 정리하지 못했습니다. 잠시 후 [AI로 정리하기]를 다시 눌러 주세요."
    return "warning", f"{ok}곳은 정리했고 {failed}곳은 실패했습니다. [AI로 정리하기]를 다시 누르면 실패한 매물만 다시 정리해요."


def run_all(targets: list[dict]) -> tuple[int, int]:
    ok = failed = 0
    total = len(targets)
    with st.status(f"AI가 매물을 정리하는 중… (0/{total})", expanded=False) as box:
        for i, lst in enumerate(targets, start=1):
            box.update(label=f"AI가 매물을 정리하는 중… ({i}/{total}) {lst.get('label', '')}")
            try:
                api_post(f"/listings/{lst['id']}/analyses", json={"use_cache": True})
                ok += 1
            except ApiError:
                failed += 1
        box.update(label="정리를 마쳤습니다.", state="complete" if failed == 0 else "error")
    return ok, failed


def render_button(listings: list[dict], session_id: str) -> None:
    targets = analysis_targets(listings)
    clicked = st.button(BUTTON_LABEL, key=f"p1_analyze_all:{session_id}", type="primary",
                        disabled=not targets, help=BUTTON_HELP if targets else DONE_HELP, width="stretch")
    if clicked and targets:
        ok, failed = run_all(targets)
        kind, message = result_message(ok, failed)
        flash("session_detail", message, kind)
        st.rerun()


def render_banner(listings: list[dict], session_id: str) -> None:
    """정리할 매물이 있으면 배너 + [AI로 정리하기], 없으면 한 줄 안내."""
    targets = analysis_targets(listings)
    if not targets:
        st.caption(f"✓ {DONE_HELP}")
        return
    st.html(BANNER_CSS)
    with st.container(border=True, key=BANNER_KEY):
        st.markdown(f"**{banner_title(len(targets))}**")
        st.caption(BANNER_NOTE)
        render_button(listings, session_id)
