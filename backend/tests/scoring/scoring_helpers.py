"""F12 테스트용 데이터 만들기(테스트 전용)."""

from __future__ import annotations

from typing import Any


def make_session(db: Any, user: Any, title: str = "토요일 집 보기") -> dict:
    return db.insert("tour_sessions", {"profile_id": user.profile_id, "title": title})[0]


def make_listing(db: Any, session: dict, memo: str = "메모") -> dict:
    return db.insert("listings", {"session_id": session["id"], "memo_text": memo})[0]


def make_analysis(db: Any, listing: dict, **money: Any) -> dict:
    result = {"label": "원룸", "deposit_manwon": 500, "monthly_rent_manwon": 45, "maintenance_fee_manwon": 7}
    result.update(money)
    return db.insert("analyses", {
        "listing_id": listing["id"], "result_json": result, "schema_version": "1", "prompt_version": "v1",
        "model": "gemini-3.5-flash-lite", "memo_hash": "h", "status": "success",
    })[0]


def sat_body(**values: int) -> dict:
    return {"items": [{"item_key": k, "satisfaction": v} for k, v in values.items()]}


def profile_body(name: str, **weights: int) -> dict:
    return {"name": name, "weights": [{"item_key": k, "weight": v} for k, v in weights.items()]}
