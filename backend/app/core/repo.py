"""읽기 전용 도우미. 쓰기는 각 테이블의 쓰기 담당 대화창이 한다."""

from __future__ import annotations

from typing import Any


def list_listings(db: Any, session_id: Any) -> list[dict]:
    """세션의 매물을 listing_no 오름차순으로."""
    return db.select("listings", {"session_id": str(session_id)}, order_by="listing_no")


def latest_analysis(db: Any, listing_id: Any, status: str | None = "success") -> dict | None:
    """가장 최근 분석 행. status=None이면 성공·실패 상관없이 최신 행. 없으면 None."""
    filters: dict = {"listing_id": str(listing_id)}
    if status is not None:
        filters["status"] = status
    rows = db.select("analyses", filters, order_by="created_at", desc=True, limit=1)
    return rows[0] if rows else None


def is_revert(row: dict) -> bool:
    """필드 수정 행이 '수정 취소(AI 값으로 되돌림)'인지.

    action 열(0008): "revert"면 취소, "set"이면 값(null이면 '메모에 없음').
    action이 없는 행(0008 이전 규칙)은 corrected_value null을 취소로 본다.
    """
    action = row.get("action")
    if action == "revert":
        return True
    if action == "set":
        return False
    return row.get("corrected_value") is None


def overrides_from_rows(rows: list[dict]) -> dict[str, Any]:
    """created_at 오름차순 feedback 행 → 필드별 최신 수정값 {field_name: 값}.

    키가 있고 값이 None이면 '메모에 없음(미기재)'으로 고친 것, 키가 없으면 AI 값 그대로다.
    field_name 없는 행(전체 평가)은 건너뛴다. field_overrides와 P6 지표가 같은 규칙을 쓴다.
    """
    out: dict[str, Any] = {}
    for r in rows:
        name = r.get("field_name")
        if not name:
            continue
        if is_revert(r):
            out.pop(name, None)
        else:
            out[name] = r.get("corrected_value")
    return out


def field_overrides(db: Any, analysis_id: Any) -> dict[str, Any]:
    """필드별 최신 사용자 수정값 {field_name: corrected_value}.

    field_name이 있는 feedback 행만 본다. 그 필드의 최신 행이 수정 취소(action "revert")면 결과에서 빼고,
    action "set"이면 값을 넣는다. 값이 None이면 '메모에 없음'으로 고친 것이다(키는 남는다).
    """
    rows = db.select("feedback", {"analysis_id": str(analysis_id)}, order_by="created_at")
    return overrides_from_rows(rows)


def latest_rating(db: Any, analysis_id: Any) -> str | None:
    """전체 평가(field_name null) 중 최신 행의 rating("up"/"down"/None). 행이 없으면 None."""
    rows = db.select("feedback", {"analysis_id": str(analysis_id), "field_name": ("is", None)},
                     order_by="created_at", desc=True, limit=1)
    return rows[0].get("rating") if rows else None
