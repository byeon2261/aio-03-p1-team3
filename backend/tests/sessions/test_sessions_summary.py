"""세션 상세 개편(frontend/features/sessions/summary·sections): 요약 숫자, 매물 카드 칩·금액, AI 정리 배너.

데이터는 화면이 이미 부르는 매물 목록·비교표 응답만 쓴다. 서버는 가짜.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"
if str(FRONTEND_DIR) not in sys.path:
    sys.path.append(str(FRONTEND_DIR))

from features.sessions import summary  # noqa: E402

SID = "s-1"


def _lst(n: int, status: str = "success", memo: str = "메모", re: bool = False) -> dict:
    return {"id": f"l-{n}", "label": f"{n}번 집", "listing_no": n, "memo_text": memo,
            "latest_analysis_status": status, "needs_reanalysis": re}


def _row(n: int, values: dict, budget: str | None = None) -> dict:
    cols = {"budget": {"display": "x", "status": budget, "tone": "default"}} if budget is not None else {}
    return {"listing_id": f"l-{n}", "listing_no": n, "label": f"{n}번 집", "analysis_status": "success",
            "needs_reanalysis": False, "values": values, "columns": cols}


V1 = {"deposit_manwon": 1000, "monthly_rent_manwon": 45, "maintenance_fee_manwon": 7, "monthly_cost_manwon": 52,
      "transit": "역 도보 8분", "floor": "3층", "direction": "남향", "followup_checks": ["소음"]}
V2 = {"deposit_manwon": 500, "monthly_rent_manwon": 38, "maintenance_fee_manwon": None, "monthly_cost_manwon": None,
      "transit": None, "floor": "1층", "direction": None, "followup_checks": ["채광", "소음", "수압", "난방"]}
LISTINGS = [_lst(1), _lst(2), _lst(3, "failed"), _lst(4, "none", memo="신축 깔끔")]
COMPARISON = {"session_id": SID, "enough_listings": True,
              "rows": [_row(1, V1, "within"), _row(2, V2, "unknown"), _row(3, {}, None), _row(4, {}, None)]}


def _metrics(listings, comparison) -> dict[str, str]:
    return {m["label"]: m["value"] for m in summary.summary_metrics(listings, comparison)}


# ------------------------------------------------------------------ 순수 함수
def test_summary_metrics_from_existing_responses():
    assert _metrics(LISTINGS, COMPARISON) == {"본 집": "4곳", "예산 안": "1곳", "확인 필요": "5건",
                                              "최저 월 고정비": "52만원"}


def test_summary_metrics_without_comparison_or_budget():
    assert _metrics(LISTINGS, None) == {"본 집": "4곳", "예산 안": "—", "확인 필요": "—", "최저 월 고정비": "—"}
    # 매물 1곳(enough_listings False): 예산 판정 열이 없어 예산 안은 —, 분석 값은 있음
    one = {"session_id": SID, "enough_listings": False, "rows": [_row(1, V1)]}
    assert _metrics([_lst(1)], one) == {"본 집": "1곳", "예산 안": "—", "확인 필요": "1건", "최저 월 고정비": "52만원"}
    # 예산을 안 정했으면 판정 status가 None → —
    none_budget = {"rows": [_row(1, V1, None), _row(2, V2, None)]}
    for r in none_budget["rows"]:
        r["columns"] = {"budget": {"display": "-", "status": None, "tone": "default"}}
    assert _metrics([_lst(1), _lst(2)], none_budget)["예산 안"] == "—"


def test_info_line_uses_analysis_values_then_memo():
    assert summary.info_line(_lst(1), _row(1, V1)) == "역 도보 8분 · 3층 · 남향"
    assert summary.info_line(_lst(2), _row(2, V2)) == "1층"
    assert summary.info_line(_lst(4, memo="신축   깔끔\n채광"), None) == "신축 깔끔 채광"


def test_chips_status_budget_and_checks():
    assert summary.chips(_lst(1), _row(1, V1, "within")) == [
        ":green-badge[분석 완료]", ":green-badge[예산 안]", ":blue-badge[소음 확인]"]
    assert summary.chips(_lst(2, re=True), _row(2, V2, "over")) == [
        ":green-badge[분석 완료]", ":orange-badge[재분석 필요]", ":red-badge[예산 초과]",
        ":blue-badge[채광 확인]", ":blue-badge[소음 확인]", ":gray-badge[확인 +2]"]
    assert summary.chips(_lst(3, "failed"), None) == [":red-badge[분석 실패]"]
    assert summary.chips(_lst(4, "none"), _row(4, {}, "unknown")) == [":gray-badge[분석 전]", ":gray-badge[판단 불가]"]


def test_price_lines():
    assert summary.price_lines(_row(1, V1)) == ("월 52만원", "보증금 1,000만원")
    assert summary.price_lines(_row(2, V2)) == ("월 38만원+?", "관리비 미기재 · 보증금 500만원")
    assert summary.price_lines(_row(3, {})) is None and summary.price_lines(None) is None


# ------------------------------------------------------------------ AppTest: 세션 상세 매물 영역
HEADER = f"""
import sys
sys.path.insert(0, {str(FRONTEND_DIR)!r})
import _p1_summary_fake as fake
from core.api import ApiError
from features.map import listing_map
from features.sessions import analyze_all, sections

