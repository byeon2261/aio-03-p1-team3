"""마이페이지 '내 발품 후기' 탭(P4 마이페이지가 부른다): 내가 쓴 후기만 보고, 고치고, 지운다."""

from __future__ import annotations

import streamlit as st

from core.api import ApiError, api_get
from features.community.components import opened_post, render_post_detail, render_post_list, show_error, show_flash

SCOPE = "mypage"


def render_my_posts() -> None:
    st.subheader("내 발품 후기")
    show_flash(SCOPE)
    open_id = opened_post(SCOPE)
    if open_id:
        render_post_detail(open_id, SCOPE)
        return
    try:
        posts = api_get("/community/posts", params={"mine": "true", "limit": 200})
    except ApiError as e:
        show_error(e)
        return
    render_post_list(posts, SCOPE, "아직 쓴 발품 후기가 없어요. 사이드바의 '발품 후기 쓰기'에서 써 보세요.")
