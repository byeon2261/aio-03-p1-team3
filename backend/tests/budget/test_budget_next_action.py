"""예산 필터 숨김 안내: 다음 행동 문구(service.next_action)와 판정 불변 확인."""

from __future__ import annotations

import pytest

from app.features.budget import service

CAPS = {"deposit_max_manwon": 1000, "monthly_max_manwon": 55}   # 배포 앱 테스트 세션의 예산


def vals(deposit=500, rent=38, fee=7) -> dict:
    return {"deposit_manwon": deposit, "monthly_rent_manwon": rent, "maintenance_fee_manwon": fee}


def action(values, budget=CAPS) -> str | None:
    return service.next_action(values, budget, service.evaluate(values, budget))


# ---------------------------------------------------------------- 2번 집 사례
def test_house2_fee_missing_shows_room_left():
    """월세 38, 관리비 미기재, 월 고정비 상한 55 → 관리비 17만원 이하면 예산 안."""
    values = vals(rent=38, fee=None)
    ev = service.evaluate(values, CAPS)
    assert (ev.status, ev.reason, ev.missing) == ("unknown", "관리비 미기재", ("관리비",))
    assert service.next_action(values, CAPS, ev) == "관리비 17만원 이하면 예산 안"


def test_fee_missing_rent_equals_cap():
    assert action(vals(rent=55, fee=None)) == "관리비가 없어야 예산 안"


def test_fee_missing_rent_over_cap_stays_over_without_action():
    values = vals(rent=60, fee=None)
    assert service.evaluate(values, CAPS).status == "over"
    assert action(values) is None


# ---------------------------------------------------------------- 그 밖의 문구
def test_no_analysis_asks_to_run_ai():
    assert action({}) == "AI 정리를 실행하세요"
    assert action(None) == "AI 정리를 실행하세요"


@pytest.mark.parametrize(("values", "expected"), [
    (vals(deposit=None), "보증금을 확인하세요"),
    (vals(rent=None), "월세를 확인하세요"),
    (vals(rent=None, fee=None), "월세·관리비를 확인하세요"),
    (vals(deposit=None, rent=None), "보증금을 확인하세요 · 월세를 확인하세요"),
    (vals(deposit=None, fee=None), "보증금을 확인하세요 · 관리비는 17만원 이하여야 합니다"),
    (vals(deposit=None, rent=55, fee=None), "보증금을 확인하세요 · 관리비가 없어야 합니다"),
    (vals(deposit=None, rent=None, fee=None), "보증금을 확인하세요 · 월세·관리비를 확인하세요"),
])
def test_missing_combinations(values, expected):
    assert action(values) == expected


def test_only_caps_that_exist_are_asked():
    """해당 상한이 없으면 그 값은 묻지 않는다."""
    monthly_only = {"deposit_max_manwon": None, "monthly_max_manwon": 55}
    deposit_only = {"deposit_max_manwon": 1000, "monthly_max_manwon": None}
    assert service.evaluate(vals(deposit=None), monthly_only).status == "within"
    assert action(vals(deposit=None, fee=None), monthly_only) == "관리비 17만원 이하면 예산 안"
    assert service.evaluate(vals(rent=None, fee=None), deposit_only).status == "within"
    assert action(vals(deposit=None, rent=None, fee=None), deposit_only) == "보증금을 확인하세요"


def test_within_and_over_have_no_action():
    assert action(vals()) is None                    # 38 + 7 = 45 ≤ 55
    assert action(vals(deposit=1500)) is None        # over
    assert service.next_action(vals(), None, service.evaluate(vals(), None)) is None   # 예산 미설정


# ---------------------------------------------------------------- 판정 불변
def test_evaluation_status_and_reason_unchanged_by_missing_field():
    """missing은 안내용으로만 붙고, status·reason은 기존 그대로다. 미기재를 0으로 채우지 않는다."""
    ev = service.evaluate(vals(deposit=None, rent=None, fee=None), CAPS)
    assert (ev.status, ev.reason) == ("unknown", "보증금·월세·관리비 미기재")
    assert ev.missing == ("보증금", "월세", "관리비")
    assert service.evaluate(vals(fee=None), CAPS).status == "unknown"   # 38 + 0 = 38이어도 within이 아님
    for ev in (service.evaluate(vals(), CAPS), service.evaluate(vals(deposit=2000), CAPS),
               service.evaluate({}, CAPS), service.evaluate(vals(), None)):
        assert ev.missing == ()