def _get(path, params=None, **kw):
    fake.calls.append(path)
    if path in fake.errors:
        raise ApiError(503, "DB_UNAVAILABLE", "잠시 후 다시 시도해 주세요.")
    return fake.responses[path]

def _post(path, json=None, **kw):
    fake.posts.append(path)
    return {{}}

sections.api_get = _get
listing_map.api_get = _get
analyze_all.api_post = _post
sections._render_listings({{"id": "{SID}", "title": "토요일"}})
"""


@pytest.fixture
def fake():
    mod = types.ModuleType("_p1_summary_fake")
    mod.calls, mod.posts, mod.errors = [], [], set()
    mod.responses = {
        f"/sessions/{SID}/listings": LISTINGS,
        f"/sessions/{SID}/comparison": COMPARISON,
        f"/sessions/{SID}/locations": [],
        "/me/photos": [],
    }
    sys.modules["_p1_summary_fake"] = mod
    yield mod
    sys.modules.pop("_p1_summary_fake", None)


def _app():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_string(HEADER, default_timeout=10)
    at.run()
    assert not at.exception, at.exception
    return at


def _md(at) -> str:
    return "\n".join(str(m.value) for m in at.markdown)


def test_session_listings_summary_cards_and_chips(fake):
    at = _app()
    assert {m.label: m.value for m in at.metric} == {"본 집": "4곳", "예산 안": "1곳", "확인 필요": "5건",
                                                      "최저 월 고정비": "52만원"}
    md = _md(at)
    assert "**1번 집**" in md and "**4번 집**" in md
    assert ":green-badge[예산 안]" in md and ":red-badge[분석 실패]" in md
    assert "월 52만원" in md and "월 38만원+?" in md
    assert "역 도보 8분 · 3층 · 남향" in [c.value for c in at.caption]
    assert fake.calls.count(f"/sessions/{SID}/comparison") == 1
    assert not at.error


def test_buttons_keep_keys_and_banner_runs_existing_action(fake):
    at = _app()
    keys = {b.key for b in at.button}
    assert {f"p1_open_listing:l-{n}" for n in range(1, 5)} <= keys
    assert f"p1_analyze_all:{SID}" in keys
    assert any("AI로 한 번에 정리" in str(m.value) for m in at.markdown)
    assert any("정리 안 된 매물이 2곳 있어요" in str(m.value) for m in at.markdown)
    at.button(key=f"p1_analyze_all:{SID}").click().run()
    assert fake.posts == ["/listings/l-3/analyses", "/listings/l-4/analyses"]   # 정리 안 된 매물만


def test_all_done_shows_caption_instead_of_banner(fake):
    fake.responses[f"/sessions/{SID}/listings"] = [_lst(1), _lst(2)]
    at = _app()
    assert f"p1_analyze_all:{SID}" not in {b.key for b in at.button}
    assert not any("AI로 한 번에 정리" in str(m.value) for m in at.markdown)
    assert any("모든 매물이 정리되어 있습니다" in c.value for c in at.caption)


def test_comparison_failure_keeps_cards_without_numbers(fake):
    fake.errors.add(f"/sessions/{SID}/comparison")
    at = _app()
    assert {m.label: m.value for m in at.metric}["본 집"] == "4곳"
    assert {m.label: m.value for m in at.metric}["최저 월 고정비"] == "—"
    md = _md(at)
    assert "**1번 집**" in md and "월 52만원" not in md
    assert any("요약 숫자를 불러오지 못했습니다" in c.value for c in at.caption)
    assert not at.error                      # 부가 정보라 오류 상자는 띄우지 않는다


def test_no_listings_keeps_empty_message(fake):
    fake.responses[f"/sessions/{SID}/listings"] = []
    at = _app()
    assert not at.metric
    assert any("아직 매물이 없습니다" in i.value for i in at.info)
    assert f"/sessions/{SID}/comparison" not in fake.calls
