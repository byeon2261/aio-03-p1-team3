"""대화별 초안 저장·복원·수정·삭제의 HTTP 경로를 제공한다."""

from uuid import UUID

from fastapi import APIRouter, Response

from app.schemas import DraftInput, DraftRecord, PositiveId

router = APIRouter(prefix="/conversations/{conversation_id}/work-sessions", tags=["작업 세션"])

