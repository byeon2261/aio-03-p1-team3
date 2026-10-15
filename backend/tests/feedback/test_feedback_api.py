"""F7 AI 결과 수정·피드백: POST /analyses/{analysis_id}/feedback"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.repo import field_overrides, latest_rating
from app.features.feedback.schemas import FeedbackCreateIn
from tests.comparison.seed import add_failed, add_override, add_success, make_listing, make_session

REASONS = ["amount", "not_in_memo", "missing_info", "pros_cons", "check_error", "other"]


def _analysis(db, user):
    s = make_session(db, user)
    l1, l2 = make_listing(db, s, "a"), make_listing(db, s, "b")
    a1 = add_success(db, l1, monthly_rent_manwon=45)
    add_success(db, l2, monthly_rent_manwon=50)
    return s, l1, a1


def _post(client, aid, body):
    return client.post(f"/analyses/{aid}/feedback", json=body)


# ------------------------------------------------------------------ 저장·반영
def test_feedback_corrections_saved_and_reflected(client_as, make_user, memory_db):
    alice = make_user()
    s, l1, a1 = _analysis(memory_db, alice)
    original = memory_db.select("analyses", {"id": a1["id"]})[0]["result_json"]
    c = client_as(alice)
    r = _post(c, a1["id"], {
        "corrections": [{"field_name": "monthly_rent_manwon", "corrected_value": 40},
                        {"field_name": "pros", "corrected_value": ["역까지 3분"]},
                        {"field_name": "floor", "corrected_value": "4층"}],
        "rating": "down", "reason": "amount", "comment": "월세가 40이에요",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["field_name"] is None and body["rating"] == "down" and body["reason"] == "amount"
    assert len(body["items"]) == 4

    rows = memory_db.select("feedback", {"analysis_id": a1["id"]})
    assert sorted((x["field_name"] or "") for x in rows) == ["", "floor", "monthly_rent_manwon", "pros"]
    summary = [x for x in rows if x["field_name"] is None]
    assert len(summary) == 1 and summary[0]["corrected_value"] is None
    assert all(x["profile_id"] == alice.profile_id for x in rows)

    # 다시 조회하면 수정값 유지, AI 원본(result_json)은 그대로
    assert field_overrides(memory_db, a1["id"]) == {"monthly_rent_manwon": 40, "pros": ["역까지 3분"], "floor": "4층"}
    assert latest_rating(memory_db, a1["id"]) == "down"
    assert memory_db.select("analyses", {"id": a1["id"]})[0]["result_json"] == original
    comp = c.get(f"/sessions/{s['id']}/comparison").json()
    row = next(x for x in comp["rows"] if x["listing_id"] == l1["id"])
    assert row["values"]["monthly_rent_manwon"] == 40 and row["values"]["floor"] == "4층"
    assert comp["lowest"]["monthly_rent_manwon"] == [l1["id"]]


def test_feedback_revert_action_cancels_override(client_as, make_user, memory_db):
    """I2: 수정 취소는 action "revert"로 한다(null은 '메모에 없음'으로 뜻이 바뀌었다)."""
    alice = make_user()
    _, _, a1 = _analysis(memory_db, alice)
    c = client_as(alice)
    assert _post(c, a1["id"], {"corrections": [{"field_name": "deposit_manwon", "corrected_value": 300}]}).status_code == 200
    assert field_overrides(memory_db, a1["id"]) == {"deposit_manwon": 300}
    r = _post(c, a1["id"], {"corrections": [{"field_name": "deposit_manwon", "action": "revert"}]})
    assert r.status_code == 200
    assert r.json()["action"] == "revert" and r.json()["corrected_value"] is None
    assert field_overrides(memory_db, a1["id"]) == {}
    # 평가 행은 만들지 않았다
    assert memory_db.select("feedback", {"analysis_id": a1["id"], "field_name": ("is", None)}) == []


def test_feedback_rating_only_creates_one_summary_row(client_as, make_user, memory_db):
    alice = make_user()
    _, _, a1 = _analysis(memory_db, alice)
    r = _post(client_as(alice), a1["id"], {"rating": "up"})
    assert r.status_code == 200 and r.json()["rating"] == "up" and len(r.json()["items"]) == 1
    rows = memory_db.select("feedback", {"analysis_id": a1["id"]})
    assert len(rows) == 1 and rows[0]["field_name"] is None


def test_feedback_contract_single_field_shape_accepted(client_as, make_user, memory_db):
    alice = make_user()
    _, _, a1 = _analysis(memory_db, alice)
    r = _post(client_as(alice), a1["id"], {"field_name": "direction", "corrected_value": "동향"})
    assert r.status_code == 200
    assert r.json()["field_name"] == "direction" and r.json()["corrected_value"] == "동향"
    assert field_overrides(memory_db, a1["id"]) == {"direction": "동향"}


@pytest.mark.parametrize("reason", REASONS)
def test_feedback_six_reasons_saved(client_as, make_user, memory_db, reason):
    alice = make_user()
    _, _, a1 = _analysis(memory_db, alice)
    r = _post(client_as(alice), a1["id"], {"reason": reason})
    assert r.status_code == 200 and r.json()["reason"] == reason
    assert memory_db.select("feedback", {"analysis_id": a1["id"]})[0]["reason"] == reason


# ------------------------------------------------------------------ 거부
def _assert_422(r):
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("field_name", ["label", "unchecked", "missing_checks", "checks", "mixed_listings", "nope"])
def test_feedback_field_outside_editable_422(client_as, make_user, memory_db, field_name):
    alice = make_user()
    _, _, a1 = _analysis(memory_db, alice)
    _assert_422(_post(client_as(alice), a1["id"], {"corrections": [{"field_name": field_name, "corrected_value": "x"}]}))
    assert memory_db.select("feedback", {"analysis_id": a1["id"]}) == []


@pytest.mark.parametrize("field_name,value", [
    ("monthly_rent_manwon", "45"),        # 문자열 금액
    ("monthly_rent_manwon", 45.5),        # 실수
    ("deposit_manwon", True),             # 참거짓
    ("maintenance_fee_manwon", -1),       # 음수
    ("pros", "장점 하나"),                  # 목록 자리에 문자열
    ("cons", [1, 2]),                     # 문자열이 아닌 목록
    ("maintenance_includes", "수도"),      # 목록 자리에 문자열
    ("transit", 3),                       # 글 자리에 숫자
    ("floor", ["3층"]),                   # 글 자리에 목록
])
def test_feedback_wrong_type_422(client_as, make_user, memory_db, field_name, value):
    alice = make_user()
    _, _, a1 = _analysis(memory_db, alice)
    _assert_422(_post(client_as(alice), a1["id"], {"corrections": [{"field_name": field_name, "corrected_value": value}]}))
    assert memory_db.select("feedback", {"analysis_id": a1["id"]}) == []


def test_feedback_one_bad_correction_saves_nothing(client_as, make_user, memory_db):
    alice = make_user()
    _, _, a1 = _analysis(memory_db, alice)
    _assert_422(_post(client_as(alice), a1["id"], {
        "corrections": [{"field_name": "floor", "corrected_value": "4층"},
                        {"field_name": "deposit_manwon", "corrected_value": "300"}],
        "rating": "up"}))
    assert memory_db.select("feedback", {"analysis_id": a1["id"]}) == []


@pytest.mark.parametrize("body", [
    {},
    {"comment": "   "},
    {"corrections": []},
    {"reason": "bad_reason"},
    {"rating": "meh"},
    {"comment": "가" * 501},
    {"corrections": [{"field_name": "floor"}]},          # corrected_value 키 없음
    {"corrections": [{"field_name": "floor", "corrected_value": "3층"},
                     {"field_name": "floor", "corrected_value": "4층"}]},   # 같은 항목 두 번
])
def test_feedback_invalid_body_422(client_as, make_user, memory_db, body):
    alice = make_user()
    _, _, a1 = _analysis(memory_db, alice)
    _assert_422(_post(client_as(alice), a1["id"], body))


def test_feedback_other_users_analysis_404(client_as, make_user, memory_db):
    alice, bob = make_user(), make_user()
    _, _, a_bob = _analysis(memory_db, bob)
    r = _post(client_as(alice), a_bob["id"], {"rating": "up"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"
    assert memory_db.select("feedback", {"analysis_id": a_bob["id"]}) == []
    assert _post(client_as(alice), "not-a-uuid", {"rating": "up"}).status_code == 404


def test_feedback_requires_login(client_as, make_user, memory_db):
    _, _, a1 = _analysis(memory_db, make_user())
    assert _post(client_as(None), a1["id"], {"rating": "up"}).status_code == 401


def test_feedback_failed_analysis_rejects_corrections_but_accepts_rating(client_as, make_user, memory_db):
    alice = make_user()
    s = make_session(memory_db, alice)
    failed = add_failed(memory_db, make_listing(memory_db, s))
    c = client_as(alice)
    _assert_422(_post(c, failed["id"], {"corrections": [{"field_name": "floor", "corrected_value": "3층"}]}))
    assert _post(c, failed["id"], {"rating": "down", "reason": "other"}).status_code == 200


# ------------------------------------------------------------------ 모델 직접
def test_feedback_model_strict_types():
    ok = FeedbackCreateIn(corrections=[{"field_name": "monthly_rent_manwon", "corrected_value": 0},
                                       {"field_name": "cons", "corrected_value": []}])
    assert [(c.field_name, c.corrected_value) for c in ok.corrections] == [("monthly_rent_manwon", 0), ("cons", [])]
    with pytest.raises(ValidationError):
        FeedbackCreateIn(corrections=[{"field_name": "monthly_rent_manwon", "corrected_value": 45.0}])
    blank = FeedbackCreateIn(rating="up", comment="  ")
    assert blank.comment is None and blank.has_summary


# ------------------------------------------------------------------ I2: '메모에 없음'과 '수정 취소' 구분 (0008 action)
def test_feedback_null_with_set_marks_memo_none(client_as, make_user, memory_db):
    alice = make_user()
    s, l1, a1 = _analysis(memory_db, alice)
    c = client_as(alice)
    r = _post(c, a1["id"], {"corrections": [{"field_name": "monthly_rent_manwon", "corrected_value": None},
                                            {"field_name": "floor", "action": "set", "corrected_value": None}]})
    assert r.status_code == 200, r.text
    assert [(i["field_name"], i["action"], i["corrected_value"]) for i in r.json()["items"]] == [
        ("monthly_rent_manwon", "set", None), ("floor", "set", None)]
    rows = memory_db.select("feedback", {"analysis_id": a1["id"]}, order_by="created_at")
    assert [x["action"] for x in rows] == ["set", "set"]
    # 키가 남고 값이 None = 메모에 없음(수정 취소와 다르다)
    assert field_overrides(memory_db, a1["id"]) == {"monthly_rent_manwon": None, "floor": None}

    # 비교표: 미기재(None)이고 최저 월세 후보에서 빠진다(0으로 보지 않음)
    comp = c.get(f"/sessions/{s['id']}/comparison").json()
    row = next(x for x in comp["rows"] if x["listing_id"] == l1["id"])
    assert row["values"]["monthly_rent_manwon"] is None
    assert l1["id"] not in comp["lowest"]["monthly_rent_manwon"]

    # 되돌리면 AI 값(45)으로 돌아간다
    assert _post(c, a1["id"], {"corrections": [{"field_name": "monthly_rent_manwon", "action": "revert"}]}).status_code == 200
    assert field_overrides(memory_db, a1["id"]) == {"floor": None}


def test_feedback_single_field_shape_with_action(client_as, make_user, memory_db):
    alice = make_user()
    _, _, a1 = _analysis(memory_db, alice)
    c = client_as(alice)
    r = _post(c, a1["id"], {"field_name": "direction", "corrected_value": None})
    assert r.status_code == 200 and r.json()["action"] == "set"
    assert field_overrides(memory_db, a1["id"]) == {"direction": None}
    r = _post(c, a1["id"], {"field_name": "direction", "action": "revert"})
    assert r.status_code == 200 and r.json()["action"] == "revert"
    assert field_overrides(memory_db, a1["id"]) == {}


def test_feedback_summary_row_has_no_action(client_as, make_user, memory_db):
    alice = make_user()
    _, _, a1 = _analysis(memory_db, alice)
    r = _post(client_as(alice), a1["id"], {"rating": "up"})
    assert r.status_code == 200 and r.json()["action"] is None
    assert memory_db.select("feedback", {"analysis_id": a1["id"]})[0]["action"] is None


@pytest.mark.parametrize("body", [
    {"corrections": [{"field_name": "floor", "action": "revert", "corrected_value": "3층"}]},   # 되돌리며 값
    {"corrections": [{"field_name": "pros", "corrected_value": None}]},          # 목록은 null 대신 []
    {"corrections": [{"field_name": "floor", "action": "delete"}]},              # 모르는 동작
    {"corrections": [{"field_name": "floor", "action": "set"}]},                 # set인데 값 키 없음
    {"field_name": "floor"},                                                      # 한 필드 모양, 값 키 없음
    {"action": "revert", "rating": "up"},                                         # field_name 없이 action
])
def test_feedback_action_invalid_422(client_as, make_user, memory_db, body):
    alice = make_user()
    _, _, a1 = _analysis(memory_db, alice)
    _assert_422(_post(client_as(alice), a1["id"], body))
    assert memory_db.select("feedback", {"analysis_id": a1["id"]}) == []


def test_feedback_legacy_rows_without_action_keep_old_rule(make_user, memory_db):
    """0008 이전 행(action 없음): corrected_value null = 수정 취소. 새 행과 섞여도 최신 행 기준."""
    alice = make_user()
    _, _, a1 = _analysis(memory_db, alice)
    add_override(memory_db, alice, a1, "deposit_manwon", 300)
    add_override(memory_db, alice, a1, "deposit_manwon", None)                  # 옛 규칙: 수정 취소
    add_override(memory_db, alice, a1, "transit", "버스")
    add_override(memory_db, alice, a1, "transit", None, action="set")           # 새 규칙: 메모에 없음
    assert field_overrides(memory_db, a1["id"]) == {"transit": None}


def test_feedback_model_action_defaults_and_revert_value():
    m = FeedbackCreateIn(corrections=[{"field_name": "floor", "corrected_value": None},
                                      {"field_name": "transit", "action": "revert"}])
    assert [(c.field_name, c.action, c.corrected_value) for c in m.corrections] == [
        ("floor", "set", None), ("transit", "revert", None)]
