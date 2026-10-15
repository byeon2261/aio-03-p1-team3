"""예산 판정(service.evaluate) 테스트."""

from __future__ import annotations

import pytest

from app.core.schemas import BudgetIn
from app.features.budget import service
from tests.budget.budget_helpers import correct, make_analysis, make_listing, make_session

BOTH = {"deposit_max_manwon": 1000, "monthly_max_manwon": 60}


def vals(deposit=500, rent=45, fee=7) -> dict:
    return {"deposit_manwon": deposit, "monthly_rent_manwon": rent, "maintenance_fee_manwon": fee}


# ---------------------------------------------------------------- 판정 3종
def test_budget_within():
    ev = service.evaluate(vals(), BOTH)
    assert ev.status == "within"


def test_budget_within_at_exact_limit():
    ev = service.evaluate(vals(deposit=1000, rent=50, fee=10), BOTH)
    assert ev.status == "within"


def test_budget_over_deposit():
    ev = service.evaluate(vals(deposit=1500), BOTH)
    assert ev.status == "over" and "보증금" in ev.reason


def test_budget_over_monthly_cost_rent_plus_fee():
    ev = service.evaluate(vals(rent=55, fee=10), BOTH)   # 65 > 60
    assert ev.status == "over" and "월 고정비" in ev.reason


def test_budget_over_both_items_listed_in_reason():
    ev = service.evaluate(vals(deposit=2000, rent=55, fee=10), BOTH)
    assert ev.status == "over" and "보증금" in ev.reason and "월 고정비" in ev.reason


def test_budget_unknown_when_deposit_missing():
    ev = service.evaluate(vals(deposit=None), BOTH)
    assert ev.status == "unknown" and "보증금" in ev.reason


def test_budget_unknown_when_rent_missing():
    ev = service.evaluate(vals(rent=None), BOTH)
    assert ev.status == "unknown" and "월세" in ev.reason


def test_budget_unknown_without_analysis():
    assert service.evaluate({}, BOTH).status == "unknown"
    assert service.evaluate(None, BOTH).status == "unknown"


# ---------------------------------------------------------------- 확실한 초과가 미기재보다 앞선다
def test_budget_over_deposit_even_if_rent_missing():
    ev = service.evaluate(vals(deposit=1500, rent=None), BOTH)
    assert ev.status == "over" and "보증금" in ev.reason


def test_budget_over_by_rent_alone_when_fee_missing():
    ev = service.evaluate(vals(rent=65, fee=None), BOTH)   # 관리비를 몰라도 65 > 60
    assert ev.status == "over" and "월세" in ev.reason


def test_budget_unknown_when_not_over_and_fee_missing():
    ev = service.evaluate(vals(rent=55, fee=None), BOTH)   # 관리비가 6 이상이면 넘을 수 있다
    assert ev.status == "unknown" and "관리비" in ev.reason


def test_budget_rent_equal_to_limit_with_fee_missing_is_unknown():
    ev = service.evaluate(vals(rent=60, fee=None), BOTH)   # 관리비 0이면 안, 1 이상이면 초과
    assert ev.status == "unknown"


def test_budget_missing_fee_is_not_treated_as_zero():
    ev = service.evaluate(vals(rent=10, fee=None), {"monthly_max_manwon": 60})
    assert ev.status != "within"


def test_budget_zero_fee_is_a_real_value():
    ev = service.evaluate(vals(rent=60, fee=0), BOTH)
    assert ev.status == "within"


# ---------------------------------------------------------------- 상한 한쪽만·둘 다 미설정
def test_budget_only_deposit_cap_ignores_monthly_values():
    budget = {"deposit_max_manwon": 1000, "monthly_max_manwon": None}
    assert service.evaluate(vals(rent=None, fee=None), budget).status == "within"
    assert service.evaluate(vals(rent=999, fee=999), budget).status == "within"
    assert service.evaluate(vals(deposit=1001), budget).status == "over"
    assert service.evaluate(vals(deposit=None), budget).status == "unknown"


def test_budget_only_monthly_cap_ignores_deposit():
    budget = {"deposit_max_manwon": None, "monthly_max_manwon": 60}
    assert service.evaluate(vals(deposit=None), budget).status == "within"
    assert service.evaluate(vals(deposit=99999), budget).status == "within"
    assert service.evaluate(vals(rent=60, fee=1), budget).status == "over"


@pytest.mark.parametrize("budget", [None, {}, {"deposit_max_manwon": None, "monthly_max_manwon": None}])
def test_budget_no_caps_means_no_judgement(budget):
    ev = service.evaluate(vals(deposit=99999), budget)
    assert ev.status is None


def test_budget_accepts_pydantic_budget():
    assert service.evaluate(vals(deposit=1500), BudgetIn(deposit_max_manwon=1000)).status == "over"


# ---------------------------------------------------------------- 사용자 수정값
def test_budget_user_correction_changes_result(memory_db, make_user):
    alice = make_user()
    session = make_session(memory_db, alice)
    listing = make_listing(memory_db, session)
    analysis = make_analysis(memory_db, listing, monthly_rent_manwon=70, maintenance_fee_manwon=5)
    budget = {"monthly_max_manwon": 60}

    assert service.evaluate(service.listing_values(memory_db, listing["id"]), budget).status == "over"

    correct(memory_db, alice, analysis, "monthly_rent_manwon", 50)       # AI가 잘못 읽은 월세를 고침
    assert service.evaluate(service.listing_values(memory_db, listing["id"]), budget).status == "within"

    correct(memory_db, alice, analysis, "maintenance_fee_manwon", None)  # 수정 취소 → AI 값(5) 복귀
    correct(memory_db, alice, analysis, "deposit_manwon", 300)
    assert service.evaluate(service.listing_values(memory_db, listing["id"]), budget).status == "within"


def test_budget_user_correction_fills_missing_fee(memory_db, make_user):
    alice = make_user()
    session = make_session(memory_db, alice)
    listing = make_listing(memory_db, session)
    analysis = make_analysis(memory_db, listing, monthly_rent_manwon=50, maintenance_fee_manwon=None)
    budget = {"monthly_max_manwon": 60}
    assert service.evaluate(service.listing_values(memory_db, listing["id"]), budget).status == "unknown"
    # 사용자가 미기재 관리비를 채우면 판정이 바뀐다
    correct(memory_db, alice, analysis, "maintenance_fee_manwon", 15)
    assert service.evaluate(service.listing_values(memory_db, listing["id"]), budget).status == "over"
    correct(memory_db, alice, analysis, "maintenance_fee_manwon", 0)
    assert service.evaluate(service.listing_values(memory_db, listing["id"]), budget).status == "within"


def test_budget_listing_without_analysis_has_empty_values(memory_db, make_user):
    alice = make_user()
    listing = make_listing(memory_db, make_session(memory_db, alice))
    assert service.listing_values(memory_db, listing["id"]) == {}
