"""F12 화면(frontend/features/scoring): 순수 함수 + Streamlit AppTest로 섹션 표시·요청 확인. 서버는 가짜."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"
if str(FRONTEND_DIR) not in sys.path:
    sys.path.append(str(FRONTEND_DIR))

from features.scoring import view  # noqa: E402

ITEMS = ["채광", "소음", "수압", "곰팡이", "난방", "층수", "옵션", "보안", "교통"]
SID, LID = "s1", "l1"
SUMMER = {"id": "p-summer", "name": "여름 6개월",
          "weights": [{"item_key": k, "weight": {"채광": 20, "곰팡이": 50, "소음": 30}.get(k, 0)} for k in ITEMS]}


# ------------------------------------------------------------------ 순수 함수
def test_scoring_view_bodies_and_labels():
    assert view.satisfaction_body({"채광": 90, "소음": None, "수압": 0.0}) == {
        "items": [{"item_key": "채광", "satisfaction": 90}, {"item_key": "수압", "satisfaction": 0}]}
    assert view.weights_body(" 여름 ", {"채광": 20, "소음": None}) == {
        "name": "여름", "weights": [{"item_key": "채광", "weight": 20}, {"item_key": "소음", "weight": 0}]}
    assert view.profile_options([SUMMER]) == [None, "p-summer"]
    assert view.profile_label(None, [SUMMER]) == view.NO_PROFILE_LABEL
    assert view.profile_label("p-summer", [SUMMER]) == "여름 6개월"
    assert view.weights_summary(SUMMER) == "채광 20 · 소음 30 · 곰팡이 50"
    assert view.weights_summary(None) == "모든 항목 같은 가중치"
    assert view.fmt_score(None) == "미입력" and view.fmt_score(73) == "73점"


def test_scoring_view_ranking_markdown():
    md = view.ranking_markdown([
        {"label": "2번 집", "score": 73, "rank": 1, "entered_count": 3, "total_items": 9},
        {"label": "3번 집", "score": None, "rank": None, "entered_count": 0, "total_items": 9},
    ])
    lines = md.splitlines()
    assert lines[0] == "| 순위 | 매물 | 적합도 | 입력한 항목 |"
    assert lines[2] == "| 1위 | **2번 집** | 73점 | 3/9 |"
    assert lines[3] == "| — | **3번 집** | 미입력 | 0/9 |"
    assert view.hidden_message({"hidden_count": {"within_budget": 2}}).startswith("필터로 2건 숨김")
    assert view.hidden_message({"hidden_count": {}}) is None


# ------------------------------------------------------------------ AppTest
SCRIPT = f"""
import sys
sys.path.insert(0, {str(FRONTEND_DIR)!r})
import _scoring_ui_fake as fake
from features.scoring import sections

def _get(path, **kw):
    fake.calls.append(("GET", path, kw.get("params")))
    return fake.responses[path]

def _put(path, json=None, **kw):
    fake.calls.append(("PUT", path, json))
    return fake.put_result.get(path, fake.responses.get(path))

def _post(path, json=None, **kw):
    fake.calls.append(("POST", path, json))
    return {{}}

def _delete(path, **kw):
    fake.calls.append(("DELETE", path, None))
    return {{"ok": True}}

sections.api_get, sections.api_put, sections.api_post, sections.api_delete = _get, _put, _post, _delete
ctx = {{"session": {{"id": "{SID}", "title": "토요일"}}, "listing": {{"id": "{LID}"}}}}
for sec in sections.SECTIONS:
    if sec["slot"] == fake.slot:
        sec["render"](ctx)
