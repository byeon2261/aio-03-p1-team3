"""F14 발품 후기 화면: 실제 페이지를 AppTest로 그려서 목록·검색·상세·쓰기·마이페이지 탭 확인. 서버는 가짜."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"
if str(FRONTEND_DIR) not in sys.path:
    sys.path.append(str(FRONTEND_DIR))

from features.community import view  # noqa: E402

MINE = {"id": "p-mine", "address": "가상시 예시구 샘플동 123-45", "floor": 3, "topic": "구조·설비",
        "visit_date": "2026-10-17", "title": "보일러가 욕실 안쪽에 있어요", "nickname": "테스터", "is_mine": True,
        "has_photo": False, "created_at": "2026-10-17T01:00:00+00:00", "updated_at": "2026-10-17T01:00:00+00:00"}
OTHERS = {**MINE, "id": "p-other", "floor": None, "visit_date": None, "topic": "소음", "title": "밤에 도로 소음이 커요",
          "nickname": "이웃", "is_mine": False}

HEADER = f"""
import sys
sys.path.insert(0, {str(FRONTEND_DIR)!r})
import _community_fake as fake
import streamlit as st
from features.community import components, pages, mypage_tab

def _get(path, params=None, **kw):
    fake.calls.append(("GET", path, params))
    return fake.responses.get(path, [])

def _write(method):
    def f(path, json=None, files=None, **kw):
        fake.calls.append((method, path, json))
        return fake.responses.get((method, path), {{"id": "new-id"}})
    return f

for m in (components, pages, mypage_tab):
    m.api_get = _get
for m in (components, pages):
    m.api_post, m.api_patch = _write("POST"), _write("PATCH")
components.api_delete = _write("DELETE")
components.api_put = _write("PUT")
from core import nav as _nav
_nav.go_page = lambda key: fake.calls.append(("NAV", key, None))   # 화면 이동은 기록만
st.session_state.setdefault("auth", {{"access_token": "t", "refresh_token": "r", "expires_at": None,
                                      "profile": {{"id": "me", "nickname": "테스터", "role": "user"}}}})
