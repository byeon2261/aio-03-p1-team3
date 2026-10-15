"""st.session_state 키와 로그인 상태.

키
    auth                     {"access_token", "refresh_token", "expires_at", "profile": {id, nickname, role}}
    selected_session_id      세션 상세에서 볼 세션
    selected_listing_id      매물 상세에서 볼 매물
    budget_filter_on:{sid}   예산 안 매물만 보기 (P5가 쓰고 P3가 읽음) → budget_filter_key(sid)
"""

from __future__ import annotations

import streamlit as st

AUTH = "auth"
SELECTED_SESSION_ID = "selected_session_id"
SELECTED_LISTING_ID = "selected_listing_id"


def budget_filter_key(session_id: str) -> str:
    return f"budget_filter_on:{session_id}"


def _auth() -> dict:
    return st.session_state.get(AUTH) or {}


def is_logged_in() -> bool:
    return bool(_auth().get("access_token"))


def current_profile() -> dict | None:
    return _auth().get("profile")


def is_admin() -> bool:
    p = current_profile()
    return bool(p and p.get("role") == "admin")


def access_token() -> str | None:
    return _auth().get("access_token")


def refresh_token() -> str | None:
    return _auth().get("refresh_token")


def expires_at() -> int | None:
    return _auth().get("expires_at")


def set_auth(tokens: dict) -> None:
    """로그인·갱신 응답(AuthTokensOut)을 그대로 넣는다."""
    st.session_state[AUTH] = {
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "expires_at": tokens.get("expires_at"),
        "profile": tokens.get("profile") or current_profile(),
    }


def set_profile(profile: dict) -> None:
    """닉네임 변경 등으로 프로필이 바뀌었을 때(P4)."""
    if is_logged_in():
        st.session_state[AUTH] = {**_auth(), "profile": profile}


def clear_auth() -> None:
    """로그아웃: 토큰과 화면에 남은 사용자 데이터를 모두 지운다."""
    awake = st.session_state.get("_server_awake")
    st.session_state.clear()
    if awake:
        st.session_state["_server_awake"] = True
