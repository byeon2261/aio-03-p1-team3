"""발품 후기 화면 부품: 후기 카드, 상세(내 글이면 수정·삭제·사진 바꾸기).
목록 페이지와 마이페이지 '내 발품 후기' 탭이 함께 쓴다. import 시 st 함수를 부르지 않는다.

상세는 숨김 페이지 balpum_post(features/community/pages.py)에서 보인다. 카드의 [자세히 보기]가
그 페이지로 이동하므로 브라우저 뒤로가기·'← 목록으로'·사이드바 '발품 후기'는 모두 목록을 보여 준다.
"""

from __future__ import annotations

import datetime as dt

import streamlit as st

from core import nav
from core.api import ApiError, api_delete, api_get, api_patch, api_post, api_put
from core.ui import empty_state, fmt_kst, notify, show_api_error
from features.community.view import (
    BODY_MAX, FLOOR_OPTIONS, PHOTO_EXTS, REASONS, TITLE_MAX, TOPICS, ADDRESS_MAX, PRIVACY_NOTICE,
    DEFAULT_SORT, LIKE_HELP, OWN_POST_LIKE_NOTE, SORTS, UNLIKE_HELP,
    fmt_floor_option, like_button_label, like_mark, meta_line,
)

OPEN_KEY = "balpum_post"                # 상세 페이지에서 볼 후기 {"id", "scope"}
FLASH_KEY = "balpum_flash:{scope}"
# 상세에서 돌아갈 목록 페이지(scope → 페이지 key). 마이페이지는 '내 발품 후기' 탭을 열어 둔다
BACK_PAGES = {"list": "balpum_list", "mypage": "mypage"}
MYPAGE_TAB_FLAG = "mypage_open_tab:balpum"


def set_flash(scope: str, message: str) -> None:
    st.session_state[FLASH_KEY.format(scope=scope)] = message


def show_flash(scope: str) -> None:
    msg = st.session_state.pop(FLASH_KEY.format(scope=scope), None)
    if msg:
        st.success(msg)
        notify(msg)


def show_error(e: ApiError) -> None:
    reason = (e.detail or {}).get("reason")
    if e.code == "VALIDATION_ERROR" and reason in REASONS:
        st.error(REASONS[reason] or e.message)
    elif e.code == "POST_NOT_FOUND":
        st.error("발품 후기를 찾을 수 없습니다. 목록을 새로 고쳐 주세요.")
    elif e.code == "FORBIDDEN":
        st.error("내가 쓴 후기만 고치거나 지울 수 있습니다.")
    elif e.code == "STORAGE_UNAVAILABLE":
        st.error("사진 저장소에 연결하지 못했습니다. 잠시 후 다시 올려 주세요.")
    else:
        show_api_error(e)


def upload_photo(post_id: str, file) -> bool:
    try:
        api_post(f"/community/posts/{post_id}/photo",
                 files={"file": (file.name, file.getvalue(), file.type or "application/octet-stream")})
        return True
    except ApiError as e:
        show_error(e)
        return False


def open_post(scope: str, post_id: str) -> None:
    """후기 상세 페이지로 이동한다(목록과 다른 주소라 브라우저 뒤로가기가 목록으로 돌아온다)."""
    st.session_state[OPEN_KEY] = {"id": post_id, "scope": scope}
    if scope == "mypage":    # '← 목록으로'든 브라우저 뒤로가기든 마이페이지는 '내 발품 후기' 탭으로 연다
        st.session_state[MYPAGE_TAB_FLAG] = True
    nav.go_page("balpum_post")


def opened_post() -> dict | None:
    """상세 페이지에서 볼 후기 {"id", "scope"}. 고른 후기가 없으면 None."""
    opened = st.session_state.get(OPEN_KEY)
    return opened if isinstance(opened, dict) and opened.get("id") else None


