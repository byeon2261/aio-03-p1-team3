"""P2 분석 테스트 도구. Gemini는 FakeAiClient(가짜)로 바꾼다."""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.core.analysis_contract import register_pipeline
from app.features.analysis.gemini_client import AiCallError, AiReply
from app.features.analysis.pipeline import GeminiAnalysisPipeline

EXAMPLE_MEMO = (
    "2번 집. 신림역 도보 8분. 500에 45, 관리비 7(인터넷 포함). 남향이라 채광 좋음.\n"
    "화장실 천장에 곰팡이 조금. 옆 건물이랑 가까워서 창문 열면 보임. 수압 확인 못함."
)


def example_ai_json(**overrides: Any) -> dict:
    data = {
        "label": "2번 집", "deposit_manwon": 500, "monthly_rent_manwon": 45, "maintenance_fee_manwon": 7,
        "maintenance_includes": ["인터넷"], "transit": "신림역 도보 8분", "floor": None, "direction": "남향",
        "pros": ["남향이라 채광 좋음"], "cons": ["화장실 천장에 곰팡이 조금", "옆 건물이랑 가까워서 창문 열면 보임"],
        "checks": [
            {"item": "채광", "status": "confirmed", "evidence": "남향이라 채광 좋음"},
            {"item": "곰팡이", "status": "confirmed", "evidence": "화장실 천장에 곰팡이 조금"},
            {"item": "교통", "status": "confirmed", "evidence": "신림역 도보 8분"},
            {"item": "수압", "status": "unchecked", "evidence": "수압 확인 못함"},
        ],
        "ambiguous": [], "mixed_listings": False,
    }
    data.update(overrides)
    return data


def example_ai_text(**overrides: Any) -> str:
    return json.dumps(example_ai_json(**overrides), ensure_ascii=False)


class FakeAiClient:
    """미리 넣어 둔 응답(문자열 또는 AiCallError)을 차례로 돌려준다. 마지막 응답은 반복한다."""

    def __init__(self, *responses: Any, latency_ms: int = 100):
        self.responses = list(responses) or [example_ai_text()]
        self.latency_ms = latency_ms
        self.calls: list[dict] = []

    async def generate(self, *, system_instruction: str, user_input: str, schema: dict, model: str,
                       thinking_level: str, timeout_sec: float) -> AiReply:
        self.calls.append({"system_instruction": system_instruction, "user_input": user_input, "schema": schema,
                           "model": model, "thinking_level": thinking_level, "timeout_sec": timeout_sec})
        idx = min(len(self.calls) - 1, len(self.responses) - 1)
        r = self.responses[idx]
        if isinstance(r, Exception):
            raise r
        return AiReply(text=r, latency_ms=self.latency_ms, interaction_id=f"fake-{len(self.calls)}")


def timeout_error() -> AiCallError:
    return AiCallError("AI_TIMEOUT", 30000)


def rate_limit_error() -> AiCallError:
    return AiCallError("AI_RATE_LIMITED", 50, 429)


@pytest.fixture
def fake_ai() -> FakeAiClient:
    return FakeAiClient()


@pytest.fixture
def use_fake_ai():
    """use_fake_ai(FakeAiClient(...)) → 그 가짜로 도는 실제 파이프라인을 등록하고 돌려준다."""

    def _use(ai: FakeAiClient, **kw: Any) -> GeminiAnalysisPipeline:
        p = GeminiAnalysisPipeline(ai, **kw)
        register_pipeline(p)
        return p

    return _use


@pytest.fixture
def make_listing(memory_db):
    """make_listing(user, memo) → listings 행(dict). 세션도 함께 만든다."""

    def _make(user, memo: str = EXAMPLE_MEMO, session_id: str | None = None) -> dict:
        if session_id is None:
            session_id = memory_db.insert("tour_sessions", {"profile_id": user.profile_id, "title": "토요일"})[0]["id"]
        return memory_db.insert("listings", {"session_id": session_id, "memo_text": memo})[0]

    return _make


def logs_for(memory_db, endpoint_part: str, method: str = "POST") -> list[dict]:
    return [r for r in memory_db.select("request_logs", order_by="id")
            if endpoint_part in (r.get("endpoint") or "") and r.get("method") == method]
