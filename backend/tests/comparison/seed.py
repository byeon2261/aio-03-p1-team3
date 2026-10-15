"""P3 테스트용 데이터 만들기(세션·매물·분석·피드백 행을 MemoryDatabase에 직접 넣는다)."""

from __future__ import annotations

from typing import Any

from app.core.analysis_contract import SCHEMA_VERSION, build_result, memo_hash
from tests.fakes import sample_ai_output


def make_session(db, user, title: str = "토요일 집 보기") -> dict:
    return db.insert("tour_sessions", {"profile_id": user.profile_id, "title": title})[0]


def make_listing(db, session: dict, memo: str = "메모") -> dict:
    return db.insert("listings", {"session_id": session["id"], "memo_text": memo})[0]


def add_success(db, listing: dict, *, memo: str | None = None, **ai: Any) -> dict:
    """성공 분석 행. ai는 sample_ai_output 덮어쓰기(예: monthly_rent_manwon=None)."""
    result = build_result(sample_ai_output(**ai)).model_dump(mode="json")
    return db.insert("analyses", {
        "listing_id": listing["id"], "status": "success", "result_json": result,
        "schema_version": SCHEMA_VERSION, "prompt_version": "v1", "model": "gemini-3.5-flash-lite",
        "thinking_level": "minimal", "memo_hash": memo_hash(listing["memo_text"] if memo is None else memo),
    })[0]


def add_failed(db, listing: dict) -> dict:
    return db.insert("analyses", {
        "listing_id": listing["id"], "status": "failed", "result_json": None, "error_code": "AI_FORMAT_ERROR",
        "schema_version": SCHEMA_VERSION, "prompt_version": "v1", "model": "gemini-3.5-flash-lite",
        "thinking_level": "minimal", "memo_hash": memo_hash(listing["memo_text"]),
    })[0]


def add_override(db, user, analysis: dict, field_name: str, value: Any, action: str | None = None) -> dict:
    """action을 주지 않으면 0008 이전 모양의 행(null = 수정 취소)으로 넣는다."""
    row = {"analysis_id": analysis["id"], "profile_id": user.profile_id,
           "field_name": field_name, "corrected_value": value}
    if action is not None:
        row["action"] = action
    return db.insert("feedback", row)[0]
