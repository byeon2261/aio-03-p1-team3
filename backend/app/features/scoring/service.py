"""F12 저장·조회와 세션 점수 계산.

테이블(0120): weight_profiles, weight_items, listing_satisfactions, session_scoring.
- 항목 행은 '통째로 바꾸기'로 저장한다(그 대상의 행을 지우고 새로 넣는다).
- 프로필 삭제는 DB의 ON DELETE(세션 설정 null, 가중치 행 삭제)에 맡기되, 같은 결과가 되도록
  코드에서도 먼저 처리한다(가짜 DB에서도 같은 결과).
- 점수는 저장하지 않고 요청 때마다 계산한다.
"""

from __future__ import annotations

import copy
import datetime as dt
from typing import Any, Iterable

from app.core.db import UniqueViolation, is_valid_uuid
from app.core.errors import AppError
from app.core.registry import get_row_filter
from app.core.repo import field_overrides, latest_analysis, list_listings
from app.core.values import effective_values, monthly_cost
from app.features.scoring.calc import fitness_score, rank
from app.features.scoring.items import SCORE_ITEMS
from app.features.scoring.schemas import (
    SatisfactionIn, SatisfactionItemOut, SatisfactionOut, ScoreRow, ScoresOut, ScoringSettingIn,
    ScoringSettingOut, WeightItemOut, WeightProfileIn, WeightProfileOut,
)

PROFILES = "weight_profiles"
ITEMS = "weight_items"
SATISFACTIONS = "listing_satisfactions"
SETTINGS = "session_scoring"


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def profile_not_found() -> AppError:
    return AppError(404, "WEIGHT_PROFILE_NOT_FOUND", "가중치 프로필을 찾을 수 없습니다.")


# ------------------------------------------------------------------ 가중치 프로필
def get_owned_profile(db: Any, user: Any, profile_id: Any) -> dict:
    """없거나 남의 것이면 404(core/ownership.py와 같은 방식)."""
    if not is_valid_uuid(profile_id):
        raise profile_not_found()
    rows = db.select(PROFILES, {"id": str(profile_id)}, limit=1)
    if not rows or str(rows[0].get("profile_id")) != str(user.profile_id):
        raise profile_not_found()
    return rows[0]


def weights_of(db: Any, weight_profile_id: Any) -> dict[str, int]:
    """{항목: 가중치}. SCORE_ITEMS에 없는 항목 행은 뺀다."""
    rows = db.select(ITEMS, {"weight_profile_id": str(weight_profile_id)})
    return {r["item_key"]: int(r["weight"]) for r in rows if r.get("item_key") in SCORE_ITEMS}


def to_profile_out(row: dict, weights: dict[str, int]) -> WeightProfileOut:
    return WeightProfileOut(
        id=str(row["id"]), name=row["name"],
        weights=[WeightItemOut(item_key=k, weight=int(weights.get(k, 0))) for k in SCORE_ITEMS],
        created_at=row.get("created_at"), updated_at=row.get("updated_at"),
    )


def list_profiles(db: Any, user: Any) -> list[WeightProfileOut]:
    rows = db.select(PROFILES, {"profile_id": str(user.profile_id)}, order_by="created_at")
    return [to_profile_out(r, weights_of(db, r["id"])) for r in rows]


def _replace_weights(db: Any, weight_profile_id: str, body: WeightProfileIn) -> dict[str, int]:
    db.delete(ITEMS, {"weight_profile_id": weight_profile_id})
    weights = {it.item_key: it.weight for it in body.weights}
    db.insert(ITEMS, [{"weight_profile_id": weight_profile_id, "item_key": k, "weight": w}
                      for k, w in weights.items()])
    return weights


def create_profile(db: Any, user: Any, body: WeightProfileIn) -> WeightProfileOut:
    row = db.insert(PROFILES, {"profile_id": str(user.profile_id), "name": body.name})[0]
    weights = _replace_weights(db, str(row["id"]), body)
    return to_profile_out(row, weights)


def update_profile(db: Any, user: Any, profile_id: Any, body: WeightProfileIn) -> WeightProfileOut:
    row = get_owned_profile(db, user, profile_id)
    pid = str(row["id"])
    updated = db.update(PROFILES, {"id": pid}, {"name": body.name, "updated_at": _now()})
    weights = _replace_weights(db, pid, body)
    return to_profile_out(updated[0] if updated else {**row, "name": body.name}, weights)


