"""매물 상세 [⋯] 팝오버 안의 [매물 삭제] → 같은 팝오버 안 확인 → [삭제]/[취소]. key·삭제 흐름은 예전과 같다. 서버는 가짜."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"
LID, SID = "l-1", "s-1"

SCRIPT = f"""
import sys
sys.path.insert(0, {str(FRONTEND_DIR)!r})
import _p1_menu_fake as fake
import streamlit as st
from core import nav
from features.sessions import sections

sections.api_delete = lambda path, **kw: fake.calls.append(("DELETE", path))
sections.nav.go_session_detail = lambda sid: fake.calls.append(("go", sid))
ctx = {{"listing": {{"id": "{LID}", "label": "1번 집"}}, "session": {{"id": "{SID}", "title": "토요일"}}}}
for sec in sections.SECTIONS:
    if sec["slot"] == "listing_detail" and sec.get("area") == "menu":
        with st.popover("more"):
            sec["render"](ctx)
"""


@pytest.fixture
def fake():
    mod = types.ModuleType("_p1_menu_fake")
    mod.calls = []
    sys.modules["_p1_menu_fake"] = mod
    yield mod
    sys.modules.pop("_p1_menu_fake", None)


def _app():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_string(SCRIPT, default_timeout=10)
    at.run()
    assert not at.exception, at.exception
    return at


def test_listing_sections_areas():
    from features.sessions import sections

    areas = {s.get("area") for s in sections.SECTIONS if s["slot"] == "listing_detail"}
    assert areas == {"menu", "notice", "memo"}


def test_delete_confirm_inside_popover_then_delete(fake):
    at = _app()
    assert [b.key for b in at.button] == [f"p1_delete_listing:{LID}"]
    at.button(key=f"p1_delete_listing:{LID}").click().run()
    assert not at.warning                                         # 노란 상자 없이 팝오버 안에서 확인
    assert any("삭제할까요" in str(m.value) for m in at.markdown)
    assert any("되돌릴 수 없습니다" in c.value for c in at.caption)
    keys = {b.key: b for b in at.button}
    assert {f"p1_delete_listing_ok:{LID}", f"p1_delete_listing_cancel:{LID}"} <= set(keys)
    assert keys[f"p1_delete_listing_ok:{LID}"].proto.type != "primary"   # 테두리 버튼(빨간 글씨는 CSS)
    at.button(key=f"p1_delete_listing_ok:{LID}").click().run()
    assert fake.calls == [("DELETE", f"/listings/{LID}"), ("go", SID)]


def test_delete_cancel_returns_to_menu(fake):
    at = _app()
    at.button(key=f"p1_delete_listing:{LID}").click().run()
    at.button(key=f"p1_delete_listing_cancel:{LID}").click().run()
    assert [b.key for b in at.button] == [f"p1_delete_listing:{LID}"] and fake.calls == []