"""


@pytest.fixture
def ui_fake():
    mod = types.ModuleType("_community_fake")
    mod.calls = []
    mod.responses = {"/community/posts": [OTHERS, MINE],
                     "/community/posts/p-mine": {**MINE, "body": "본문입니다", "photo": None},
                     "/community/posts/p-other": {**OTHERS, "body": "남의 본문", "photo": None}}
    sys.modules["_community_fake"] = mod
    yield mod
    sys.modules.pop("_community_fake", None)


def _app(body: str):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_string(HEADER + body, default_timeout=10)
    at.run()
    assert not at.exception, at.exception
    return at


def _detail(post_id: str, scope: str = "list"):
    """상세 페이지(balpum_post): [자세히 보기]로 고른 후기를 연 상태."""
    return _app(f'st.session_state.setdefault("balpum_post", {{"id": {post_id!r}, "scope": {scope!r}}})\n'
                "pages.render_post()")


def _button(at, label):
    return next(b for b in at.button if b.label == label)


# ------------------------------------------------------------------ 순수 함수
def test_community_view_helpers():
    assert view.fmt_floor(None) == "층수 미입력" and view.fmt_floor(3) == "3층" and view.fmt_floor(-1) == "지하 1층"
    assert view.meta_line(OTHERS).endswith("소음 · 이웃 · 방문일 미입력")
    assert view.list_params({"address": "  ", "floor": view.ALL, "topic": view.ALL}) == {}
    assert view.list_params({"address": "샘플동", "floor": 3, "topic": "소음"}) == {
        "address": "샘플동", "floor": 3, "topic": "소음"}
    assert view.form_problems("", "", "", None) == [
        "지번 주소를 입력하세요.", "주제를 고르세요.", "제목을 입력하세요.", "내용을 입력하세요."]
    assert view.form_problems("샘플동 1", "제목", "내용", "기타") == []


# ------------------------------------------------------------------ 목록
def test_community_list_shows_all_posts_first(ui_fake):
    at = _app("pages.render_list()")
    assert at.title[0].value == "발품 후기"
    assert ui_fake.calls[0] == ("GET", "/community/posts", {})          # 처음엔 전체
    md = "\n".join(str(m.value) for m in at.markdown)
    assert "밤에 도로 소음이 커요" in md and "`내 글`" in md
    assert [b.label for b in at.button].count("자세히 보기 →") == 2
    assert not any(t.label == "제목 *" for t in at.text_input)        # 목록 화면에는 쓰기 칸이 없다


def test_community_list_search_and_reset(ui_fake):
    at = _app("pages.render_list()")
    next(t for t in at.text_input if t.label == "지번 주소 검색").set_value("샘플동 123")
    next(s for s in at.selectbox if s.label == "층").set_value(3)
    _button(at, "조회").click().run()
    assert not at.exception, at.exception
    assert ui_fake.calls[-1] == ("GET", "/community/posts", {"address": "샘플동 123", "floor": 3})
    _button(at, "초기화").click().run()
    assert ui_fake.calls[-1] == ("GET", "/community/posts", {})


def test_community_list_write_button_goes_to_write(ui_fake):
    at = _app("pages.render_list()")
    _button(at, "발품 후기 쓰기").click().run()
    assert not at.exception, at.exception
    assert ("NAV", "balpum_write", None) in ui_fake.calls


def test_community_list_empty_message(ui_fake):
    ui_fake.responses["/community/posts"] = []
    at = _app("pages.render_list()")
    assert any("아직 등록된 후기가 없어요" in str(m.value) for m in at.markdown)       # 빈 화면 카드
    assert [b.label for b in at.button].count("발품 후기 쓰기") == 2                    # 위쪽 + 빈 카드의 다음 행동


def test_community_open_goes_to_detail_page(ui_fake):
    """[자세히 보기]는 상세 페이지로 이동한다(목록 페이지는 늘 목록만 보인다)."""
    at = _app("pages.render_list()")
    at.button(key="balpum_open:list:p-other").click().run()
    assert ("NAV", "balpum_post", None) in ui_fake.calls
    assert at.session_state["balpum_post"] == {"id": "p-other", "scope": "list"}
    assert not at.subheader and at.button(key="balpum_open:list:p-other")   # 목록 페이지에 상세를 그리지 않는다


def test_community_list_ignores_previous_detail(ui_fake):
    """마지막에 본 후기가 있어도 사이드바 '발품 후기'는 목록을 보여 준다."""
    at = _app('st.session_state["balpum_post"] = {"id": "p-mine", "scope": "list"}\npages.render_list()')
    assert not at.subheader and len([b for b in at.button if b.label == "자세히 보기 →"]) == 2


def test_community_detail_back_goes_to_list(ui_fake):
    at = _detail("p-other")
    assert at.title[0].value == "발품 후기" and at.subheader[0].value == "밤에 도로 소음이 커요"
    _button(at, "← 목록으로").click().run()
    assert ("NAV", "balpum_list", None) in ui_fake.calls
    assert "mypage_open_tab:balpum" not in at.session_state


def test_community_detail_without_selection_goes_to_list(ui_fake):
    _app("pages.render_post()")
    assert ui_fake.calls[-1] == ("NAV", "balpum_list", None)


def test_community_detail_edit_only_for_mine(ui_fake):
    at = _detail("p-other")
    assert at.subheader[0].value == "밤에 도로 소음이 커요"
    assert not any(b.label in ("수정", "삭제") for b in at.button)    # 남의 글은 보기만
    at = _detail("p-mine")
    assert {"수정", "삭제"} <= {b.label for b in at.button}
    _button(at, "수정").click().run()
    next(t for t in at.text_input if t.label == "제목 *").set_value("고친 제목")
    _button(at, "수정 저장").click().run()
    assert not at.exception, at.exception
    patch = [c for c in ui_fake.calls if c[0] == "PATCH"]
    assert patch and patch[0][1] == "/community/posts/p-mine" and patch[0][2]["title"] == "고친 제목"
    assert patch[0][2]["floor"] == 3


def test_community_detail_delete_with_confirm(ui_fake):
    at = _detail("p-mine")
    _button(at, "삭제").click().run()
    assert any("지울까요" in w.value for w in at.warning)
    _button(at, "지우기").click().run()
    assert not at.exception, at.exception
    assert ("DELETE", "/community/posts/p-mine", None) in ui_fake.calls
    assert ("NAV", "balpum_list", None) in ui_fake.calls                          # 지우면 목록으로
    assert at.session_state["balpum_flash:list"] == "후기를 지웠습니다."


# ------------------------------------------------------------------ 좋아요·정렬
def test_community_like_helpers():
    assert view.like_mark({"like_count": 8, "liked_by_me": True}) == "♥ 8"
    assert view.like_mark({}) == "♡ 0"
    assert view.like_button_label({"like_count": 2, "liked_by_me": False}) == "♡ 좋아요 2"
    assert view.list_params({"address": "", "floor": view.ALL, "topic": view.ALL}, "좋아요 많은순") == {"sort": "likes"}
    assert view.list_params({"address": "", "floor": view.ALL, "topic": view.ALL}, "최신순") == {}


def test_community_list_shows_like_counts_and_sort(ui_fake):
    ui_fake.responses["/community/posts"] = [{**OTHERS, "like_count": 8, "liked_by_me": True},
                                             {**MINE, "like_count": 2}]
    at = _app("pages.render_list()")
    captions = [c.value for c in at.caption]
    assert "♥ 8" in captions and "♡ 2" in captions
    radio = at.radio(key="balpum_sort")
    assert radio.options == ["최신순", "좋아요 많은순"] and radio.value == "최신순"
    radio.set_value("좋아요 많은순").run()
    assert not at.exception, at.exception
    assert ui_fake.calls[-1] == ("GET", "/community/posts", {"sort": "likes"})
    # 정렬만 바꾸면 '검색 결과 없음'이 아니라 '아직 후기가 없음' 안내
    ui_fake.responses["/community/posts"] = []
    at.run()
    assert any("아직 등록된 후기가 없어요" in str(m.value) for m in at.markdown)


def test_community_detail_like_toggle(ui_fake):
    at = _detail("p-other")
    like = at.button(key="balpum_like:list:p-other")
    assert like.label == "♡ 좋아요 0"
    like.click().run()
    assert not at.exception, at.exception
    assert ("PUT", "/community/posts/p-other/like", None) in ui_fake.calls
    ui_fake.responses["/community/posts/p-other"] = {**OTHERS, "body": "남의 본문", "photo": None,
                                                     "like_count": 1, "liked_by_me": True}
    at.run()
    like = at.button(key="balpum_like:list:p-other")
    assert like.label == "♥ 좋아요 1"
    like.click().run()
    assert ("DELETE", "/community/posts/p-other/like", None) in ui_fake.calls


def test_community_detail_own_post_has_no_like_button(ui_fake):
    at = _detail("p-mine")
    assert not any(b.key and b.key.startswith("balpum_like:") for b in at.button)
    assert any("내 글에는 누를 수 없어요" in c.value for c in at.caption)


# ------------------------------------------------------------------ 쓰기
def test_community_write_back_button_goes_to_list(ui_fake):
    at = _app("pages.render_write()")
    _button(at, "← 발품 후기").click().run()
    assert not at.exception, at.exception
    assert ("NAV", "balpum_list", None) in ui_fake.calls


def test_community_write_requires_fields_and_agree(ui_fake):
    at = _app("pages.render_write()")
    assert any("연락처·실명은 적지 마세요" in i.value for i in at.info)
    assert not any("호수" in i.value for i in at.info)
    _button(at, "등록").click().run()
    warnings = [w.value for w in at.warning]
    assert "지번 주소를 입력하세요." in warnings and "개인정보 확인란에 체크해 주세요." in warnings
    assert not [c for c in ui_fake.calls if c[0] == "POST"]


def test_community_write_posts_only_required_fields(ui_fake):
    at = _app("pages.render_write()")
    next(t for t in at.text_input if t.label == "지번 주소 *").set_value("가상시 예시구 샘플동 123-45")
    next(s for s in at.selectbox if s.label == "주제 *").set_value("소음")
    next(t for t in at.text_input if t.label == "제목 *").set_value("밤에 시끄러워요")
    next(t for t in at.text_area if t.label == "내용 *").set_value("큰길 쪽 창문이라 밤에 소음이 큽니다.")
    at.checkbox[0].check()
    _button(at, "등록").click().run()
    assert not at.exception, at.exception
    post = [c for c in ui_fake.calls if c[0] == "POST"]
    assert post == [("POST", "/community/posts", {
        "address": "가상시 예시구 샘플동 123-45", "topic": "소음", "title": "밤에 시끄러워요",
        "body": "큰길 쪽 창문이라 밤에 소음이 큽니다.", "floor": None, "visit_date": None})]
    assert ui_fake.calls[-1] == ("NAV", "balpum_list", None)                     # 등록 후 목록으로 간다
    assert "후기를 등록했습니다" in at.session_state["balpum_flash:list"]          # 목록에서 보일 안내
    at.run()                                                                       # 다시 쓰기 화면을 열면
    assert next(t for t in at.text_input if t.label == "제목 *").value == ""      # 칸이 비어 있다


# ------------------------------------------------------------------ 마이페이지 탭
def test_community_mypage_tab_lists_my_posts(ui_fake):
    ui_fake.responses["/community/posts"] = [MINE]
    at = _app("mypage_tab.render_my_posts()")
    assert ("GET", "/community/posts", {"mine": "true", "limit": 200}) in ui_fake.calls
    assert "보일러가 욕실 안쪽에 있어요" in "\n".join(str(m.value) for m in at.markdown)
    assert not at.subheader                                          # 탭 이름과 겹치는 제목은 없다


def test_community_mypage_tab_ignores_previous_detail(ui_fake):
    """마지막에 본 후기가 있어도 '내 발품 후기' 탭은 목록을 보여 준다."""
    ui_fake.responses["/community/posts"] = [MINE]
    at = _app('st.session_state["balpum_post"] = {"id": "p-mine", "scope": "mypage"}\n'
              "mypage_tab.render_my_posts()")
    assert not any(b.label == "← 목록으로" for b in at.button)
    at.button(key="balpum_open:mypage:p-mine").click().run()
    assert ui_fake.calls[-1] == ("NAV", "balpum_post", None)
    assert at.session_state["mypage_open_tab:balpum"] is True       # 돌아오면 '내 발품 후기' 탭


def test_community_mypage_detail_keeps_mypage_title_and_tabs(ui_fake, monkeypatch):
    """마이페이지에서 연 상세: 마이페이지 제목·탭은 그대로, '내 발품 후기' 탭에 상세."""
    from features.mypage import pages as mypage

    for name in ("_my_photos", "_summary", "render_profile_manager"):   # 다른 탭은 이 테스트와 상관없다
        monkeypatch.setattr(mypage, name, lambda: None)
    at = _app('st.session_state.setdefault("balpum_post", {"id": "p-mine", "scope": "mypage"})\n'
              "pages.render_post()")
    assert at.title[0].value == "마이페이지"
    assert [t.label for t in at.tabs] == ["내 정보", "내 사진", "요약", "가중치 프로필", "내 발품 후기"]
    balpum = at.tabs[4]
    assert [h.value for h in balpum.subheader] == ["보일러가 욕실 안쪽에 있어요"]   # 탭 안에 '내 발품 후기' 제목은 없다
    assert {"← 목록으로", "수정", "삭제"} <= {b.label for b in balpum.button}
    _button(at, "← 목록으로").click().run()
    assert ("NAV", "mypage", None) in ui_fake.calls
    assert at.session_state["mypage_open_tab:balpum"] is True


def test_community_pages_registered():
    from features.community.pages import PAGES

    assert [(p["key"], p["title"], p["order"], p.get("hidden", False)) for p in PAGES] == [
        ("balpum_write", "발품 후기 쓰기", 60, True), ("balpum_list", "발품 후기", 65, False),
        ("balpum_post", "발품 후기 상세", 66, True)]
