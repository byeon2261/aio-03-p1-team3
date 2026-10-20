"""F1 로그인·가입 화면. 로그인 전에만 보이므로 PAGES는 비워 두고 app.py가 render_login을 직접 쓴다."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from core import state
from core.api import ApiError, api_post
from core.ui import show_api_error

PAGES: list[dict] = []
LOGO = Path(__file__).resolve().parents[2] / "assets" / "golabang_logo.png"
INTRO = "집 보고 적은 메모를 AI가 비교표로 정리해 드려요"


def render_login() -> None:
    _, center, _ = st.columns([1, 2, 1])
    with center:
        if LOGO.exists():
            st.image(str(LOGO), width=240)
        else:
            st.title("골라방")
        st.markdown(f":gray[{INTRO}]")
        _login_form()


def _login_form() -> None:
    mode = st.radio("모드", ["로그인", "회원가입"], horizontal=True, label_visibility="collapsed", key="auth_mode")
    notice = st.session_state.pop("_auth_notice", None)
    if notice:
        st.success(notice)

    with st.form("auth_form", clear_on_submit=False):
        email = st.text_input("이메일", key="auth_email", placeholder="name@example.com")
        password = st.text_input("비밀번호", type="password", key="auth_password",
                                 help="6자 이상" if mode == "회원가입" else None)
        submitted = st.form_submit_button(mode, type="primary", width="stretch")

    if not submitted:
        return
    if not email.strip() or not password:
        st.warning("이메일과 비밀번호를 모두 입력하세요.")
        return
    if mode == "회원가입" and len(password) < 6:
        st.warning("비밀번호는 6자 이상으로 정하세요.")
        return

    body = {"email": email.strip(), "password": password}
    try:
        with st.spinner("처리하는 중…"):
            if mode == "로그인":
                tokens = api_post("/auth/login", json=body)
            else:
                res = api_post("/auth/signup", json=body)
                if res.get("needs_email_confirm"):
                    st.session_state["_auth_notice"] = "가입했습니다. 메일 확인 후 로그인하세요."
                    st.rerun()
                tokens = res
    except ApiError as e:
        show_api_error(e)
        return

    state.set_auth(tokens)
    st.rerun()
