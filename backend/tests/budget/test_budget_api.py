"""GET·PUT /sessions/{session_id}/budget 테스트."""

from __future__ import annotations

import datetime as dt
import uuid

from tests.budget.budget_helpers import correct, make_analysis, make_listing, make_session, set_budget


def test_budget_get_unset_returns_nulls(client_as, make_user, memory_db):
    alice = make_user()
    s = make_session(memory_db, alice)
    r = client_as(alice).get(f"/sessions/{s['id']}/budget")
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == s["id"]
    assert body["deposit_max_manwon"] is None and body["monthly_max_manwon"] is None
    assert body["updated_at"] is None


def test_budget_put_then_get(client_as, make_user, memory_db):
    alice = make_user()
    s = make_session(memory_db, alice)
    c = client_as(alice)
    r = c.put(f"/sessions/{s['id']}/budget", json={"deposit_max_manwon": 1000, "monthly_max_manwon": 60})
    assert r.status_code == 200
    assert r.json()["deposit_max_manwon"] == 1000 and r.json()["updated_at"] is not None
    got = c.get(f"/sessions/{s['id']}/budget").json()
    assert (got["deposit_max_manwon"], got["monthly_max_manwon"]) == (1000, 60)


def test_budget_put_updates_existing_and_can_clear(client_as, make_user, memory_db):
    alice = make_user()
    s = make_session(memory_db, alice)
    c = client_as(alice)
    first = c.put(f"/sessions/{s['id']}/budget", json={"deposit_max_manwon": 1000, "monthly_max_manwon": 60}).json()
    r = c.put(f"/sessions/{s['id']}/budget", json={"monthly_max_manwon": 70})   # 보증금은 보내지 않음 → 비움
    assert r.status_code == 200
    assert r.json()["deposit_max_manwon"] is None and r.json()["monthly_max_manwon"] == 70
    assert dt.datetime.fromisoformat(r.json()["updated_at"]) >= dt.datetime.fromisoformat(first["updated_at"])
    r = c.put(f"/sessions/{s['id']}/budget", json={"deposit_max_manwon": None, "monthly_max_manwon": None})
    assert r.json()["deposit_max_manwon"] is None and r.json()["monthly_max_manwon"] is None
    assert len(memory_db.select("session_budgets", {"session_id": s["id"]})) == 1


def test_budget_zero_is_allowed(client_as, make_user, memory_db):
    alice = make_user()
    s = make_session(memory_db, alice)
    r = client_as(alice).put(f"/sessions/{s['id']}/budget", json={"deposit_max_manwon": 0, "monthly_max_manwon": 0})
    assert r.status_code == 200 and r.json()["deposit_max_manwon"] == 0


def test_budget_negative_is_422(client_as, make_user, memory_db):
    alice = make_user()
    s = make_session(memory_db, alice)
    c = client_as(alice)
    for body in ({"deposit_max_manwon": -1}, {"monthly_max_manwon": -5}):
        r = c.put(f"/sessions/{s['id']}/budget", json=body)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert memory_db.select("session_budgets") == []


def test_budget_other_users_session_is_404(client_as, make_user, memory_db):
    alice, bob = make_user(), make_user()
    s = make_session(memory_db, bob)
    c = client_as(alice)
    r = c.get(f"/sessions/{s['id']}/budget")
    assert r.status_code == 404 and r.json()["error"]["code"] == "SESSION_NOT_FOUND"
    r = c.put(f"/sessions/{s['id']}/budget", json={"deposit_max_manwon": 1})
    assert r.status_code == 404 and r.json()["error"]["code"] == "SESSION_NOT_FOUND"
    assert memory_db.select("session_budgets") == []


def test_budget_unknown_or_bad_session_id_is_404(client_as, make_user):
    c = client_as(make_user())
    assert c.get(f"/sessions/{uuid.uuid4()}/budget").status_code == 404
    assert c.get("/sessions/not-a-uuid/budget").status_code == 404


def test_budget_requires_login(client_as, make_user, memory_db):
    alice = make_user()
    s = make_session(memory_db, alice)
    assert client_as(None).get(f"/sessions/{s['id']}/budget").status_code == 401


def test_budget_deleted_with_session(client_as, make_user, memory_db):
    alice = make_user()
    s = make_session(memory_db, alice)
    client_as(alice).put(f"/sessions/{s['id']}/budget", json={"deposit_max_manwon": 1000})
    memory_db.delete("tour_sessions", {"id": s["id"]})   # CASCADE
    assert memory_db.select("session_budgets") == []


