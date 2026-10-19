"""F14 발품 후기 페이지 2개: 쓰기(key balpum_write, order 60) · 목록(key balpum_list, order 65).

사이드바에는 목록('발품 후기')만 보인다. 쓰기는 목록의 [발품 후기 쓰기] 버튼으로 가고,
등록을 마치면 목록으로 돌아간다.
"""

from __future__ import annotations

import datetime as dt

import streamlit as st

from core import nav
from core.api import ApiError, api_get, api_post
from features.community.address_picker import open_search_dialog
from features.community.components import (
    opened_post, render_post_detail, render_post_list, set_flash, show_error, show_flash, upload_photo,
)
from features.community.view import (
    ADDRESS_MAX, ALL, BODY_MAX, DEFAULT_SORT, FLOOR_OPTIONS, PHOTO_EXTS, PRIVACY_NOTICE, TITLE_MAX, TOPICS,
    fmt_floor_option, form_problems, list_params,
)

WRITE_SCOPE = "write"
LIST_SCOPE = "list"
_W = "balpum_w_"                 # 쓰기 칸 key 앞부분
WRITE_KEYS = ["address", "topic", "floor", "visit", "title", "body", "photo", "agree"]
_CLEAR_FLAG = "balpum_w_clear"
FILTER_KEY = "balpum_filters"
SORT_KEY = "balpum_sort"


# ------------------------------------------------------------------ 쓰기
def _clear_write_form() -> None:
    for k in WRITE_KEYS:
        st.session_state.pop(_W + k, None)
    # file_uploader는 key를 바꿔야 비워진다
    st.session_state["balpum_w_photo_gen"] = st.session_state.get("balpum_w_photo_gen", 0) + 1


def render_write() -> None:
    if st.button("← 발품 후기", key="balpum_w_back"):
        nav.go_page("balpum_list")
    st.title("발품 후기 쓰기")
    st.caption("직접 방문한 집의 구조·설비·소음·채광 등을 주소 기준으로 공유하세요.")
    if st.session_state.pop(_CLEAR_FLAG, False):
        _clear_write_form()
    show_flash(WRITE_SCOPE)
    st.info(PRIVACY_NOTICE, icon="🔒")

    c1, c2 = st.columns([4, 1], vertical_alignment="bottom")
    c1.text_input("지번 주소 *", key=_W + "address", max_chars=ADDRESS_MAX,
                  placeholder="'주소 검색'으로 고르거나 직접 입력 (예: OO동 123-45)")
    if c2.button("주소 검색", key="balpum_w_search", width="stretch"):
        open_search_dialog(_W + "address")

    st.selectbox("주제 *", TOPICS, index=None, placeholder="주제를 고르세요", key=_W + "topic")
    c3, c4 = st.columns(2)
    c3.selectbox("층수 (선택)", FLOOR_OPTIONS[1:], index=None, placeholder="비워도 돼요",
                 format_func=fmt_floor_option, key=_W + "floor")
    c4.date_input("방문일 (선택)", value=None, max_value=dt.date.today(), format="YYYY-MM-DD", key=_W + "visit")
    st.text_input("제목 *", key=_W + "title", max_chars=TITLE_MAX, placeholder="예: 보일러가 욕실 안쪽에 있어요")
    st.text_area("내용 *", key=_W + "body", max_chars=BODY_MAX, height=200,
                 placeholder="직접 확인한 구조와 다른 사람에게 참고가 될 내용을 적어 주세요.")
    photo = st.file_uploader("사진 (선택, JPG·PNG, 5MB, 1장)", type=PHOTO_EXTS,
                             key=f"{_W}photo_{st.session_state.get('balpum_w_photo_gen', 0)}")
    agree = st.checkbox("사진과 내용에 연락처·실명 같은 개인정보가 없는지 확인했어요", key=_W + "agree")

    if not st.button("등록", type="primary", key="balpum_w_submit"):
        return
    ss = st.session_state
    problems = form_problems(ss.get(_W + "address", ""), ss.get(_W + "title", ""), ss.get(_W + "body", ""),
                             ss.get(_W + "topic"))
    if not agree:
        problems.append("개인정보 확인란에 체크해 주세요.")
    if problems:
        for p in problems:
            st.warning(p)
        return
    visit = ss.get(_W + "visit")
    payload = {"address": ss[_W + "address"], "topic": ss[_W + "topic"], "title": ss[_W + "title"],
               "body": ss[_W + "body"], "floor": ss.get(_W + "floor"),
               "visit_date": visit.isoformat() if visit else None}
    try:
        with st.spinner("등록하는 중…"):
            post = api_post("/community/posts", json=payload)
    except ApiError as e:
        show_error(e)
        return
    message = "후기를 등록했습니다."
    if photo is not None:
        with st.spinner("사진을 올리는 중…"):
            if not upload_photo(post["id"], photo):
                message = "후기는 등록했지만 사진은 올리지 못했습니다. 목록의 내 글에서 다시 올려 주세요."
    set_flash(LIST_SCOPE, message)
    st.session_state[_CLEAR_FLAG] = True       # 다음에 쓰기 화면을 열면 칸이 비어 있다
    nav.go_page("balpum_list")


