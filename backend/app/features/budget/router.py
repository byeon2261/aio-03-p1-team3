"""F11 예산: GET·PUT /sessions/{session_id}/budget, GET /sessions/{session_id}/budget/evaluations"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.auth import CurrentUser, get_current_user
from app.core.db import Database, get_user_db
from app.core.ownership import get_owned_session
from app.core.schemas import BudgetIn, BudgetOut
from app.features.budget import service
from app.features.budget.schemas import BudgetCountsOut, BudgetEvaluationOut, BudgetEvaluationsOut

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


@router.get("/sessions/{session_id}/budget/evaluations", response_model=BudgetEvaluationsOut)
def read_budget_evaluations(session_id: str, user: CurrentUser = Depends(get_current_user),
                            db: Database = Depends(get_user_db)) -> BudgetEvaluationsOut:
    """매물별 예산 판정·사유·미기재 항목·다음 행동(listing_no 순). '예산 안만 보기'로 숨긴 이유를 보여 줄 때 쓴다."""
    session = get_owned_session(db, user, session_id)
    budget, items = service.evaluate_session(db, session)
    counts = BudgetCountsOut()
    out: list[BudgetEvaluationOut] = []
    for it in items:
        ev = it["evaluation"]
        if ev.status is not None:
            setattr(counts, ev.status, getattr(counts, ev.status) + 1)
        out.append(BudgetEvaluationOut(
            listing_id=it["listing_id"], listing_no=it["listing_no"], label=it["label"], status=ev.status,
            status_label=ev.label, reason=ev.reason, missing=list(ev.missing), next_action=it["next_action"]))
    return BudgetEvaluationsOut(session_id=str(session["id"]), budget_set=service.has_caps(budget),
                                counts=counts, items=out)
