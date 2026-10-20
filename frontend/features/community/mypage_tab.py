"""마이페이지 '내 발품 후기' 탭(P4 마이페이지가 부른다): 내가 쓴 후기만 보고, 고치고, 지운다."""

from __future__ import annotations

from core.api import ApiError, api_get
from features.community.components import render_post_detail, render_post_list, show_error, show_flash

SCOPE = "mypage"


def render_my_posts(post_id: str | None = None) -> None:
    """post_id가 없으면 내 후기 목록, 있으면 그 후기 상세(상세 페이지 balpum_post가 마이페이지째로 부른다).

    [자세히 보기]는 상세 페이지로 가므로 마이페이지(mypage)의 이 탭은 늘 목록이다.
    """
    show_flash(SCOPE)   # 탭 이름이 '내 발품 후기'라 따로 제목을 두지 않는다
    if post_id:
        render_post_detail(post_id, SCOPE)
        return
    try:
        posts = api_get("/community/posts", params={"mine": "true", "limit": 200})
    except ApiError as e:
        show_error(e)
        return
    render_post_list(posts, SCOPE, "아직 쓴 발품 후기가 없어요. 사이드바 '발품 후기'의 [발품 후기 쓰기]에서 써 보세요.")
