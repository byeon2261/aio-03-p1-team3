"""F11 화면(frontend/features/budget): 숨김 안내 순수 함수 + Streamlit AppTest. 서버는 가짜."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"
if str(FRONTEND_DIR) not in sys.path:
    sys.path.append(str(FRONTEND_DIR))

from features.budget import view  # noqa: E402
from features.comparison import cells  # noqa: E402

SID = "s1"


def _item(no, status, reason, next_action=None, missing=()):
    labels = {"within": "예산 안", "over": "예산 초과", "unknown": "판단 불가"}
    return {"listing_id": f"l{no}", "listing_no": no, "label": f"{no}번 집", "status": status,
            "status_label": labels.get(status, "-"), "reason": reason, "missing": list(missing),
            "next_action": next_action}


EVALUATIONS = {
    "session_id": SID, "budget_set": True, "counts": {"within": 1, "over": 2, "unknown": 2},
    "items": [
        _item(1, "within", "예산 안"),
        _item(2, "unknown", "관리비 미기재", "관리비 17만원 이하면 예산 안", ["관리비"]),
        _item(3, "unknown", "분석 결과 없음", "AI 정리를 실행하세요"),
        _item(4, "over", "보증금 초과"),
        _item(5, "over", "월 고정비 초과"),
    ],
}


# ------------------------------------------------------------------ 순수 함수
def test_budget_hidden_summary_splits_by_reason():
    assert view.hidden_summary(EVALUATIONS) == "예산 초과 2건 · 판단 불가 2건 숨김"
    assert view.hidden_summary({"counts": {"within": 1, "over": 0, "unknown": 3}}) == "판단 불가 3건 숨김"
    assert view.hidden_summary({"counts": {"within": 2, "over": 1, "unknown": 0}}) == "예산 초과 1건 숨김"
    assert view.hidden_summary({"counts": {"within": 3, "over": 0, "unknown": 0}}) is None
    assert view.hidden_summary(None) is None


def test_budget_unknown_lines():
    items = view.unknown_items(EVALUATIONS)
    assert [it["label"] for it in items] == ["2번 집", "3번 집"]
    assert view.unknown_line(items[0]) == "**2번 집** · 관리비 미기재 · 관리비 17만원 이하면 예산 안"
    assert view.unknown_line(items[1]) == "**3번 집** · 분석 결과 없음 · AI 정리를 실행하세요"


def test_comparison_hidden_message_points_to_budget_section():
    assert cells.hidden_message({"hidden_count": {"within_budget": 4}}) == "4건 숨김 · 사유는 아래 '예산' 섹션에서 확인"
    assert cells.hidden_message({"hidden_count": {}}) is None


# ------------------------------------------------------------------ AppTest
SCRIPT = f"""
import sys
sys.path.insert(0, {str(FRONTEND_DIR)!r})
import streamlit as st
import _budget_ui_fake as fake
from core.state import budget_filter_key
from features.budget import sections

def _get(path, **kw):
    fake.calls.append(("GET", path))
    return fake.responses[path]

def _put(path, json=None, **kw):
    fake.calls.append(("PUT", path))
    return fake.responses[f"/sessions/{SID}/budget"]

sections.api_get, sections.api_put = _get, _put
if fake.filter_on and budget_filter_key("{SID}") not in st.session_state:
    st.session_state[budget_filter_key("{SID}")] = True
# 비교표(30)·적합도 순위(35)처럼 예산(40)보다 위에서 필터 값을 읽는 섹션 흉내
fake.seen.append(bool(st.session_state.get(budget_filter_key("{SID}"))))
sections.render_budget({{"session": {{"id": "{SID}", "title": "토요일"}}}})
"""


@pytest.fixture
def ui_fake():
    mod = types.ModuleType("_budget_ui_fake")
    mod.calls, mod.filter_on, mod.seen = [], True, []
    mod.responses = {
        f"/sessions/{SID}/budget": {"session_id": SID, "deposit_max_manwon": 1000, "monthly_max_manwon": 55,
                                    "updated_at": "2026-10-17T07:00:00+00:00"},
        f"/sessions/{SID}/budget/evaluations": EVALUATIONS,
    }
    sys.modules["_budget_ui_fake"] = mod
    yield mod
    sys.modules.pop("_budget_ui_fake", None)


def _app():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_string(SCRIPT, default_timeout=10)
    at.run()
    assert not at.exception, at.exception
    return at


def _texts(at):
    out = []
    for kind in ("markdown", "caption", "info", "warning", "error", "success"):
        out += [e.value for e in getattr(at, kind)]
    return "\n".join(str(x) for x in out)


def test_budget_ui_filter_on_shows_hidden_reasons_and_actions(ui_fake):
    at = _app()
    text = _texts(at)
    assert "예산 필터 적용 중 · **예산 초과 2건 · 판단 불가 2건 숨김**" in text
    assert "**2번 집** · 관리비 미기재 · 관리비 17만원 이하면 예산 안" in text
    assert "**3번 집** · 분석 결과 없음 · AI 정리를 실행하세요" in text
    assert "4번 집" not in text   # 예산 초과는 개수만
    assert [b.label for b in at.button if b.key and b.key.startswith("budget_open:")] == ["열기", "열기"]
    assert ("GET", f"/sessions/{SID}/budget/evaluations") in ui_fake.calls


def test_budget_ui_filter_off_does_not_call_evaluations(ui_fake):
    ui_fake.filter_on = False
    at = _app()
    assert "숨김" not in _texts(at)
    assert ("GET", f"/sessions/{SID}/budget/evaluations") not in ui_fake.calls


def test_budget_toggle_reaches_sections_above_in_same_click(ui_fake):
    """예산은 비교표·순위보다 아래(order 40)에 그려진다. 토글을 바꾼 그 실행에서 위쪽이 새 값을 읽어야 한다."""
    ui_fake.filter_on = False
    at = _app()
    assert ui_fake.seen[-1] is False
    at.toggle(key=f"budget_toggle:{SID}").set_value(True).run()
    assert not at.exception, at.exception
    assert ui_fake.seen[-1] is True                 # 콜백이 화면을 그리기 전에 값을 옮겼다
    at.toggle(key=f"budget_toggle:{SID}").set_value(False).run()
    assert ui_fake.seen[-1] is False


def test_weights_above_ranking_and_budget_below():
    from core.loader import load_sections

    order = [(s["feature"], s["order"]) for s in load_sections() if s["slot"] == "session_detail"]
    assert [f for f, _ in order] == ["sessions", "comparison", "scoring", "scoring", "budget", "sessions"]
    assert [o for _, o in order] == [10, 30, 32, 35, 40, 90]          # 항목 가중치 32 → 적합도 순위 35 → 예산 40
