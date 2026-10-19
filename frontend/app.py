"""Streamlit 진입점. 저장소 루트에서 `streamlit run frontend/app.py`.

- 로그인 전: 로그인 페이지만.
- 로그인 후: features/*/pages.py의 PAGES + R 상세 페이지 2개(세션 상세 20, 매물 상세 30)를 order 순으로.
  admin_only 페이지는 운영자에게만 보인다. hidden=True 페이지는 사이드바 메뉴에 안 보이고 버튼으로만 간다.
"""

from __future__ import annotations

import time
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="집 보기 메모 비교", page_icon="🏠", layout="wide")
# 공통 스타일(카드·탭·헤더). 색·글꼴은 .streamlit/config.toml [theme]. CSS만 있어 화면 자리를 차지하지 않는다
st.html(Path(__file__).resolve().parent / "core" / "theme.css")

from core import nav, slots, state  # noqa: E402
from core.api import ApiError, api_post, ping_health  # noqa: E402
from core.host_pages import render_listing_detail, render_session_detail  # noqa: E402
from core.loader import load_pages, load_sections  # noqa: E402
from core.ui import privacy_notice  # noqa: E402
from features.auth.pages import render_login  # noqa: E402

HOST_PAGES = [
    {"key": "session_detail", "title": "세션 상세", "order": 20, "admin_only": False, "hidden": True,
     "render": render_session_detail, "feature": "core"},
    {"key": "listing_detail", "title": "매물 상세", "order": 30, "admin_only": False, "hidden": True,
     "render": render_listing_detail, "feature": "core"},
]
WAKE_LIMIT_SEC = 60
# 사이드바 메뉴 아이콘(페이지 key → Material 아이콘). 없는 key는 아이콘 없이 보인다
PAGE_ICONS = {
    "sessions": ":material/home_work:",
    "balpum_list": ":material/forum:",
    "map": ":material/map:",
    "mypage": ":material/person:",
    "admin_logs": ":material/monitoring:",
    "evals": ":material/compare_arrows:",
}
_MD_SPECIAL = str.maketrans({c: "\\" + c for c in "\\`*_{}[]()<>#+-.!|~:"})


def _md_escape(text: str) -> str:
    """닉네임 같은 사용자 입력을 마크다운 서식 없이 그대로 보여 준다."""
    return str(text).translate(_MD_SPECIAL)


def wake_server() -> None:
    """Render 무료 서버는 잠들어 있을 수 있다. /health가 늦으면 안내하고 최대 1분 기다린다."""
    if st.session_state.get("_server_awake"):
        return
    if ping_health(timeout_sec=3):
        st.session_state["_server_awake"] = True
        return
    deadline = time.time() + WAKE_LIMIT_SEC
    with st.spinner("서버를 깨우는 중입니다(최대 1분)"):
        while time.time() < deadline:
            if ping_health(timeout_sec=10):
                st.session_state["_server_awake"] = True
                return
            time.sleep(2)
    st.error("서버에 연결할 수 없습니다. 잠시 후 '다시 시도'를 누르세요.")
    if st.button("다시 시도", type="primary"):
        st.rerun()
    st.stop()


def sidebar() -> None:
    with st.sidebar:
        profile = state.current_profile() or {}
        role = " :gray[· 운영자]" if state.is_admin() else ""
        st.markdown(f"**{_md_escape(profile.get('nickname', '사용자'))}** 님{role}")
        if st.button("로그아웃", key="logout", type="tertiary", icon=":material/logout:"):
            try:
                api_post("/auth/logout")
            except ApiError:
                pass  # 서버 응답과 상관없이 화면 토큰은 지운다
            state.clear_auth()
            st.rerun()


def main() -> None:
    wake_server()
    privacy_notice()

    if not state.is_logged_in():
        st.navigation([st.Page(render_login, title="로그인", url_path="login", default=True)],
                      position="hidden").run()
        return

    slots.register_sections(load_sections())
    items = [p for p in load_pages() + HOST_PAGES if state.is_admin() or not p["admin_only"]]
    items.sort(key=lambda p: (p["order"], p["key"]))
    default_key = next((p["key"] for p in items if not p.get("hidden")), items[0]["key"])
    pages = {
        p["key"]: st.Page(p["render"], title=p["title"], url_path=p["key"], default=(p["key"] == default_key),
                          icon=PAGE_ICONS.get(p["key"]), visibility="hidden" if p.get("hidden") else "visible")
        for p in items
    }
    nav.register_pages(pages)
    sidebar()
    st.navigation(list(pages.values())).run()


main()
