"""F11 예산: 저장·조회와 예산 판정.

판정 규칙 (evaluate)
    1) 두 상한이 모두 비어 있으면 판정하지 않는다 → status None.
    2) 초과를 먼저 본다(확실한 초과가 미기재보다 앞선다).
       - 보증금이 있고 상한을 넘으면 over.
       - 월세·관리비가 둘 다 있으면 monthly_cost(월세+관리비)로 비교.
       - 관리비가 미기재여도 월세만으로 월 상한을 넘으면 over(관리비는 0 이상).
    3) 초과가 없는데 판정할 항목에 필요한 값이 하나라도 미기재면 unknown.
    4) 모두 있고 상한 이내면 within. 미기재를 0원으로 더해 within을 만들지 않는다.
금액은 만원 단위 정수. None은 '미기재'이며 0으로 취급하지 않는다.

다음 행동 안내 (next_action) — 판정 결과를 바꾸지 않고, unknown 매물에 무엇을 하면 판정되는지만 알려 준다.
    - 분석 결과 없음 → "AI 정리를 실행하세요"
    - 관리비만 미기재(월세 ≤ 월 상한) → "관리비 n만원 이하면 예산 안"(n = 월 상한 − 월세), n=0이면 "관리비가 없어야 예산 안"
    - 보증금·월세 미기재 → "보증금을 확인하세요"·"월세를 확인하세요"(월세·관리비 둘 다면 "월세·관리비를 확인하세요")
    - 여러 값이 미기재면 " · "로 잇고, 관리비는 "관리비는 n만원 이하여야 합니다"(다른 값이 확인되기 전이라 '예산 안'이라 하지 않음)
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Literal

from app.core.db import UniqueViolation
from app.core.repo import field_overrides, latest_analysis, list_listings, listing_label
from app.core.schemas import BudgetIn, BudgetOut
from app.core.values import effective_values, monthly_cost

TABLE = "session_budgets"

Status = Literal["within", "over", "unknown"]

STATUS_LABELS: dict[str, str] = {"within": "예산 안", "over": "예산 초과", "unknown": "판단 불가"}


@dataclass(frozen=True)
class Evaluation:
    """판정 결과. status None은 '판정하지 않음(예산 미설정)'."""

    status: Status | None
    reason: str
    missing: tuple[str, ...] = ()   # unknown일 때 미기재 항목("보증금"·"월세"·"관리비"), 판정에는 쓰지 않는 안내용

    @property
    def label(self) -> str:
        return STATUS_LABELS.get(self.status or "", "-")


# ------------------------------------------------------------------ 저장·조회
def get_budget(db: Any, session_id: Any) -> dict | None:
    rows = db.select(TABLE, {"session_id": str(session_id)}, limit=1)
    return rows[0] if rows else None


def to_out(session_id: Any, row: dict | None) -> BudgetOut:
    if row is None:
        return BudgetOut(session_id=str(session_id))
    return BudgetOut(session_id=str(session_id), deposit_max_manwon=row.get("deposit_max_manwon"),
                     monthly_max_manwon=row.get("monthly_max_manwon"), updated_at=row.get("updated_at"))


def save_budget(db: Any, session_id: Any, body: BudgetIn) -> dict:
    """PUT은 통째로 바꾼다(보내지 않은 상한은 비움). 행이 없으면 만들고 있으면 고친다."""
    sid = str(session_id)
    values = {"deposit_max_manwon": body.deposit_max_manwon, "monthly_max_manwon": body.monthly_max_manwon}
    if get_budget(db, sid) is None:
        try:
            return db.insert(TABLE, {"session_id": sid, **values})[0]
        except UniqueViolation:
            pass  # 동시에 다른 요청이 먼저 만들었으면 고치기로 넘어간다
    # updated_at은 DB 기본값이 insert에만 걸리므로 고칠 때는 직접 넣는다
    rows = db.update(TABLE, {"session_id": sid}, {**values, "updated_at": dt.datetime.now(dt.timezone.utc)})
    return rows[0] if rows else (get_budget(db, sid) or {"session_id": sid, **values})


def has_caps(budget: Any) -> bool:
    """상한이 하나라도 있으면 True."""
    return _cap(budget, "deposit_max_manwon") is not None or _cap(budget, "monthly_max_manwon") is not None


# ------------------------------------------------------------------ 판정
def _cap(budget: Any, name: str) -> int | None:
    if budget is None:
        return None
    raw = budget.get(name) if isinstance(budget, dict) else getattr(budget, name, None)
    return _to_int(raw)


def _to_int(v: Any) -> int | None:
    """금액을 정수로. None·해석할 수 없는 값은 None(미기재)."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v) if v.is_integer() else None
    if isinstance(v, str):
        s = v.strip().replace(",", "")
        return int(s) if s.lstrip("-").isdigit() else None
    return None


