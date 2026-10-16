"""F12 마이페이지 '가중치 프로필' 탭: 실제 마이페이지(P4) 화면을 그려서 탭·프로필 목록·만들기·고치기 확인. 서버는 가짜."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"
if str(FRONTEND_DIR) not in sys.path:
    sys.path.append(str(FRONTEND_DIR))

from features.scoring import view  # noqa: E402

ITEMS = ["채광", "소음", "수압", "곰팡이", "난방", "층수", "옵션", "보안", "교통"]
WINTER = {"id": "p-winter", "name": "겨울 6개월",
          "weights": [{"item_key": k, "weight": {"채광": 85, "곰팡이": 10, "난방": 80}.get(k, 0)} for k in ITEMS]}

SCRIPT = f"""
import sys
sys.path.insert(0, {str(FRONTEND_DIR)!r})
import _scoring_mypage_fake as fake
import streamlit as st
from features.scoring import sections
from features.mypage import pages

def _get(path, **kw):
    fake.calls.append(("GET", path, None))
    return fake.responses.get(path, {{}})

def _write(method):
    def f(path, json=None, **kw):
        fake.calls.append((method, path, json))
        return {{}}
    return f

sections.api_get = _get
sections.api_post, sections.api_put, sections.api_delete = _write("POST"), _write("PUT"), _write("DELETE")
pages.api_get = _get   # 마이페이지의 다른 탭(사진·요약)도 같은 가짜 서버를 쓴다
st.session_state.setdefault("auth", {{"access_token": "t", "refresh_token": "r", "expires_at": None,
                                      "profile": {{"id": "me", "nickname": "테스터", "role": "user"}}}})
pages.render_mypage()
"""


@pytest.fixture
def ui_fake():
    mod = types.ModuleType("_scoring_mypage_fake")
    mod.calls = []
    mod.responses = {"/weight-profiles": [WINTER], "/score-items": {"items": ITEMS},
                     "/me/photos": [], "/me/summary": {"session_count": 0, "listing_count": 0, "analysis_count": 0,
                                                       "photo_count": 0, "feedback_count": 0}}
    sys.modules["_scoring_mypage_fake"] = mod
    yield mod
    sys.modules.pop("_scoring_mypage_fake", None)


def _app():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_string(SCRIPT, default_timeout=10)
    at.run()
    assert not at.exception, at.exception
    return at


def test_scoring_view_profiles_markdown():
    md = view.profiles_markdown([WINTER]).splitlines()
    assert md[0] == "| 프로필 | 가중치 (0인 항목은 뺌) |"
    assert md[2] == "| **겨울 6개월** | 채광 85 · 곰팡이 10 · 난방 80 |"


def test_scoring_mypage_has_weight_profile_tab_with_list(ui_fake):
    at = _app()
    assert [t.label for t in at.tabs] == ["내 정보", "내 사진", "요약", "가중치 프로필"]
    texts = "\n".join(str(m.value) for m in at.markdown)
    assert "| **겨울 6개월** | 채광 85 · 곰팡이 10 · 난방 80 |" in texts
    assert "가중치 프로필" in [s.value for s in at.subheader]


def test_scoring_mypage_create_profile_when_none_exist(ui_fake):
    ui_fake.responses["/weight-profiles"] = []
    at = _app()
    assert any("아직 만든 프로필이 없습니다" in i.value for i in at.info)
    name = next(t for t in at.text_input if t.label == "프로필 이름")
    name.set_value("여름 6개월")
    sliders = {s.label: s for s in at.slider}
    assert set(sliders) == set(ITEMS)           # 프로필이 없어도 /score-items로 입력칸을 그린다
    sliders["곰팡이"].set_value(90)
    next(b for b in at.button if b.label == "프로필 저장").click().run()
    assert not at.exception, at.exception
    post = [c for c in ui_fake.calls if c[0] == "POST"]
    assert len(post) == 1 and post[0][1] == "/weight-profiles"
    weights = {w["item_key"]: w["weight"] for w in post[0][2]["weights"]}
    assert post[0][2]["name"] == "여름 6개월" and weights["곰팡이"] == 90 and weights["채광"] == 50


def test_scoring_mypage_edit_existing_profile(ui_fake):
    at = _app()
    target = next(s for s in at.selectbox if s.label == "고칠 프로필")
    target.set_value("p-winter").run()
    assert not at.exception, at.exception
    sliders = {s.label: s for s in at.slider}
    assert sliders["채광"].value == 85 and sliders["수압"].value == 0     # 저장된 값으로 채워진다
    sliders["채광"].set_value(60)
    next(b for b in at.button if b.label == "프로필 저장").click().run()
    assert not at.exception, at.exception
    put = [c for c in ui_fake.calls if c[0] == "PUT"]
    assert len(put) == 1 and put[0][1] == "/weight-profiles/p-winter"
    assert {w["item_key"]: w["weight"] for w in put[0][2]["weights"]}["채광"] == 60
