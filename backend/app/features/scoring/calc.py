"""F12 적합도 계산(순수 함수). DB를 쓰지 않는다.

적합도 = Σ(가중치 × 만족도) ÷ Σ가중치 → 반올림(0.5는 올림)한 0~100 정수
    - 계산에 쓰는 항목 = 만족도를 입력한 항목. 미입력 항목은 빼고 남은 항목의 가중치로 비율을 맞춘다.
    - 쓰는 항목의 가중치 합이 0이면(전부 0) 동일 가중치로 계산한다.
    - 프로필을 고르지 않으면(weights=None) 동일 가중치로 계산한다.
    - 입력한 항목이 하나도 없으면 None('미입력').
    - 프로필에 없는 항목의 가중치는 0이다(항목이 나중에 추가된 경우).

순위: 점수가 높을수록 앞. 같은 점수는 같은 순위(1, 2, 2, 4). 점수 None은 순위 None.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Mapping

from app.features.scoring.items import SCORE_ITEMS


def round_half_up(value: Decimal | float | int) -> int:
    """사사오입. 파이썬 round()는 0.5를 짝수 쪽으로 보내므로(72.5 → 72) 쓰지 않는다."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fitness_score(satisfactions: Mapping[str, int | None], weights: Mapping[str, int] | None,
                  items: Iterable[str] = SCORE_ITEMS) -> int | None:
    used = [k for k in items if satisfactions.get(k) is not None]
    if not used:
        return None
    if weights is None:
        w = {k: 1 for k in used}
    else:
        w = {k: int(weights.get(k) or 0) for k in used}
        if sum(w.values()) == 0:
            w = {k: 1 for k in used}
    total_w = sum(w.values())
    total = sum(Decimal(w[k]) * Decimal(int(satisfactions[k])) for k in used)  # type: ignore[arg-type]
    return round_half_up(total / Decimal(total_w))


def rank(scores: Mapping[str, int | None]) -> dict[str, int | None]:
    """{id: 점수} → {id: 순위}. 같은 점수는 같은 순위, 다음 순위는 건너뛴다."""
    known = sorted((s for s in scores.values() if s is not None), reverse=True)
    first_pos: dict[int, int] = {}
    for i, s in enumerate(known, start=1):
        first_pos.setdefault(s, i)
    return {k: (None if s is None else first_pos[s]) for k, s in scores.items()}


__all__ = ["round_half_up", "fitness_score", "rank"]
