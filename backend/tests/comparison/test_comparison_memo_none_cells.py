"""I2: 수정 화면의 순수 함수 — 'AI 값으로 되돌리기'와 '메모에 없음으로 표시'를 다른 요청으로 만든다."""

import sys
from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"
if str(FRONTEND_DIR) not in sys.path:
    sys.path.append(str(FRONTEND_DIR))

from features.comparison.cells import NULLABLE_EDIT_KEYS, correction_entry, pending_previous  # noqa: E402


def fv(ai, *, edited=False, user=None):
    return {"ai_value": ai, "user_value": user, "value": user if edited else ai, "edited": edited}


def test_comparison_cells_nullable_keys_exclude_lists():
    assert set(NULLABLE_EDIT_KEYS) == {"deposit_manwon", "monthly_rent_manwon", "maintenance_fee_manwon",
                                       "transit", "floor", "direction"}


def test_comparison_cells_revert_and_memo_none_are_different_requests():
    assert correction_entry("monthly_rent_manwon", None, fv(45, edited=True, user=50), revert=True) == {
        "field_name": "monthly_rent_manwon", "action": "revert"}
    assert correction_entry("monthly_rent_manwon", None, fv(45), memo_none=True) == {
        "field_name": "monthly_rent_manwon", "action": "set", "corrected_value": None}
    # 이미 값이 없으면(AI null 또는 이미 메모에 없음) 보내지 않는다
    assert correction_entry("floor", None, fv(None), memo_none=True) is None
    assert correction_entry("floor", None, fv("3층", edited=True, user=None), memo_none=True) is None
    # 목록은 '메모에 없음' 대상이 아니다(빈 목록으로 고친다)
    assert correction_entry("pros", "", fv(["역세권"]), memo_none=True) is None


def test_comparison_cells_plain_edit_and_blank_input():
    assert correction_entry("monthly_rent_manwon", 40, fv(45)) == {
        "field_name": "monthly_rent_manwon", "action": "set", "corrected_value": 40}
    assert correction_entry("monthly_rent_manwon", None, fv(45)) is None          # 칸 비움 = 바꾸지 않음
    assert correction_entry("floor", "  ", fv("3층")) is None
    assert correction_entry("pros", "", fv(["역세권"])) == {"field_name": "pros", "action": "set", "corrected_value": []}


def test_comparison_cells_pending_previous_handles_memo_none():
    previous = {"monthly_rent_manwon": None, "floor": "3층"}
    # 이번 분석에서 아직 안 고침 → 둘 다 대기(값 None도 대기로 본다)
    assert pending_previous(previous, {"monthly_rent_manwon": fv(45), "floor": fv("2층")}) == previous
    # 이미 같은 값으로 고침 → 대기 없음
    done = {"monthly_rent_manwon": fv(45, edited=True, user=None), "floor": fv("2층", edited=True, user="3층")}
    assert pending_previous(previous, done) == {}