def evaluate(values: dict | None, budget: Any) -> Evaluation:
    """매물 값(effective_values 결과)과 예산(dict·BudgetIn·BudgetOut)으로 판정한다."""
    dep_max = _cap(budget, "deposit_max_manwon")
    mon_max = _cap(budget, "monthly_max_manwon")
    if dep_max is None and mon_max is None:
        return Evaluation(None, "예산 미설정")
    if not values:
        return Evaluation("unknown", "분석 결과 없음")

    deposit = _to_int(values.get("deposit_manwon"))
    rent = _to_int(values.get("monthly_rent_manwon"))
    fee = _to_int(values.get("maintenance_fee_manwon"))

    over: list[str] = []
    missing: list[str] = []

    if dep_max is not None:
        if deposit is None:
            missing.append("보증금")
        elif deposit > dep_max:
            over.append("보증금 초과")

    if mon_max is not None:
        cost = monthly_cost({"monthly_rent_manwon": rent, "maintenance_fee_manwon": fee})
        if cost is not None:
            if cost > mon_max:
                over.append("월 고정비 초과")
        elif rent is not None and rent > mon_max:
            over.append("월세만으로 월 고정비 초과")
        else:
            if rent is None:
                missing.append("월세")
            if fee is None:
                missing.append("관리비")

    if over:
        return Evaluation("over", ", ".join(over))
    if missing:
        return Evaluation("unknown", f"{'·'.join(missing)} 미기재", tuple(missing))
    return Evaluation("within", "예산 안")


# ------------------------------------------------------------------ 다음 행동 안내
NO_ANALYSIS_ACTION = "AI 정리를 실행하세요"


def next_action(values: dict | None, budget: Any, ev: Evaluation) -> str | None:
    """unknown 매물이 판정되려면 무엇을 하면 되는지. unknown이 아니면 None. 값을 채워 넣지 않는다."""
    if ev.status != "unknown":
        return None
    if not values:
        return NO_ANALYSIS_ACTION
    missing = set(ev.missing)
    parts: list[str] = []
    if "보증금" in missing:
        parts.append("보증금을 확인하세요")
    if "월세" in missing:
        parts.append("월세·관리비를 확인하세요" if "관리비" in missing else "월세를 확인하세요")
    elif "관리비" in missing:
        # 관리비만 비어 unknown이면 월세는 있고 월 상한 이하다(넘으면 evaluate가 over로 판정).
        mon_max, rent = _cap(budget, "monthly_max_manwon"), _to_int(values.get("monthly_rent_manwon"))
        room = None if mon_max is None or rent is None else mon_max - rent
        if room is None or room < 0:   # evaluate와 다른 예산을 넘긴 경우의 안전장치
            parts.append("관리비를 확인하세요")
        elif parts:   # 보증금도 미기재 → 관리비 조건만 알려 준다
            parts.append("관리비가 없어야 합니다" if room == 0 else f"관리비는 {room}만원 이하여야 합니다")
        else:
            parts.append("관리비가 없어야 예산 안" if room == 0 else f"관리비 {room}만원 이하면 예산 안")
    return " · ".join(parts) or None


def evaluate_session(db: Any, session: dict) -> tuple[dict | None, list[dict]]:
    """세션 매물 전체(listing_no 순)의 판정·안내. (예산 행, [{listing_id, listing_no, label, evaluation, next_action}])"""
    budget = get_budget(db, session["id"])
    items: list[dict] = []
    for listing in list_listings(db, session["id"]):
        values = listing_values(db, listing["id"])
        ev = evaluate(values, budget)
        no = int(listing.get("listing_no") or 0)
        items.append({"listing_id": str(listing["id"]), "listing_no": no, "label": listing_label(listing),
                      "evaluation": ev, "next_action": next_action(values, budget, ev)})
    return budget, items


# ------------------------------------------------------------------ 비교표 행 도우미
def listing_values(db: Any, listing_id: Any) -> dict:
    """매물의 최신 성공 분석 + 사용자 수정값. 분석이 없으면 {}."""
    analysis = latest_analysis(db, listing_id)
    if analysis is None:
        return {}
    return effective_values(analysis.get("result_json"), field_overrides(db, analysis["id"]))


def row_values(db: Any, row: dict) -> dict:
    """P3가 넘긴 행의 values를 쓴다. 키가 아예 없으면 직접 계산한다."""
    if "values" in row:
        return row.get("values") or {}
    return listing_values(db, row["listing_id"])


def evaluate_rows(db: Any, session: dict, rows: list[dict]) -> dict[str, Evaluation]:
    """세션 예산으로 비교표 행 전체를 판정한다. {listing_id: Evaluation}"""
    budget = get_budget(db, session["id"])
    return {str(r["listing_id"]): evaluate(row_values(db, r), budget) for r in rows}
