"""R 상세 페이지: 세션 상세 위에 '← 세션' 버튼이 있고 누르면 세션 목록으로 간다(AppTest, 서버는 가짜)."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"

HEADER = f"""
import sys
sys.path.insert(0, {str(FRONTEND_DIR)!r})
import _host_fake as fake
import streamlit as st
from core import host_pages, nav

host_pages.api_get = lambda path, **kw: fake.responses[path]
host_pages.render_slot = lambda *a, **kw: None
host_pages.sections_for = lambda slot: [1]
nav.go_sessions = lambda: fake.calls.append("sessions")
nav.go_session_detail = lambda sid: fake.calls.append(("session_detail", sid))
st.session_state.setdefault("selected_session_id", "s1")
st.session_state.setdefault("selected_listing_id", "l1")
"""
SESSION = {"id": "s1", "title": "토요일 집 보기", "visit_date": None, "listing_count": 1,
           "created_at": "2026-10-17T01:00:00+00:00"}
LISTING = {"id": "l1", "session_id": "s1", "listing_no": 1, "label": None,
           "memo_updated_at": "2026-10-17T01:00:00+00:00"}


@pytest.fixture
def fake():
    mod = types.ModuleType("_host_fake")
    mod.calls = []
    mod.responses = {"/sessions/s1": SESSION, "/listings/l1": LISTING}
    sys.modules["_host_fake"] = mod
    yield mod
    sys.modules.pop("_host_fake", None)


def _app(body: str):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_string(HEADER + body, default_timeout=10)
    at.run()
    assert not at.exception, at.exception
    return at


def test_session_detail_has_back_to_sessions(fake):
    at = _app("host_pages.render_session_detail()")
    assert at.title[0].value == "토요일 집 보기"
    next(b for b in at.button if b.label == "← 세션").click().run()
    assert fake.calls == ["sessions"]


def test_listing_detail_has_back_to_session(fake):
    at = _app("host_pages.render_listing_detail()")
    next(b for b in at.button if b.label == "← 토요일 집 보기").click().run()
    assert fake.calls == [("session_detail", "s1")]


def test_detail_pages_hidden_from_sidebar():
    src = (FRONTEND_DIR / "app.py").read_text(encoding="utf-8")
    assert src.count('"hidden": True') == 2 and 'visibility="hidden" if p.get("hidden")' in src
