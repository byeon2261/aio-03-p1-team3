"""F7 피드백 저장. analyses.result_json은 건드리지 않고 feedback 행만 새로 쌓는다.

- 수정: 필드마다 feedback 행 1개(field_name, corrected_value, action). action "set"+null은 메모에 없음,
  "revert"는 수정 취소(AI 값으로 되돌림, corrected_value null).
- 평가·사유·의견: field_name이 null인 행 1개.
- 한 번의 insert로 함께 넣는다(PostgREST 일괄 insert는 한 문장이라 일부만 들어가지 않는다).
다시 조회하면 core.repo.field_overrides가 필드별 최신 수정값을 돌려준다.
"""

from __future__ import annotations

from typing import Any

from app.core.errors import AppError
from app.core.ownership import get_owned_analysis
from app.core.schemas import FeedbackOut
from app.features.feedback.schemas import FeedbackCreateIn, FeedbackSaveOut


def _out(row: dict) -> FeedbackOut:
    return FeedbackOut(
        id=str(row["id"]), analysis_id=str(row["analysis_id"]), field_name=row.get("field_name"),
        corrected_value=row.get("corrected_value"), action=row.get("action"), rating=row.get("rating"),
        reason=row.get("reason"), comment=row.get("comment"), created_at=row["created_at"],
    )


def save_feedback(db: Any, user: Any, analysis_id: Any, body: FeedbackCreateIn) -> FeedbackSaveOut:
    analysis = get_owned_analysis(db, user, analysis_id)
    aid = str(analysis["id"])
    if body.corrections and analysis.get("status") != "success":
        raise AppError(422, "VALIDATION_ERROR", "분석에 실패한 결과는 고칠 수 없습니다. 다시 분석한 뒤 고치세요.",
                       {"fields": [{"loc": ["body", "corrections"], "type": "analysis_failed",
                                    "msg": "실패한 분석에는 수정값을 저장할 수 없습니다."}]})

    base = {"analysis_id": aid, "profile_id": str(user.profile_id)}
    rows: list[dict] = [
        {**base, "field_name": c.field_name, "corrected_value": c.corrected_value, "action": c.action}
        for c in body.corrections
    ]
    if body.has_summary:
        rows.append({**base, "field_name": None, "corrected_value": None, "action": None,
                     "rating": body.rating, "reason": body.reason, "comment": body.comment})

    saved = [_out(r) for r in db.insert("feedback", rows)]
    summary = next((s for s in saved if s.field_name is None), None)
    head = summary or saved[0]
    return FeedbackSaveOut(**head.model_dump(), items=saved)
