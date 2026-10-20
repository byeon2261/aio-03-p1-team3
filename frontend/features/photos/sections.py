"""매물 상세 슬롯(listing_detail, order 40): 사진 올리기·목록·삭제. 사진은 나만 볼 수 있다."""

from __future__ import annotations

import streamlit as st

from core.api import ApiError, api_get, api_post
from core.ui import icon_badge, icon_title, show_api_error
from features.photos.components import (
    ALLOWED_EXTS,
    MAX_PHOTO_MB,
    photo_grid,
    set_flash,
    show_flash,
    show_upload_error,
)

_TYPE_BY_EXT = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


def _uploader(listing_id: str) -> None:
    nonce_key = f"photos_uploader_nonce:{listing_id}"
    nonce = st.session_state.get(nonce_key, 0)
    file = st.file_uploader(
        "사진 올리기",
        type=ALLOWED_EXTS,
        key=f"photos_uploader:{listing_id}:{nonce}",
        help=f"JPG·PNG·WEBP, 한 장에 {MAX_PHOTO_MB}MB 이하",
        max_upload_size=MAX_PHOTO_MB,
    )
    if file is None:
        return
    if file.size > MAX_PHOTO_MB * 1024 * 1024:
        st.error(f"사진이 너무 큽니다. 한 장에 {MAX_PHOTO_MB}MB 이하로 줄여서 다시 올리세요.")
        return
    if not st.button("이 사진 올리기", key=f"photos_upload_btn:{listing_id}", type="primary"):
        return

    ext = file.name.rsplit(".", 1)[-1].lower() if "." in file.name else ""
    content_type = file.type or _TYPE_BY_EXT.get(ext, "application/octet-stream")
    try:
        with st.spinner("사진을 올리는 중…"):
            # 파일 이름에 개인정보가 있을 수 있어 서버에는 일반 이름으로 보낸다
            api_post(f"/listings/{listing_id}/photos",
                     files={"file": (f"photo.{ext or 'jpg'}", file.getvalue(), content_type)})
    except ApiError as e:
        show_upload_error(e)
        return
    st.session_state[nonce_key] = nonce + 1      # 업로더 비우기
    set_flash(listing_id, "사진을 올렸습니다.")
    st.rerun()


def render_photos(ctx: dict) -> None:
    listing = ctx.get("listing") or {}
    listing_id = listing.get("id")
    if not listing_id:
        return

    icon_title("photo_camera", "사진")
    st.caption(f"JPG·PNG·WEBP, 한 장에 {MAX_PHOTO_MB}MB 이하. 올린 사진은 나만 볼 수 있습니다.")
    show_flash(listing_id)

    try:
        with st.spinner("사진을 불러오는 중…"):
            photos = api_get(f"/listings/{listing_id}/photos")
    except ApiError as e:
        _uploader(listing_id)
        show_api_error(e)
        if st.button("다시 시도", key=f"photos_retry:{listing_id}"):
            st.rerun()
        return

    if not photos:
        # 빈 화면 카드: 아이콘 + 한 줄 + 다음 행동(사진 올리기) 하나
        with st.container(border=True, key=f"ht_empty_photos_{listing_id}"):
            st.markdown(
                '<div style="display:flex;flex-direction:column;align-items:center;gap:.6rem;padding:.5rem 0">'
                f'{icon_badge("photo_camera", "blue", 44)}<div style="color:#3d4152">'
                '아직 올린 사진이 없어요. 사진을 골라 올려 보세요.</div></div>', unsafe_allow_html=True)
            _uploader(listing_id)
        return
    _uploader(listing_id)
    st.caption(f"{len(photos)}장 · 미리보기 주소는 10분 동안만 열립니다. 오래 열어 뒀다면 새로 고침하세요.")
    photo_grid(photos, scope=listing_id)


SECTIONS = [{"slot": "listing_detail", "order": 40, "area": "media", "render": render_photos}]   # '사진·위치' 탭
