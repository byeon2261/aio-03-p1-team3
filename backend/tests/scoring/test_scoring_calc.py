"""F12 계산 규칙(순수 함수)."""

from __future__ import annotations

from app.core.analysis_contract import CHECKLIST
from app.features.scoring.calc import fitness_score, rank, round_half_up
from app.features.scoring.items import SCORE_ITEMS

EXAMPLE_ITEMS = ("일조량", "습도", "소음")
A = {"일조량": 90, "습도": 40, "소음": 60}
B = {"일조량": 50, "습도": 90, "소음": 60}
SUMMER = {"일조량": 20, "습도": 50, "소음": 30}
WINTER = {"일조량": 50, "습도": 20, "소음": 30}


def test_scoring_items_default_to_service_checklist():
    assert SCORE_ITEMS == tuple(CHECKLIST)


def test_scoring_example_season_profiles_flip_ranking():
    """기능 정리 문서의 계산 예시: 같은 매물이라도 계절 프로필에 따라 순위가 바뀐다."""
    assert fitness_score(A, SUMMER, EXAMPLE_ITEMS) == 56
    assert fitness_score(B, SUMMER, EXAMPLE_ITEMS) == 73
    assert fitness_score(A, WINTER, EXAMPLE_ITEMS) == 71
    assert fitness_score(B, WINTER, EXAMPLE_ITEMS) == 61
    assert rank({"A": 56, "B": 73}) == {"A": 2, "B": 1}
    assert rank({"A": 71, "B": 61}) == {"A": 1, "B": 2}


def test_scoring_weights_need_not_sum_to_100():
    doubled = {k: v * 2 for k, v in SUMMER.items()}
    assert fitness_score(A, doubled, EXAMPLE_ITEMS) == fitness_score(A, SUMMER, EXAMPLE_ITEMS) == 56


def test_scoring_unrated_items_are_left_out_and_rest_renormalized():
    # 습도 미입력 → 일조량·소음만: (20×90 + 30×60) ÷ 50 = 72
    assert fitness_score({"일조량": 90, "습도": None, "소음": 60}, SUMMER, EXAMPLE_ITEMS) == 72
    assert fitness_score({"일조량": 90, "소음": 60}, SUMMER, EXAMPLE_ITEMS) == 72


def test_scoring_all_zero_weights_or_no_profile_means_equal_weights():
    zero = {k: 0 for k in EXAMPLE_ITEMS}
    assert fitness_score(A, zero, EXAMPLE_ITEMS) == 63           # (90+40+60) ÷ 3 = 63.33
    assert fitness_score(A, None, EXAMPLE_ITEMS) == 63
    # 쓰는 항목(입력한 항목)의 가중치만 보고 판단: 습도만 입력했는데 습도 가중치가 0이면 동일 가중치
    assert fitness_score({"습도": 40}, {"일조량": 100, "습도": 0}, EXAMPLE_ITEMS) == 40


def test_scoring_missing_weight_key_counts_as_zero():
    # 프로필에 소음 가중치 행이 없음(항목이 나중에 추가된 경우) → 소음은 0
    assert fitness_score(A, {"일조량": 50, "습도": 50}, EXAMPLE_ITEMS) == 65


def test_scoring_nothing_entered_is_none():
    assert fitness_score({}, SUMMER, EXAMPLE_ITEMS) is None
    assert fitness_score({"일조량": None}, None, EXAMPLE_ITEMS) is None


def test_scoring_items_outside_list_are_ignored():
    assert fitness_score({"일조량": 90, "엘리베이터": 0}, None, EXAMPLE_ITEMS) == 90


def test_scoring_rounds_half_up_not_bankers():
    assert round(72.5) == 72                         # 파이썬 기본 반올림은 짝수 쪽
    assert round_half_up(72.5) == 73
    assert round_half_up(0.5) == 1 and round_half_up(99.49) == 99
    assert fitness_score({"일조량": 72, "습도": 73}, None, EXAMPLE_ITEMS) == 73   # 72.5 → 73


def test_scoring_bounds():
    assert fitness_score({k: 0 for k in EXAMPLE_ITEMS}, SUMMER, EXAMPLE_ITEMS) == 0
    assert fitness_score({k: 100 for k in EXAMPLE_ITEMS}, SUMMER, EXAMPLE_ITEMS) == 100


def test_scoring_rank_ties_share_and_skip():
    assert rank({"a": 80, "b": 90, "c": 80, "d": None, "e": 70}) == {"a": 2, "b": 1, "c": 2, "d": None, "e": 4}
    assert rank({}) == {}
