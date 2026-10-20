"""마이페이지(key mypage, order 80): 닉네임, 비밀번호 변경, 내 사진, 요약, 가중치 프로필(F12), 내 발품 후기(F14)."""

from __future__ import annotations

import streamlit as st

from core import nav, state
from core.api import ApiError, api_get, api_patch, api_post
from core.ui import fmt_kst, show_api_error
from features.photos.components import photo_grid, show_flash
from features.scoring.sections import render_profile_manager   # F12 가중치 프로필 탭
from features.community.mypage_tab import render_my_posts   # F14 내 발품 후기 탭

NICKNAME_MAX = 20
PASSWORD_MIN = 6           # Supabase Auth 기본 최소 길이(서버 정책을 따른다)
PASSWORD_MAX = 72
SCOPE = "mypage"
# R의 로그인 화면(features/auth/pages.py)이 한 번 보여 주고 지우는 안내 키
_LOGIN_NOTICE_KEY = "_auth_notice"


# ------------------------------------------------------------------ 닉네임
def _nickname_form() -> None:
    profile = state.current_profile() or {}
    st.subheader("닉네임")
    with st.form("mypage_nickname_form"):
        nickname = st.text_input("닉네임", value=profile.get("nickname", ""), max_chars=NICKNAME_MAX,
                                 help=f"1~{NICKNAME_MAX}자. 앞뒤 공백은 지워집니다.")
        submitted = st.form_submit_button("닉네임 저장", type="primary")
    if not submitted:
        return
    value = nickname.strip()
    if not value:
        st.warning("닉네임을 1자 이상 입력하세요.")
        return
    if len(value) > NICKNAME_MAX:
        st.warning(f"닉네임은 {NICKNAME_MAX}자 이하로 정하세요.")
        return
    try:
        with st.spinner("저장하는 중…"):
            updated = api_patch("/me", json={"nickname": value})
    except ApiError as e:
        show_api_error(e)
        return
    state.set_profile(updated)
    st.session_state["mypage_flash:nickname"] = f"닉네임을 '{updated['nickname']}'(으)로 바꿨습니다."
    st.rerun()


# ------------------------------------------------------------------ 비밀번호
def _password_form() -> None:
    st.subheader("비밀번호 변경")
    with st.form("mypage_password_form", clear_on_submit=True):
        current = st.text_input("지금 비밀번호", type="password", max_chars=PASSWORD_MAX)
        new = st.text_input("새 비밀번호", type="password", max_chars=PASSWORD_MAX, help=f"{PASSWORD_MIN}자 이상")
        confirm = st.text_input("새 비밀번호 확인", type="password", max_chars=PASSWORD_MAX)
        submitted = st.form_submit_button("비밀번호 바꾸기", type="primary")
    if not submitted:
        return
    if not current or not new or not confirm:
        st.warning("세 칸을 모두 입력하세요.")
        return
    if len(new) < PASSWORD_MIN:
        st.warning(f"새 비밀번호는 {PASSWORD_MIN}자 이상으로 정하세요.")
        return
    if new != confirm:
        st.warning("새 비밀번호와 확인 값이 다릅니다. 다시 입력하세요.")
        return
    if new == current:
        st.warning("새 비밀번호가 지금 비밀번호와 같습니다. 다른 비밀번호를 정하세요.")
        return
    try:
        with st.spinner("바꾸는 중…"):
            api_post("/me/password", json={"current_password": current, "new_password": new})
    except ApiError as e:
        if e.code == "INVALID_CREDENTIALS" and not state.is_logged_in():
            # core/api.py가 401을 받으면 로그인을 지운다(계약 변경 요청 참고). 로그인 화면에 이유를 남긴다.
            st.session_state[_LOGIN_NOTICE_KEY] = (
                "지금 비밀번호가 맞지 않아 로그아웃됐습니다. 다시 로그인한 뒤 마이페이지에서 다시 시도하세요.")
            st.rerun()
        if e.code == "INVALID_CREDENTIALS":
            st.error("지금 비밀번호가 맞지 않습니다. 확인하고 다시 입력하세요.")
            return
        if (e.detail or {}).get("reason") == "reauthentication_needed":
            # Supabase '보안 비밀번호 변경'이 켜져 있고 로그인한 지 24시간이 지난 경우
            st.error("보안을 위해 다시 로그인한 뒤 바꿔야 합니다. 로그아웃 후 다시 로그인하고 시도하세요.")
            return
        show_api_error(e)
        return
    st.success("비밀번호를 바꿨습니다. 다음 로그인부터 새 비밀번호를 쓰세요.")


