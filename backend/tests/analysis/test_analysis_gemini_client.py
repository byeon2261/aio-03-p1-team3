"""google-genai SDK가 실제로 보내는 요청 모양과 오류 변환 (네트워크 없이 httpx MockTransport)."""

import asyncio
import json

import httpx
import pytest

from app.core.analysis_contract import AnalysisAIOutput
from app.core.errors import AppError
from app.features.analysis.gemini_client import AiCallError, GoogleGenAIClient, to_gemini_schema


def _interaction(text: str) -> dict:
    return {"id": "int_1", "status": "completed", "model": "gemini-3.5-flash-lite",
            "steps": [{"type": "user_input", "content": [{"type": "text", "text": "q"}]},
                      {"type": "model_output", "content": [{"type": "text", "text": text}]}]}


def _client(handler) -> GoogleGenAIClient:
    return GoogleGenAIClient(api_key="test-key",
                             httpx_async_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def _call(c: GoogleGenAIClient, timeout_sec: float = 5):
    return asyncio.run(c.generate(system_instruction="SYS", user_input="<memo>m</memo>",
                                  schema=to_gemini_schema(AnalysisAIOutput), model="gemini-3.5-flash-lite",
                                  thinking_level="minimal", timeout_sec=timeout_sec))


def test_analysis_gemini_request_shape():
    seen = []

    def handler(req: httpx.Request):
        seen.append((str(req.url), json.loads(req.content)))
        return httpx.Response(200, json=_interaction('{"label": "a"}'))

    reply = _call(_client(handler))
    assert reply.text == '{"label": "a"}' and reply.interaction_id == "int_1"
    url, body = seen[0]
    assert url.endswith("/interactions")
    assert body["model"] == "gemini-3.5-flash-lite"
    assert body["system_instruction"] == "SYS" and body["input"] == "<memo>m</memo>"
    assert body["generation_config"] == {"thinking_level": "minimal"}
    assert body["response_format"]["type"] == "text"
    assert body["response_format"]["mime_type"] == "application/json"
    sent = json.dumps(body)
    for banned in ("temperature", "top_p", "top_k", "$ref", "$defs", "anyOf", "\"default\""):
        assert banned not in sent


def test_analysis_gemini_schema_uses_documented_subset():
    s = to_gemini_schema(AnalysisAIOutput)
    props = s["properties"]
    assert props["deposit_manwon"]["type"] == ["integer", "null"]
    assert props["floor"]["type"] == ["string", "null"]
    check = props["checks"]["items"]
    assert check["properties"]["item"]["enum"][0] == "채광"
    assert check["properties"]["status"]["enum"] == ["confirmed", "unchecked", "ambiguous"]
    assert set(s["required"]) == set(props)
    assert set(check["required"]) == {"item", "status", "evidence"}


def test_analysis_gemini_429_not_retried():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(429, json={"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}})

    with pytest.raises(AiCallError) as e:
        _call(_client(handler))
    assert e.value.code == "AI_RATE_LIMITED" and len(calls) == 1


def test_analysis_gemini_timeout():
    def handler(req):
        raise httpx.ReadTimeout("slow", request=req)

    with pytest.raises(AiCallError) as e:
        _call(_client(handler))
    assert e.value.code == "AI_TIMEOUT"


def test_analysis_gemini_overall_timeout():
    async def handler(req):
        await asyncio.sleep(2)
        return httpx.Response(200, json=_interaction("{}"))

    with pytest.raises(AiCallError) as e:
        _call(_client(handler), timeout_sec=0.2)
    assert e.value.code == "AI_TIMEOUT"


def test_analysis_gemini_bad_key_is_config_missing():
    def handler(req):
        return httpx.Response(403, json={"error": {"code": 403, "message": "denied", "status": "PERMISSION_DENIED"}})

    with pytest.raises(AppError) as e:
        _call(_client(handler))
    assert e.value.status == 503 and e.value.code == "CONFIG_MISSING"


def test_analysis_gemini_400_is_upstream_error():
    def handler(req):
        return httpx.Response(400, json={"error": {"code": 400, "message": "bad schema", "status": "INVALID_ARGUMENT"}})

    with pytest.raises(AiCallError) as e:
        _call(_client(handler))
    assert e.value.code == "AI_UPSTREAM_ERROR" and e.value.status == 400


def test_analysis_gemini_missing_key(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "GEMINI_API_KEY", None)
    with pytest.raises(AppError) as e:
        _call(GoogleGenAIClient())
    assert e.value.code == "CONFIG_MISSING"
