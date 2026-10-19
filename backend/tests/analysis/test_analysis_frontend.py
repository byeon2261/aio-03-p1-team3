"""화면(frontend/features/analysis): 순수 로직 + Streamlit AppTest로 상태별 표시 확인. 서버는 가짜."""

import sys
import types
from pathlib import Path

import pytest

FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"
if str(FRONTEND_DIR) not in sys.path:
    sys.path.append(str(FRONTEND_DIR))

from features.analysis import logic  # noqa: E402

LID = "11111111-1111-1111-1111-111111111111"


def _analysis(**kw):
    def fv(v, edited=False, user=None):
        return {"ai_value": v, "user_value": user, "value": user if edited else v, "edited": edited}

    a = {
        "id": "a1", "listing_id": LID, "status": "success", "error_code": None, "prompt_version": "v1",
        "model": "gemini-3.5-flash-lite", "thinking_level": "minimal", "schema_version": "1",
        "created_at": "2026-10-14T06:00:00+00:00",
        "fields": {"label": fv("2번 집"), "deposit_manwon": fv(500), "monthly_rent_manwon": fv(45, True, 50),
                   "maintenance_fee_manwon": fv(7), "maintenance_includes": fv(["인터넷"]),
                   "transit": fv("신림역 도보 8분"), "floor": fv(None), "direction": fv("남향"),
                   "pros": fv(["남향이라 채광 좋음"]), "cons": fv(["화장실 천장에 곰팡이 조금"])},
        "checks": [{"item": "채광", "status": "confirmed", "evidence": "남향이라 채광 좋음"},
                   {"item": "곰팡이", "status": "confirmed", "evidence": "화장실 천장에 곰팡이 조금"},
                   {"item": "수압", "status": "unchecked", "evidence": "수압 확인 못함"},
                   {"item": "소음", "status": "ambiguous", "evidence": "조용한 듯?"}],
        "confirmed_checks": ["채광", "곰팡이"], "unchecked": ["수압"], "ambiguous_checks": ["소음"],
        "missing_checks": ["난방", "층수", "옵션", "보안", "교통"],
        "ambiguous": ["관리비 별도"], "mixed_listings": False, "rating": None,
        "needs_reanalysis": False, "previous_overrides": {},
    }
    a.update(kw)
    return a


# ------------------------------------------------------------------ 순수 로직
def test_analysis_frontend_status_groups_and_questions():
    a = _analysis()
    groups = {g["title"]: g for g in logic.status_groups(a)}
    assert [i["item"] for i in groups["확인됨"]["items"]] == ["채광", "곰팡이"]
    assert groups["미확인"]["items"][0] == {"item": "수압", "evidence": "수압 확인 못함"}
    assert groups["모호함"]["items"][0]["evidence"] == "조용한 듯?"
    assert groups["미기재"]["show_evidence"] is False and groups["미기재"]["items"][0]["evidence"] == ""
    qs = logic.inquiry_questions(a)
    assert [q[0] for q in qs] == ["소음", "수압", "난방", "층수", "옵션", "보안", "교통"]
    assert ("수압", "샤워기와 세면대를 함께 틀어도 수압이 괜찮나요?") in qs
    assert set(logic.INQUIRY_QUESTIONS) == set(logic.CHECKLIST)


def test_analysis_frontend_checklist_matches_backend():
    from app.core.analysis_contract import CHECKLIST

    assert logic.CHECKLIST == CHECKLIST


@pytest.mark.parametrize("listing, analysis, show, label", [
    ({"memo_text": "메모"}, None, True, "AI로 정리하기"),
    ({"memo_text": ""}, None, True, "AI로 정리하기"),
    ({"memo_text": "메모"}, {"status": "failed"}, True, "다시 시도"),
    ({"memo_text": "메모", "needs_reanalysis": True}, {"status": "success"}, True, "다시 분석"),
    ({"memo_text": "메모"}, {"status": "success", "needs_reanalysis": True}, True, "다시 분석"),
    ({"memo_text": "메모"}, {"status": "success"}, False, ""),
])
def test_analysis_frontend_button_state(listing, analysis, show, label):
    s = logic.button_state(listing, analysis)
    assert s["show"] is show and s["label"] == label
    assert s["disabled"] is (not listing["memo_text"].strip() or not show)


# ------------------------------------------------------------------ AppTest
# 매물 상세의 'AI 정리' 네 자리(actions·notice·overview·summary)를 화면 순서대로, 같은 ctx로 그린다
SCRIPT = f"""
import sys
sys.path.insert(0, {str(FRONTEND_DIR)!r})
import _analysis_ui_fake as fake
from features.analysis import sections
from core.api import ApiError

def _get(path, **kw):
    fake.calls.append(("GET", path))
    if fake.latest is None:
        raise ApiError(404, "ANALYSIS_NOT_FOUND", "분석 결과가 없습니다.")
    if isinstance(fake.latest, ApiError):
        raise fake.latest
    return fake.latest

def _post(path, **kw):
    fake.calls.append(("POST", path))
    if fake.post_error is not None:
        raise fake.post_error
    fake.latest = fake.after_post
    return fake.after_post

sections.api_get = _get
sections.api_post = _post
ctx = {{"listing": fake.listing, "session": {{"id": "s1", "title": "토요일"}}, "comparison_row": fake.row}}
for area in ("actions", "notice", "overview", "summary"):
    for sec in sections.SECTIONS:
        if sec.get("area") == area:
            sec["render"](ctx)
"""


