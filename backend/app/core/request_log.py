"""요청 로그 미들웨어.

- 요청마다 request_id(uuid4)를 만들고 응답 헤더 X-Request-ID로 돌려준다.
- 응답을 다 보낸 뒤 request_logs에 한 행을 저장(admin db)하고 publish_log로 실시간 발행한다.
- /health, /ready, /admin/logs/stream은 기록하지 않는다.
- 저장·발행 실패는 응답을 막지 않는다. 메모 원문·토큰은 남기지 않는다.

기능 코드는 AI 관련 값을 이렇게 넘긴다.
    set_log_fields(request, ai_latency_ms=812, prompt_version="v1", cache_hit=False, error_code="FMT")
error_code를 넘기지 않으면 AppError의 code가 자동으로 들어간다.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
import uuid
from typing import Any

from fastapi import Request
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.broker import publish_log
from app.core.errors import internal_error_response, log_unhandled

logger = logging.getLogger("app.request_log")

SKIP_PATHS = frozenset({"/health", "/ready", "/admin/logs/stream"})
LOG_FIELDS = ("ai_latency_ms", "prompt_version", "cache_hit", "error_code")


def set_log_fields(request: Request, **fields: Any) -> None:
    unknown = set(fields) - set(LOG_FIELDS)
    if unknown:
        raise ValueError(f"알 수 없는 로그 필드: {sorted(unknown)}")
    state = request.scope.setdefault("state", {})
    state.setdefault("log_fields", {}).update(fields)


def _endpoint_of(scope: Scope) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    if path:
        return path
    return (scope.get("path") or "")[:200]


class RequestLogMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid.uuid4())
        state = scope.setdefault("state", {})
        state["request_id"] = request_id
        started = time.perf_counter()
        status_holder = {"code": 500, "started": False}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["code"] = message["status"]
                status_holder["started"] = True
                headers = list(message.get("headers") or [])
                if not any(k.lower() == b"x-request-id" for k, _ in headers):
                    headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            log_unhandled(exc, request_id)
            state.setdefault("log_fields", {}).setdefault("error_code", "INTERNAL_ERROR")
            if status_holder["started"]:
                status_holder["code"] = 500
                await self._record(scope, status_holder["code"], started)
                raise
            response = internal_error_response(request_id)
            await response(scope, receive, send_wrapper)

        await self._record(scope, status_holder["code"], started)

    async def _record(self, scope: Scope, status_code: int, started: float) -> None:
        path = scope.get("path") or ""
        if path in SKIP_PATHS:
            return
        state = scope.get("state") or {}
        fields = state.get("log_fields") or {}
        row = {
            "request_id": state.get("request_id"),
            "profile_id": state.get("profile_id"),
            "endpoint": _endpoint_of(scope),
            "method": scope.get("method", ""),
            "status_code": int(status_code),
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "ai_latency_ms": fields.get("ai_latency_ms"),
            "error_code": fields.get("error_code"),
            "prompt_version": fields.get("prompt_version"),
            "cache_hit": fields.get("cache_hit"),
        }
        app = scope.get("app")
        await run_in_threadpool(_save_and_publish, app, row)


def _save_and_publish(app: Any, row: dict) -> None:
    from app.core.db import get_admin_db
    from app.core.deps import resolve

    saved = None
    try:
        db = resolve(app, get_admin_db)
        result = db.insert("request_logs", row)
        saved = result[0] if result else None
    except Exception as exc:
        logger.warning("request_logs insert failed: %s", type(exc).__name__)
    if saved is None:
        saved = {**row, "id": None, "created_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    publish_log(saved)
