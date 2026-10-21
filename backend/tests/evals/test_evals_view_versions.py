"""개선 전후 비교 화면(frontend/features/evals/view.py): v3를 고를 수 있고, 기본 '개선 후'는 가장 높은 버전(#57)."""

from __future__ import annotations

import sys
from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"
if str(FRONTEND_DIR) not in sys.path:
    sys.path.append(str(FRONTEND_DIR))

from features.evals import view  # noqa: E402


def _runs(*versions):
    return [{"id": str(i), "prompt_version": v} for i, v in enumerate(versions)]   # 최신순


def test_evals_view_offers_v3():
    assert view.PROMPT_VERSIONS == ("v1", "v2", "v3")


def test_evals_view_default_pair_prefers_highest_version():
    assert view.default_pair(_runs("v2", "v3", "v1")) == (2, 1)        # 개선 후 = 최근 v3
    assert view.default_pair(_runs("v2", "v1")) == (1, 0)              # v3가 없으면 v2


def test_evals_view_default_pair_fallback():
    assert view.default_pair(_runs("v1", "v1")) == (1, 0)              # v1만 있으면 최근 두 개
    assert view.default_pair(_runs("v3")) == (0, 0)
