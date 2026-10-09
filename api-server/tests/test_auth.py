"""실제 Supabase SDK를 사용하되 외부 HTTP 요청은 대체한다."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.dependencies import get_resources
from app.core.resources import Resources
from app.core.settings import Settings
from app.factory import create_app


USER_ID = "8d21ae65-6f90-4f6c-b0d1-19c4066af276"
CREDENTIALS = {"email": "tester@example.com", "password": "ExamplePass123!"}
USER = {
    "id": USER_ID,
    "aud": "authenticated",
    "role": "authenticated",
    "email": CREDENTIALS["email"],
    "app_metadata": {"provider": "email"},
    "user_metadata": {},
    "created_at": "2026-01-01T00:00:00Z",
}
SESSION = {
    "access_token": "test-access-token",
    "refresh_token": "test-refresh-token",
    "token_type": "bearer",
    "expires_in": 3600,
    "user": USER,
}


@pytest.fixture
def auth_api():
    settings = Settings(
        supabase_url="https://project.supabase.co",
        supabase_publishable_key="sb_publishable_test",
        redis_url="redis://localhost:6379/0",
    )
    requests = []
    responses = []

    def handle(request):
        requests.append(request)
        status, body = responses.pop(0)
        return httpx.Response(status, json=body, headers={"x-supabase-api-version": "2024-01-01"})

    mock_http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    app = create_app(settings)
    app.dependency_overrides[get_resources] = lambda: Resources(settings, mock_http, None)
    with TestClient(app) as client:
        try:
            yield client, requests, responses
        finally:
            client.portal.call(mock_http.aclose)


@pytest.mark.parametrize("confirmed", [False, True])
def test_signup(auth_api, confirmed):
    client, requests, responses = auth_api
    responses.append((200, SESSION if confirmed else USER))
    response = client.post("/auth/signup", json=CREDENTIALS)
    assert response.status_code == 201
    assert response.json() == {
        "user_id": USER_ID,
        "email_confirmation_required": not confirmed,
    }
    assert requests[0].url.path == "/auth/v1/signup"
    assert requests[0].headers["apikey"] == "sb_publishable_test"
    assert json.loads(requests[0].content)["password"] == CREDENTIALS["password"]


def test_login_and_request_isolation(auth_api):
    client, requests, responses = auth_api
    responses.extend([(200, SESSION), (200, SESSION)])
    for _ in range(2):
        response = client.post("/auth/login", json=CREDENTIALS)
        assert response.status_code == 200
        assert response.json()["access_token"] == "test-access-token"
        assert response.json()["refresh_token"] == "test-refresh-token"
        assert response.json()["user_id"] == USER_ID
    for request in requests:
        assert request.url.path == "/auth/v1/token"
        assert request.url.params["grant_type"] == "password"
        assert request.headers["authorization"] == "Bearer sb_publishable_test"


@pytest.mark.parametrize("path,status,code,expected_status,expected_code", [
    ("login", 400, "invalid_credentials", 401, "AUTH_REJECTED"),
    ("login", 400, "email_not_confirmed", 403, "EMAIL_UNCONFIRMED"),
    ("signup", 422, "user_already_exists", 409, "SIGNUP_REJECTED"),
    ("signup", 429, "over_email_send_rate_limit", 429, "AUTH_RATE_LIMIT"),
])
def test_auth_errors(auth_api, path, status, code, expected_status, expected_code):
    client, _, responses = auth_api
    responses.append((status, {"code": code, "msg": "Authentication failed"}))
    response = client.post(f"/auth/{path}", json=CREDENTIALS)
    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == expected_code
    assert response.json()["request_id"]
    assert CREDENTIALS["password"] not in response.text


def test_reject_dashboard_url():
    with pytest.raises(ValidationError, match="프로젝트 API URL"):
        Settings(
            supabase_url="https://supabase.com/dashboard/project/example",
            supabase_publishable_key="sb_publishable_test",
            redis_url="redis://localhost:6379/0",
        )
