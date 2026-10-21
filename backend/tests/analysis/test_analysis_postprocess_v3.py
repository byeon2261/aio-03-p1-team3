"""v3 후처리 규칙 S1~S4(#57). v3 이상에서만 켜지고, v1·v2 결과는 그대로다.

1. 버전 스위치: v3 이상만 켜진다.
2. 정답 불변: 평가 사례 20건의 정답을 AI 출력처럼 넣어도 v3 규칙이 아무것도 바꾸지 않는다(맞는 답을 망치지 않는다).
3. 남은 실패 4건: v2(10-21 10:04 실행)의 실제 출력을 화면 캡처대로 재현해 넣으면 v3 규칙으로 정답과 맞는다.
4. 평가 세트 밖 메모: 같은 규칙이 처음 보는 표현에도 동작하고, 지나치게 지우지 않는다.
"""

import asyncio
import json
from pathlib import Path

import pytest

from app.core.analysis_contract import CHECKLIST, AnalysisAIOutput
from app.features.analysis.pipeline import GeminiAnalysisPipeline
from app.features.analysis.postprocess import postprocess, strict_rules_enabled
from app.features.evals.metrics import score_case
from tests.analysis.conftest import FakeAiClient

EVAL_CASES = Path(__file__).resolve().parents[3] / "eval" / "eval_cases.json"
AI_FIELDS = tuple(AnalysisAIOutput.model_fields)


def _cases() -> dict[str, dict]:
    data = json.loads(EVAL_CASES.read_text(encoding="utf-8"))
    return {c["case_key"]: c for c in data["cases"]}


def _ai(**kw) -> AnalysisAIOutput:
    base = {"label": "매물 1", "deposit_manwon": None, "monthly_rent_manwon": None, "maintenance_fee_manwon": None,
            "maintenance_includes": [], "transit": None, "floor": None, "direction": None, "pros": [], "cons": [],
            "checks": [], "ambiguous": [], "mixed_listings": False}
    return AnalysisAIOutput.model_validate({**base, **kw})


def _check(item, status, evidence):
    return {"item": item, "status": status, "evidence": evidence}


# ------------------------------------------------------------------ 1. 버전 스위치
@pytest.mark.parametrize("version, on", [
    ("v1", False), ("v2", False), ("v3", True), ("v4", True), ("v10", True), (None, False), ("", False), ("x3", False),
])
def test_v3_rules_switch_by_prompt_version(version, on):
    assert strict_rules_enabled(version) is on


# ------------------------------------------------------------------ 2. 정답 불변
@pytest.mark.parametrize("case_key", sorted(_cases()))
def test_v3_rules_do_not_change_gold_answers(case_key):
    case = _cases()[case_key]
    expected = case["expected_json"]
    gold = AnalysisAIOutput.model_validate({k: expected[k] for k in AI_FIELDS})
    v2 = postprocess(gold, case["memo_text"], "v2")
    v3 = postprocess(gold, case["memo_text"], "v3")
    assert v3.model_dump() == v2.model_dump()
    assert score_case(expected, v3.model_dump(mode="json")).failure_codes == []


# ------------------------------------------------------------------ 3. 남은 실패 4건(v2 실제 출력 재현)
V2_OUTPUTS = {
    # 방향·'앞이 트여 있음'을 근거로 채광 confirmed → CHK
    "money_03": _ai(deposit_manwon=1000, monthly_rent_manwon=50, maintenance_fee_manwon=5, direction="북향",
                    pros=["앞이 트여 있음"],
                    checks=[_check("채광", "confirmed", "북향인데 앞이 트여 있음"), _check("수압", "confirmed", "수압 좋음")]),
    # 섞인 집인데 방향 '남향'(HAL), '첫 번째 집은 남향'으로 채광 confirmed(CHK)
    "mixed_02": _ai(direction="남향", mixed_listings=True, ambiguous=["두 번째 집은 관리비 10"],
                    checks=[_check("채광", "confirmed", "첫 번째 집은 남향"), _check("곰팡이", "confirmed", "둘 다 곰팡이 없음")]),
    # 층수·교통을 애매한 구절에만 넣고 체크에서 뺌 → CHK
    "mixed_01": _ai(mixed_listings=True, pros=["A가 채광 좋음"],
                    ambiguous=["A집 500/40 3층", "B집 1000/35 반지하", "A가 채광 좋음", "B는 역 가까움"],
                    checks=[_check("채광", "confirmed", "A가 채광 좋음")]),
    # 정정 표현을 충돌로 보고 월세 null → NUM
    "conflict_01": _ai(deposit_manwon=500, maintenance_fee_manwon=5,
                       ambiguous=["보증금 500 월세 45... 아 다시 들어보니 월세 50이래."]),
}


@pytest.mark.parametrize("case_key", sorted(V2_OUTPUTS))
def test_v3_rules_fix_remaining_v2_failures(case_key):
    case = _cases()[case_key]
    ai, memo, expected = V2_OUTPUTS[case_key], case["memo_text"], case["expected_json"]
    assert score_case(expected, postprocess(ai, memo, "v2").model_dump(mode="json")).failure_codes != []  # v2에선 실패 그대로
    out = postprocess(ai, memo, "v3").model_dump(mode="json")
    assert score_case(expected, out).failure_codes == []