"""


def _setting(enabled=True, pid=None, name=None):
    return {"session_id": SID, "enabled": enabled, "weight_profile_id": pid, "weight_profile_name": name,
            "updated_at": None, "items": ITEMS}


@pytest.fixture
def ui_fake():
    mod = types.ModuleType("_scoring_ui_fake")
    mod.calls, mod.put_result, mod.slot = [], {}, "session_detail"
    mod.responses = {
        "/weight-profiles": [SUMMER],
        f"/sessions/{SID}/scoring": _setting(True, "p-summer", "여름 6개월"),
        f"/sessions/{SID}/scores": {
            "session_id": SID, "setting": _setting(True, "p-summer", "여름 6개월"), "items": ITEMS,
            "rows": [{"listing_id": "b", "listing_no": 2, "label": "2번 집", "score": 73, "rank": 1,
                      "entered_count": 3, "total_items": 9},
                     {"listing_id": "a", "listing_no": 1, "label": "1번 집", "score": 56, "rank": 2,
                      "entered_count": 3, "total_items": 9}],
            "hidden_count": {}},
        f"/listings/{LID}/satisfaction": {
            "listing_id": LID, "entered_count": 1, "updated_at": "2026-10-16T07:00:00+00:00",
            "items": [{"item_key": k, "satisfaction": 90 if k == "채광" else None} for k in ITEMS]},
    }
    sys.modules["_scoring_ui_fake"] = mod
    yield mod
    sys.modules.pop("_scoring_ui_fake", None)


def _app():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_string(SCRIPT, default_timeout=10)
    at.run()
    assert not at.exception, at.exception
    return at


def _texts(at):
    out = []
    for kind in ("markdown", "caption", "info", "warning", "error", "success", "subheader"):
        out += [e.value for e in getattr(at, kind)]
    return "\n".join(str(x) for x in out)


def test_scoring_ui_session_sections_show_setting_and_ranking(ui_fake):
    at = _app()
    text = _texts(at)
    assert "항목 가중치" in text and "적합도 순위" in text
    assert "적용 중인 가중치: 채광 20 · 소음 30 · 곰팡이 50" in text
    assert "| 1위 | **2번 집** | 73점 | 3/9 |" in text
    assert at.toggle[0].value is True
    assert at.selectbox[0].value == "p-summer"
    # 예산 필터가 꺼져 있으면 filters 없이 부른다
    assert ("GET", f"/sessions/{SID}/scores", None) in ui_fake.calls


def test_scoring_ui_turning_off_saves_setting(ui_fake):
    ui_fake.put_result[f"/sessions/{SID}/scoring"] = _setting(False, "p-summer", "여름 6개월")
    at = _app()
    at.toggle[0].set_value(False).run()
    assert not at.exception, at.exception
    assert ("PUT", f"/sessions/{SID}/scoring", {"enabled": False, "weight_profile_id": "p-summer"}) in ui_fake.calls


def test_scoring_ui_ranking_hidden_when_disabled(ui_fake):
    ui_fake.responses[f"/sessions/{SID}/scores"]["setting"]["enabled"] = False
    ui_fake.responses[f"/sessions/{SID}/scoring"] = _setting(False)
    at = _app()
    text = _texts(at)
    assert "적합도 순위" not in text
    assert "항목 가중치가 꺼져 있습니다" in text


def test_scoring_ui_satisfaction_save_sends_only_filled_items(ui_fake):
    ui_fake.slot = "listing_detail"
    at = _app()
    assert "항목 만족도" in _texts(at)
    inputs = {n.label: n for n in at.number_input}
    assert inputs["채광"].value == 90 and inputs["소음"].value is None
    inputs["소음"].set_value(60)
    at.button[0].click().run()     # 만족도 저장(폼 제출 버튼)
    assert not at.exception, at.exception
    put = [c for c in ui_fake.calls if c[0] == "PUT"]
    assert put == [("PUT", f"/listings/{LID}/satisfaction",
                    {"items": [{"item_key": "채광", "satisfaction": 90}, {"item_key": "소음", "satisfaction": 60}]})]


def test_scoring_ui_profile_editor_creates_profile(ui_fake):
    at = _app()
    at.text_input[0].set_value("겨울 6개월")
    sliders = {s.label: s for s in at.slider}
    assert sliders["채광"].value == 50                     # 새 프로필 기본값
    sliders["채광"].set_value(80)
    save = next(b for b in at.button if b.label == "프로필 저장")
    save.click().run()
    assert not at.exception, at.exception
    post = [c for c in ui_fake.calls if c[0] == "POST"]
    assert len(post) == 1 and post[0][1] == "/weight-profiles"
    body = post[0][2]
    assert body["name"] == "겨울 6개월"
    weights = {w["item_key"]: w["weight"] for w in body["weights"]}
    assert weights["채광"] == 80 and weights["소음"] == 50 and set(weights) == set(ITEMS)
