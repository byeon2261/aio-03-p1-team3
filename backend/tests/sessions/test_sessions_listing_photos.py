"""세션 상세 매물 카드의 대표 사진: 이 세션 사진만, 처음 올린 사진, 여러 장이면 +N, 실패해도 목록은 보인다."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"

SID = "s-1"
LISTINGS = [
    {"id": "l-1", "label": "1번 집", "listing_no": 1, "memo_text": "첫 집", "latest_analysis_status": "none",
     "needs_reanalysis": False},
    {"id": "l-2", "label": "2번 집", "listing_no": 2, "memo_text": "둘째 집", "latest_analysis_status": "none",
     "needs_reanalysis": False},
]


def _photo(pid: str, lid: str, sid: str = SID) -> dict:
    return {"id": pid, "listing_id": lid, "session_id": sid, "content_type": "image/png", "size_bytes": 10,
            "created_at": "2026-10-18T05:00:00Z", "url": f"https://example.com/{pid}.png?token=x&y=1"}


HEADER = f"""
import sys
sys.path.insert(0, {str(FRONTEND_DIR)!r})
import _p1_photo_fake as fake
import streamlit as st
from core.api import ApiError
from features.map import listing_map
from features.sessions import sections

def _get(path, params=None, **kw):
    fake.calls.append(path)
    if path in fake.errors:
        raise ApiError(503, "STORAGE_UNAVAILABLE", "잠시 후 다시 시도해 주세요.")
    return fake.responses[path]

sections.api_get = _get
listing_map.api_get = _get
sections._render_listings({{"id": "{SID}", "title": "토요일"}})
"""


@pytest.fixture
def fake():
    mod = types.ModuleType("_p1_photo_fake")
    mod.calls, mod.errors = [], set()
    mod.responses = {
        f"/sessions/{SID}/listings": LISTINGS,
        f"/sessions/{SID}/locations": [],
        # 최신순: 1번 집에 사진 2장(p-1을 먼저 올림), 다른 세션 사진 1장
        "/me/photos": [_photo("p-2", "l-1"), _photo("p-other", "l-9", sid="s-9"), _photo("p-1", "l-1")],
    }
    sys.modules["_p1_photo_fake"] = mod
    yield mod
    sys.modules.pop("_p1_photo_fake", None)


def _app():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_string(HEADER, default_timeout=10)
    at.run()
    assert not at.exception, at.exception
    return at


def _html(at) -> str:
    return "\n".join(str(m.value) for m in at.markdown)


def test_listing_card_shows_first_photo_with_count(fake):
    at = _app()
    md = _html(at)
    assert md.count("<img ") == 1                                   # 사진이 있는 1번 집만
    assert "https://example.com/p-1.png?token=x&amp;y=1" in md      # 처음 올린 사진, URL은 escape
    assert "p-other" not in md and "p-2.png" not in md
    assert "+1</span>" in md
    assert "**2번 집**" in md and fake.calls.count("/me/photos") == 1


def test_listing_card_without_photos_or_on_error(fake):
    fake.errors.add("/me/photos")
    at = _app()
    md = _html(at)
    assert "<img " not in md and "**1번 집**" in md and "**2번 집**" in md
    assert not at.error                                             # 사진 실패는 조용히 넘어간다
