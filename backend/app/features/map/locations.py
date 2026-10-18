"""F13 내 매물 위치: 매물 하나당 주소·좌표 하나(listing_locations).

소유 확인은 core/ownership(남의 매물·세션은 404). 주소는 메모와 따로 두고 AI 분석에 보내지 않는다.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from app.core.db import Database, UniqueViolation
from app.core.repo import list_listings
from app.features.map.schemas import ListingLocationOut, LocationIn, LocationOut, SessionPinOut

TABLE = "listing_locations"


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def label_of(listing: dict) -> str:
    return f"{int(listing['listing_no'])}번 집"


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


def session_pins(db: Database, session_id: Any) -> list[SessionPinOut]:
    """세션 매물 중 위치가 있는 것만, 매물 번호 순."""
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
                                      label=label_of(listing), location=LocationOut.model_validate(row)))
    return pins
