"""F3 초안: GET·PUT /listings/{listing_id}/draft, GET·PUT·DELETE /sessions/{session_id}/draft

- 소유 확인을 먼저 한다(남의 세션·매물 → 404). 그다음 KV를 쓸 수 없으면 503 KV_UNAVAILABLE.
- GET: 초안 있음 → DraftOut, 초안 없고 draftmeta만 → 410 DRAFT_EXPIRED, 둘 다 없음 → 404 DRAFT_NOT_FOUND.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.auth import CurrentUser, get_current_user
from app.core.db import Database, get_user_db
from app.core.ownership import get_owned_listing, get_owned_session
from app.core.schemas import DraftIn, DraftOut, OkOut
from app.features.drafts.store import (
    delete_draft,
    listing_draft_key,
    load_draft,
    new_draft_key,
    require_kv,
    save_draft,
)

router = APIRouter(tags=["drafts"])


def _listing_key(db: Database, user: CurrentUser, listing_id: str) -> str:
    listing = get_owned_listing(db, user, listing_id)
    return listing_draft_key(user.auth_user_id, str(listing["id"]))


def _new_key(db: Database, user: CurrentUser, session_id: str) -> str:
    session = get_owned_session(db, user, session_id)
    return new_draft_key(user.auth_user_id, str(session["id"]))


@router.get("/listings/{listing_id}/draft", response_model=DraftOut)
def get_listing_draft(listing_id: str, user: CurrentUser = Depends(get_current_user),
                      db: Database = Depends(get_user_db)) -> DraftOut:
    key = _listing_key(db, user, listing_id)
    return load_draft(require_kv(), key)


@router.put("/listings/{listing_id}/draft", response_model=DraftOut)
def put_listing_draft(listing_id: str, body: DraftIn, user: CurrentUser = Depends(get_current_user),
                      db: Database = Depends(get_user_db)) -> DraftOut:
    key = _listing_key(db, user, listing_id)
    return save_draft(require_kv(), key, body.memo_text)


@router.get("/sessions/{session_id}/draft", response_model=DraftOut)
def get_new_draft(session_id: str, user: CurrentUser = Depends(get_current_user),
                  db: Database = Depends(get_user_db)) -> DraftOut:
    key = _new_key(db, user, session_id)
    return load_draft(require_kv(), key)


@router.put("/sessions/{session_id}/draft", response_model=DraftOut)
def put_new_draft(session_id: str, body: DraftIn, user: CurrentUser = Depends(get_current_user),
                  db: Database = Depends(get_user_db)) -> DraftOut:
    key = _new_key(db, user, session_id)
    return save_draft(require_kv(), key, body.memo_text)


@router.delete("/sessions/{session_id}/draft", response_model=OkOut)
def delete_new_draft(session_id: str, user: CurrentUser = Depends(get_current_user),
                     db: Database = Depends(get_user_db)) -> OkOut:
    key = _new_key(db, user, session_id)
    delete_draft(require_kv(), key)
    return OkOut()
