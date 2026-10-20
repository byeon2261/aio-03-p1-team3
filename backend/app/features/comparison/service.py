"""F6 매물 비교표 계산. 라우터와 떼어 두어 DB 가짜로 바로 시험할 수 있게 한다.

행 하나 = 매물 하나.
    analysis_status  latest_analysis(status=None)의 상태(none/success/failed)
    values           최신 '성공' 분석의 result_json → 사용자 수정값(field_overrides) → effective_values
                     최신이 실패여도 이전 성공 값이 있으면 그 값을 쓴다. 성공 분석이 없으면 {}.
금액 None은 '미기재'이고 0으로 바꾸지 않는다. 최저값 비교에서도 뺀다.
분석·수정값은 매물마다 따로 묻지 않고 세션 매물 전체를 한 번에 읽는다(_load_analyses, _load_overrides).
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Iterable

from app.core.analysis_contract import CHECKLIST, needs_reanalysis
from app.core.ownership import get_owned_session
from app.core.registry import ColumnValue, get_column_providers, get_row_filter
from app.core.repo import list_listings, listing_label, overrides_from_rows
from app.core.schemas import ComparisonOut, ComparisonRow, FieldTitle
from app.core.values import effective_values, monthly_cost

logger = logging.getLogger("app.features.comparison")

# 열 순서 고정
FIELDS: tuple[tuple[str, str], ...] = (
    ("deposit_manwon", "보증금"),
    ("monthly_rent_manwon", "월세"),
    ("maintenance_fee_manwon", "관리비"),
    ("monthly_cost_manwon", "월 고정비"),
    ("maintenance_includes", "포함 내역"),     # 관리비에 들어 있는 항목(인터넷·수도 등). 화면 제목 옆 ?에 설명
    ("transit", "교통"),
    ("floor", "층수"),
    ("direction", "방향"),
    ("pros", "장점"),
    ("cons", "단점"),
    ("followup_checks", "추가 확인 항목"),
)
FIELD_KEYS = tuple(k for k, _ in FIELDS)
LOWEST_FIELDS = ("monthly_rent_manwon", "maintenance_fee_manwon")
NOT_ENOUGH_MESSAGE = "매물을 하나 더 추가하세요"
PROVIDER_ERROR = ColumnValue(display="불러오지 못함", status="error", tone="muted")


def parse_filters(raw: str | None) -> list[str]:
    """'a, b,,a' → ['a', 'b'] (공백 제거, 빈 이름·중복 제거, 순서 유지)."""
    out: list[str] = []
    for part in (raw or "").split(","):
        name = part.strip()
        if name and name not in out:
            out.append(name)
    return out


def followup_checks(values: dict) -> list[str]:
    """확인 못함 + 애매함 + 언급 없음을 CHECKLIST 순서로."""
    wanted: set[str] = set()
    for key in ("unchecked", "ambiguous_checks", "missing_checks"):
        wanted.update(values.get(key) or [])
    return [name for name in CHECKLIST if name in wanted]


def full_values(result_json: dict | None, overrides: dict | None) -> dict[str, Any]:
    """effective_values + 계산 열(monthly_cost_manwon, followup_checks). 열 제공자·행 필터에 넘기는 값."""
    values = effective_values(result_json, overrides)
    values["monthly_cost_manwon"] = monthly_cost(values)
    values["followup_checks"] = followup_checks(values)
    return values


def _load_analyses(db: Any, listing_ids: list[str]) -> dict[str, tuple[dict | None, dict | None]]:
    """{listing_id: (최신 분석, 최신 성공 분석)}. 매물마다 latest_analysis를 두 번 부르던 것을 한 번의 조회로."""
    out: dict[str, tuple[dict | None, dict | None]] = {lid: (None, None) for lid in listing_ids}
    if not listing_ids:
        return out
    for row in db.select("analyses", {"listing_id": listing_ids}, order_by="created_at", desc=True):
        lid = str(row.get("listing_id"))
        if lid not in out:
            continue
        newest, success = out[lid]
        if newest is None:
            newest = row
        if success is None and row.get("status") == "success":
            success = row
        out[lid] = (newest, success)
    return out


def _load_overrides(db: Any, analysis_ids: list[str]) -> dict[str, dict[str, Any]]:
    """{analysis_id: 필드별 최신 수정값}. field_overrides를 분석마다 부르던 것을 한 번의 조회로(같은 규칙)."""
    if not analysis_ids:
        return {}
    by_analysis: dict[str, list[dict]] = {aid: [] for aid in analysis_ids}
    for row in db.select("feedback", {"analysis_id": analysis_ids}, order_by="created_at"):
        by_analysis.setdefault(str(row.get("analysis_id")), []).append(row)
    return {aid: overrides_from_rows(rows) for aid, rows in by_analysis.items()}


def _base_row(listing: dict, newest: dict | None, success: dict | None, overrides: dict[str, dict]) -> dict:
    lid = str(listing["id"])
    status = "none" if newest is None else (newest.get("status") or "failed")
    if newest is None:
        success = None
    values: dict[str, Any] = {}
    if success is not None:
        values = full_values(success.get("result_json"), overrides.get(str(success["id"]), {}))
    return {
        "listing_id": lid,
        "listing_no": int(listing.get("listing_no") or 0),
        "label": listing_label(listing),
        "analysis_status": status,
        "needs_reanalysis": needs_reanalysis(listing, newest),
        "values": values,
    }


def _base_rows(db: Any, listings: list[dict]) -> list[dict]:
    """매물 N곳의 기본 행. DB 조회는 분석 1번 + 수정값 1번(매물이 없으면 0번)."""
    analyses = _load_analyses(db, [str(x["id"]) for x in listings])
    success_ids = [str(s["id"]) for _, s in analyses.values() if s is not None]
    overrides = _load_overrides(db, success_ids)
    return [_base_row(x, *analyses[str(x["id"])], overrides) for x in listings]


def _as_column_value(v: Any) -> ColumnValue | None:
    if v is None or isinstance(v, ColumnValue):
        return v
    return ColumnValue.model_validate(v)


def _apply_providers(db: Any, user: Any, session: dict, rows: list[dict]) -> tuple[list[FieldTitle], dict[str, dict]]:
    titles: list[FieldTitle] = []
    columns: dict[str, dict[str, ColumnValue]] = {r["listing_id"]: {} for r in rows}
    for p in get_column_providers():
        titles.append(FieldTitle(key=p.key, title=p.title))
        try:
            result = p.compute(db=db, user=user, session=session, rows=copy.deepcopy(rows)) or {}
            for lid, raw in result.items():
                cv = _as_column_value(raw)
                if cv is not None and str(lid) in columns:
                    columns[str(lid)][p.key] = cv
        except Exception as exc:  # 열 하나가 망가져도 비교표 전체는 보여 준다
            logger.error("column provider %s failed: %s", p.key, type(exc).__name__)
            for lid in columns:
                columns[lid][p.key] = PROVIDER_ERROR
    return titles, columns


def _apply_filters(db: Any, user: Any, session: dict, rows: list[dict],
                   names: Iterable[str]) -> tuple[set[str], dict[str, int]]:
    """필터마다 전체 행에 따로 적용한다. 남는 행 = 모든 필터가 남긴 행의 교집합."""
    all_ids = {r["listing_id"] for r in rows}
    visible = set(all_ids)
    hidden: dict[str, int] = {}
    for name in names:
        fn = get_row_filter(name)
        if fn is None:  # 등록되지 않은 이름은 무시
            continue
        keep = {str(x) for x in (fn(db=db, user=user, session=session, rows=copy.deepcopy(rows)) or set())}
        keep &= all_ids
        hidden[name] = len(all_ids - keep)
        visible &= keep
    return visible, hidden


def _lowest(rows: list[dict]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for key in LOWEST_FIELDS:
        known = [(r["listing_id"], r["values"].get(key)) for r in rows if r["values"].get(key) is not None]
        if not known:
            out[key] = []
            continue
        best = min(v for _, v in known)
        out[key] = [lid for lid, v in known if v == best]
    return out


def build_comparison(db: Any, user: Any, session_id: Any, filter_names: Iterable[str] = ()) -> ComparisonOut:
    session = get_owned_session(db, user, session_id)
    sid = str(session["id"])
    rows = _base_rows(db, list_listings(db, sid))
    fields = [FieldTitle(key=k, title=t) for k, t in FIELDS]

    def _out_row(r: dict, cols: dict | None = None) -> ComparisonRow:
        vals = r["values"]
        shown = {k: vals.get(k) for k in FIELD_KEYS} if vals else {}
        return ComparisonRow(listing_id=r["listing_id"], listing_no=r["listing_no"], label=r["label"],
                             analysis_status=r["analysis_status"], needs_reanalysis=r["needs_reanalysis"],
                             values=shown, columns=cols or {})

    if len(rows) < 2:
        return ComparisonOut(session_id=sid, enough_listings=False, message=NOT_ENOUGH_MESSAGE,
                             fields=fields, rows=[_out_row(r) for r in rows])

    providers, columns = _apply_providers(db, user, session, rows)
    visible, hidden = _apply_filters(db, user, session, rows, filter_names)
    shown_rows = [r for r in rows if r["listing_id"] in visible]
    return ComparisonOut(
        session_id=sid,
        enough_listings=True,
        fields=fields,
        providers=providers,
        rows=[_out_row(r, columns[r["listing_id"]]) for r in shown_rows],
        lowest=_lowest(shown_rows),
        hidden_count=hidden,
    )
