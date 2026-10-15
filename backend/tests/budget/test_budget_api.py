"""GET·PUT /sessions/{session_id}/budget 테스트."""

from __future__ import annotations

import datetime as dt
import uuid

from tests.budget.budget_helpers import make_session


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
