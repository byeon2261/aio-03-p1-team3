"""슬롯 listing_detail(order 30): AI 결과 수정·피드백.

GET /listings/{id}/analyses/latest(P2)로 필드별 AI 값·수정값을 받고,
POST /analyses/{analysis_id}/feedback(P3)로 수정값·평가를 저장한다. 분석이 없으면(404) 섹션을 숨긴다.
"""

from __future__ import annotations

import streamlit as st

from core.api import ApiError, api_get, api_post
from core.ui import show_api_error
from features.comparison.cells import (
    EDIT_FIELDS, EDIT_TITLES, NULLABLE_EDIT_KEYS, REASON_LABELS, REASONS, correction_entry, kind_of,
    pending_previous, plain_value,
)

RATING_OPTIONS = ("up", "down")
RATING_LABELS = {"up": "👍 도움이 됐어요", "down": "👎 아쉬워요"}
SAVED = "반영됨"


def _key(aid: str, name: str) -> str:
    return f"fb:{aid}:{name}"


def _reset_inputs(aid: str) -> None:
    """저장 뒤 입력 칸이 새 값으로 다시 채워지도록 이 분석의 위젯 상태를 지운다."""
    prefix = f"fb:{aid}:"
    for k in [k for k in st.session_state if isinstance(k, str) and k.startswith(prefix)]:
        del st.session_state[k]


def _post(aid: str, lid: str, body: dict) -> bool:
    try:
        with st.spinner("저장하는 중…"):
            api_post(f"/analyses/{aid}/feedback", json=body)
    except ApiError as e:
        show_api_error(e)
        return False
    _reset_inputs(aid)
    st.session_state[f"fb_flash:{lid}"] = SAVED
    return True


def _field_input(aid: str, key: str, fv: dict):
    title = EDIT_TITLES[key]
    current = fv.get("value")
    kind = kind_of(key)
    if kind == "money":
        start = current if isinstance(current, int) and not isinstance(current, bool) and current >= 0 else None
        return st.number_input(f"{title}(만원)", min_value=0, step=1, value=start, format="%d",
                               placeholder="미기재", key=_key(aid, key))
    if kind == "list":
        return st.text_area(title, value="\n".join(str(x) for x in (current or [])), height=80,
                            placeholder="한 줄에 하나씩", key=_key(aid, key))
    return st.text_input(title, value=current or "", placeholder="미기재", key=_key(aid, key))


def _previous_block(aid: str, lid: str, analysis: dict) -> None:
    pending = pending_previous(analysis.get("previous_overrides"), analysis.get("fields"))
    if not pending:
        return
    names = ", ".join(EDIT_TITLES[k] for k in pending)
    st.caption(f"이전 분석에서 직접 고친 값이 있습니다({names}). 누르기 전에는 이번 분석에 들어가지 않습니다.")
    if st.button(f"이전 수정 {len(pending)}개 적용", key=_key(aid, "apply_prev")):
        body = {"corrections": [{"field_name": k, "action": "set", "corrected_value": v} for k, v in pending.items()]}
        if _post(aid, lid, body):
            st.rerun()


def render_feedback(ctx: dict) -> None:
    listing = ctx["listing"]
    lid = listing["id"]
    try:
        analysis = api_get(f"/listings/{lid}/analyses/latest")
    except ApiError as e:
        if e.status == 404:
            return  # 분석 전: 섹션 숨김
        st.subheader("✏️ AI 결과 수정·피드백")
        show_api_error(e)
        return

    st.subheader("✏️ AI 결과 수정·피드백")
    flash = st.session_state.pop(f"fb_flash:{lid}", None)
    if flash:
        st.success(flash)
    if analysis.get("status") != "success":
        st.caption("최근 분석이 실패해 고칠 값이 없습니다. 분석을 다시 실행한 뒤 고치거나 평가하세요.")
        return

    aid = analysis["id"]
    fields = analysis.get("fields") or {}
    _previous_block(aid, lid, analysis)
    st.caption("AI가 정리한 값과 내가 고친 값을 함께 보여 줍니다. 금액·글 칸을 비우면 바꾸지 않습니다. "
               "메모에 없는 값은 '메모에 없음으로 표시'를 고르세요.")

    with st.form(_key(aid, "form")):
        raw: dict[str, object] = {}
        revert: dict[str, bool] = {}
        memo_none: dict[str, bool] = {}
        for key, title in EDIT_FIELDS:
            fv = fields.get(key) or {}
            left, right = st.columns([3, 2])
            with left:
                raw[key] = _field_input(aid, key, fv)
            with right:
                st.caption(f"AI 값: {plain_value(key, fv.get('ai_value'))}")
                if fv.get("edited"):
                    mine = "메모에 없음(미기재)" if fv.get("user_value") is None else plain_value(key, fv.get("user_value"))
                    st.caption(f"✏️ 내 수정값 적용 중: {mine}")
                    revert[key] = st.checkbox("AI 값으로 되돌리기", key=_key(aid, f"revert:{key}"))
                if key in NULLABLE_EDIT_KEYS and fv.get("value") is not None:
                    memo_none[key] = st.checkbox("메모에 없음으로 표시", key=_key(aid, f"none:{key}"))

        st.divider()
        old_rating = analysis.get("rating")
        rating = st.radio("이 분석 결과는 어땠나요?", RATING_OPTIONS, format_func=RATING_LABELS.get, horizontal=True,
                          index=RATING_OPTIONS.index(old_rating) if old_rating in RATING_OPTIONS else None,
                          key=_key(aid, "rating"))
        reason = st.selectbox("사유(선택)", [k for k, _ in REASONS], format_func=REASON_LABELS.get, index=None,
                              placeholder="고르지 않음", key=_key(aid, "reason"))
        comment = st.text_area("의견(선택)", max_chars=500, height=80, key=_key(aid, "comment"))
        submitted = st.form_submit_button("저장", type="primary")

    if not submitted:
        return

    both = [EDIT_TITLES[k] for k, _ in EDIT_FIELDS if revert.get(k) and memo_none.get(k)]
    if both:
        st.warning(f"{', '.join(both)}: 'AI 값으로 되돌리기'와 '메모에 없음으로 표시' 중 하나만 고른 뒤 저장하세요.")
        return
    corrections = []
    for key, _ in EDIT_FIELDS:
        item = correction_entry(key, raw[key], fields.get(key), revert=bool(revert.get(key)),
                                memo_none=bool(memo_none.get(key)))
        if item:
            corrections.append(item)

    body: dict = {}
    if corrections:
        body["corrections"] = corrections
    comment = (comment or "").strip()
    if rating != old_rating or reason or comment:
        body.update({"rating": rating, "reason": reason, "comment": comment or None})
    if not body:
        st.warning("바뀐 내용이 없습니다. 값을 고치거나 평가를 고른 뒤 저장하세요.")
        return
    if _post(aid, lid, body):
        st.rerun()
