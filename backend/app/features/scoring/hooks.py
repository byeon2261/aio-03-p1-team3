"""비교표 확장 등록: 열 `score`(적합도).

create_app()마다 다시 import된다. 같은 key로 다시 등록하면 바꿔 끼우므로 여러 번 돌아도 안전하다.
열 제공자는 필터 전 전체 매물에 대해 계산하므로 순위는 넣지 않는다(순위는 GET /sessions/{id}/scores).
"""

from __future__ import annotations

from typing import Any

from app.core.registry import ColumnProvider, ColumnValue, register_column_provider
from app.features.scoring import service

COLUMN_KEY = "score"

OFF = ColumnValue(display="꺼짐", status="off", tone="muted")
UNRATED = ColumnValue(display="만족도 미입력", status="unrated", tone="muted")


def to_column_value(score: int | None) -> ColumnValue:
    if score is None:
        return UNRATED
    return ColumnValue(display=f"{score}점", status="scored", tone="default")


def compute_score_column(*, db: Any, user: Any, session: dict, rows: list[dict]) -> dict[str, ColumnValue]:
    sid = str(session["id"])
    setting = service.to_setting_out(db, sid, service.get_setting_row(db, sid))
    ids = [str(r["listing_id"]) for r in rows]
    if not setting.enabled:
        return {lid: OFF for lid in ids}
    scored = service.score_listings(db, setting, ids)
    return {lid: to_column_value(score) for lid, (score, _) in scored.items()}


register_column_provider(ColumnProvider(key=COLUMN_KEY, title="적합도", compute=compute_score_column, order=20))
