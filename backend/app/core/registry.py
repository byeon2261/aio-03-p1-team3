"""비교표 확장 지점. P5가 등록하고 P3가 쓴다.

열 제공자(ColumnProvider)
    def compute(*, db, user, session, rows) -> dict[listing_id, ColumnValue]
        rows: P3가 만든 행 목록. 각 행은 dict:
              {"listing_id", "listing_no", "label", "analysis_status", "needs_reanalysis", "values"}
              values는 effective_values(사용자 수정 반영) 결과, 분석이 없으면 {}.
    register_column_provider(ColumnProvider(key="budget", title="예산", compute=compute, order=10))

행 필터
    def keep(*, db, user, session, rows) -> set[listing_id]   # 남길 행의 listing_id
    register_row_filter("within_budget", keep)

같은 key·이름으로 다시 등록하면 바꿔 끼운다(hooks.py를 다시 읽어도 안전).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

from pydantic import BaseModel


class ColumnValue(BaseModel):
    display: str
    status: str | None = None
    tone: Literal["default", "good", "bad", "muted"] = "default"


ComputeFn = Callable[..., dict[str, ColumnValue]]
RowFilterFn = Callable[..., set[str]]


@dataclass(frozen=True)
class ColumnProvider:
    key: str
    title: str
    compute: ComputeFn
    order: int = 100


_providers: dict[str, ColumnProvider] = {}
_filters: dict[str, RowFilterFn] = {}


def register_column_provider(provider: ColumnProvider) -> None:
    _providers[provider.key] = provider


def get_column_providers() -> list[ColumnProvider]:
    return sorted(_providers.values(), key=lambda p: (p.order, p.key))


def register_row_filter(name: str, fn: RowFilterFn) -> None:
    _filters[name] = fn


def get_row_filter(name: str) -> RowFilterFn | None:
    return _filters.get(name)


def list_row_filters() -> list[str]:
    return sorted(_filters)


def reset_registry() -> None:
    """테스트용."""
    _providers.clear()
    _filters.clear()


__all__ = [
    "ColumnValue", "ColumnProvider", "register_column_provider", "get_column_providers",
    "register_row_filter", "get_row_filter", "list_row_filters", "reset_registry",
]
