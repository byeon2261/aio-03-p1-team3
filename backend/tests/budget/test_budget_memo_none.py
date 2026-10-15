"""I2: 사용자가 금액을 '메모에 없음'(action set + null)으로 고치면 예산 판정은 '판단 불가'다(0으로 보지 않음)."""

from __future__ import annotations

from app.features.budget.service import evaluate, listing_values
from tests.budget.budget_helpers import correct, make_analysis, make_listing, make_session

BUDGET = {"deposit_max_manwon": 1000, "monthly_max_manwon": 60}


def test_budget_memo_none_override_is_unknown_and_revert_restores(make_user, memory_db):
    alice = make_user()
    listing = make_listing(memory_db, make_session(memory_db, alice))
    analysis = make_analysis(memory_db, listing)                 # 500 / 45 / 7 → 예산 안
    assert evaluate(listing_values(memory_db, listing["id"]), BUDGET).status == "within"

    correct(memory_db, alice, analysis, "maintenance_fee_manwon", None, action="set")   # 메모에 없음
    values = listing_values(memory_db, listing["id"])
    assert "maintenance_fee_manwon" in values and values["maintenance_fee_manwon"] is None
    ev = evaluate(values, BUDGET)
    assert ev.status == "unknown" and "관리비" in ev.reason

    correct(memory_db, alice, analysis, "maintenance_fee_manwon", None, action="revert")  # AI 값으로 되돌림
    assert evaluate(listing_values(memory_db, listing["id"]), BUDGET).status == "within"
