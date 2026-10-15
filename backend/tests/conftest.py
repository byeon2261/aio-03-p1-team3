"""공통 픽스처. backend 폴더에서 `pytest -q`.

    def test_x(memory_db, make_user, client_as):
        alice = make_user()
        c = client_as(alice)            # 의존성을 모두 가짜로 바꾼 TestClient (Authorization 헤더 자동)
        r = c.get("/me")

client_as(None)은 로그인하지 않은 클라이언트다(인증은 FakeAuthProvider가 실제로 검사).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.core import analysis_contract, broker, events, kv, registry
from app.core.auth import CurrentUser, get_current_user, mark_request_user
from app.core.auth_provider import get_auth_provider
from app.core.db import get_admin_db, get_user_db
from app.core.storage import get_storage
from tests.fakes import FakeAuthProvider, MemoryBroker, MemoryDatabase, MemoryKV, MemoryStorage


@pytest.fixture(autouse=True)
def reset_registries():
    """테스트마다 등록부(비교표 열·행 필터, 이벤트, 분석 파이프라인)와 KV·브로커 교체를 초기화한다."""
    registry.reset_registry()
    events.reset_events()
    analysis_contract.reset_pipeline()
    kv.use_kv(None)
    broker.use_broker(None)
    yield
    registry.reset_registry()
    events.reset_events()
    analysis_contract.reset_pipeline()
    kv.use_kv(None)
    broker.use_broker(None)


@pytest.fixture
def memory_db() -> MemoryDatabase:
    return MemoryDatabase()


@pytest.fixture
def memory_kv() -> MemoryKV:
    store = MemoryKV()
    kv.use_kv(store)
    return store


@pytest.fixture
def memory_storage() -> MemoryStorage:
    return MemoryStorage()


@pytest.fixture
def memory_broker() -> MemoryBroker:
    b = MemoryBroker()
    broker.use_broker(b)
    return b


@pytest.fixture
def fake_auth() -> FakeAuthProvider:
    return FakeAuthProvider()


@pytest.fixture
def make_user(memory_db, fake_auth):
    """profiles 행을 만들고 유효한 토큰을 가진 CurrentUser를 돌려준다."""

    def _make(role: str = "user", nickname: str | None = None, email: str | None = None) -> CurrentUser:
        auth_user_id = str(uuid.uuid4())
        email = email or f"{auth_user_id[:8]}@example.com"
        row = memory_db.insert("profiles", {"auth_user_id": auth_user_id,
                                            "nickname": nickname or email.split("@")[0], "role": role})[0]
        token = fake_auth.issue_token(auth_user_id, email)
        return CurrentUser(auth_user_id=auth_user_id, profile_id=row["id"], role=role, access_token=token)

    return _make


@pytest.fixture
def client_as(memory_db, memory_kv, memory_storage, memory_broker, fake_auth):
    """client_as(user) → 그 사용자로 로그인한 TestClient. client_as(None) → 로그인 안 함.

    새 앱을 만들므로(create_app) 기능의 hooks.py가 다시 등록된다.
    """
    from app.main import create_app

    clients: list[TestClient] = []

    def _make(user: CurrentUser | None, *, raise_server_exceptions: bool = False) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_admin_db] = lambda: memory_db
        app.dependency_overrides[get_user_db] = lambda: memory_db
        app.dependency_overrides[get_storage] = lambda: memory_storage
        app.dependency_overrides[get_auth_provider] = lambda: fake_auth
        headers = {}
        if user is not None:
            def _current_user(request: Request) -> CurrentUser:
                mark_request_user(request, user)
                return user

            app.dependency_overrides[get_current_user] = _current_user
            headers["Authorization"] = f"Bearer {user.access_token}"
        client = TestClient(app, raise_server_exceptions=raise_server_exceptions, headers=headers)
        clients.append(client)
        return client

    yield _make
    for c in clients:
        c.close()
