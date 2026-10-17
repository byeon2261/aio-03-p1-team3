"""발품 후기 화면 부품: 후기 카드, 상세(내 글이면 수정·삭제·사진 바꾸기).
목록 페이지와 마이페이지 '내 발품 후기' 탭이 함께 쓴다. import 시 st 함수를 부르지 않는다.
"""

from __future__ import annotations

import datetime as dt

import streamlit as st

from core.api import ApiError, api_delete, api_get, api_patch, api_post
from core.ui import fmt_kst, show_api_error
from features.community.view import (
    BODY_MAX, FLOOR_OPTIONS, PHOTO_EXTS, REASONS, TITLE_MAX, TOPICS, ADDRESS_MAX, PRIVACY_NOTICE,
    fmt_floor_option, meta_line,
)

OPEN_KEY = "balpum_open:{scope}"        # 상세로 연 후기 id
FLASH_KEY = "balpum_flash:{scope}"


def set_flash(scope: str, message: str) -> None:
    st.session_state[FLASH_KEY.format(scope=scope)] = message


def show_flash(scope: str) -> None:
    msg = st.session_state.pop(FLASH_KEY.format(scope=scope), None)
    if msg:
        st.success(msg)


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


def open_post(scope: str, post_id: str | None) -> None:
    key = OPEN_KEY.format(scope=scope)
    if post_id is None:
        st.session_state.pop(key, None)
    else:
        st.session_state[key] = post_id


def opened_post(scope: str) -> str | None:
    return st.session_state.get(OPEN_KEY.format(scope=scope))


# ------------------------------------------------------------------ 카드
def post_card(post: dict, scope: str) -> None:
    with st.container(border=True):
        title = post["title"] + (" 📷" if post.get("has_photo") else "")
        c1, c2 = st.columns([5, 1], vertical_alignment="center")
        c1.markdown(f"**{title}**" + ("  `내 글`" if post.get("is_mine") else ""))
        c1.caption(meta_line(post))
        if c2.button("자세히", key=f"balpum_open:{scope}:{post['id']}", width="stretch"):
            open_post(scope, post["id"])
            st.rerun()


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
        open_post(scope, None)
        set_flash(scope, "후기를 지웠습니다.")
        st.rerun()
    if c2.button("취소", key=f"balpum_del_no:{scope}:{pid}", width="stretch"):
        st.session_state.pop(confirm_key, None)
        st.rerun()


def render_post_detail(post_id: str, scope: str) -> None:
    if st.button("← 목록으로", key=f"balpum_back:{scope}"):
        open_post(scope, None)
        st.rerun()
    try:
        post = api_get(f"/community/posts/{post_id}")
    except ApiError as e:
        show_error(e)
        open_post(scope, None)
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


def render_post_list(posts: list[dict], scope: str, empty_message: str) -> None:
    if not posts:
        st.info(empty_message)
        return
    st.caption(f"후기 {len(posts)}개 · 최신순")
    for p in posts:
        post_card(p, scope)
