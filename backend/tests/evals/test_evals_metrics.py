"""채점 함수 단위 테스트: 일치·집합·null·환각·failure_codes·지표·condition_mismatches·failure_counts."""

import pytest

from app.core.analysis_contract import EVAL_FIELDS, build_result
from app.features.evals import metrics
from tests.fakes import sample_ai_output


def expected_dict(**overrides):
    d = build_result(sample_ai_output()).model_dump(mode="json")
    d.update(overrides)
    return d


def test_evals_field_match_exact_money_including_null():
    assert metrics.field_match("deposit_manwon", 500, 500)
    assert not metrics.field_match("deposit_manwon", 500, 50)
    assert metrics.field_match("maintenance_fee_manwon", None, None)
    assert not metrics.field_match("maintenance_fee_manwon", None, 0)   # null과 0은 다르다
    assert not metrics.field_match("maintenance_fee_manwon", 0, None)


def test_evals_field_match_set_ignores_order_and_duplicates():
    assert metrics.field_match("maintenance_includes", ["수도", "인터넷"], ["인터넷", "수도", "수도"])
    assert not metrics.field_match("unchecked", ["수압"], ["수압", "난방"])
    assert metrics.field_match("missing_checks", [], None)


def test_evals_field_match_text_strips_whitespace():
    assert metrics.field_match("floor", "3 층", "3층")
    assert metrics.field_match("direction", " 남향\n", "남향")
    assert not metrics.field_match("floor", "3층", "4층")
    assert metrics.field_match("floor", None, "  ")   # 공백뿐이면 값 없음
    assert not metrics.field_match("floor", None, "3층")


def test_evals_score_case_all_match():
    exp = expected_dict()
    s = metrics.score_case(exp, dict(exp))
    assert set(s.field_matches) == set(EVAL_FIELDS)
    assert all(s.field_matches.values())
    assert s.failure_codes == []
    assert s.missing_checks_match is True


def test_evals_score_case_money_mismatch_gives_num():
    exp = expected_dict()
    s = metrics.score_case(exp, {**exp, "monthly_rent_manwon": 50})
    assert s.field_matches["monthly_rent_manwon"] is False
    assert s.failure_codes == ["NUM"]


def test_evals_score_case_hallucination_when_expected_null():
    exp = expected_dict(maintenance_fee_manwon=None, direction=None)
    out = {**exp, "maintenance_fee_manwon": 7, "direction": "남향"}
    s = metrics.score_case(exp, out)
    assert "HAL" in s.failure_codes and "NUM" in s.failure_codes
    assert s.null_expected == 2 and s.hallucinated == 2
    assert sorted(s.hallucinated_fields) == ["direction", "maintenance_fee_manwon"]


def test_evals_score_case_missing_list_item_gives_mis_and_chk():
    exp = expected_dict()
    out = {**exp, "maintenance_includes": ["수도"], "missing_checks": exp["missing_checks"][:-1]}
    s = metrics.score_case(exp, out)
    assert s.failure_codes == ["MIS", "CHK"]
    assert s.missing_checks_match is False


def test_evals_score_case_extra_list_item_is_not_mis():
    exp = expected_dict()
    s = metrics.score_case(exp, {**exp, "maintenance_includes": ["수도", "인터넷", "전기"]})
    assert "MIS" not in s.failure_codes
    assert s.field_matches["maintenance_includes"] is False


def test_evals_score_case_format_failure():
    s = metrics.score_case(expected_dict(), None, "AI_FORMAT_ERROR")
    assert s.failure_codes == ["FMT"]
    assert not any(s.field_matches.values())
    assert s.has_output is False


def test_evals_score_case_other_ai_error_is_not_fmt():
    s = metrics.score_case(expected_dict(), None, "AI_TIMEOUT")
    assert s.failure_codes == []
    assert s.status == "AI_TIMEOUT"


def test_evals_score_case_ignores_criteria_key():
    exp = {**expected_dict(), metrics.CRITERIA_KEY: "금액을 본다"}
    s = metrics.score_case(exp, expected_dict())
    assert s.failure_codes == []


def test_evals_aggregate_metrics():
    exp = expected_dict(maintenance_fee_manwon=None)  # 환각 대상 null 1개
    ok = metrics.score_case(exp, dict(exp))
    hal = metrics.score_case(exp, {**exp, "maintenance_fee_manwon": 5})
    fmt = metrics.score_case(exp, None, "AI_FORMAT_ERROR")
    m = metrics.aggregate([ok, hal, fmt])
    n_fields = len(EVAL_FIELDS)
    assert m["field_accuracy"] == pytest.approx((n_fields + (n_fields - 1) + 0) / (3 * n_fields))
    assert m["hallucination_rate"] == pytest.approx(1 / 2)   # 출력 있는 사례 2건의 null 필드 2개 중 1개
    assert m["missing_check_accuracy"] == pytest.approx(2 / 3)
    assert m["format_error_rate"] == pytest.approx(1 / 3)


def test_evals_aggregate_empty_is_none():
    assert metrics.aggregate([]) == {"field_accuracy": None, "hallucination_rate": None,
                                     "missing_check_accuracy": None, "format_error_rate": None}


def test_evals_failure_counts_counts_cases():
    counts = metrics.failure_counts([["NUM", "HAL"], ["NUM"], [], None, ["FMT", "FMT"], ["CLS"]])
    assert counts == {"NUM": 2, "HAL": 1, "MIS": 0, "CHK": 0, "FMT": 1}


RUN = {"model": "gemini-3.5-flash-lite", "thinking_level": "minimal", "schema_version": "1"}


def test_evals_condition_mismatches_same():
    assert metrics.condition_mismatches(RUN, dict(RUN), ["a", "b"], ["b", "a"]) == []


def test_evals_condition_mismatches_model_differs():
    other = {**RUN, "model": "다른-모델"}
    assert metrics.condition_mismatches(RUN, other, ["a"], ["a"]) == ["model"]


def test_evals_condition_mismatches_case_list_differs():
    assert metrics.condition_mismatches(RUN, dict(RUN), ["a", "b"], ["a"]) == ["case_list"]


def test_evals_condition_mismatches_settings_differ():
    other = {**RUN, "thinking_level": "low", "schema_version": "2"}
    assert metrics.condition_mismatches(RUN, other, ["a"], ["a"]) == ["thinking_level", "schema_version"]
