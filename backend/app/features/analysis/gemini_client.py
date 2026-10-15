"""Gemini 호출 어댑터 (SDK google-genai, Interactions API).

- 모델·thinking_level·시간 제한은 settings에서 읽는다. temperature·top_p·top_k는 보내지 않는다.
- 응답은 JSON 스키마(response_format)로 강제한다. 스키마는 공식 문서 지원 범위로 바꿔 보낸다
  ($ref 펼치기, anyOf[X, null] → "type": [X, "null"], default 제거, 모든 속성 required).
- 오류는 AiCallError(code)로 바꾼다: AI_TIMEOUT · AI_RATE_LIMITED · AI_UPSTREAM_ERROR.
  API 키가 없거나 거부되면 AppError 503 CONFIG_MISSING.
- 로그에는 오류 종류·상태 코드만 남긴다(메모 원문·키 금지).
"""

from __future__ import annotations

import asyncio
import copy
import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel

from app.core.config import settings
from app.core.errors import AppError

logger = logging.getLogger("app.analysis.gemini")


# ------------------------------------------------------------------ 결과·오류
@dataclass
class AiReply:
    text: str | None          # interaction.output_text (없으면 None)
    latency_ms: int
    interaction_id: str | None = None


class AiCallError(Exception):
    """Gemini 호출 실패. code: AI_TIMEOUT / AI_RATE_LIMITED / AI_UPSTREAM_ERROR."""

    def __init__(self, code: str, latency_ms: int | None = None, status: int | None = None):
        super().__init__(code)
        self.code = code
        self.latency_ms = latency_ms
        self.status = status


class AiClient(Protocol):
    async def generate(self, *, system_instruction: str, user_input: str, schema: dict,
                       model: str, thinking_level: str, timeout_sec: float) -> AiReply: ...


# ------------------------------------------------------------------ 응답 스키마 변환
_DROP_KEYS = {"default", "$defs", "definitions"}


def to_gemini_schema(model: type[BaseModel]) -> dict:
    """Pydantic JSON 스키마를 공식 문서 지원 범위로 바꾼다.

    지원 범위(2026-10 Structured outputs 문서): type(string·number·integer·boolean·object·array·null 배열),
    title, description, properties, required, additionalProperties, enum, format, minimum, maximum,
    items, prefixItems, minItems, maxItems.
    """
    raw = model.model_json_schema()
    defs = raw.get("$defs", {}) or raw.get("definitions", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, list):
            return [resolve(x) for x in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            name = node["$ref"].rsplit("/", 1)[-1]
            merged = {**copy.deepcopy(defs[name]), **{k: v for k, v in node.items() if k != "$ref"}}
            return resolve(merged)
        if "anyOf" in node:
            options = [resolve(o) for o in node["anyOf"]]
            non_null = [o for o in options if o.get("type") != "null"]
            has_null = len(non_null) != len(options)
            if has_null and len(non_null) == 1 and isinstance(non_null[0].get("type"), str):
                base = {k: v for k, v in node.items() if k not in ("anyOf",) and k not in _DROP_KEYS}
                inner = non_null[0]
                out = {**inner, **base, "type": [inner["type"], "null"]}
                return resolve(out)
            # 그 밖의 anyOf는 쓰지 않는다(AnalysisAIOutput에는 없음)
            raise ValueError("지원하지 않는 anyOf 형태")
        out = {}
        for k, v in node.items():
            if k in _DROP_KEYS:
                continue
            out[k] = resolve(v)
        if out.get("type") == "object" and isinstance(out.get("properties"), dict):
            out["required"] = list(out["properties"].keys())   # 없는 값도 null로 반드시 쓰게 한다
        return out

    return resolve({k: v for k, v in raw.items() if k not in _DROP_KEYS})


# ------------------------------------------------------------------ 실제 구현
def _status_of(exc: BaseException) -> int | None:
    for attr in ("status_code", "code"):
        v = getattr(exc, attr, None)
        if isinstance(v, int):
            return v
    return None


def _is_timeout(exc: BaseException) -> bool:
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return True
    try:
        import httpx

        if isinstance(exc, httpx.TimeoutException):
            return True
    except ImportError:  # pragma: no cover
        pass
    return "timeout" in type(exc).__name__.lower()


class GoogleGenAIClient:
    """google-genai 비동기 클라이언트(client.aio.interactions.create)로 부른다."""

    def __init__(self, api_key: str | None = None, *, httpx_async_client: Any = None):
        self._api_key = api_key
        self._httpx_async_client = httpx_async_client   # 테스트에서 가짜 전송 계층을 끼울 때만
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            if not self._api_key:
                settings.require("GEMINI_API_KEY")
            from google import genai
            from google.genai import types

            options: dict[str, Any] = dict(
                timeout=int(settings.GEMINI_TIMEOUT_SEC * 1000),
                # SDK 자동 재시도는 503에만 1회. 429는 바로 돌려받아 AI_RATE_LIMITED로 알린다.
                retry_options=types.HttpRetryOptions(attempts=1, http_status_codes=[503]),
            )
            if self._httpx_async_client is not None:
                options["httpx_async_client"] = self._httpx_async_client
            self._client = genai.Client(api_key=self._api_key or settings.GEMINI_API_KEY,
                                        http_options=types.HttpOptions(**options))
        return self._client

    async def generate(self, *, system_instruction: str, user_input: str, schema: dict,
                       model: str, thinking_level: str, timeout_sec: float) -> AiReply:
        client = self._get_client()
        started = time.perf_counter()

        def elapsed() -> int:
            return int((time.perf_counter() - started) * 1000)

        try:
            interaction = await asyncio.wait_for(
                client.aio.interactions.create(
                    model=model,
                    system_instruction=system_instruction,
                    input=user_input,
                    response_format={"type": "text", "mime_type": "application/json", "schema": schema},
                    generation_config={"thinking_level": thinking_level},
                ),
                timeout=timeout_sec,
            )
        except AppError:
            raise
        except Exception as exc:  # noqa: BLE001 — SDK 예외 종류가 버전마다 다르다
            status = _status_of(exc)
            name = type(exc).__name__
            if _is_timeout(exc):
                logger.warning("gemini timeout type=%s", name)
                raise AiCallError("AI_TIMEOUT", elapsed()) from None
            if status == 429 or "RESOURCE_EXHAUSTED" in str(getattr(exc, "status", "")):
                logger.warning("gemini rate limited type=%s", name)
                raise AiCallError("AI_RATE_LIMITED", elapsed(), 429) from None
            if status in (401, 403):
                logger.error("gemini auth rejected status=%s", status)
                raise AppError(503, "CONFIG_MISSING", "AI 설정을 확인해야 합니다. 관리자에게 알려 주세요.",
                               {"missing": ["GEMINI_API_KEY"]}) from None
            logger.error("gemini call failed type=%s status=%s", name, status)
            raise AiCallError("AI_UPSTREAM_ERROR", elapsed(), status) from None

        text = getattr(interaction, "output_text", None)
        return AiReply(text=text if isinstance(text, str) else None, latency_ms=elapsed(),
                       interaction_id=getattr(interaction, "id", None))
