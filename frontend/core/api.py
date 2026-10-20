"""서버 API 호출. 화면은 이 모듈로만 서버를 부른다(Supabase·Gemini·Redis 직접 호출 금지).

    data = api_get("/sessions")
    api_post(f"/sessions/{sid}/listings", json={"memo_text": text})
    api_post(f"/listings/{lid}/photos", files={"file": (name, data, content_type)})

- 로그인 토큰을 자동으로 붙인다. 만료가 가까우면 먼저 갱신하고, 401이면 한 번 갱신 후 다시 시도한다.
  갱신한 토큰으로도 401 INVALID_CREDENTIALS(예: 현재 비밀번호 틀림)면 로그인을 지우지 않고 오류만 낸다.
- 대기 시간 90초(AI 분석·서버 깨우기 포함).
- 서버 연결은 앱 전체가 httpx.Client 하나를 같이 쓴다(연결 재사용으로 요청마다 새로 연결·TLS 하지 않음).
  로그인 토큰은 요청마다 따로 붙이므로 사용자끼리 섞이지 않는다.
- 실패하면 ApiError(status, code, message). 연결 실패는 status 0, code NETWORK_ERROR / TIMEOUT.
- 서버 주소: st.secrets["API_BASE_URL"](저장소 루트 .streamlit/secrets.toml) → 환경변수 API_BASE_URL → http://localhost:8000
"""

from __future__ import annotations

import json as _json
import os
import threading
import time
from typing import Any, Iterator

import httpx
import streamlit as st

from core import state

TIMEOUT_SEC = 90
DEFAULT_BASE_URL = "http://localhost:8000"


_client: httpx.Client | None = None
_client_lock = threading.Lock()


def _http() -> httpx.Client:
    """앱 전체가 같이 쓰는 연결 풀. 처음 부를 때 만든다(Streamlit 세션은 여러 스레드에서 돈다)."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = httpx.Client(timeout=TIMEOUT_SEC)
    return _client


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, detail: dict | None = None):
        super().__init__(f"{status} {code}")
        self.status = status
        self.code = code
        self.message = message
        self.detail = detail or {}


def base_url() -> str:
    url = None
    try:
        url = st.secrets.get("API_BASE_URL")
    except Exception:  # secrets.toml이 없으면 예외
        url = None
    return (url or os.environ.get("API_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")


def _headers() -> dict[str, str]:
    token = state.access_token()
    return {"Authorization": f"Bearer {token}"} if token else {}


def _error_from(r: httpx.Response) -> ApiError:
    try:
        err = r.json().get("error") or {}
    except ValueError:
        err = {}
    return ApiError(r.status_code, err.get("code") or f"HTTP_{r.status_code}",
                    err.get("message") or "요청을 처리하지 못했습니다.", err.get("detail") or {})


def _refresh() -> bool:
    """refresh_token으로 토큰을 갱신한다. 실패하면 로그인 상태를 지우고 False."""
    rt = state.refresh_token()
    if not rt:
        return False
    try:
        r = _http().post(base_url() + "/auth/refresh", json={"refresh_token": rt}, timeout=30)
    except httpx.HTTPError:
        return False  # 연결 문제는 로그인 해제 사유가 아니다
    if r.status_code != 200:
        state.clear_auth()
        return False
    state.set_auth(r.json())
    return True


def _request(method: str, path: str, *, json: Any = None, params: dict | None = None,
             files: Any = None, retry: bool = True) -> Any:
    is_auth_path = path.startswith("/auth/")
    exp = state.expires_at()
    if retry and not is_auth_path and exp and exp - time.time() < 60:
        _refresh()
    try:
        r = _http().request(method, base_url() + path, json=json, params=params, files=files,
                            headers=_headers(), timeout=TIMEOUT_SEC)
    except httpx.TimeoutException:
        raise ApiError(0, "TIMEOUT", "서버 응답이 늦습니다.") from None
    except httpx.HTTPError:
        raise ApiError(0, "NETWORK_ERROR", "서버에 연결할 수 없습니다.") from None

    if r.status_code == 401 and retry and not is_auth_path and state.refresh_token():
        if _refresh():
            return _request(method, path, json=json, params=params, files=files, retry=False)
    if r.status_code >= 400:
        err = _error_from(r)
        # 방금 갱신한 토큰(retry=False)으로도 INVALID_CREDENTIALS면 로그인 문제가 아니라
        # 사용자가 입력한 값 문제다(예: /me/password의 현재 비밀번호 틀림). 이때는 로그인을 유지한다.
        keep_login = not retry and err.code == "INVALID_CREDENTIALS"
        if r.status_code == 401 and not is_auth_path and not keep_login:
            state.clear_auth()
        raise err
    if r.status_code == 204 or not r.content:
        return None
    return r.json()


def api_get(path: str, *, json: Any = None, params: dict | None = None, files: Any = None) -> Any:
    return _request("GET", path, json=json, params=params, files=files)


def api_post(path: str, *, json: Any = None, params: dict | None = None, files: Any = None) -> Any:
    return _request("POST", path, json=json, params=params, files=files)


def api_put(path: str, *, json: Any = None, params: dict | None = None, files: Any = None) -> Any:
    return _request("PUT", path, json=json, params=params, files=files)


def api_patch(path: str, *, json: Any = None, params: dict | None = None, files: Any = None) -> Any:
    return _request("PATCH", path, json=json, params=params, files=files)


def api_delete(path: str, *, json: Any = None, params: dict | None = None, files: Any = None) -> Any:
    return _request("DELETE", path, json=json, params=params, files=files)


def api_stream(path: str, *, params: dict | None = None, read_timeout_sec: float = 60) -> Iterator[dict]:
    """SSE 구독(운영 대시보드용). 이벤트마다 {"event", "data", "id"}를 낸다(data는 JSON이면 해석).

    연결이 끊기면 ApiError(0, "NETWORK_ERROR")로 끝난다. 401 갱신 재시도는 하지 않는다.
    """
    timeout = httpx.Timeout(10, read=read_timeout_sec)
    try:
        with httpx.stream("GET", base_url() + path, params=params, timeout=timeout,
                          headers={**_headers(), "Accept": "text/event-stream"}) as r:
            if r.status_code >= 400:
                r.read()
                raise _error_from(r)
            event: dict[str, Any] = {"event": "message", "data": "", "id": None}
            lines: list[str] = []
            for line in r.iter_lines():
                if line == "":
                    if lines:
                        raw = "\n".join(lines)
                        try:
                            event["data"] = _json.loads(raw)
                        except ValueError:
                            event["data"] = raw
                        yield event
                    event, lines = {"event": "message", "data": "", "id": None}, []
                elif line.startswith(":"):
                    continue  # 주석·keep-alive
                elif line.startswith("data:"):
                    lines.append(line[5:].lstrip(" "))
                elif line.startswith("event:"):
                    event["event"] = line[6:].strip()
                elif line.startswith("id:"):
                    event["id"] = line[3:].strip()
    except httpx.TimeoutException:
        raise ApiError(0, "TIMEOUT", "실시간 연결이 끊겼습니다.") from None
    except httpx.HTTPError:
        raise ApiError(0, "NETWORK_ERROR", "실시간 연결이 끊겼습니다.") from None


def ping_health(timeout_sec: float = 5) -> bool:
    """/health가 timeout 안에 200이면 True(서버 깨우기 확인용)."""
    try:
        return _http().get(base_url() + "/health", timeout=timeout_sec).status_code == 200
    except httpx.HTTPError:
        return False
