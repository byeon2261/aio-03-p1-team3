"""비교표 열 제공자(budget)와 행 필터(within_budget) 테스트."""

from __future__ import annotations

from app.core.registry import get_column_providers, get_row_filter
from tests.budget.budget_helpers import load_hooks, make_listing, make_session, row, set_budget


def _setup(memory_db, make_user, deposit=1000, monthly=60):
    alice = make_user()
    session = make_session(memory_db, alice)
    if deposit is not None or monthly is not None:
        set_budget(memory_db, session, deposit, monthly)
    ls = [make_listing(memory_db, session) for _ in range(4)]
    rows = [
        row(ls[0], {"deposit_manwon": 500, "monthly_rent_manwon": 45, "maintenance_fee_manwon": 7}),   # within
        row(ls[1], {"deposit_manwon": 2000, "monthly_rent_manwon": 45, "maintenance_fee_manwon": 7}),  # over
        row(ls[2], {"deposit_manwon": 500, "monthly_rent_manwon": 55, "maintenance_fee_manwon": None}),  # unknown
        row(ls[3], {}, status="none"),                                                                  # 분석 없음
    ]
    return alice, session, ls, rows


def test_budget_hooks_registered_on_app_start(client_as, make_user):
    client_as(make_user())   # create_app()이 hooks.py를 읽는다
    providers = {p.key: p for p in get_column_providers()}
    assert "budget" in providers and providers["budget"].title == "예산"
    assert get_row_filter("within_budget") is not None


def test_budget_hooks_reload_is_safe():
    load_hooks()
    load_hooks()
    assert [p.key for p in get_column_providers()].count("budget") == 1


def test_budget_column_values_and_tones(memory_db, make_user):
    load_hooks()
    alice, session, ls, rows = _setup(memory_db, make_user)
    provider = next(p for p in get_column_providers() if p.key == "budget")
    out = provider.compute(db=memory_db, user=alice, session=session, rows=rows)
    assert set(out) == {l["id"] for l in ls}
    assert (out[ls[0]["id"]].status, out[ls[0]["id"]].tone) == ("within", "good")
    assert (out[ls[1]["id"]].status, out[ls[1]["id"]].tone) == ("over", "bad")
    assert (out[ls[2]["id"]].status, out[ls[2]["id"]].tone) == ("unknown", "muted")
    assert (out[ls[3]["id"]].status, out[ls[3]["id"]].tone) == ("unknown", "muted")
    assert "예산 초과" in out[ls[1]["id"]].display
    assert "판단 불가" in out[ls[2]["id"]].display


def test_budget_row_filter_keeps_only_within(memory_db, make_user):
    load_hooks()
    alice, session, ls, rows = _setup(memory_db, make_user)
    keep = get_row_filter("within_budget")(db=memory_db, user=alice, session=session, rows=rows)
    assert keep == {ls[0]["id"]}


def test_budget_column_without_budget_is_not_judged(memory_db, make_user):
    load_hooks()
    alice, session, ls, rows = _setup(memory_db, make_user, deposit=None, monthly=None)
    provider = next(p for p in get_column_providers() if p.key == "budget")
    out = provider.compute(db=memory_db, user=alice, session=session, rows=rows)
    assert all(v.status is None for v in out.values())
    assert get_row_filter("within_budget")(db=memory_db, user=alice, session=session, rows=rows) == set()
