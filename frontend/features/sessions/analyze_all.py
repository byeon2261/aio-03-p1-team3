"""세션 화면의 [AI 정리] 버튼: 아직 정리되지 않은 매물만 한 번에 분석한다.

대상 = 메모가 있고 (분석 전 · 최신 분석 실패 · 메모가 바뀌어 재분석 필요)인 매물.
요청은 매물 화면과 같은 POST /listings/{id}/analyses(use_cache=True)를 매물마다 차례로 보낸다.
결과는 flash로 남기고 화면 전체를 다시 그려 아래 비교표·적합도 순위에 바로 반영한다.
"""

from __future__ import annotations

import streamlit as st

from core.api import ApiError, api_post
from features.sessions.common import flash

BUTTON_LABEL = "AI 정리"
BUTTON_HELP = "아직 정리하지 않은 매물(분석 전·실패·메모가 바뀐 매물)만 한 번에 정리합니다."
DONE_HELP = "모든 매물이 정리되어 있습니다. 메모를 고치거나 매물을 추가하면 다시 누를 수 있어요."
CARD_HINT = "위의 [AI 정리]를 누르면 정리됩니다."


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
        return "warning", f"{failed}곳 모두 정리하지 못했습니다. 잠시 후 [AI 정리]를 다시 눌러 주세요."
    return "warning", f"{ok}곳은 정리했고 {failed}곳은 실패했습니다. [AI 정리]를 다시 누르면 실패한 매물만 다시 정리해요."


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
