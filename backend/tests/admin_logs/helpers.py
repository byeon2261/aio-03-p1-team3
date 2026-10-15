"""admin_logs 테스트 도우미: 로그·분석·피드백 행 만들기."""

from __future__ import annotations

import datetime as dt
import uuid

UTC = dt.timezone.utc
BASE = dt.datetime(2026, 10, 1, 3, 0, tzinfo=UTC)   # 서울 12:00


def at(minutes: float = 0, hours: float = 0, days: float = 0) -> dt.datetime:
    return BASE + dt.timedelta(minutes=minutes, hours=hours, days=days)


def add_log(db, *, endpoint="/sessions", method="GET", status_code=200, latency_ms=100, ai_latency_ms=None,
            error_code=None, prompt_version=None, cache_hit=None, profile_id=None, created_at=None) -> dict:
    row = {
        "request_id": str(uuid.uuid4()),
        "profile_id": profile_id,
        "endpoint": endpoint,
        "method": method,
        "status_code": status_code,
        "latency_ms": latency_ms,
        "ai_latency_ms": ai_latency_ms,
        "error_code": error_code,
        "prompt_version": prompt_version,
        "cache_hit": cache_hit,
    }
    if created_at is not None:
        row["created_at"] = created_at
    return db.insert("request_logs", row)[0]


def add_analysis_request(db, *, status_code=200, latency_ms=900, ai_latency_ms=800, cache_hit=False,
                         error_code=None, prompt_version="v1", created_at=None) -> dict:
    return add_log(db, endpoint="/listings/{listing_id}/analyses", method="POST", status_code=status_code,
                   latency_ms=latency_ms, ai_latency_ms=ai_latency_ms, cache_hit=cache_hit, error_code=error_code,
                   prompt_version=prompt_version, created_at=created_at)


def make_listing(db, profile_id: str, memo_text: str = "역앞 원룸. 500에 45, 관리비 7.") -> dict:
    session = db.insert("tour_sessions", {"profile_id": profile_id, "title": "10월 집 보기"})[0]
    return db.insert("listings", {"session_id": session["id"], "memo_text": memo_text})[0]


def add_analysis(db, listing_id: str, *, status="success", prompt_version="v1", created_at=None,
                 result_json=None) -> dict:
    row = {
        "listing_id": listing_id,
        "result_json": result_json if result_json is not None else {
            "label": "역앞 원룸", "deposit_manwon": 500, "monthly_rent_manwon": 45,
            "maintenance_fee_manwon": None, "unchecked": ["수압"], "missing_checks": ["소음", "난방"],
        },
        "schema_version": "1",
        "prompt_version": prompt_version,
        "model": "gemini-3.5-flash-lite",
        "memo_hash": "h",
        "status": status,
    }
    if created_at is not None:
        row["created_at"] = created_at
    return db.insert("analyses", row)[0]


def add_feedback(db, analysis_id: str, profile_id: str, *, field_name=None, corrected_value=None, rating=None,
                 reason=None, comment=None, created_at=None, action=None) -> dict:
    row = {"analysis_id": analysis_id, "profile_id": profile_id, "field_name": field_name,
           "corrected_value": corrected_value, "rating": rating, "reason": reason, "comment": comment}
    if action is not None:
        row["action"] = action
    if created_at is not None:
        row["created_at"] = created_at
    return db.insert("feedback", row)[0]
