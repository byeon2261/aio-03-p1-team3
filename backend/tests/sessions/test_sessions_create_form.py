"""P1 세션 목록 '새 집 보기 세션 만들기' 폼: 제목·방문일 + 예산(선택). 서버는 가짜."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"
if str(FRONTEND_DIR) not in sys.path:
    sys.path.append(str(FRONTEND_DIR))

SCRIPT = f"""
import sys
sys.path.insert(0, {str(FRONTEND_DIR)!r})
import _p1_create_fake as fake
from core.api import ApiError
from features.sessions import pages

def _get(path, params=None, **kw):
    return fake.sessions

def _post(path, json=None, **kw):
    fake.calls.append(("POST", path, json))
    return {{"id": "s-new", "title": json["title"]}}

def _put(path, json=None, **kw):
    fake.calls.append(("PUT", path, json))
    if fake.budget_error:
        raise ApiError(503, "DB_UNAVAILABLE", "잠시 후 다시 시도해 주세요.")
    return {{"session_id": "s-new", **json}}

pages.api_get, pages.api_post, pages.api_put = _get, _post, _put
pages.nav.go_session_detail = lambda sid: fake.calls.append(("NAV", sid, None))
pages.render_sessions()
"""


@pytest.fixture
def fake():
    mod = types.ModuleType("_p1_create_fake")
    mod.calls, mod.sessions, mod.budget_error = [], [], False
    sys.modules["_p1_create_fake"] = mod
    yield mod
    sys.modules.pop("_p1_create_fake", None)


def _app():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_string(SCRIPT, default_timeout=10)
    at.run()
    assert not at.exception, at.exception
    return at


def _fill(at, title: str, deposit=None, monthly=None):
    at.text_input[0].set_value(title)
    inputs = {n.label: n for n in at.number_input}
    if deposit is not None:
        inputs["보증금 상한 (만원, 선택)"].set_value(deposit)
    if monthly is not None:
        inputs["월 고정비 상한 (만원, 선택)"].set_value(monthly)
    next(b for b in at.button if b.label == "세션 만들기").click().run()
    assert not at.exception, at.exception


def test_create_form_has_budget_fields(fake):
    at = _app()
    labels = [n.label for n in at.number_input]
    assert labels == ["보증금 상한 (만원, 선택)", "월 고정비 상한 (만원, 선택)"]
    assert all(n.value is None for n in at.number_input)            # 비우면 제한 없음
    fake.sessions = [{"id": "s-1", "title": "토요일", "listing_count": 0, "created_at": "2026-10-20T00:00:00Z"}]
    at = _app()                                                       # 세션이 있으면 펼침 상자 안 같은 폼
    assert [n.label for n in at.number_input] == labels


def test_create_with_budget_saves_budget_then_opens_session(fake):
    at = _app()
    _fill(at, " 신촌 토요일 ", deposit=1000, monthly=60)
    assert fake.calls == [
        ("POST", "/sessions", {"title": "신촌 토요일", "visit_date": None}),
        ("PUT", "/sessions/s-new/budget", {"deposit_max_manwon": 1000, "monthly_max_manwon": 60}),
        ("NAV", "s-new", None),
    ]
    assert at.session_state["p1_flash:session_detail"][0] == "success"


def test_create_with_one_budget_value(fake):
    at = _app()
    _fill(at, "신촌", monthly=55)
    assert ("PUT", "/sessions/s-new/budget", {"deposit_max_manwon": None, "monthly_max_manwon": 55}) in fake.calls


def test_create_without_budget_skips_budget_call(fake):
    at = _app()
    _fill(at, "신촌")
    assert [c[0] for c in fake.calls] == ["POST", "NAV"]


def test_budget_failure_still_opens_session_with_warning(fake):
    fake.budget_error = True
    at = _app()
    _fill(at, "신촌", deposit=1000)
    assert fake.calls[-1] == ("NAV", "s-new", None)                   # 세션은 만들었으니 상세로 간다
    kind, message = at.session_state["p1_flash:session_detail"]
    assert kind == "warning" and "예산은 저장하지 못했습니다" in message


def test_blank_title_creates_nothing(fake):
    at = _app()
    _fill(at, "  ", deposit=1000)
    assert fake.calls == [] and any("세션 제목을 입력하세요" in w.value for w in at.warning)