def back_to_list(scope: str) -> None:
    """상세 → 그 후기를 연 목록(발품 후기 목록 또는 마이페이지 '내 발품 후기' 탭)."""
    st.session_state.pop(OPEN_KEY, None)
    if scope == "mypage":
        st.session_state[MYPAGE_TAB_FLAG] = True
    nav.go_page(BACK_PAGES.get(scope, "balpum_list"))


# ------------------------------------------------------------------ 카드
def post_card(post: dict, scope: str) -> None:
    with st.container(border=True):
        title = post["title"] + (" 📷" if post.get("has_photo") else "")
        c1, c2 = st.columns([5, 1], vertical_alignment="center")
        c1.markdown(f"**{title}**" + ("  `내 글`" if post.get("is_mine") else ""))
        c1.caption(meta_line(post))
        c1.caption(like_mark(post))
        if c2.button("자세히 보기 →", key=f"balpum_open:{scope}:{post['id']}", type="tertiary", width="stretch"):
            open_post(scope, post["id"])


# ------------------------------------------------------------------ 상세
def _edit_form(post: dict, scope: str) -> None:
    pid = post["id"]
    with st.form(f"balpum_edit:{scope}:{pid}"):
        address = st.text_input("지번 주소 *", value=post["address"], max_chars=ADDRESS_MAX)
        topic = st.selectbox("주제 *", TOPICS, index=TOPICS.index(post["topic"]) if post["topic"] in TOPICS else 0)
        floor_value = post.get("floor")
        floor_opts = ["미입력"] + FLOOR_OPTIONS[1:]
        floor = st.selectbox("층수 (선택)", floor_opts,
                             index=floor_opts.index(floor_value) if floor_value in floor_opts else 0,
                             format_func=lambda v: v if v == "미입력" else fmt_floor_option(v))
        visit = st.date_input("방문일 (선택)",
                              value=dt.date.fromisoformat(post["visit_date"]) if post.get("visit_date") else None,
                              format="YYYY-MM-DD")
        title = st.text_input("제목 *", value=post["title"], max_chars=TITLE_MAX)
        body = st.text_area("내용 *", value=post["body"], max_chars=BODY_MAX, height=180)
        submitted = st.form_submit_button("수정 저장", type="primary")
    if not submitted:
        return
    payload = {"address": address, "topic": topic, "title": title, "body": body,
               "floor": None if floor == "미입력" else int(floor),
               "visit_date": visit.isoformat() if visit else None}
    try:
        api_patch(f"/community/posts/{pid}", json=payload)
    except ApiError as e:
        show_error(e)
        return
    st.session_state.pop(f"balpum_editing:{scope}:{pid}", None)
    set_flash(scope, "후기를 고쳤습니다.")
    st.rerun()


def _photo_controls(post: dict, scope: str) -> None:
    pid = post["id"]
    new = st.file_uploader(f"사진 {'바꾸기' if post.get('photo') else '올리기'} (JPG·PNG, 5MB, 1장)",
                           type=PHOTO_EXTS, key=f"balpum_photo:{scope}:{pid}")
    c1, c2 = st.columns(2)
    if new is not None and c1.button("사진 저장", key=f"balpum_photo_save:{scope}:{pid}", width="stretch"):
        if upload_photo(pid, new):
            set_flash(scope, "사진을 저장했습니다.")
            st.rerun()
    if post.get("photo") and c2.button("사진 지우기", key=f"balpum_photo_del:{scope}:{pid}", width="stretch"):
        try:
            api_delete(f"/community/posts/{pid}/photo")
        except ApiError as e:
            show_error(e)
            return
        set_flash(scope, "사진을 지웠습니다.")
        st.rerun()