def test_v3_rules_detail_of_fixed_cases():
    cases = _cases()
    conflict = postprocess(V2_OUTPUTS["conflict_01"], cases["conflict_01"]["memo_text"], "v3")
    assert conflict.monthly_rent_manwon == 50 and conflict.ambiguous == []
    mixed_01 = postprocess(V2_OUTPUTS["mixed_01"], cases["mixed_01"]["memo_text"], "v3")
    assert {"층수", "교통"} <= set(mixed_01.ambiguous_checks)
    floor_check = next(c for c in mixed_01.checks if c.item == "층수")
    assert "3층" in floor_check.evidence and "반지하" in floor_check.evidence
    mixed_02 = postprocess(V2_OUTPUTS["mixed_02"], cases["mixed_02"]["memo_text"], "v3")
    assert mixed_02.direction is None and mixed_02.confirmed_checks == ["곰팡이"]


# ------------------------------------------------------------------ 4. 평가 세트 밖 메모
def test_v3_correction_other_wording():
    memo = "보증금 300 월세 40. 잘못 들었음, 월세 42였음. 관리비 6."
    r = postprocess(_ai(deposit_manwon=300, maintenance_fee_manwon=6, ambiguous=["월세 40", "잘못 들었음, 월세 42였음"]),
                    memo, "v3")
    assert r.monthly_rent_manwon == 42 and r.ambiguous == ["월세 40"]


def test_v3_correction_does_not_overwrite_existing_value():
    memo = "보증금 1000 월세 60, 아 다시 들어보니 보증금 2000이래."
    r = postprocess(_ai(deposit_manwon=2000, monthly_rent_manwon=60), memo, "v3")
    assert (r.deposit_manwon, r.monthly_rent_manwon) == (2000, 60)


def test_v3_correction_needs_correction_word():
    memo = "월세 45, 월세 50."   # 정정 표현이 없는 충돌은 그대로 null(공통 규칙 3)
    r = postprocess(_ai(ambiguous=["월세 45", "월세 50"]), memo, "v3")
    assert r.monthly_rent_manwon is None and r.ambiguous == ["월세 45", "월세 50"]


def test_v3_mixed_listings_clear_values_and_keep_mentions():
    memo = "1번 집은 2층, 2번 집은 옥탑. 2번 집이 버스 정류장 앞. 보증금 500."
    ai = _ai(deposit_manwon=500, floor="2층", transit="버스 정류장 앞", direction="동향", mixed_listings=True,
             ambiguous=["1번 집은 2층, 2번 집은 옥탑", "2번 집이 버스 정류장 앞"])
    r = postprocess(ai, memo, "v3")
    assert (r.deposit_manwon, r.floor, r.transit, r.direction) == (None, None, None, None)
    assert r.ambiguous_checks == ["층수", "교통"] and r.confirmed_checks == []


def test_v3_mixed_listings_ignore_non_station_words():
    memo = "첫 집은 지역 분위기 조용함, 둘째 집은 소음 있음."
    ai = _ai(mixed_listings=True, ambiguous=["첫 집은 지역 분위기 조용함", "둘째 집은 소음 있음"])
    r = postprocess(ai, memo, "v3")
    assert "교통" not in r.ambiguous_checks and "교통" in r.missing_checks


def test_v3_direct_evidence_keeps_real_mentions_and_drops_guesses():
    memo = "남향이라 햇빛 잘 들어옴. 벽지에 얼룩. 수압 좋음."
    ai = _ai(direction="남향", checks=[_check("채광", "confirmed", "남향이라 햇빛 잘 들어옴"),
                                     _check("곰팡이", "confirmed", "벽지에 얼룩"),
                                     _check("수압", "confirmed", "수압 좋음")])
    r = postprocess(ai, memo, "v3")
    assert r.confirmed_checks == ["채광", "수압"] and "곰팡이" in r.missing_checks
    only_direction = postprocess(_ai(direction="북향", checks=[_check("채광", "confirmed", "북향")]), "북향.", "v3")
    assert "채광" in only_direction.missing_checks


def test_v3_rules_off_for_v2_keeps_old_behavior():
    memo = "첫 번째 집은 남향, 두 번째 집은 관리비 10. 둘 다 곰팡이 없음."
    ai = V2_OUTPUTS["mixed_02"]
    assert postprocess(ai, memo, "v2").model_dump() == postprocess(ai, memo).model_dump()
    assert postprocess(ai, memo, "v2").direction == "남향"


def test_v3_result_partition_still_holds():
    r = postprocess(V2_OUTPUTS["mixed_01"], _cases()["mixed_01"]["memo_text"], "v3")
    groups = [r.confirmed_checks, r.unchecked, r.ambiguous_checks, r.missing_checks]
    flat = [x for g in groups for x in g]
    assert len(flat) == len(set(flat)) and set(flat) == set(CHECKLIST)


def test_v3_pipeline_passes_prompt_version_to_postprocess():
    """파이프라인이 실행 버전을 후처리에 넘긴다: 같은 AI 응답이 v2에선 남향, v3에선 null."""
    case = _cases()["mixed_02"]
    reply = V2_OUTPUTS["mixed_02"].model_dump_json()
    out_v2 = asyncio.run(GeminiAnalysisPipeline(FakeAiClient(reply)).run(case["memo_text"], "v2", use_cache=False))
    out_v3 = asyncio.run(GeminiAnalysisPipeline(FakeAiClient(reply)).run(case["memo_text"], "v3", use_cache=False))
    assert out_v2.result.direction == "남향" and out_v3.result.direction is None
