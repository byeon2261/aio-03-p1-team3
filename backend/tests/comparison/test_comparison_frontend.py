"""F6 비교표 화면(frontend/features/comparison/comparison_table): 제목 옆 ? 설명과 '포함 내역' 칸. 서버는 가짜."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"
if str(FRONTEND_DIR) not in sys.path:
    sys.path.append(str(FRONTEND_DIR))

from features.comparison import comparison_table  # noqa: E402

SCRIPT = f"""
import sys
sys.path.insert(0, {str(FRONTEND_DIR)!r})
import _comparison_ui_fake as fake
from features.comparison import comparison_table

comparison_table.api_get = lambda path, params=None, **kw: fake.data
comparison_table.render_comparison({{"session": {{"id": "s1", "title": "토요일"}}}})
"""


@pytest.fixture
def ui_fake():
    mod = types.ModuleType("_comparison_ui_fake")
    row = {"listing_id": "l1", "listing_no": 1, "label": "1번 집", "analysis_status": "success",
           "needs_reanalysis": False, "values": {"maintenance_includes": ["인터넷", "수도"]}, "columns": {}}
    mod.data = {"enough_listings": True, "message": None,
                "fields": [{"key": "maintenance_includes", "title": "포함 내역"}],
                "providers": [], "lowest": {}, "hidden_count": {},
                "rows": [row, {**row, "listing_id": "l2", "listing_no": 2, "label": "2번 집"}]}
    sys.modules["_comparison_ui_fake"] = mod
    yield mod
    sys.modules.pop("_comparison_ui_fake", None)


def test_title_help_text():
    assert comparison_table.TITLE_HELP.startswith("관리비가 비싸도 **포함 내역**이 많으면 더 쌀 수 있어요.")
    assert "'미기재'는 집주인에게 꼭 물어보세요." in comparison_table.TITLE_HELP


def test_comparison_title_has_help_and_includes_column(ui_fake):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_string(SCRIPT, default_timeout=10)
    at.run()
    assert not at.exception, at.exception
    assert any("매물 비교표" in str(m.value) and "table_chart" in str(m.value) for m in at.markdown)   # 아이콘 제목
    assert comparison_table.TITLE_HELP in [c.value for c in at.caption]          # 도움말은 제목 아래 회색 한 줄
    table = next(m.value for m in at.markdown if m.value.startswith("| 매물"))
    assert "포함 내역" in table.splitlines()[0] and "인터넷, 수도" in table