def _delete_controls(post: dict, scope: str) -> None:
    pid = post["id"]
    confirm_key = f"balpum_confirm:{scope}:{pid}"
    if not st.session_state.get(confirm_key):
        if st.button("삭제", key=f"balpum_del:{scope}:{pid}"):
            st.session_state[confirm_key] = True
            st.rerun()
        return
    st.warning("이 후기를 지울까요? 사진도 함께 지워지고 되돌릴 수 없습니다.")
    c1, c2 = st.columns(2)
    if c1.button("지우기", key=f"balpum_del_yes:{scope}:{pid}", type="primary", width="stretch"):
        st.session_state.pop(confirm_key, None)
        try:
            api_delete(f"/community/posts/{pid}")
        except ApiError as e:
            show_error(e)
            return
        set_flash(scope, "후기를 지웠습니다.")
        back_to_list(scope)
    if c2.button("취소", key=f"balpum_del_no:{scope}:{pid}", width="stretch"):
        st.session_state.pop(confirm_key, None)
        st.rerun()


def render_post_detail(post_id: str, scope: str) -> None:
    if st.button("← 목록으로", key=f"balpum_back:{scope}"):
        back_to_list(scope)
    try:
        post = api_get(f"/community/posts/{post_id}")
    except ApiError as e:
        show_error(e)
        return
    with st.container(border=True):
        st.subheader(post["title"])
        st.caption(meta_line(post))
        st.caption(f"작성 {fmt_kst(post.get('created_at'))}"
                   + (f" · 수정 {fmt_kst(post.get('updated_at'))}" if post.get("updated_at") != post.get("created_at")
                      else ""))
        photo = post.get("photo")
        if photo and photo.get("url"):
            st.image(photo["url"], width="stretch")
        elif photo:
            st.caption("사진을 불러오지 못했습니다. 잠시 후 새로 고쳐 주세요.")
        st.write(post["body"])
        _like_controls(post, scope)

    if not post.get("is_mine"):
        return
    editing_key = f"balpum_editing:{scope}:{post_id}"
    c1, c2 = st.columns([1, 5])
    if c1.button("수정", key=f"balpum_edit_btn:{scope}:{post_id}"):
        st.session_state[editing_key] = not st.session_state.get(editing_key, False)
        st.rerun()
    if st.session_state.get(editing_key):
        st.info(PRIVACY_NOTICE, icon="🔒")
        _edit_form(post, scope)
        _photo_controls(post, scope)
    with c2:
        _delete_controls(post, scope)


def _like_controls(post: dict, scope: str) -> None:
    """상세 본문 아래 좋아요. 내 글은 수만 보여 주고, 남의 글은 누르기·취소."""
    if post.get("is_mine"):
        st.caption(f"♥ 좋아요 {int(post.get('like_count') or 0)} · {OWN_POST_LIKE_NOTE}")
        return
    liked = bool(post.get("liked_by_me"))
    c1, c2 = st.columns([1, 3], vertical_alignment="center")
    clicked = c1.button(like_button_label(post), key=f"balpum_like:{scope}:{post['id']}", width="stretch")
    c2.caption(UNLIKE_HELP if liked else LIKE_HELP)
    if not clicked:
        return
    path = f"/community/posts/{post['id']}/like"
    try:
        api_delete(path) if liked else api_put(path)
    except ApiError as e:
        show_error(e)
        return
    st.rerun()


def render_post_list(posts: list[dict], scope: str, empty_message: str, *, sort_key: str | None = None,
                     on_write=None) -> None:
    """sort_key를 주면 '후기 N개' 옆에 [최신순 / 좋아요 많은순]을 보여 준다(값은 그 key의 session_state).

    on_write를 주면 빈 목록 카드에 [발품 후기 쓰기] 버튼을 두고 누르면 on_write()를 부른다.
    """
    if not posts:
        if empty_state("forum", empty_message, button="발품 후기 쓰기" if on_write else None,
                       key=f"balpum_empty_write:{scope}") and on_write:
            on_write()
        return
    if sort_key is None:
        st.caption(f"후기 {len(posts)}개 · 최신순")
    else:
        c1, c2 = st.columns([1, 3], vertical_alignment="center")
        c1.caption(f"후기 {len(posts)}개")
        st.session_state.setdefault(sort_key, DEFAULT_SORT)
        c2.radio("정렬", list(SORTS), key=sort_key, horizontal=True, label_visibility="collapsed")
    for p in posts:
        post_card(p, scope)
