"""frontend/core/api.py: 서버 연결을 httpx.Client 하나로 재사용하고, 토큰은 요청마다 따로 붙인다. 서버는 가짜."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"
if str(FRONTEND_DIR) not in sys.path:
    sys.path.append(str(FRONTEND_DIR))

from core import api  # noqa: E402


@pytest.fixture
def fake_server(monkeypatch):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/missing":
            return httpx.Response(404, json={"error": {"code": "NOT_FOUND", "message": "없음"}})
        return httpx.Response(200, json={"path": request.url.path})

    token = {"value": "token-a"}
    monkeypatch.setattr(api, "_client", httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(api, "base_url", lambda: "http://api.test")
    monkeypatch.setattr(api.state, "expires_at", lambda: None)
    monkeypatch.setattr(api.state, "refresh_token", lambda: None)
    monkeypatch.setattr(api.state, "access_token", lambda: token["value"])
    return seen, token


def test_requests_share_one_client(fake_server):
    seen, _ = fake_server
    first = api._http()
    assert api.api_get("/sessions") == {"path": "/sessions"}
    assert api.api_post("/sessions", json={"title": "토요일"}) == {"path": "/sessions"}
    assert api.ping_health() is True
    assert api._http() is first and len(seen) == 3


def test_token_is_attached_per_request(fake_server):
    seen, token = fake_server
    api.api_get("/a")
    token["value"] = "token-b"                      # 다른 사용자(세션)의 요청
    api.api_get("/b")
    assert [r.headers["Authorization"] for r in seen] == ["Bearer token-a", "Bearer token-b"]


def test_error_still_becomes_api_error(fake_server):
    with pytest.raises(api.ApiError) as e:
        api.api_get("/missing")
    assert e.value.status == 404 and e.value.code == "NOT_FOUND"


def test_http_creates_client_lazily(monkeypatch):
    monkeypatch.setattr(api, "_client", None)
    client = api._http()
    try:
        assert isinstance(client, httpx.Client) and api._http() is client
    finally:
        client.close()