def delete_profile(db: Any, user: Any, profile_id: Any) -> None:
    row = get_owned_profile(db, user, profile_id)
    pid = str(row["id"])
    db.update(SETTINGS, {"weight_profile_id": pid}, {"weight_profile_id": None, "updated_at": _now()})
    db.delete(ITEMS, {"weight_profile_id": pid})
    db.delete(PROFILES, {"id": pid})


# ------------------------------------------------------------------ 매물 만족도
def satisfactions_of(db: Any, listing_id: Any) -> tuple[dict[str, int], Any]:
    """({항목: 만족도}, 가장 최근 저장 시각). SCORE_ITEMS에 없는 항목 행은 뺀다."""
    rows = [r for r in db.select(SATISFACTIONS, {"listing_id": str(listing_id)})
            if r.get("item_key") in SCORE_ITEMS]
    values = {r["item_key"]: int(r["satisfaction"]) for r in rows}
    stamps = [r.get("updated_at") for r in rows if r.get("updated_at")]
    return values, (max(stamps, key=str) if stamps else None)


def to_satisfaction_out(listing_id: Any, values: dict[str, int], updated_at: Any) -> SatisfactionOut:
    return SatisfactionOut(
        listing_id=str(listing_id),
        items=[SatisfactionItemOut(item_key=k, satisfaction=values.get(k)) for k in SCORE_ITEMS],
        entered_count=sum(1 for k in SCORE_ITEMS if values.get(k) is not None),
        updated_at=updated_at,
    )


def save_satisfactions(db: Any, listing_id: Any, body: SatisfactionIn) -> SatisfactionOut:
    lid = str(listing_id)
    now = _now()
    db.delete(SATISFACTIONS, {"listing_id": lid})
    values = {it.item_key: it.satisfaction for it in body.items}
    db.insert(SATISFACTIONS, [{"listing_id": lid, "item_key": k, "satisfaction": v, "updated_at": now}
                              for k, v in values.items()])
    return to_satisfaction_out(lid, values, now if values else None)


# ------------------------------------------------------------------ 세션 설정
def get_setting_row(db: Any, session_id: Any) -> dict | None:
    rows = db.select(SETTINGS, {"session_id": str(session_id)}, limit=1)
    return rows[0] if rows else None


def to_setting_out(db: Any, session_id: Any, row: dict | None) -> ScoringSettingOut:
    if row is None:
        return ScoringSettingOut(session_id=str(session_id))
    pid = row.get("weight_profile_id")
    name = None
    if pid:
        found = db.select(PROFILES, {"id": str(pid)}, limit=1)
        if found:
            name = found[0].get("name")
        else:
            pid = None   # 지워진 프로필(가짜 DB 등) → 동일 가중치
    return ScoringSettingOut(session_id=str(session_id), enabled=bool(row.get("enabled", True)),
                             weight_profile_id=str(pid) if pid else None, weight_profile_name=name,
                             updated_at=row.get("updated_at"))


def save_setting(db: Any, user: Any, session_id: Any, body: ScoringSettingIn) -> ScoringSettingOut:
    sid = str(session_id)
    pid = None
    if body.weight_profile_id is not None:
        pid = str(get_owned_profile(db, user, body.weight_profile_id)["id"])
    values = {"enabled": body.enabled, "weight_profile_id": pid, "updated_at": _now()}
    if get_setting_row(db, sid) is None:
        try:
            return to_setting_out(db, sid, db.insert(SETTINGS, {"session_id": sid, **values})[0])
        except UniqueViolation:
            pass  # 동시에 다른 요청이 먼저 만들었으면 고치기로 넘어간다
    rows = db.update(SETTINGS, {"session_id": sid}, values)
    return to_setting_out(db, sid, rows[0] if rows else get_setting_row(db, sid))


# ------------------------------------------------------------------ 점수 계산
def session_weights(db: Any, setting: ScoringSettingOut) -> dict[str, int] | None:
    """세션에 고른 프로필의 가중치. 고르지 않았으면 None(동일 가중치)."""
    if not setting.weight_profile_id:
        return None
    return weights_of(db, setting.weight_profile_id)


