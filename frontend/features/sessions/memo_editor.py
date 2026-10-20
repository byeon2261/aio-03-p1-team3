"""메모 입력 부품(새 메모·메모 편집 공용). 초안 자동 저장·복원을 한다.

- 화면에 들어올 때 GET 초안으로 복원한다. 410이면 "초안이 만료되었습니다"를 보여 준다.
- 입력이 바뀔 때(on_change: 다른 곳을 누르거나 Ctrl+Enter)와 "임시 저장" 버튼으로 PUT 초안.
- "메모 저장"은 on_save(text)를 부르고, 성공하면 앱 전체를 다시 그린다.
  validate()를 주면 저장 전에 부르고, 문구를 돌려주면 경고로 보여 주고 저장하지 않는다(새 메모의 매물 이름 확인).
- 자동 저장 때 화면 전체가 다시 그려지지 않도록 st.fragment 안에서 그린다
  (fragment는 처음 그릴 때 만든다. import 시 st 함수를 부르지 않기 위해서다).
"""

from __future__ import annotations

from typing import Any, Callable

import streamlit as st

from core.api import ApiError, api_get, api_put
from core.ui import fmt_kst, notify, show_api_error

MEMO_MAX_CHARS = 5000
AUTOSAVE_HINT = "다른 곳을 누르거나 Ctrl+Enter를 누르면 자동 저장됩니다. 임시 저장본은 24시간 보관됩니다."
_PREFIX = "p1_memo:"

_fragment_fn: Callable[..., Any] | None = None


def _text_key(scope: str) -> str:
    return f"{_PREFIX}text:{scope}"


def _state_key(scope: str) -> str:
    return f"{_PREFIX}state:{scope}"


def _reset_key(scope: str) -> str:
    return f"{_PREFIX}reset:{scope}"


def _state(scope: str) -> dict:
    return st.session_state.setdefault(_state_key(scope), {})


def _restore(scope: str, draft_path: str, initial_text: str) -> None:
    """화면에 들어올 때(입력칸 값이 아직 없을 때) 서버 초안을 불러온다."""
    s = _state(scope)
    s.clear()
    text = initial_text
    try:
        draft = api_get(draft_path)
    except ApiError as e:
        if e.code == "DRAFT_EXPIRED":
            last = (e.detail or {}).get("saved_at")
            when = f"(마지막 임시 저장 {fmt_kst(last)})" if last else ""
            s["notice"] = ("warning", f"초안이 만료되었습니다{when}. 24시간이 지나 임시 저장본이 지워졌습니다. "
                                      "다시 작성하세요.")
        elif e.code == "DRAFT_NOT_FOUND":
            pass
        elif e.code == "KV_UNAVAILABLE":
            s["notice"] = ("info", "지금은 임시 저장을 쓸 수 없습니다. 작성한 뒤 '메모 저장'을 눌러 저장하세요.")
        else:
            s["error"] = e
    else:
        text = draft.get("memo_text") or ""
        s["saved_at"] = draft.get("saved_at")
        if text != initial_text:
            s["notice"] = ("info", f"임시 저장한 내용을 불러왔습니다({fmt_kst(draft.get('saved_at'))} 저장). "
                                   "'메모 저장'을 눌러야 반영됩니다.")
    s["last_saved_text"] = text
    st.session_state[_text_key(scope)] = text


def _autosave(scope: str, draft_path: str, force: bool = False) -> None:
    """on_change·임시 저장 버튼 콜백. 화면 요소를 직접 그리지 않고 결과를 상태에 남긴다."""
    s = _state(scope)
    text = st.session_state.get(_text_key(scope), "")
    if not force and text == s.get("last_saved_text"):
        return
    try:
        draft = api_put(draft_path, json={"memo_text": text})
    except ApiError as e:
        s["error"] = e
        return
    s.pop("error", None)
    s.pop("notice", None)   # 만료·복원 안내는 새로 저장하면 더 필요 없다
    s["saved_at"] = draft.get("saved_at")
    s["last_saved_text"] = text


def _editor_body(*, scope: str, draft_path: str, initial_text: str, label: str, placeholder: str,
                 save_label: str, on_save: Callable[[str], str], clear_after_save: bool,
                 validate: Callable[[], str | None] | None = None) -> None:
    text_key = _text_key(scope)
    if st.session_state.pop(_reset_key(scope), False):
        st.session_state[text_key] = ""
        _state(scope).update({"saved_at": None, "last_saved_text": ""})
    if text_key not in st.session_state:
        with st.spinner("임시 저장한 메모를 확인하는 중…"):
            _restore(scope, draft_path, initial_text)

    s = _state(scope)
    notice = s.get("notice")
    if notice:
        (st.warning if notice[0] == "warning" else st.info)(notice[1])

    st.text_area(label, key=text_key, height=220, max_chars=MEMO_MAX_CHARS, placeholder=placeholder,
                 on_change=_autosave, args=(scope, draft_path))

    saved_at = s.get("saved_at")
    status = f"마지막 임시 저장 {fmt_kst(saved_at, '%m-%d %H:%M:%S')}" if saved_at else "임시 저장본 없음"
    st.caption(f"{status} · {AUTOSAVE_HINT}")

    err = s.pop("error", None)
    if err is not None:
        if err.code == "KV_UNAVAILABLE":
            st.warning("임시 저장에 실패했습니다. 입력한 내용은 화면에 남아 있습니다. '메모 저장'으로 저장하세요.")
        else:
            show_api_error(err)

    col_save, col_draft = st.columns([1, 1])
    with col_draft:
        st.button("임시 저장", key=f"{_PREFIX}draft_btn:{scope}", on_click=_autosave,
                  args=(scope, draft_path, True), width="stretch")
    with col_save:
        clicked = st.button(save_label, key=f"{_PREFIX}save_btn:{scope}", type="primary", width="stretch")
    if not clicked:
        return

    problem = validate() if validate else None
    if problem:
        st.warning(problem)
        return
    text = st.session_state.get(text_key, "")
    if not text.strip():
        st.warning("메모가 비어 있습니다. 내용을 적은 뒤 저장하세요.")
        return
    try:
        with st.spinner("저장하는 중…"):
            message = on_save(text)
    except ApiError as e:
        show_api_error(e)
        return
    s.pop("notice", None)
    if clear_after_save:
        st.session_state[_reset_key(scope)] = True
    else:
        s.update({"saved_at": None, "last_saved_text": text})   # 서버가 초안을 지웠다
    if message:
        st.session_state[f"{_PREFIX}saved:{scope}"] = message
    st.rerun(scope="app")


def render_memo_editor(*, scope: str, draft_path: str, initial_text: str = "", label: str = "메모",
                       placeholder: str = "", save_label: str = "메모 저장",
                       on_save: Callable[[str], str], clear_after_save: bool = False,
                       validate: Callable[[], str | None] | None = None) -> None:
    """메모 입력칸을 그린다. on_save(text)는 정식 저장을 하고 성공 문구를 돌려준다(ApiError는 여기서 보여 준다)."""
    global _fragment_fn
    message = st.session_state.pop(f"{_PREFIX}saved:{scope}", None)
    if message:
        st.success(message)
        notify("메모를 저장했어요")
    if _fragment_fn is None:
        _fragment_fn = st.fragment(_editor_body)
    _fragment_fn(scope=scope, draft_path=draft_path, initial_text=initial_text, label=label,
                 placeholder=placeholder, save_label=save_label, on_save=on_save,
                 clear_after_save=clear_after_save, validate=validate)
