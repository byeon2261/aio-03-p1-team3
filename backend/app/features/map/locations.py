"""F13 내 매물 위치: 매물 하나당 주소·좌표 하나(listing_locations).

소유 확인은 core/ownership(남의 매물·세션은 404). 주소는 메모와 따로 두고 AI 분석에 보내지 않는다.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from app.core.analysis_contract import needs_reanalysis
from app.core.db import Database, UniqueViolation
from app.core.repo import field_overrides, latest_analysis, list_listings, listing_label
from app.core.values import MONEY_FIELDS, effective_values
from app.features.map.schemas import (
    ListingLocationOut, LocationIn, LocationOut, MyPinOut, MyPinsOut, SessionPinOut,
)

TABLE = "listing_locations"


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def label_of(listing: dict) -> str:
    return listing_label(listing)


def get_row(db: Database, listing_id: Any) -> dict | None:
    rows = db.select(TABLE, {"listing_id": str(listing_id)}, limit=1)
    return rows[0] if rows else None


def to_out(listing_id: Any, row: dict | None) -> ListingLocationOut:
    return ListingLocationOut(listing_id=str(listing_id),
                              location=LocationOut.model_validate(row) if row else None)


def save(db: Database, listing_id: Any, body: LocationIn) -> ListingLocationOut:
    lid = str(listing_id)
    values = {**body.model_dump(), "updated_at": _now()}
    if get_row(db, lid) is None:
        try:
            return to_out(lid, db.insert(TABLE, {"listing_id": lid, **values})[0])
        except UniqueViolation:
            pass  # 동시에 다른 요청이 먼저 만들었으면 고치기로 넘어간다
    rows = db.update(TABLE, {"listing_id": lid}, values)
    return to_out(lid, rows[0] if rows else get_row(db, lid))


def delete(db: Database, listing_id: Any) -> None:
    db.delete(TABLE, {"listing_id": str(listing_id)})


def money_of(db: Database, listing_id: Any) -> dict[str, Any]:
    """최신 성공 분석에 사용자 수정값을 덮은 금액(비교표와 같은 값). 분석이 없으면 analyzed=False."""
    success = latest_analysis(db, listing_id)
    if success is None:
        return {"analyzed": False}
    values = effective_values(success.get("result_json"), field_overrides(db, success["id"]))
    return {"analyzed": True, **{k: values.get(k) for k in MONEY_FIELDS}}


def session_pins(db: Database, session_id: Any) -> list[SessionPinOut]:
    """세션 매물 중 위치가 있는 것만, 매물 번호 순. 팝업에 보일 금액을 붙인다."""
    listings = list_listings(db, session_id)
    if not listings:
        return []
    rows = db.select(TABLE, {"listing_id": [str(x["id"]) for x in listings]})
    by_listing = {str(r["listing_id"]): r for r in rows}
    pins = []
    for listing in sorted(listings, key=lambda x: int(x["listing_no"])):
        row = by_listing.get(str(listing["id"]))
        if row:
            pins.append(SessionPinOut(listing_id=str(listing["id"]), listing_no=int(listing["listing_no"]),
                                      label=label_of(listing), location=LocationOut.model_validate(row),
                                      **money_of(db, listing["id"])))
    return pins


def my_pins(db: Database, profile_id: Any) -> MyPinsOut:
    """내 모든 세션의 매물 중 위치가 있는 것. 세션 만든 순(최신 먼저) → 매물 번호 순.

    지도 왼쪽 목록에 쓰도록 메모·분석 상태(세션 상세 매물 카드와 같은 정보)도 붙인다.
    """
    sessions = db.select("tour_sessions", {"profile_id": str(profile_id)}, order_by="created_at", desc=True)
    if not sessions:
        return MyPinsOut(pins=[], listing_count=0)
    listings = db.select("listings", {"session_id": [str(s["id"]) for s in sessions]})
    if not listings:
        return MyPinsOut(pins=[], listing_count=0)
    rows = db.select(TABLE, {"listing_id": [str(x["id"]) for x in listings]})
    by_listing = {str(r["listing_id"]): r for r in rows}
    by_session: dict[str, list[dict]] = {}
    for listing in listings:
        by_session.setdefault(str(listing["session_id"]), []).append(listing)
    pins = []
    for session in sessions:
        for listing in sorted(by_session.get(str(session["id"]), []), key=lambda x: int(x["listing_no"])):
            row = by_listing.get(str(listing["id"]))
            if row:
                newest = latest_analysis(db, listing["id"], status=None)
                pins.append(MyPinOut(listing_id=str(listing["id"]), listing_no=int(listing["listing_no"]),
                                     label=label_of(listing), location=LocationOut.model_validate(row),
                                     session_id=str(session["id"]), session_title=session.get("title") or "",
                                     memo_text=listing.get("memo_text") or "",
                                     analysis_status=(newest or {}).get("status") or "none",
                                     needs_reanalysis=needs_reanalysis(listing, newest),
                                     **money_of(db, listing["id"])))
    return MyPinsOut(pins=pins, listing_count=len(listings))