# ------------------------------------------------------------------ 내 사진
def _photo_caption(photo: dict) -> str:
    label = photo.get("listing_label") or f"{photo.get('listing_no')}번 집"
    return f"{photo.get('session_title') or '세션'} · {label} · {fmt_kst(photo.get('created_at'))}"


def _open_listing_button(photo: dict) -> None:
    if st.button("매물 보기", key=f"mypage_open_listing:{photo['id']}", width="stretch"):
        nav.go_listing_detail(photo["listing_id"])


def _my_photos() -> None:
    st.subheader("내 사진")
    show_flash(SCOPE)
    try:
        with st.spinner("사진을 불러오는 중…"):
            photos = api_get("/me/photos")
    except ApiError as e:
        show_api_error(e)
        if st.button("다시 시도", key="mypage_photos_retry"):
            st.rerun()
        return
    if not photos:
        st.info("아직 올린 사진이 없습니다. 매물 상세 화면에서 사진을 올려 보세요.")
        return
    st.caption(f"모두 {len(photos)}장 · 최신순 · 나만 볼 수 있습니다.")
    photo_grid(photos, scope=SCOPE, caption_fn=_photo_caption, extra_fn=_open_listing_button)


# ------------------------------------------------------------------ 요약
def _summary() -> None:
    st.subheader("요약")
    try:
        with st.spinner("불러오는 중…"):
            s = api_get("/me/summary")
    except ApiError as e:
        show_api_error(e)
        if st.button("다시 시도", key="mypage_summary_retry"):
            st.rerun()
        return
    cols = st.columns(5)
    cols[0].metric("세션", s.get("session_count", 0))
    cols[1].metric("매물", s.get("listing_count", 0))
    cols[2].metric("분석", s.get("analysis_count", 0))
    cols[3].metric("사진", s.get("photo_count", 0))
    cols[4].metric("피드백", s.get("feedback_count", 0))

    recent = s.get("recent_sessions") or []
    st.markdown("**최근 세션**")
    if not recent:
        st.info("아직 세션이 없습니다. 세션 목록에서 첫 세션을 만들어 보세요.")
        if st.button("세션 목록으로", key="mypage_go_sessions"):
            nav.go_sessions()
        return
    for sess in recent:
        c1, c2 = st.columns([4, 1], vertical_alignment="center")
        visit = sess.get("visit_date") or "날짜 미정"
        c1.write(f"{sess['title']} · 방문일 {visit} · 매물 {sess.get('listing_count', 0)}곳")
        if c2.button("열기", key=f"mypage_open_session:{sess['id']}", width="stretch"):
            nav.go_session_detail(sess["id"])


def render_mypage() -> None:
    st.title("마이페이지")
    nick_msg = st.session_state.pop("mypage_flash:nickname", None)
    if nick_msg:
        st.success(nick_msg)
    tab_info, tab_photos, tab_summary, tab_weights, tab_balpum = st.tabs(
        ["내 정보", "내 사진", "요약", "가중치 프로필", "내 발품 후기"])
    with tab_info:
        _nickname_form()
        st.divider()
        _password_form()
    with tab_photos:
        _my_photos()
    with tab_summary:
        _summary()
    with tab_weights:
        render_profile_manager()
    with tab_balpum:
        render_my_posts()


PAGES = [{"key": "mypage", "title": "마이페이지", "order": 80, "admin_only": False, "render": render_mypage}]
