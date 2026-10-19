"""세션 화면 [AI 정리](frontend/features/sessions/analyze_all): 대상 고르기 + Streamlit AppTest. 서버는 가짜."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"
if str(FRONTEND_DIR) not in sys.path:
    sys.path.append(str(FRONTEND_DIR))

from features.sessions import analyze_all  # noqa: E402
from core.api import ApiError  # noqa: E402


def _lst(lid, status="none", memo="보증금 500 월세 45", needs=False):
    return {"id": lid, "label": f"{lid}번 집", "memo_text": memo,
            "latest_analysis_status": status, "needs_reanalysis": needs}


# ------------------------------------------------------------------ 순수 함수
def test_targets_are_unanalyzed_failed_or_changed_with_memo():
    listings = [_lst("1"), _lst("2", "success"), _lst("3", "failed"), _lst("4", "success", needs=True),
                _lst("5", memo="  ")]
    assert [x["id"] for x in analyze_all.analysis_targets(listings)] == ["1", "3", "4"]
    assert analyze_all.analysis_targets([_lst("2", "success")]) == []


def test_result_message():
    assert analyze_all.result_message(2, 0) == ("success", "2곳을 정리했습니다. 아래 매물 비교표에 바로 반영됐어요.")
    kind, msg = analyze_all.result_message(1, 1)
    assert kind == "warning" and "1곳은 정리했고 1곳은 실패" in msg
    kind, msg = analyze_all.result_message(0, 2)
    assert kind == "warning" and "2곳 모두" in msg


# ------------------------------------------------------------------ AppTest
SCRIPT = f"""
import sys
sys.path.insert(0, {str(FRONTEND_DIR)!r})
import _analyze_all_fake as fake
from core.api import ApiError
from features.sessions import analyze_all
from features.sessions.common import show_flash

def _post(path, json=None, **kw):
    fake.calls.append((path, json))
    if path in fake.fail:
        raise ApiError(502, "AI_UPSTREAM_ERROR", "AI 서비스에서 문제가 생겼습니다.")
    return {{}}

analyze_all.api_post = _post
show_flash("session_detail")
analyze_all.render_button(fake.listings, "s1")
"""


@pytest.fixture
def ui_fake():
    mod = types.ModuleType("_analyze_all_fake")
    mod.calls, mod.fail = [], set()
    mod.listings = [_lst("1"), _lst("2", "success"), _lst("3", "failed")]
    sys.modules["_analyze_all_fake"] = mod
    yield mod
    sys.modules.pop("_analyze_all_fake", None)


def _app():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_string(SCRIPT, default_timeout=10)
    at.run()
    assert not at.exception, at.exception
    return at


def test_button_analyzes_only_targets_and_reports(ui_fake):
    at = _app()
    assert at.button[0].label == "AI 정리" and not at.button[0].disabled
    at.button[0].click().run()
    assert ui_fake.calls == [("/listings/1/analyses", {"use_cache": True}),
                             ("/listings/3/analyses", {"use_cache": True})]
    assert any("2곳을 정리했습니다" in s.value for s in at.success)


def test_button_partial_failure_shows_warning(ui_fake):
    ui_fake.fail = {"/listings/3/analyses"}
    at = _app()
    at.button[0].click().run()
    assert any("1곳은 정리했고 1곳은 실패" in w.value for w in at.warning)


def test_button_disabled_when_all_done(ui_fake):
    ui_fake.listings = [_lst("2", "success")]
    at = _app()
    assert at.button[0].disabled
    assert ui_fake.calls == []
