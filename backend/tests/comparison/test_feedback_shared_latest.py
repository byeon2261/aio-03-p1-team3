"""매물 상세 '수정·평가' 탭: 화면 위쪽(분석 섹션)이 받아 둔 최신 분석을 같이 써서 같은 API를 다시 부르지 않는다."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"
if str(FRONTEND_DIR) not in sys.path:
    sys.path.append(str(FRONTEND_DIR))

from core.api import ApiError  # noqa: E402
from features.analysis import sections as analysis_sections  # noqa: E402
from features.comparison import feedback_form  # noqa: E402

ANALYSIS = {"id": "a1", "status": "success", "fields": {}}


@pytest.fixture
def calls(monkeypatch):
    class Seen(list):
        fake = None

    seen = Seen()

    def fake_get(path, **kw):
        seen.append(path)
        if fake_get.error:
            raise fake_get.error
        return ANALYSIS

    fake_get.error = None
    monkeypatch.setattr(feedback_form, "api_get", fake_get)
    monkeypatch.setattr(analysis_sections, "api_get", fake_get)
    seen.fake = fake_get
    return seen


def test_shared_key_matches_analysis_section():
    assert feedback_form.SHARED_LATEST == analysis_sections._CACHE


def test_uses_analysis_already_loaded_on_page(calls):
    ctx = {"listing": {"id": "l1"}}
    analysis_sections._latest(ctx)                       # 위쪽 분석 섹션이 먼저 한 번 부른다
    assert feedback_form._latest(ctx, "l1") == ANALYSIS
    assert calls == ["/listings/l1/analyses/latest"]     # 한 번만


def test_shared_not_analyzed_is_none_without_call(calls):
    ctx = {"listing": {"id": "l1"}, feedback_form.SHARED_LATEST: (None, None)}
    assert feedback_form._latest(ctx, "l1") is None
    assert calls == []


def test_shared_error_is_raised_like_before(calls):
    err = ApiError(503, "SERVICE_UNAVAILABLE", "잠시 후 다시")
    ctx = {"listing": {"id": "l1"}, feedback_form.SHARED_LATEST: (None, err)}
    with pytest.raises(ApiError) as e:
        feedback_form._latest(ctx, "l1")
    assert e.value is err and calls == []


def test_without_shared_calls_api_and_404_is_none(calls):
    assert feedback_form._latest({"listing": {"id": "l1"}}, "l1") == ANALYSIS
    calls.fake.error = ApiError(404, "ANALYSIS_NOT_FOUND", "없음")
    assert feedback_form._latest({"listing": {"id": "l1"}}, "l1") is None
    calls.fake.error = ApiError(500, "INTERNAL_ERROR", "오류")
    with pytest.raises(ApiError):
        feedback_form._latest({"listing": {"id": "l1"}}, "l1")
