"""docs/SCREEN_DESIGN.md가 화면 코드와 맞는지 확인한다.

1) 1절 화면 목록: 사이드바에 보이는 페이지마다 "order 제목"(예: 10 세션)이, 숨김 페이지는 제목이나 key가 나온다
2) 1절 '상세 화면을 이루는 섹션(슬롯)' 표: S2·S3의 order 집합 = 각 기능 sections.py의 SECTIONS order 집합
3) 5.4절 오류 문구 표의 코드 = core/ui.py ERROR_MESSAGES의 키

화면(페이지·섹션)을 더하거나 순서를 바꾸는 PR은 이 문서도 함께 고쳐야 통과한다.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FRONTEND = ROOT / "frontend"
DOC = ROOT / "docs" / "SCREEN_DESIGN.md"
DOC_NAME = "docs/SCREEN_DESIGN.md"
SLOT_ROW = re.compile(r"^\|\s*(S[23][^|]*)?\|\s*(\d+)(?:~(\d+))?\s*\|", re.MULTILINE)


def _frontend():
    if str(FRONTEND) not in sys.path:
        sys.path.append(str(FRONTEND))
    from core.loader import load_pages, load_sections

    return load_pages(), load_sections()


def _section1() -> str:
    text = DOC.read_text(encoding="utf-8")
    assert "## 1. 화면 목록" in text and "## 2. " in text, f"{DOC_NAME}에서 1절·2절 제목을 찾지 못했습니다."
    return text.split("## 1. 화면 목록", 1)[1].split("\n## 2. ", 1)[0]


def test_screen_list_has_every_page():
    pages, _ = _frontend()
    sec = _section1()
    missing = []
    for p in pages:
        if p.get("hidden"):
            if p["title"] not in sec and f"`{p['key']}`" not in sec:
                missing.append(f"{p['key']}(숨김, 제목 '{p['title']}')")
        elif f"{p['order']} {p['title']}" not in sec:
            missing.append(f"{p['key']}('{p['order']} {p['title']}')")
    assert not missing, f"{DOC_NAME} 1절 화면 목록에 없는 페이지: {missing}"


def test_slot_table_orders_match_sections():
    _, sections = _frontend()
    table = _section1().split("### 상세 화면을 이루는 섹션(슬롯)", 1)
    assert len(table) == 2, f"{DOC_NAME} 1절에서 '상세 화면을 이루는 섹션(슬롯)' 표를 찾지 못했습니다."
    doc: dict[str, set[int]] = {"session_detail": set(), "listing_detail": set()}
    current = None
    for screen, start, end in SLOT_ROW.findall(table[1]):
        if screen.strip():
            current = "session_detail" if screen.strip().startswith("S2") else "listing_detail"
        if current:
            doc[current].update(range(int(start), int(end or start) + 1))
    for slot, orders in doc.items():
        code = {s["order"] for s in sections if s["slot"] == slot}
        assert orders == code, (f"{DOC_NAME} 1절 섹션 표의 {slot} order {sorted(orders)} ≠ "
                                f"코드 SECTIONS {sorted(code)}. 표의 order·섹션 행을 고치세요.")


def test_error_message_table_matches_ui():
    """5.4절 오류 문구 표의 코드 집합 = 화면 공통 문구 core/ui.py ERROR_MESSAGES의 키."""
    _frontend()
    from core.ui import ERROR_MESSAGES

    text = DOC.read_text(encoding="utf-8")
    assert "### 5.4 " in text and "### 5.5 " in text, f"{DOC_NAME}에서 5.4·5.5절 제목을 찾지 못했습니다."
    section = text.split("### 5.4 ", 1)[1].split("### 5.5 ", 1)[0]
    doc_codes = set(re.findall(r"`([A-Z][A-Z0-9_]{2,})`", section))
    assert doc_codes == set(ERROR_MESSAGES), (
        f"{DOC_NAME} 5.4절 오류 코드와 core/ui.py ERROR_MESSAGES가 다릅니다. "
        f"문서에 없음: {sorted(set(ERROR_MESSAGES) - doc_codes)}, 코드에 없음: {sorted(doc_codes - set(ERROR_MESSAGES))}")