@pytest.fixture
def ui_fake():
    mod = types.ModuleType("_analysis_ui_fake")
    mod.calls, mod.latest, mod.after_post, mod.post_error = [], None, None, None
    mod.listing = {"id": LID, "memo_text": "메모 있음", "needs_reanalysis": False}
    mod.row = {"values": {"monthly_cost_manwon": 57}}
    sys.modules["_analysis_ui_fake"] = mod
    yield mod
    sys.modules.pop("_analysis_ui_fake", None)


def _run():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_string(SCRIPT, default_timeout=10)
    at.run()
    assert not at.exception, at.exception
    return at


def _texts(at):
    out = []
    for kind in ("markdown", "caption", "info", "warning", "error", "success", "subheader"):
        out += [e.value for e in getattr(at, kind)]
    out += [f"{m.label}={m.value}" for m in at.metric]
    out += [c.label for c in at.checkbox] + [e.label for e in at.expander]
    return "\n".join(str(x) for x in out)


def test_analysis_frontend_sections_have_areas():
    from features.analysis import sections

    assert [(s["area"], s["order"]) for s in sections.SECTIONS] == [
        ("actions", 20), ("notice", 21), ("overview", 22), ("summary", 23)]


def test_analysis_frontend_empty_state_and_run(ui_fake):
    at = _run()
    assert "아직 정리 전이에요" in _texts(at) and "내 메모" not in _texts(at)   # 메모 미리보기 없음
    assert [(b.label, b.key) for b in at.button] == [("✨ AI로 정리하기", f"analysis_run_{LID}")]   # 카드 안 버튼만
    ui_fake.after_post = _analysis()
    at.button[0].click().run()
    texts = _texts(at)
    assert ("POST", f"/listings/{LID}/analyses") in ui_fake.calls
    assert "정리했습니다" in texts and "보증금=500만원" in texts and "월세 ✎=50만원" in texts
    assert "월 고정비=57만원" in texts                                           # 비교표 응답의 월 고정비
    assert [b.label for b in at.button] == ["✨ 다시 정리"] and at.button[0].disabled


def test_analysis_frontend_memo_empty_disables_button(ui_fake):
    ui_fake.listing = {"id": LID, "memo_text": "  "}
    at = _run()
    assert "메모가 비어 있어요" in _texts(at) and at.button[0].disabled


def test_analysis_frontend_result_summary(ui_fake):
    ui_fake.latest = _analysis()
    at = _run()
    t = _texts(at)
    for s in ("관리비=7만원", "관리비 포함: 인터넷", "미기재", "신림역 도보 8분", "남향",
              "확인됨", "모호함", "미확인", "미기재", ":green-badge[채광]", ":gray-badge[난방]",
              "“수압 확인 못함”", "“조용한 듯?”", "“관리비 별도”", "근거 문장 보기",
              "다음 방문 때 물어볼 것", "**수압** · 샤워기와 세면대를 함께 틀어도 수압이 괜찮나요?"):
        assert s in t, s
    assert "2번 집" not in t                                                  # 카드 안 중복 제목 없음
    assert len(at.checkbox) == 7 and any(e.label == "+3개 더 보기" for e in at.expander)   # 4개 + 더 보기
    assert at.warning == []
    assert [b.label for b in at.button] == ["✨ 다시 정리"] and at.button[0].disabled   # 메모 그대로면 비활성
    assert at.button[0].help == "메모를 고치면 다시 정리할 수 있어요"


def test_analysis_frontend_status_line_order(ui_fake):
    ui_fake.latest = _analysis()
    at = _run()
    line = next(str(m.value) for m in at.markdown if "확인됨" in str(m.value) and "-badge[" in str(m.value))
    assert line.index("확인됨") < line.index("모호함") < line.index("미확인") < line.index("미기재")


def test_analysis_frontend_mixed_listings_warning(ui_fake):
    ui_fake.latest = _analysis(mixed_listings=True)
    at = _run()
    assert logic.MIXED_LISTINGS_MESSAGE in [w.value for w in at.warning]


def test_analysis_frontend_failed_shows_card(ui_fake):
    ui_fake.latest = _analysis(status="failed", error_code="FMT", fields={}, checks=[], confirmed_checks=[],
                               unchecked=[], ambiguous_checks=[], missing_checks=[])
    at = _run()
    t = _texts(at)
    assert "정리하지 못했어요" in t and "형식이 맞지 않아" in t
    assert [b.label for b in at.button] == ["✨ AI로 정리하기"] and not at.button[0].disabled


def test_analysis_frontend_post_error_message(ui_fake):
    from core.api import ApiError

    ui_fake.post_error = ApiError(504, "AI_TIMEOUT", "AI 응답이 늦습니다.", {"request_id": "rid-1"})
    at = _run()
    at.button[0].click().run()
    assert any("AI 응답이 늦습니다" in e.value for e in at.error)
    assert "rid-1" in _texts(at)


def test_analysis_frontend_needs_reanalysis(ui_fake):
    ui_fake.latest = _analysis(needs_reanalysis=True)
    at = _run()
    assert any("메모가 바뀌었습니다" in w.value for w in at.warning)
    assert [b.label for b in at.button] == ["✨ 다시 분석"] and not at.button[0].disabled


def test_analysis_frontend_network_error(ui_fake):
    from core.api import ApiError

    ui_fake.latest = ApiError(0, "NETWORK_ERROR", "연결 실패")
    at = _run()
    assert any("서버에 연결할 수 없습니다" in w.value for w in at.warning)
    assert at.button == []
