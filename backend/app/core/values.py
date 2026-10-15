"""화면·비교표에 쓰는 '실제 값' 계산. 금액은 만원 단위 정수, None은 '미기재'(0 아님)."""

from __future__ import annotations

from typing import Any

from app.core.analysis_contract import EDITABLE_FIELDS

MONEY_FIELDS = ("deposit_manwon", "monthly_rent_manwon", "maintenance_fee_manwon")


def effective_values(result_json: dict | None, overrides: dict | None) -> dict[str, Any]:
    """AI 결과에 사용자 수정값을 덮어쓴 dict. 덮어쓰기는 EDITABLE_FIELDS에만 한다.

    overrides의 값이 None이면 사용자가 '메모에 없음'으로 고친 것이므로 None(미기재)으로 덮는다.
    """
    values = dict(result_json or {})
    for k, v in (overrides or {}).items():
        if k in EDITABLE_FIELDS:
            values[k] = v
    return values


def monthly_cost(values: dict | None) -> int | None:
    """월세 + 관리비. 둘 중 하나라도 None(미기재)이면 None."""
    v = values or {}
    rent, fee = v.get("monthly_rent_manwon"), v.get("maintenance_fee_manwon")
    if rent is None or fee is None:
        return None
    return int(rent) + int(fee)
