"""F13 내 매물 위치: GET·PUT·DELETE /listings/{listing_id}/location,
GET /sessions/{session_id}/locations, GET /me/locations(전체 매물 지도)

- 로그인한 사용자만 쓴다(없으면 401).
- 내 매물 위치는 본인 매물만(남의 매물·세션은 404 LISTING_NOT_FOUND·SESSION_NOT_FOUND).
  주소는 메모와 따로 저장하고 AI 분석에 보내지 않는다. 요청 본문(주소)은 로그에 남지 않는다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.auth import CurrentUser, get_current_user
from app.core.db import Database, get_user_db
from app.core.ownership import get_owned_listing, get_owned_session
from app.core.schemas import OkOut
from app.features.map import locations
from app.features.map.schemas import ListingLocationOut, LocationIn, MyPinsOut, SessionPinOut

router = APIRouter(tags=["map"])


@router.get("/listings/{listing_id}/location", response_model=ListingLocationOut)
def read_listing_location(listing_id: str, user: CurrentUser = Depends(get_current_user),
                          db: Database = Depends(get_user_db)) -> ListingLocationOut:
    listing = get_owned_listing(db, user, listing_id)
    return locations.to_out(listing["id"], locations.get_row(db, listing["id"]))


@router.put("/listings/{listing_id}/location", response_model=ListingLocationOut)
def save_listing_location(listing_id: str, body: LocationIn, user: CurrentUser = Depends(get_current_user),
                          db: Database = Depends(get_user_db)) -> ListingLocationOut:
    listing = get_owned_listing(db, user, listing_id)
    return locations.save(db, listing["id"], body)


@router.delete("/listings/{listing_id}/location", response_model=OkOut)
def delete_listing_location(listing_id: str, user: CurrentUser = Depends(get_current_user),
                            db: Database = Depends(get_user_db)) -> OkOut:
    listing = get_owned_listing(db, user, listing_id)
    locations.delete(db, listing["id"])
    return OkOut()


@router.get("/sessions/{session_id}/locations", response_model=list[SessionPinOut])
def list_session_locations(session_id: str, user: CurrentUser = Depends(get_current_user),
                           db: Database = Depends(get_user_db)) -> list[SessionPinOut]:
    session = get_owned_session(db, user, session_id)
    return locations.session_pins(db, session["id"])


@router.get("/me/locations", response_model=MyPinsOut)
def list_my_locations(user: CurrentUser = Depends(get_current_user),
                      db: Database = Depends(get_user_db)) -> MyPinsOut:
    """전체 매물 지도: 내 모든 세션에서 위치를 넣은 매물(금액·세션 이름 포함)."""
    return locations.my_pins(db, user.profile_id)