# ---------------------------------------------------------------- GET /sessions/{id}/budget/evaluations
def _five_houses(db, user):
    """배포 앱 테스트와 같은 구성: 예산 안 1, 판단 불가 2(관리비 미기재·분석 전), 예산 초과 2."""
    s = make_session(db, user)
    set_budget(db, s, deposit=1000, monthly=55)
    ls = [make_listing(db, s, memo=f"{i}번 메모") for i in range(1, 6)]
    make_analysis(db, ls[0], deposit_manwon=500, monthly_rent_manwon=40, maintenance_fee_manwon=5)
    make_analysis(db, ls[1], deposit_manwon=500, monthly_rent_manwon=38, maintenance_fee_manwon=None)
    # ls[2]: 분석 전
    make_analysis(db, ls[3], deposit_manwon=2000)
    make_analysis(db, ls[4], monthly_rent_manwon=50, maintenance_fee_manwon=10)
    return s, ls


def test_budget_evaluations_counts_and_next_actions(client_as, make_user, memory_db):
    alice = make_user()
    s, ls = _five_houses(memory_db, alice)
    r = client_as(alice).get(f"/sessions/{s['id']}/budget/evaluations")
    assert r.status_code == 200
    body = r.json()
    assert body["budget_set"] is True
    assert body["counts"] == {"within": 1, "over": 2, "unknown": 2}
    items = body["items"]
    assert [it["label"] for it in items] == ["1번 집", "2번 집", "3번 집", "4번 집", "5번 집"]
    assert [it["status"] for it in items] == ["within", "unknown", "unknown", "over", "over"]
    house2 = items[1]
    assert house2["listing_id"] == ls[1]["id"]
    assert (house2["status_label"], house2["reason"], house2["missing"]) == ("판단 불가", "관리비 미기재", ["관리비"])
    assert house2["next_action"] == "관리비 17만원 이하면 예산 안"
    assert (items[2]["reason"], items[2]["next_action"]) == ("분석 결과 없음", "AI 정리를 실행하세요")
    assert items[0]["next_action"] is None and items[3]["next_action"] is None


def test_budget_evaluations_match_comparison_filter(client_as, make_user, memory_db):
    """숨김 개수는 비교표 within_budget 필터가 숨긴 수와 같다(판정이 같다)."""
    alice = make_user()
    s, _ = _five_houses(memory_db, alice)
    c = client_as(alice)
    counts = c.get(f"/sessions/{s['id']}/budget/evaluations").json()["counts"]
    cmp = c.get(f"/sessions/{s['id']}/comparison", params={"filters": "within_budget"}).json()
    assert cmp["hidden_count"]["within_budget"] == counts["over"] + counts["unknown"] == 4
    assert len(cmp["rows"]) == counts["within"] == 1


def test_budget_evaluations_uses_user_correction(client_as, make_user, memory_db):
    """사용자가 관리비를 고치면 그 값으로 판정한다."""
    alice = make_user()
    s, ls = _five_houses(memory_db, alice)
    a = memory_db.select("analyses", {"listing_id": ls[1]["id"]})[0]
    correct(memory_db, alice, a, "maintenance_fee_manwon", 10, action="set")
    house2 = client_as(alice).get(f"/sessions/{s['id']}/budget/evaluations").json()["items"][1]
    assert (house2["status"], house2["next_action"]) == ("within", None)


def test_budget_evaluations_without_budget(client_as, make_user, memory_db):
    alice = make_user()
    s = make_session(memory_db, alice)
    make_analysis(memory_db, make_listing(memory_db, s))
    body = client_as(alice).get(f"/sessions/{s['id']}/budget/evaluations").json()
    assert body["budget_set"] is False
    assert body["counts"] == {"within": 0, "over": 0, "unknown": 0}
    assert body["items"][0]["status"] is None and body["items"][0]["reason"] == "예산 미설정"


def test_budget_evaluations_other_users_session_is_404(client_as, make_user, memory_db):
    alice, bob = make_user(), make_user()
    s = make_session(memory_db, bob)
    r = client_as(alice).get(f"/sessions/{s['id']}/budget/evaluations")
    assert r.status_code == 404 and r.json()["error"]["code"] == "SESSION_NOT_FOUND"
    assert client_as(None).get(f"/sessions/{s['id']}/budget/evaluations").status_code == 401
