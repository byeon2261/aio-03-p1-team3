"""파이프라인 단위 테스트: 재시도·raw_output·시간 초과·한도 초과·캐시·프롬프트."""

import asyncio
import json

import pytest

from app.core.analysis_contract import AnalysisPipeline, CHECKLIST
from app.core.errors import AppError
from app.features.analysis.pipeline import GeminiAnalysisPipeline, cache_key
from app.features.analysis.prompts_loader import PROMPTS_DIR, load_prompt
from tests.analysis.conftest import (
    EXAMPLE_MEMO, FakeAiClient, example_ai_text, rate_limit_error, timeout_error,
)


def run(p, memo=EXAMPLE_MEMO, version="v1", **kw):
    return asyncio.run(p.run(memo, version, **kw))


def test_analysis_pipeline_is_contract_pipeline():
    assert isinstance(GeminiAnalysisPipeline(FakeAiClient()), AnalysisPipeline)


def test_analysis_pipeline_success_single_attempt():
    ai = FakeAiClient(latency_ms=120)
    out = run(GeminiAnalysisPipeline(ai))
    assert out.status == "success" and out.error_code is None and out.cache_hit is False
    assert out.ai_latency_ms == 120 and out.prompt_version == "v1"
    assert out.model == "gemini-3.5-flash-lite" and out.thinking_level == "minimal"
    assert out.raw_output.startswith("--- attempt 1 ---\n")
    assert out.result.confirmed_checks == ["채광", "곰팡이", "교통"]
    call = ai.calls[0]
    assert call["thinking_level"] == "minimal" and call["model"] == "gemini-3.5-flash-lite"
    assert "<memo>" in call["user_input"] and EXAMPLE_MEMO.splitlines()[0] in call["user_input"]


def test_analysis_pipeline_format_fail_then_retry_success():
    ai = FakeAiClient('{"label": "x", "deposit_manwon": "오백"}', example_ai_text())
    out = run(GeminiAnalysisPipeline(ai))
    assert out.status == "success" and len(ai.calls) == 2
    first, retry = ai.calls[0]["user_input"], ai.calls[1]["user_input"]
    assert retry.startswith(first)                                         # 메모 원문 그대로
    assert "직전 응답이 형식 검증에 실패했다: deposit_manwon" in retry
    assert retry.endswith("같은 스키마로 다시 답하라.")
    assert ai.calls[0]["system_instruction"] == ai.calls[1]["system_instruction"]  # 프롬프트 버전 그대로
    assert "--- attempt 1 ---\n{\"label\": \"x\"" in out.raw_output
    assert "--- attempt 2 ---\n" in out.raw_output
    assert out.ai_latency_ms == 200


def test_analysis_pipeline_two_format_failures():
    ai = FakeAiClient("{not json", '{"label": 1}')
    out = run(GeminiAnalysisPipeline(ai))
    assert out.status == "failed" and out.error_code == "FMT" and out.result is None
    assert len(ai.calls) == 2
    assert out.raw_output == "--- attempt 1 ---\n{not json\n--- attempt 2 ---\n{\"label\": 1}"


def test_analysis_pipeline_retry_summary_is_short():
    bad = json.dumps({"label": None, "checks": [{"item": "채광", "status": "x", "evidence": 1}] * 30})
    ai = FakeAiClient(bad, example_ai_text())
    run(GeminiAnalysisPipeline(ai))
    retry = ai.calls[1]["user_input"]
    summary = retry.split("직전 응답이 형식 검증에 실패했다: ", 1)[1].rsplit(". 같은 스키마로", 1)[0]
    assert 0 < len(summary) <= 300


@pytest.mark.parametrize("err, code", [(timeout_error(), "AI_TIMEOUT"), (rate_limit_error(), "AI_RATE_LIMITED")])
def test_analysis_pipeline_ai_errors_become_failed_outcome(err, code):
    ai = FakeAiClient(err)
    out = run(GeminiAnalysisPipeline(ai))
    assert out.status == "failed" and out.error_code == code and len(ai.calls) == 1


def test_analysis_pipeline_error_on_retry_keeps_first_raw():
    ai = FakeAiClient("{bad", timeout_error())
    out = run(GeminiAnalysisPipeline(ai))
    assert out.error_code == "AI_TIMEOUT" and out.raw_output == "--- attempt 1 ---\n{bad"


