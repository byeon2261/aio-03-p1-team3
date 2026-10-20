"""F3 매물 메모: GET·POST /sessions/{session_id}/listings, GET·PATCH·DELETE /listings/{listing_id}

- 번호(listing_no)는 DB 트리거가 넣는다. 서버는 보내지 않고 돌아온 행의 값을 쓴다
  (동시 저장에도 겹치지 않고, 지운 번호는 다시 쓰지 않는다).
- memo_updated_at은 메모가 바뀔 때 DB 트리거가 갱신한다(UPDATE는 memo_text와, 보냈을 때만 name. 이름만 바뀌면 재분석 필요가 아니다).
- 정식 저장(POST·PATCH)이 성공하면 해당 초안과 draftmeta를 지운다(실패는 무시, KV가 없어도 저장은 동작).
- 삭제: get_owned_listing → emit("listing.before_delete", storage 포함) → 초안 키 삭제 → 행 삭제(분석·피드백·사진 행은 CASCADE).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.analysis_contract import needs_reanalysis
from app.core.auth import CurrentUser, get_current_user
from app.core.db import Database, get_user_db
from app.core.events import emit
from app.core.ownership import get_owned_listing, get_owned_session
from app.core.repo import latest_analysis, list_listings, listing_label
from app.core.schemas import ListingCreateIn, ListingOut, ListingUpdateIn, OkOut
from app.core.storage import Storage, get_storage
from app.features.drafts.store import discard_drafts, listing_draft_key, new_draft_key
from app.features.sessions.validation import require_text

router = APIRouter(tags=["listings"])

MEMO_REQUIRED = "메모를 입력하세요."
NAME_REQUIRED = "매물 이름을 입력하세요."


def listing_out(db: Database, row: dict) -> ListingOut:
    return _to_listing_out(row, latest_analysis(db, row["id"], status=None))


def _newest_analyses(db: Database, listing_ids: list[str]) -> dict[str, dict]:
    """{listing_id: 최신 분석(성공·실패 상관없이)}. 매물마다 latest_analysis를 부르던 것을 한 번의 조회로."""
    if not listing_ids:
        return {}
    out: dict[str, dict] = {}
    for a in db.select("analyses", {"listing_id": listing_ids}, order_by="created_at", desc=True):
        out.setdefault(str(a.get("listing_id")), a)
    return out


def _to_listing_out(row: dict, latest: dict | None) -> ListingOut:
    status = (latest or {}).get("status") or "none"
    return ListingOut(
        id=str(row["id"]),
        session_id=str(row["session_id"]),
        listing_no=int(row["listing_no"]),
        label=listing_label(row),
        memo_text=row.get("memo_text") or "",
        memo_updated_at=row["memo_updated_at"],
        created_at=row["created_at"],
        latest_analysis_status=status,
        needs_reanalysis=needs_reanalysis(row, latest),
    )


@router.get("/sessions/{session_id}/listings", response_model=list[ListingOut])
def list_session_listings(session_id: str, user: CurrentUser = Depends(get_current_user),
                          db: Database = Depends(get_user_db)) -> list[ListingOut]:
    session = get_owned_session(db, user, session_id)
    rows = list_listings(db, session["id"])
    newest = _newest_analyses(db, [str(r["id"]) for r in rows])
    return [_to_listing_out(r, newest.get(str(r["id"]))) for r in rows]


@router.post("/sessions/{session_id}/listings", response_model=ListingOut)
def create_listing(session_id: str, body: ListingCreateIn, user: CurrentUser = Depends(get_current_user),
                   db: Database = Depends(get_user_db)) -> ListingOut:
    session = get_owned_session(db, user, session_id)
    name = require_text(body.name, "name", NAME_REQUIRED)
    text = require_text(body.memo_text, "memo_text", MEMO_REQUIRED)
    # listing_no는 보내지 않는다(트리거가 tour_sessions.last_listing_no + 1을 넣는다)
    row = db.insert("listings", {"session_id": str(session["id"]), "name": name, "memo_text": text})[0]
    discard_drafts([new_draft_key(user.auth_user_id, str(session["id"]))])
    return listing_out(db, row)


@router.get("/listings/{listing_id}", response_model=ListingOut)
def get_listing(listing_id: str, user: CurrentUser = Depends(get_current_user),
                db: Database = Depends(get_user_db)) -> ListingOut:
    return listing_out(db, get_owned_listing(db, user, listing_id))


@router.patch("/listings/{listing_id}", response_model=ListingOut)
def update_listing(listing_id: str, body: ListingUpdateIn, user: CurrentUser = Depends(get_current_user),
                   db: Database = Depends(get_user_db)) -> ListingOut:
    listing = get_owned_listing(db, user, listing_id)
    text = require_text(body.memo_text, "memo_text", MEMO_REQUIRED)
    changes: dict = {}
    if body.name is not None:   # 이름은 보냈을 때만 바꾼다(매물 상세 메모 탭은 메모만 보낸다)
        name = require_text(body.name, "name", NAME_REQUIRED)
        if name != (listing.get("name") or ""):
            changes["name"] = name
    if text != (listing.get("memo_text") or ""):
        changes["memo_text"] = text
    row = listing
    if changes:
        updated = db.update("listings", {"id": str(listing["id"])}, changes)
        if updated:
            row = updated[0]
    discard_drafts([listing_draft_key(user.auth_user_id, str(listing["id"]))])
    return listing_out(db, row)


@router.delete("/listings/{listing_id}", response_model=OkOut)
def delete_listing(listing_id: str, user: CurrentUser = Depends(get_current_user),
                   db: Database = Depends(get_user_db), storage: Storage = Depends(get_storage)) -> OkOut:
    listing = get_owned_listing(db, user, listing_id)
    # 사진 파일 정리(P4) 등. 예외는 그대로 올라가 응답이 되고, 아래 삭제는 하지 않는다.
    emit("listing.before_delete", db=db, user=user, listing=listing, storage=storage)
    discard_drafts([listing_draft_key(user.auth_user_id, str(listing["id"]))])
    db.delete("listings", {"id": str(listing["id"])})
    return OkOut()
