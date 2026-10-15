"""F4 분석 파이프라인 (AnalysisPipeline 구현). P7 평가도 get_pipeline()으로 이것을 쓴다.

흐름: 캐시 확인 → Gemini 호출 → AnalysisAIOutput 검증 → 실패 시 1회 재시도 → F5 후처리(AnalysisResult) → AnalysisOutcome

- 캐시: use_cache이고 cache_scope가 있을 때만. 키 analysis:{cache_scope}:{memo_hash}:{prompt_version}:{model}:{thinking_level}.
  성공 결과(raw_output 포함)를 CACHE_TTL_SEC 동안 저장. KV가 없거나 장애면 캐시 없이 동작한다.
- 재시도: 처음 입력 뒤에 "직전 응답이 형식 검증에 실패했다: {요약}. 같은 스키마로 다시 답하라"를 덧붙인다
  (상태를 남기지 않는 input 이어 쓰기. previous_interaction_id는 쓰지 않는다).
- raw_output: 시도마다 "--- attempt N ---" 머리줄과 받은 원문을 이어 붙인다. 형식 실패여도 담는다.
- 실패 outcome.error_code: FMT(형식 2회 실패) · AI_TIMEOUT · AI_RATE_LIMITED · AI_UPSTREAM_ERROR.
  API 키 없음·거부는 outcome이 아니라 AppError 503 CONFIG_MISSING으로 올린다.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from pydantic import ValidationError

from app.core.analysis_contract import AnalysisAIOutput, AnalysisOutcome, AnalysisResult, memo_hash
from app.core.config import settings
from app.core.kv import get_kv, kv_available
from app.features.analysis.gemini_client import AiCallError, AiClient, GoogleGenAIClient, to_gemini_schema
from app.features.analysis.postprocess import FormatError, parse_ai_output, postprocess
from app.features.analysis.prompts_loader import build_retry_input, build_user_input, load_prompt

logger = logging.getLogger("app.analysis.pipeline")

MAX_ATTEMPTS = 2            # 처음 1회 + 형식 실패 시 재시도 1회
FORMAT_ERROR_CODE = "FMT"


def cache_key(cache_scope: str, memo_text: str, prompt_version: str, model: str, thinking_level: str) -> str:
    return f"analysis:{cache_scope}:{memo_hash(memo_text)}:{prompt_version}:{model}:{thinking_level}"


def attempt_header(n: int) -> str:
    return f"--- attempt {n} ---"


_SCHEMA_CACHE: dict | None = None


def response_schema() -> dict:
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is None:
        _SCHEMA_CACHE = to_gemini_schema(AnalysisAIOutput)
    return _SCHEMA_CACHE


class GeminiAnalysisPipeline:
    """AnalysisPipeline 구현. ai_client를 바꿔 끼우면 테스트에서 Gemini 없이 돈다."""

    def __init__(self, ai_client: AiClient | None = None, *, model: str | None = None,
                 thinking_level: str | None = None, timeout_sec: float | None = None):
        self._ai_client = ai_client
        self._model = model
        self._thinking_level = thinking_level
        self._timeout_sec = timeout_sec

    # 설정은 실행할 때마다 읽는다(환경변수·테스트 변경 반영)
    @property
    def ai_client(self) -> AiClient:
        if self._ai_client is None:
            self._ai_client = GoogleGenAIClient()
        return self._ai_client

    @property
    def model(self) -> str:
        return self._model or settings.GEMINI_MODEL

    @property
    def thinking_level(self) -> str:
        return self._thinking_level or settings.GEMINI_THINKING_LEVEL

    @property
    def timeout_sec(self) -> float:
        return float(self._timeout_sec or settings.GEMINI_TIMEOUT_SEC)

    # ------------------------------------------------------------ 캐시
    @staticmethod
    def _cache_get(key: str) -> dict | None:
        try:
            if not kv_available():
                return None
            raw = get_kv().get(key)
            return json.loads(raw) if raw else None
        except Exception as exc:  # 캐시는 없어도 된다
            logger.warning("analysis cache get skipped: %s", type(exc).__name__)
            return None

    @staticmethod
    def _cache_set(key: str, value: dict) -> None:
        try:
            if not kv_available():
                return
            get_kv().set(key, json.dumps(value, ensure_ascii=False), settings.CACHE_TTL_SEC)
        except Exception as exc:
            logger.warning("analysis cache set skipped: %s", type(exc).__name__)

    def _outcome(self, prompt_version: str, **kw: Any) -> AnalysisOutcome:
        return AnalysisOutcome(prompt_version=prompt_version, model=self.model,
                               thinking_level=self.thinking_level, **kw)

    # ------------------------------------------------------------ 실행
    async def run(self, memo_text: str, prompt_version: str, *, use_cache: bool = True,
                  cache_scope: str | None = None) -> AnalysisOutcome:
        system_instruction = load_prompt(prompt_version)       # 없는 버전이면 422
        model, level = self.model, self.thinking_level

        key = None
        if use_cache and cache_scope:
            key = cache_key(str(cache_scope), memo_text, prompt_version, model, level)
            cached = await asyncio.to_thread(self._cache_get, key)
            if cached:
                try:
                    result = AnalysisResult.model_validate(cached["result"])
                    return self._outcome(prompt_version, result=result, raw_output=cached.get("raw_output"),
                                         ai_latency_ms=None, status="success", cache_hit=True)
                except (ValidationError, KeyError, TypeError):
                    logger.warning("analysis cache entry invalid; ignored")

        first_input = build_user_input(memo_text)
        user_input = first_input
        raws: list[str] = []
        ai_latency = 0

        def joined_raw() -> str | None:
            return "\n".join(raws) if raws else None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                reply = await self.ai_client.generate(
                    system_instruction=system_instruction, user_input=user_input, schema=response_schema(),
                    model=model, thinking_level=level, timeout_sec=self.timeout_sec,
                )
            except AiCallError as exc:
                ai_latency += exc.latency_ms or 0
                return self._outcome(prompt_version, result=None, raw_output=joined_raw(),
                                     ai_latency_ms=ai_latency, status="failed", error_code=exc.code)
            ai_latency += reply.latency_ms
            raws.append(f"{attempt_header(attempt)}\n{reply.text or ''}")
            try:
                ai = parse_ai_output(reply.text)
            except FormatError as exc:
                logger.info("analysis format error attempt=%d", attempt)
                user_input = build_retry_input(first_input, exc.summary)
                continue
            result = postprocess(ai, memo_text)
            outcome = self._outcome(prompt_version, result=result, raw_output=joined_raw(),
                                    ai_latency_ms=ai_latency, status="success")
            if key:
                await asyncio.to_thread(self._cache_set, key, {
                    "result": result.model_dump(mode="json"), "raw_output": outcome.raw_output,
                    "ai_latency_ms": ai_latency,
                })
            return outcome

        return self._outcome(prompt_version, result=None, raw_output=joined_raw(), ai_latency_ms=ai_latency,
                             status="failed", error_code=FORMAT_ERROR_CODE)
