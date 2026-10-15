"""예산 테스트용 데이터 만들기(테스트 전용)."""

from __future__ import annotations

import importlib
import sys
from typing import Any

HOOKS = "app.features.budget.hooks"


def load_hooks() -> None:
    """등록부가 테스트마다 초기화되므로 hooks.py를 다시 읽어 등록한다."""
    if HOOKS in sys.modules:
        importlib.reload(sys.modules[HOOKS])
    else:
        importlib.import_module(HOOKS)


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


def correct(db: Any, user: Any, analysis: dict, field: str, value: Any, action: str | None = None) -> dict:
    """action을 주지 않으면 0008 이전 모양의 행(null = 수정 취소)으로 넣는다."""
    row = {"analysis_id": analysis["id"], "profile_id": user.profile_id, "field_name": field, "corrected_value": value}
    if action is not None:
        row["action"] = action
    return db.insert("feedback", row)[0]


def set_budget(db: Any, session: dict, deposit: int | None = None, monthly: int | None = None) -> dict:
    return db.insert("session_budgets", {"session_id": session["id"], "deposit_max_manwon": deposit,
                                         "monthly_max_manwon": monthly})[0]


def row(listing: dict, values: dict | None, status: str = "success") -> dict:
    """P3가 넘기는 행 모양."""
    return {"listing_id": listing["id"], "listing_no": listing["listing_no"], "label": f"{listing['listing_no']}번 집",
            "analysis_status": status, "needs_reanalysis": False, "values": values or {}}
