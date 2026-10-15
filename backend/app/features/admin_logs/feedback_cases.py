"""낮은 평가 사례 (GET /admin/feedback).

계약 응답은 list[FeedbackAdminOut]이다. 화면에 필요한 메모 앞부분·분석 요약은
FeedbackAdminOut을 상속한 FeedbackCaseOut에 더한다(필드 추가 → REPORT에 적음).
사유별 개수는 /admin/metrics의 extra.feedback_reason_counts로 준다(계약 안에서 우회).
"""

from __future__ import annotations

from typing import Any

from app.core.schemas import FeedbackAdminOut
from app.features.admin_logs.common import select_in
from app.features.admin_logs.metrics import latest_overall_feedback

MEMO_HEAD_CHARS = 40
DEFAULT_LIMIT = 20
MAX_LIMIT = 100
SCAN_FACTOR = 5   # 최신 평가가 아닌 행을 걸러 낼 여유분


class FeedbackCaseOut(FeedbackAdminOut):
    memo_head: str | None = None          # 메모 앞부분(MEMO_HEAD_CHARS자, 줄바꿈은 공백)
    analysis_summary: str | None = None   # "라벨 · 보증금 500만원 · 월세 45만원 · 관리비 7만원"


def memo_head(text: Any, n: int = MEMO_HEAD_CHARS) -> str | None:
    if text is None:
        return None
    s = " ".join(str(text).split())
    if not s:
        return ""
    return s if len(s) <= n else s[:n] + "…"


def _manwon(v: Any) -> str:
    return "미기재" if v is None else f"{int(v):,}만원"


def analysis_summary(result_json: Any) -> str | None:
    if not isinstance(result_json, dict):
        return None
    parts = [
        str(result_json.get("label") or "라벨 없음"),
        f"보증금 {_manwon(result_json.get('deposit_manwon'))}",
        f"월세 {_manwon(result_json.get('monthly_rent_manwon'))}",
        f"관리비 {_manwon(result_json.get('maintenance_fee_manwon'))}",
    ]
    unchecked = result_json.get("unchecked") or []
    missing = result_json.get("missing_checks") or []
    if unchecked or missing:
        parts.append(f"확인 못함 {len(unchecked)} · 빠짐 {len(missing)}")
    return " · ".join(parts)


def list_feedback_cases(db: Any, *, rating: str = "down", limit: int = DEFAULT_LIMIT) -> list[FeedbackCaseOut]:
    """rating 평가 중 '분석별 최신 평가'인 것만 최신순으로."""
    limit = max(1, min(int(limit), MAX_LIMIT))
    candidates = db.select("feedback", {"field_name": ("is", None), "rating": rating},
                           order_by="created_at", desc=True, limit=limit * SCAN_FACTOR)
    if not candidates:
        return []
    aids = sorted({str(r["analysis_id"]) for r in candidates})
    overall = select_in(db, "feedback", "analysis_id", aids, {"field_name": ("is", None)})
    latest = latest_overall_feedback(overall)
    valid = [r for r in candidates if latest.get(str(r["analysis_id"]), {}).get("id") == r["id"]][:limit]
    if not valid:
        return []

    analyses = {str(a["id"]): a for a in select_in(db, "analyses", "id", sorted({str(r["analysis_id"]) for r in valid}))}
    listing_ids = sorted({str(a["listing_id"]) for a in analyses.values() if a.get("listing_id")})
    listings = {str(x["id"]): x for x in select_in(db, "listings", "id", listing_ids)}

    out: list[FeedbackCaseOut] = []
    for r in valid:
        a = analyses.get(str(r["analysis_id"])) or {}
        lst = listings.get(str(a.get("listing_id"))) or {}
        out.append(FeedbackCaseOut(
            id=str(r["id"]),
            analysis_id=str(r["analysis_id"]),
            field_name=r.get("field_name"),
            corrected_value=r.get("corrected_value"),
            action=r.get("action"),
            rating=r.get("rating"),
            reason=r.get("reason"),
            comment=r.get("comment"),
            created_at=r["created_at"],
            listing_id=str(a["listing_id"]) if a.get("listing_id") else None,
            prompt_version=a.get("prompt_version"),
            memo_head=memo_head(lst.get("memo_text")),
            analysis_summary=analysis_summary(a.get("result_json")),
        ))
    return out