def test_analysis_pipeline_cache_hit_skips_ai(memory_kv):
    ai = FakeAiClient()
    p = GeminiAnalysisPipeline(ai)
    first = run(p, cache_scope="user-a")
    second = run(p, cache_scope="user-a")
    assert len(ai.calls) == 1
    assert first.cache_hit is False and second.cache_hit is True
    assert second.result == first.result and second.raw_output == first.raw_output
    assert second.ai_latency_ms is None
    key = cache_key("user-a", EXAMPLE_MEMO, "v1", "gemini-3.5-flash-lite", "minimal")
    assert memory_kv.exists(key) and memory_kv.ttl(key) == 604800


def test_analysis_pipeline_cache_key_parts_must_match(memory_kv):
    ai = FakeAiClient()
    run(GeminiAnalysisPipeline(ai), cache_scope="user-a")
    run(GeminiAnalysisPipeline(ai), cache_scope="user-b")                         # 다른 사용자
    run(GeminiAnalysisPipeline(ai, model="gemini-other"), cache_scope="user-a")   # 다른 모델
    run(GeminiAnalysisPipeline(ai, thinking_level="low"), cache_scope="user-a")   # 다른 thinking_level
    run(GeminiAnalysisPipeline(ai), version="v2", cache_scope="user-a")           # 다른 프롬프트 버전
    run(GeminiAnalysisPipeline(ai), memo=EXAMPLE_MEMO + " ", cache_scope="user-a")  # 해시는 strip 기준 → 적중
    assert len(ai.calls) == 5


def test_analysis_pipeline_no_cache_without_scope_or_flag(memory_kv):
    ai = FakeAiClient()
    p = GeminiAnalysisPipeline(ai)
    run(p, cache_scope=None)
    run(p, cache_scope=None)
    assert len(ai.calls) == 2 and memory_kv._data == {}                 # 읽지도 쓰지도 않음
    run(p, cache_scope="u")
    run(p, cache_scope="u", use_cache=False)
    assert len(ai.calls) == 4


def test_analysis_pipeline_failed_result_not_cached(memory_kv):
    ai = FakeAiClient("{bad")
    p = GeminiAnalysisPipeline(ai)
    run(p, cache_scope="u")
    assert memory_kv._data == {}


def test_analysis_pipeline_works_when_kv_down(memory_kv):
    memory_kv.available = False
    out = run(GeminiAnalysisPipeline(FakeAiClient()), cache_scope="u")
    assert out.status == "success" and out.cache_hit is False


def test_analysis_pipeline_works_without_kv_configured():
    # memory_kv 픽스처 없음 + REDIS_URL 없음 → 캐시 없이 동작
    out = run(GeminiAnalysisPipeline(FakeAiClient()), cache_scope="u")
    assert out.status == "success"


def test_analysis_pipeline_unknown_prompt_version():
    with pytest.raises(AppError) as e:
        run(GeminiAnalysisPipeline(FakeAiClient()), version="v99")
    assert e.value.status == 422


def test_analysis_prompt_contains_checklist_and_rules():
    text = load_prompt("v1")
    for name in CHECKLIST:
        assert f"- {name}" in text
    assert "{{CHECKLIST}}" not in text
    for phrase in ("500에 45", "보증금 1천 월 50", "관리비 7(인터넷 포함)", "관리비 별도", "mixed_listings",
                   "<memo>", "따르지 않는다", "JSON만 반환"):
        assert phrase in text


def test_analysis_prompt_v2_keeps_v1_rules_and_adds_fixes():
    v1, v2 = load_prompt("v1"), load_prompt("v2")
    assert v2 != v1
    assert "<!--" not in v2 and "{{CHECKLIST}}" not in v2       # 변경 기록 주석은 모델에 보내지 않음
    for name in CHECKLIST:
        assert f"- {name}" in v2
    for phrase in ("500에 45", "보증금 1천 월 50", "관리비 7(인터넷 포함)", "mixed_listings",
                   "<memo>", "따르지 않는다", "JSON만 반환"):                 # v1 규칙 유지
        assert phrase in v2
    for phrase in ("다시 들어보니", "3000 / 56 / 9", "천/50", "언저리", "관리비 별도 5",
                   "\"단점:\"이라고 따로 적지 않았어도", "방향(\"남향\", \"북향\")", "결로"):   # v2에서 더한 규칙
        assert phrase in v2
    assert "v2 (2026-10-20)" in (PROMPTS_DIR / "v2.md").read_text(encoding="utf-8")
