"""예산 화면 부품. st를 쓰지 않는 순수 함수만 둔다(테스트하기 쉽게)."""

from __future__ import annotations

NO_LIMIT = "제한 없음"


def has_budget(budget: dict | None) -> bool:
    """상한이 하나라도 있으면 True."""
    b = budget or {}
    return b.get("deposit_max_manwon") is not None or b.get("monthly_max_manwon") is not None


def fmt_cap(v: int | None) -> str:
    """상한 표시. None은 '제한 없음'(매물 금액의 '미기재'와 구분한다)."""
    return NO_LIMIT if v is None else f"{int(v):,}만원"


def budget_summary(budget: dict | None) -> str:
    b = budget or {}
    return (f"보증금 상한 {fmt_cap(b.get('deposit_max_manwon'))} · "
            f"월 고정비 상한 {fmt_cap(b.get('monthly_max_manwon'))} (월세+관리비)")


def budget_body(deposit: int | float | None, monthly: int | float | None) -> dict:
    """PUT 본문. 빈 칸은 null(제한 없음)."""
    return {
        "deposit_max_manwon": None if deposit is None else int(deposit),
        "monthly_max_manwon": None if monthly is None else int(monthly),
    }