# ------------------------------------------------------------------ 목록
def _filters() -> dict:
    return st.session_state.setdefault(FILTER_KEY, {"address": "", "floor": ALL, "topic": ALL})


def _search_bar() -> None:
    current = _filters()
    with st.form("balpum_search"):
        address = st.text_input("지번 주소 검색", value=current["address"], placeholder="예: OO동 123 (일부만 적어도 돼요)")
        c1, c2 = st.columns(2)
        floor = c1.selectbox("층", FLOOR_OPTIONS, index=FLOOR_OPTIONS.index(current["floor"]),
                             format_func=fmt_floor_option)
        topics = [ALL] + TOPICS
        topic = c2.selectbox("주제", topics, index=topics.index(current["topic"]))
        b1, b2 = st.columns(2)
        search = b1.form_submit_button("조회", type="primary", width="stretch")
        reset = b2.form_submit_button("초기화", width="stretch")
    if search:
        st.session_state[FILTER_KEY] = {"address": address, "floor": floor, "topic": topic}
        st.rerun()
    if reset:
        st.session_state[FILTER_KEY] = {"address": "", "floor": ALL, "topic": ALL}
        st.rerun()


def render_list() -> None:
    c1, c2 = st.columns([4, 1], vertical_alignment="bottom")
    c1.title("발품 후기")
    show_flash(LIST_SCOPE)
    open_id = opened_post(LIST_SCOPE)
    if open_id:
        render_post_detail(open_id, LIST_SCOPE)
        return
    if c2.button("발품 후기 쓰기", type="primary", key="balpum_list_go_write", width="stretch"):
        nav.go_page("balpum_write")
    st.caption("집 보러 가기 전, 같은 주소·층의 후기로 확인할 것을 준비하세요.")

    _search_bar()
    params = list_params(_filters(), st.session_state.get(SORT_KEY, DEFAULT_SORT))
    try:
        with st.spinner("후기를 불러오는 중…"):
            posts = api_get("/community/posts", params=params)
    except ApiError as e:
        show_error(e)
        if st.button("다시 시도", key="balpum_list_retry"):
            st.rerun()
        return
    searched = {k: v for k, v in params.items() if k != "sort"}
    empty = ("이 조건에 맞는 후기가 아직 없어요. 처음으로 써 보세요." if searched
             else "아직 등록된 후기가 없어요. 처음으로 써 보세요.")
    render_post_list(posts, LIST_SCOPE, empty, sort_key=SORT_KEY)


PAGES = [
    {"key": "balpum_write", "title": "발품 후기 쓰기", "order": 60, "admin_only": False, "hidden": True,
     "render": render_write},
    {"key": "balpum_list", "title": "발품 후기", "order": 65, "admin_only": False, "render": render_list},
]