def score_listings(db: Any, setting: ScoringSettingOut, listing_ids: Iterable[str]) -> dict[str, tuple[int | None, int]]:
    """{listing_id: (적합도, 입력한 항목 수)}."""
    weights = session_weights(db, setting)
    out: dict[str, tuple[int | None, int]] = {}
    for lid in listing_ids:
        values, _ = satisfactions_of(db, lid)
        out[str(lid)] = (fitness_score(values, weights), len(values))
    return out


def _filter_rows(db: Any, listings: list[dict]) -> list[dict]:
    """행 필터(예: 예산)에 넘길 행. 비교표(P3)와 같은 모양: values = 최신 성공 분석 + 사용자 수정값
    + monthly_cost_manwon. 분석이 없으면 {}."""
    rows = []
    for listing in listings:
        lid = str(listing["id"])
        values: dict[str, Any] = {}
        analysis = latest_analysis(db, lid)
        if analysis is not None:
            values = effective_values(analysis.get("result_json"), field_overrides(db, analysis["id"]))
            values["monthly_cost_manwon"] = monthly_cost(values)
        newest = latest_analysis(db, lid, status=None)
        rows.append({"listing_id": lid, "listing_no": int(listing.get("listing_no") or 0),
                     "label": f"{listing.get('listing_no')}번 집",
                     "analysis_status": "none" if newest is None else (newest.get("status") or "failed"),
                     "needs_reanalysis": False, "values": values})
    return rows


def parse_filters(raw: str | None) -> list[str]:
    """'a, b,,a' → ['a', 'b'] (비교표와 같은 규칙)."""
    out: list[str] = []
    for part in (raw or "").split(","):
        name = part.strip()
        if name and name not in out:
            out.append(name)
    return out


def apply_filters(db: Any, user: Any, session: dict, rows: list[dict],
                  names: Iterable[str]) -> tuple[set[str], dict[str, int]]:
    """비교표와 같은 규칙: 필터마다 전체 행에 따로 적용하고 교집합을 남긴다. 등록 안 된 이름은 무시."""
    all_ids = {r["listing_id"] for r in rows}
    visible = set(all_ids)
    hidden: dict[str, int] = {}
    for name in names:
        fn = get_row_filter(name)
        if fn is None:
            continue
        keep = {str(x) for x in (fn(db=db, user=user, session=session, rows=copy.deepcopy(rows)) or set())}
        keep &= all_ids
        hidden[name] = len(all_ids - keep)
        visible &= keep
    return visible, hidden


def build_scores(db: Any, user: Any, session: dict, filter_names: Iterable[str] = ()) -> ScoresOut:
    sid = str(session["id"])
    setting = to_setting_out(db, sid, get_setting_row(db, sid))
    if not setting.enabled:
        return ScoresOut(session_id=sid, setting=setting, items=list(SCORE_ITEMS), rows=[])
    listings = list_listings(db, sid)
    names = list(filter_names)
    if names:
        visible, hidden = apply_filters(db, user, session, _filter_rows(db, listings), names)
    else:
        visible, hidden = {str(x["id"]) for x in listings}, {}
    shown = [x for x in listings if str(x["id"]) in visible]
    scored = score_listings(db, setting, [str(x["id"]) for x in shown])
    ranks = rank({lid: s for lid, (s, _) in scored.items()})
    rows = [ScoreRow(listing_id=str(x["id"]), listing_no=int(x.get("listing_no") or 0),
                     label=f"{x.get('listing_no')}번 집", score=scored[str(x["id"])][0],
                     rank=ranks[str(x["id"])], entered_count=scored[str(x["id"])][1],
                     total_items=len(SCORE_ITEMS))
            for x in shown]
    rows.sort(key=lambda r: (r.rank is None, r.rank or 0, r.listing_no))
    return ScoresOut(session_id=sid, setting=setting, items=list(SCORE_ITEMS), rows=rows, hidden_count=hidden)


__all__ = [
    "get_owned_profile", "list_profiles", "create_profile", "update_profile", "delete_profile", "weights_of",
    "satisfactions_of", "save_satisfactions", "to_satisfaction_out", "get_setting_row", "to_setting_out",
    "save_setting", "score_listings", "build_scores", "profile_not_found",
]
