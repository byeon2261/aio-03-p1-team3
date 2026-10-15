"""F11 예산: GET·PUT /sessions/{session_id}/budget"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.auth import CurrentUser, get_current_user
from app.core.db import Database, get_user_db
from app.core.ownership import get_owned_session
from app.core.schemas import BudgetIn, BudgetOut
from app.features.budget import service

router = APIRouter(tags=["budget"])


@router.get("/sessions/{session_id}/budget", response_model=BudgetOut)
def read_budget(session_id: str, user: CurrentUser = Depends(get_current_user),
                db: Database = Depends(get_user_db)) -> BudgetOut:
    """설정한 적이 없으면 두 상한과 updated_at이 null인 응답."""
    session = get_owned_session(db, user, session_id)
    return service.to_out(session["id"], service.get_budget(db, session["id"]))


@router.put("/sessions/{session_id}/budget", response_model=BudgetOut)
def put_budget(session_id: str, body: BudgetIn, user: CurrentUser = Depends(get_current_user),
               db: Database = Depends(get_user_db)) -> BudgetOut:
    """두 상한을 통째로 바꾼다. 비우려면 null로 보낸다. 음수는 422."""
    session = get_owned_session(db, user, session_id)
    row = service.save_budget(db, session["id"], body)
    return service.to_out(session["id"], row)
