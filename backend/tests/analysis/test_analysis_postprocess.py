"""F5 후처리: 근거 확인·중복 합치기·floor/transit 보충·체크리스트 밖 제거·네 목록 계산."""

import json

import pytest

from app.core.analysis_contract import CHECKLIST, AnalysisAIOutput, CheckItem
from app.features.analysis.postprocess import FormatError, evidence_in_memo, parse_ai_output, postprocess
from tests.analysis.conftest import EXAMPLE_MEMO, example_ai_json, example_ai_text


def _ai(**kw) -> AnalysisAIOutput:
    return AnalysisAIOutput.model_validate(example_ai_json(**kw))


def _assert_partition(r):
    groups = [r.confirmed_checks, r.unchecked, r.ambiguous_checks, r.missing_checks]
    flat = [x for g in groups for x in g]
    assert len(flat) == len(set(flat)) and set(flat) == set(CHECKLIST)
    for g in groups:
        assert g == [x for x in CHECKLIST if x in g]   # CHECKLIST 순서


def test_analysis_postprocess_example_memo():
    r = postprocess(parse_ai_output(example_ai_text()), EXAMPLE_MEMO)
    assert (r.deposit_manwon, r.monthly_rent_manwon, r.maintenance_fee_manwon) == (500, 45, 7)
    assert r.maintenance_includes == ["인터넷"]
    assert r.transit == "신림역 도보 8분" and r.direction == "남향" and r.mixed_listings is False
    assert r.confirmed_checks == ["채광", "곰팡이", "교통"]
    assert r.unchecked == ["수압"]
    assert r.ambiguous_checks == []
    # 단계 파일 예시의 순서(소음·층수·옵션·난방·보안)가 아니라 규칙대로 CHECKLIST 순서
    assert r.missing_checks == ["소음", "난방", "층수", "옵션", "보안"]
    _assert_partition(r)


def test_analysis_postprocess_negative_expression_is_confirmed():
    memo = "곰팡이 없음. 채광 좋음."
    ai = _ai(transit=None, checks=[{"item": "곰팡이", "status": "confirmed", "evidence": "곰팡이 없음"}])
    r = postprocess(ai, memo)
    assert "곰팡이" in r.confirmed_checks
    assert "곰팡이" not in r.missing_checks
    _assert_partition(r)


def test_analysis_postprocess_unchecked_stays_unchecked():
    memo = "수압 확인 못함"
    ai = _ai(transit=None, checks=[{"item": "수압", "status": "unchecked", "evidence": "수압 확인 못함"}])
    r = postprocess(ai, memo)
    assert r.unchecked == ["수압"] and "수압" not in r.missing_checks


def test_analysis_postprocess_evidence_not_in_memo_becomes_ambiguous():
    memo = "채광 좋음"
    ai = _ai(transit=None, checks=[
        {"item": "채광", "status": "confirmed", "evidence": "채 광   좋음"},       # 공백만 다르면 인정
        {"item": "소음", "status": "confirmed", "evidence": "조용함"},             # 메모에 없음
        {"item": "보안", "status": "unchecked", "evidence": ""},                  # 빈 근거
    ])
    r = postprocess(ai, memo)
    assert r.confirmed_checks == ["채광"]
    assert r.ambiguous_checks == ["소음", "보안"]
    _assert_partition(r)


def test_analysis_postprocess_conflicting_status_merges_to_ambiguous():
    memo = "수압 좋음. 근데 수압 확인 못함"
    ai = _ai(transit=None, checks=[
        {"item": "수압", "status": "confirmed", "evidence": "수압 좋음"},
        {"item": "수압", "status": "unchecked", "evidence": "수압 확인 못함"},
    ])
    r = postprocess(ai, memo)
    assert r.ambiguous_checks == ["수압"]
    assert [c.item for c in r.checks] == ["수압"]                 # 하나로 합침
    assert r.checks[0].evidence == "수압 좋음 / 수압 확인 못함"


def test_analysis_postprocess_duplicate_same_status_merges():
    memo = "채광 좋음. 남향이라 채광 좋음"
    ai = _ai(transit=None, checks=[
        {"item": "채광", "status": "confirmed", "evidence": "채광 좋음"},
        {"item": "채광", "status": "confirmed", "evidence": "남향이라 채광 좋음"},
    ])
    r = postprocess(ai, memo)
    assert r.confirmed_checks == ["채광"] and len(r.checks) == 1


def test_analysis_postprocess_floor_and_transit_rules():
    memo = "3층. 역까지 5분"
    ai = _ai(floor="3층", transit="역까지 5분", checks=[])
    r = postprocess(ai, memo)
    assert r.confirmed_checks == ["층수", "교통"]
    ev = {c.item: c.evidence for c in r.checks}
    assert ev == {"층수": "3층", "교통": "역까지 5분"}
    # 이미 있으면 덮지 않는다
    ai2 = _ai(floor="3층", transit=None, checks=[{"item": "층수", "status": "ambiguous", "evidence": "3층"}])
    r2 = postprocess(ai2, memo)
    assert r2.ambiguous_checks == ["층수"] and "교통" in r2.missing_checks


def test_analysis_postprocess_drops_items_outside_checklist():
    text = example_ai_text(checks=[
        {"item": "채광", "status": "confirmed", "evidence": "남향이라 채광 좋음"},
        {"item": "주차", "status": "confirmed", "evidence": "주차 가능"},
    ])
    ai = parse_ai_output(text)                       # 형식 실패가 아니라 제거
    assert [c.item for c in ai.checks] == ["채광"]
    r = postprocess(ai, EXAMPLE_MEMO)
    _assert_partition(r)


@pytest.mark.parametrize("text, part", [
    (None, "비어"), ("", "비어"), ("{not json", "JSON"), ("[1,2]", "객체"),
    (json.dumps({"label": "x", "deposit_manwon": "오백"}), "deposit_manwon"),
    (json.dumps({"label": "x", "checks": [{"item": "채광", "status": "maybe", "evidence": "e"}]}), "checks.0.status"),
])
def test_analysis_postprocess_format_errors_have_summary(text, part):
    with pytest.raises(FormatError) as e:
        parse_ai_output(text)
    assert part in e.value.summary and len(e.value.summary) <= 300


def test_analysis_postprocess_summary_has_no_input_values():
    secret = "비밀메모내용"
    with pytest.raises(FormatError) as e:
        parse_ai_output(json.dumps({"label": "x", "deposit_manwon": secret}, ensure_ascii=False))
    assert secret not in e.value.summary


def test_analysis_postprocess_evidence_helper():
    assert evidence_in_memo("“채광 좋음”", "남향이라 채광 좋음")
    assert not evidence_in_memo("   ", "abc")
    assert CheckItem(item="채광", status="confirmed", evidence="x")
