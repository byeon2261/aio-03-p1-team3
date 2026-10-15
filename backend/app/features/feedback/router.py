"""F7 AI 결과 수정·피드백: POST /analyses/{analysis_id}/feedback"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from app.core.auth import CurrentUser, get_current_user
from app.core.db import Database, get_user_db
from app.features.feedback.schemas import FeedbackCreateIn, FeedbackSaveOut
from app.features.feedback.service import save_feedback

router = APIRouter(tags=["feedback"])


@router.post("/analyses/{analysis_id}/feedback", response_model=FeedbackSaveOut)
async def post_feedback(
    analysis_id: str,
    body: FeedbackCreateIn,
    user: CurrentUser = Depends(get_current_user),
    db: Database = Depends(get_user_db),
) -> FeedbackSaveOut:
    return await run_in_threadpool(save_feedback, db, user, analysis_id, body)
