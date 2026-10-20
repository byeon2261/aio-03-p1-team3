"""사진 화면 부품. 매물 상세(sections.py)와 마이페이지가 함께 쓴다. import 시 st 함수를 부르지 않는다."""

from __future__ import annotations

import streamlit as st

from core.api import ApiError, api_delete
from core.ui import fmt_kst, notify, show_api_error

ALLOWED_EXTS = ["jpg", "jpeg", "png", "webp"]
MAX_PHOTO_MB = 10          # 서버 settings.MAX_PHOTO_MB와 같게 둔다(서버가 최종 검사)
COLUMNS = 3

# 업로드 422 detail.reason → 안내 문구
UPLOAD_REASONS = {
    "too_large": f"사진이 너무 큽니다. 한 장에 {MAX_PHOTO_MB}MB 이하로 줄여서 다시 올리세요.",
    "unsupported_type": "JPG·PNG·WEBP 사진만 올릴 수 있습니다. 다른 파일을 고르세요.",
    "empty_file": "빈 파일입니다. 사진 파일을 다시 고르세요.",
}


def flash_key(scope: str) -> str:
    return f"photos_flash:{scope}"


def show_flash(scope: str) -> None:
    msg = st.session_state.pop(flash_key(scope), None)
    if msg:
        st.success(msg)
        notify(msg)


def set_flash(scope: str, message: str) -> None:
    st.session_state[flash_key(scope)] = message


def show_upload_error(e: ApiError) -> None:
    reason = (e.detail or {}).get("reason")
    if e.code == "VALIDATION_ERROR" and reason in UPLOAD_REASONS:
        st.error(UPLOAD_REASONS[reason])
    elif e.code == "STORAGE_UNAVAILABLE":
        st.error("사진 저장소에 연결하지 못했습니다. 잠시 후 다시 올리세요.")
    else:
        show_api_error(e)


def _delete_controls(photo: dict, scope: str) -> None:
    """삭제 → 확인 두 단계. 확인하면 서버에서 지우고 다시 그린다."""
    pid = photo["id"]
    confirm_key = f"photos_confirm:{scope}:{pid}"
    if not st.session_state.get(confirm_key):
        if st.button("삭제", key=f"photos_del:{scope}:{pid}", width="stretch"):
            st.session_state[confirm_key] = True
            st.rerun()
        return

    st.warning("이 사진을 지울까요? 되돌릴 수 없습니다.")
    c1, c2 = st.columns(2)
    if c1.button("지우기", key=f"photos_del_yes:{scope}:{pid}", type="primary", width="stretch"):
        st.session_state.pop(confirm_key, None)
        try:
            with st.spinner("지우는 중…"):
                api_delete(f"/photos/{pid}")
        except ApiError as e:
            show_api_error(e)        # CLEANUP_FAILED면 "다시 삭제를 눌러 주세요" 안내
            return
        set_flash(scope, "사진을 지웠습니다.")
        st.rerun()
    if c2.button("취소", key=f"photos_del_no:{scope}:{pid}", width="stretch"):
        st.session_state.pop(confirm_key, None)
        st.rerun()


def photo_grid(photos: list[dict], scope: str, caption_fn=None, extra_fn=None) -> None:
    """사진을 3열로 보여 준다. 서명 URL은 10분 뒤 만료되므로 화면을 다시 그릴 때마다 새로 받는다."""
    for start in range(0, len(photos), COLUMNS):
        cols = st.columns(COLUMNS)
        for col, photo in zip(cols, photos[start:start + COLUMNS]):
            with col:
                if photo.get("url"):
                    st.image(photo["url"], width="stretch")
                else:
                    st.caption("미리보기를 불러오지 못했습니다. 새로 고침해 보세요.")
                text = caption_fn(photo) if caption_fn else f"올린 시각 {fmt_kst(photo.get('created_at'))}"
                st.caption(text)
                if extra_fn:
                    extra_fn(photo)
                _delete_controls(photo, scope)
