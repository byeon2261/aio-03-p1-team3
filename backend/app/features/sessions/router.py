"""F2 집 보기 세션: GET·POST /sessions, GET·PATCH·DELETE /sessions/{session_id}

삭제 순서
    get_owned_session → emit("session.before_delete", storage 포함) → 초안 키 삭제(실패 무시) → 세션 행 삭제(나머지는 CASCADE)
처리기가 예외를 내면 거기서 멈추고 그 오류를 돌려준다(행이 남아 다시 삭제할 수 있다).
"""

from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends

from app.core.auth import CurrentUser, get_current_user
from app.core.db import Database, get_user_db
from app.core.events import emit
from app.core.ownership import get_owned_session
from app.core.repo import list_listings
from app.core.schemas import OkOut, SessionCreateIn, SessionOut, SessionUpdateIn
from app.core.storage import Storage, get_storage
from app.features.drafts.store import discard_drafts, listing_draft_key, new_draft_key
from app.features.sessions.validation import blank_field_error, require_text

router = APIRouter(tags=["sessions"])

TITLE_REQUIRED = "세션 제목을 입력하세요."


def listing_counts(db: Database, session_ids: list[str]) -> dict[str, int]:
    if not session_ids:
        return {}
    rows = db.select("listings", {"session_id": list(session_ids)})
    return dict(Counter(str(r["session_id"]) for r in rows))


def session_out(row: dict, listing_count: int) -> SessionOut:
    return SessionOut(id=str(row["id"]), title=row["title"], visit_date=row.get("visit_date"),
                      created_at=row["created_at"], listing_count=listing_count)


def _one_out(db: Database, row: dict) -> SessionOut:
    sid = str(row["id"])
    return session_out(row, listing_counts(db, [sid]).get(sid, 0))


@router.get("/sessions", response_model=list[SessionOut])
def list_sessions(user: CurrentUser = Depends(get_current_user),
                  db: Database = Depends(get_user_db)) -> list[SessionOut]:
    rows = db.select("tour_sessions", {"profile_id": user.profile_id}, order_by="created_at", desc=True)
    counts = listing_counts(db, [str(r["id"]) for r in rows])
    return [session_out(r, counts.get(str(r["id"]), 0)) for r in rows]


@router.post("/sessions", response_model=SessionOut)
def create_session(body: SessionCreateIn, user: CurrentUser = Depends(get_current_user),
                   db: Database = Depends(get_user_db)) -> SessionOut:
    title = require_text(body.title, "title", TITLE_REQUIRED)
    row = db.insert("tour_sessions", {"profile_id": user.profile_id, "title": title,
                                      "visit_date": body.visit_date})[0]
    return session_out(row, 0)


@router.get("/sessions/{session_id}", response_model=SessionOut)
def get_session(session_id: str, user: CurrentUser = Depends(get_current_user),
                db: Database = Depends(get_user_db)) -> SessionOut:
    return _one_out(db, get_owned_session(db, user, session_id))


@router.patch("/sessions/{session_id}", response_model=SessionOut)
def update_session(session_id: str, body: SessionUpdateIn, user: CurrentUser = Depends(get_current_user),
                   db: Database = Depends(get_user_db)) -> SessionOut:
    """보낸 필드만 고친다. title: 빈 값·null이면 422. visit_date: null을 보내면 지운다."""
    session = get_owned_session(db, user, session_id)
    sent = body.model_fields_set
    values: dict = {}
    if "title" in sent:
        if body.title is None:
            raise blank_field_error("title", TITLE_REQUIRED)
        values["title"] = require_text(body.title, "title", TITLE_REQUIRED)
    if "visit_date" in sent:
        values["visit_date"] = body.visit_date
    if values:
        updated = db.update("tour_sessions", {"id": session["id"]}, values)
        if updated:
            session = updated[0]
    return _one_out(db, session)


@router.delete("/sessions/{session_id}", response_model=OkOut)
def delete_session(session_id: str, user: CurrentUser = Depends(get_current_user),
                   db: Database = Depends(get_user_db), storage: Storage = Depends(get_storage)) -> OkOut:
    session = get_owned_session(db, user, session_id)
    sid = str(session["id"])
    listing_ids = [str(r["id"]) for r in list_listings(db, sid)]
    # 사진 파일 정리(P4) 등. 예외는 그대로 올라가 응답이 되고, 아래 삭제는 하지 않는다.
    emit("session.before_delete", db=db, user=user, session=session, listing_ids=listing_ids, storage=storage)
    discard_drafts([listing_draft_key(user.auth_user_id, lid) for lid in listing_ids]
                   + [new_draft_key(user.auth_user_id, sid)])
    db.delete("tour_sessions", {"id": sid})
    return OkOut()
