"""오류 형식.

응답 본문: {"error": {"code": str, "message": str, "detail": {"request_id": str, ...}}}
기능 코드는 `raise AppError(404, "SESSION_NOT_FOUND", "세션을 찾을 수 없습니다")`처럼 쓴다.
detail에 메모 원문·비밀번호·토큰·키를 넣지 않는다.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("app.errors")


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str, detail: dict[str, Any] | None = None):
        super().__init__(f"{status} {code}")  # 메시지에 사용자 입력을 넣지 않는다
        self.status = status
        self.code = code
        self.message = message
        self.detail = dict(detail or {})


def request_id_of(scope_or_request: Any) -> str | None:
    scope = scope_or_request.scope if isinstance(scope_or_request, Request) else scope_or_request
    state = scope.get("state") or {}
    return state.get("request_id")


def error_body(code: str, message: str, request_id: str | None, detail: dict[str, Any] | None = None) -> dict:
    d = {"request_id": request_id}
    if detail:
        d.update(detail)
    return {"error": {"code": code, "message": message, "detail": d}}


def error_response(status: int, code: str, message: str, request_id: str | None,
                   detail: dict[str, Any] | None = None) -> JSONResponse:
    headers = {"X-Request-ID": request_id} if request_id else None
    return JSONResponse(error_body(code, message, request_id, detail), status_code=status, headers=headers)


def _remember_error_code(request: Request, code: str) -> None:
    # 기능이 set_log_fields(error_code=...)로 먼저 넣은 값(예: FMT)을 덮지 않는다
    state = request.scope.setdefault("state", {})
    fields = state.setdefault("log_fields", {})
    fields.setdefault("error_code", code)


_HTTP_CODES = {401: "AUTH_REQUIRED", 403: "FORBIDDEN", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}
_HTTP_MESSAGES = {404: "요청한 주소가 없습니다.", 405: "허용되지 않는 요청 방식입니다."}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):
        _remember_error_code(request, exc.code)
        return error_response(exc.status, exc.code, exc.message, request_id_of(request), exc.detail)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        _remember_error_code(request, "VALIDATION_ERROR")
        # 입력값(input)은 메모 원문일 수 있으므로 위치·종류만 돌려준다
        fields = [
            {"loc": [str(x) for x in e.get("loc", ())], "type": e.get("type"), "msg": e.get("msg")}
            for e in exc.errors()
        ]
        return error_response(422, "VALIDATION_ERROR", "입력값을 확인해 주세요.", request_id_of(request),
                              {"fields": fields})

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        code = _HTTP_CODES.get(exc.status_code, "HTTP_ERROR")
        _remember_error_code(request, code)
        message = _HTTP_MESSAGES.get(exc.status_code, "요청을 처리할 수 없습니다.")
        return error_response(exc.status_code, code, message, request_id_of(request))


def internal_error_response(request_id: str | None) -> JSONResponse:
    return error_response(500, "INTERNAL_ERROR", "서버에서 문제가 생겼습니다. 잠시 후 다시 시도해 주세요.", request_id)


def log_unhandled(exc: BaseException, request_id: str | None) -> None:
    """예외 메시지에는 사용자 입력이 섞일 수 있으므로 종류와 위치만 남긴다."""
    tb = exc.__traceback__
    where = "?"
    while tb is not None:
        where = f"{tb.tb_frame.f_code.co_filename}:{tb.tb_lineno}"
        tb = tb.tb_next
    logger.error("unhandled %s at %s request_id=%s", type(exc).__name__, where, request_id)
