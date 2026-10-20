"""세션 상세 화면의 요약 숫자·매물 카드 내용(Streamlit 함수를 부르지 않는 순수 함수).

데이터는 화면이 이미 부르는 두 응답만 쓴다.
    listings    GET /sessions/{id}/listings  (ListingOut 목록)
    comparison  GET /sessions/{id}/comparison 의 rows (ComparisonRow: values = 분석 값, columns["budget"] = 예산 판정)
비교표 응답이 없으면(None) 숫자·예산 칩 없이 매물 목록만으로 그린다.
"""

from __future__ import annotations

from typing import Any

from core.ui import fmt_manwon

NO_VALUE = "—"
MAX_CHIPS = 3        # 카드 한 장에 보이는 칩 수. 넘치면 회색 '+N'

# latest_analysis_status → 칩
ANALYSIS_CHIPS = {
    "success": ":green-badge[분석 완료]",
    "none": ":gray-badge[분석 전]",
    "failed": ":red-badge[분석 실패]",
}
REANALYSIS_CHIP = ":orange-badge[재분석 필요]"
# 예산 판정(ComparisonRow.columns["budget"].status) → 칩. None(예산 미설정)은 칩 없음
BUDGET_CHIPS = {
    "within": ":green-badge[예산 안]",
    "over": ":red-badge[예산 초과]",
    "unknown": ":gray-badge[판단 불가]",
}
INFO_KEYS = ("transit", "floor", "direction")


def rows_by_listing(comparison: dict | None) -> dict[str, dict]:
    """{listing_id: ComparisonRow}. 응답이 없으면 빈 dict."""
    if not comparison:
        return {}
    return {str(r.get("listing_id")): r for r in comparison.get("rows") or []}


def _values(row: dict | None) -> dict:
    return (row or {}).get("values") or {}


def budget_status(row: dict | None) -> str | None:
    return (((row or {}).get("columns") or {}).get("budget") or {}).get("status")


def _int(v: Any) -> int | None:
    try:
        return int(v) if v is not None and not isinstance(v, bool) else None
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ 요약 숫자
def summary_metrics(listings: list[dict], comparison: dict | None) -> list[dict]:
    """맨 위 요약 카드 4개: [{"label", "icon", "tone", "value", "help"}] (아이콘은 Material 이름, 색은 core/ui.TONES).

    본 집      매물 수
    예산 안    예산 판정이 '예산 안'인 매물 수. 예산을 안 정했거나 판정이 없으면(매물 1곳 등) —
    확인 필요  매물별 '추가 확인 항목'(확인 못함·애매함·언급 없음) 수의 합. 분석된 매물이 없으면 —
    최저 월 고정비  월세 + 관리비가 계산된 매물 중 최솟값. 없으면 —
    """
    rows = list(rows_by_listing(comparison).values())
    judged = [s for s in (budget_status(r) for r in rows) if s]
    analyzed = [_values(r) for r in rows if _values(r)]
    costs = [c for c in (_int(v.get("monthly_cost_manwon")) for v in analyzed) if c is not None]
    checks = sum(len(v.get("followup_checks") or []) for v in analyzed)
    return [
        {"label": "본 집", "icon": "home", "tone": "blue", "value": f"{len(listings)}곳", "help": "이 세션에 저장한 매물 수입니다."},
        {"label": "예산 안", "icon": "check_circle", "tone": "green", "value": f"{judged.count('within')}곳" if judged else NO_VALUE,
         "help": "예산 판정이 '예산 안'인 매물 수입니다. 예산을 정하고 매물이 2곳 이상이면 보입니다."},
        {"label": "확인 필요", "icon": "error", "tone": "orange", "value": f"{checks}건" if analyzed else NO_VALUE,
         "help": "AI가 메모에서 확인하지 못했거나 애매하다고 본 항목 수의 합입니다. 집주인에게 꼭 물어보세요."},
        {"label": "최저 월 고정비", "icon": "savings", "tone": "blue", "value": fmt_manwon(min(costs)) if costs else NO_VALUE,
         "help": "월 고정비 = 월세 + 관리비. 관리비가 미기재인 매물은 빠집니다."},
    ]


# ------------------------------------------------------------------ 매물 카드
def preview(text: str, n: int = 60) -> str:
    one_line = " ".join((text or "").split())
    return one_line if len(one_line) <= n else one_line[:n] + "…"


def info_line(listing: dict, row: dict | None) -> str:
    """교통 · 층수 · 방향(분석 값). 하나도 없으면 메모 첫 줄."""
    vals = _values(row)
    parts = [str(vals[k]).strip() for k in INFO_KEYS if vals.get(k) not in (None, "") and str(vals[k]).strip()]
    return " · ".join(parts) if parts else preview(listing.get("memo_text", ""))


def chips(listing: dict, row: dict | None) -> list[str]:
    """상태 칩(마크다운 배지, 이모지 없음). 순서: 분석 상태 → 재분석 필요 → 예산 판정 → 추가 확인 항목.

    최대 MAX_CHIPS개만 보이고 나머지는 회색 "+N" 한 개로 묶는다.
    """
    out = [ANALYSIS_CHIPS.get(listing.get("latest_analysis_status") or "none", ANALYSIS_CHIPS["none"])]
    if listing.get("needs_reanalysis"):
        out.append(REANALYSIS_CHIP)
    budget = BUDGET_CHIPS.get(budget_status(row) or "")
    if budget:
        out.append(budget)
    out += [f":blue-badge[{c} 확인]" for c in (str(c) for c in _values(row).get("followup_checks") or [])]
    if len(out) > MAX_CHIPS:
        out = out[:MAX_CHIPS] + [f":gray-badge[+{len(out) - MAX_CHIPS}]"]
    return out


def price_lines(row: dict | None) -> tuple[str, str] | None:
    """오른쪽 핵심 숫자(월 고정비)와 아래 줄: ("월 52만원", "보증금 1,000만원").

    관리비 미기재면 월세만 보여 주고 "+?"를 붙인다: ("월 38만원+?", "관리비 미기재 · 보증금 500만원").
    분석 값이 없으면(분석 전·실패) None.
    """
    vals = _values(row)
    if not vals:
        return None
    cost, rent = _int(vals.get("monthly_cost_manwon")), _int(vals.get("monthly_rent_manwon"))
    deposit = f"보증금 {fmt_manwon(_int(vals.get('deposit_manwon')))}"
    if cost is not None:
        return f"월 {fmt_manwon(cost)}", deposit
    if rent is not None:
        return f"월 {fmt_manwon(rent)}+?", f"관리비 미기재 · {deposit}"
    return "월세 미기재", deposit
