"""운영 대시보드 '사용자 평가 사례' 필터(frontend/features/admin_logs/logic): 👍·👎 목록 합치기."""

from __future__ import annotations

import sys
from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"
if str(FRONTEND_DIR) not in sys.path:
    sys.path.append(str(FRONTEND_DIR))

from features.admin_logs.logic import (  # noqa: E402
    DEFAULT_FEEDBACK_FILTER,
    FEEDBACK_FILTERS,
    merge_feedback,
)


def _fb(fid, rating, at):
    return {"id": fid, "rating": rating, "created_at": f"2026-10-19T0{at}:00:00+00:00"}


def test_filters_default_all_asks_up_and_down():
    assert DEFAULT_FEEDBACK_FILTER == "전체"
    assert FEEDBACK_FILTERS["전체"] == ("up", "down")
    assert FEEDBACK_FILTERS["👍 좋은 평가"] == ("up",)
    assert FEEDBACK_FILTERS["👎 낮은 평가"] == ("down",)


def test_merge_sorts_newest_first_and_limits():
    ups = [_fb("u1", "up", 5), _fb("u2", "up", 1)]
    downs = [_fb("d1", "down", 4), _fb("d2", "down", 3)]
    merged = merge_feedback([ups, downs], limit=3)
    assert [x["id"] for x in merged] == ["u1", "d1", "d2"]


def test_merge_drops_duplicate_ids_and_handles_empty():
    assert merge_feedback([[], None], limit=20) == []
    a = _fb("x", "up", 2)
    assert [x["id"] for x in merge_feedback([[a], [dict(a)]], limit=20)] == ["x"]
