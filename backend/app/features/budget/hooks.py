"""비교표 확장 등록: 열 `budget`, 행 필터 `within_budget`.

create_app()마다 다시 import된다. 같은 key·이름으로 다시 등록하면 바꿔 끼우므로 여러 번 돌아도 안전하다.
"""

from __future__ import annotations

from typing import Any

from app.core.registry import ColumnProvider, ColumnValue, register_column_provider, register_row_filter
from app.features.budget import service

COLUMN_KEY = "budget"
FILTER_NAME = "within_budget"

TONES = {"over": "bad", "unknown": "muted", "within": "good"}


def to_column_value(ev: service.Evaluation) -> ColumnValue:
    if ev.status is None:
        return ColumnValue(display="-", status=None, tone="default")
    if ev.status == "within":
        display = ev.label
    else:
        display = f"{ev.label} · {ev.reason}"
    return ColumnValue(display=display, status=ev.status, tone=TONES[ev.status])


def compute_budget_column(*, db: Any, user: Any, session: dict, rows: list[dict]) -> dict[str, ColumnValue]:
    results = service.evaluate_rows(db, session, rows)
    return {lid: to_column_value(ev) for lid, ev in results.items()}


def keep_within_budget(*, db: Any, user: Any, session: dict, rows: list[dict]) -> set[str]:
    """status가 within인 행만 남긴다(예산 미설정이면 남는 행이 없다)."""
    results = service.evaluate_rows(db, session, rows)
    return {lid for lid, ev in results.items() if ev.status == "within"}


register_column_provider(ColumnProvider(key=COLUMN_KEY, title="예산", compute=compute_budget_column, order=10))
register_row_filter(FILTER_NAME, keep_within_budget)
