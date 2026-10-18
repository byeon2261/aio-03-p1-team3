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


# ------------------------------------------------------------------ 예산 필터로 숨긴 매물 안내
def hidden_summary(data: dict | None) -> str | None:
    """BudgetEvaluationsOut → "예산 초과 2건 · 판단 불가 2건 숨김". 0건인 사유는 빼고, 숨긴 매물이 없으면 None."""
    counts = (data or {}).get("counts") or {}
    parts = []
    if int(counts.get("over") or 0) > 0:
        parts.append(f"예산 초과 {int(counts['over'])}건")
    if int(counts.get("unknown") or 0) > 0:
        parts.append(f"판단 불가 {int(counts['unknown'])}건")
    return " · ".join(parts) + " 숨김" if parts else None


def unknown_items(data: dict | None) -> list[dict]:
    """판단 불가 매물만(서버가 준 listing_no 순서 그대로)."""
    return [it for it in (data or {}).get("items") or [] if it.get("status") == "unknown"]


def unknown_line(item: dict) -> str:
    """판단 불가 매물 한 줄: 매물 이름 · 사유 · 다음 행동."""
    parts = [f"**{item.get('label', '')}**", item.get("reason") or "", item.get("next_action") or ""]
    return " · ".join(p for p in parts if p)
