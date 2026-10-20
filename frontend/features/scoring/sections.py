"""F12 항목 가중치화 섹션.

- session_detail order 25: 항목 가중치 켜기/끄기, 이 세션에 쓸 프로필 고르기, 프로필 만들기·고치기·삭제
- session_detail order 35: 적합도 순위(비교표 바로 아래). 예산 필터가 켜져 있으면 남은 후보끼리 순위
- listing_detail order 45: 항목 만족도 입력(0~100, 비우면 미입력)
- render_profile_manager(): 마이페이지(P4)의 '가중치 프로필' 탭이 부른다(프로필 목록·만들기·고치기·삭제)
import 시 st 함수를 부르지 않는다.
"""

from __future__ import annotations

import streamlit as st

from core.api import ApiError, api_delete, api_get, api_post, api_put
from core.state import budget_filter_key
from core.ui import fmt_kst, icon_title, notify, show_api_error
from features.scoring.view import (
    RULE_NOTE, SATISFACTION_NOTE, hidden_message, profile_label, profile_options, profiles_markdown, ranking_markdown,
    satisfaction_body, weights_body, weights_summary,
)

BUDGET_FILTER = "within_budget"
NEW_PROFILE = "__new__"
PROFILES_KEY = "scoring_profiles"
PROFILES_VER_KEY = "scoring_profiles_ver"
ITEMS_KEY = "scoring_items"


def _setting_key(sid: str) -> str:
    return f"scoring_setting:{sid}"


def _flash_key(scope: str) -> str:
    return f"scoring_flash:{scope}"


def _sat_key(lid: str) -> str:
    return f"scoring_sat:{lid}"


def _sat_ver_key(lid: str) -> str:
    return f"scoring_sat_ver:{lid}"


def _bump(key: str) -> int:
    st.session_state[key] = st.session_state.get(key, 0) + 1
    return st.session_state[key]


def _show_flash(scope: str) -> None:
    msg = st.session_state.pop(_flash_key(scope), None)
    if msg:
        st.success(msg)
        notify(msg)


def _retry_button(key: str) -> None:
    if st.button("다시 시도", key=key):
        st.rerun()


# ------------------------------------------------------------------ 불러오기
def _load_profiles() -> list[dict] | None:
    """내 가중치 프로필(계정 단위). 한 번 받으면 바꿀 때까지 화면 상태에 둔다. 실패하면 None."""
    if PROFILES_KEY not in st.session_state:
        try:
            with st.spinner("가중치 프로필을 불러오는 중…"):
                st.session_state[PROFILES_KEY] = api_get("/weight-profiles")
        except ApiError as e:
            show_api_error(e)
            _retry_button("scoring_profiles_retry")
            return None
    return st.session_state[PROFILES_KEY]


def _load_setting(sid: str) -> dict | None:
    key = _setting_key(sid)
    if key not in st.session_state:
        try:
            with st.spinner("가중치 설정을 불러오는 중…"):
                st.session_state[key] = api_get(f"/sessions/{sid}/scoring")
        except ApiError as e:
            show_api_error(e)
            _retry_button(f"scoring_setting_retry:{sid}")
            return None
    return st.session_state[key]


def _forget_profiles() -> None:
    """프로필이 바뀌면 목록과 모든 세션 설정(프로필 이름이 들어 있음)을 다시 받게 한다."""
    st.session_state.pop(PROFILES_KEY, None)
    for k in [k for k in st.session_state.keys() if str(k).startswith("scoring_setting:")]:
        st.session_state.pop(k, None)
    _bump(PROFILES_VER_KEY)


# ------------------------------------------------------------------ 세션 설정 (order 25)
def _save_setting(sid: str, enabled: bool, profile_id: str | None, done: str, widget_key: str) -> None:
    try:
        with st.spinner("저장하는 중…"):
            saved = api_put(f"/sessions/{sid}/scoring", json={"enabled": enabled, "weight_profile_id": profile_id})
    except ApiError as e:
        show_api_error(e)
        st.session_state.pop(widget_key, None)   # 위젯을 저장된 값으로 되돌린다
        return
    st.session_state[_setting_key(sid)] = saved
    st.session_state[_flash_key(sid)] = done
    st.rerun()


def _render_setting(sid: str, setting: dict, profiles: list[dict]) -> None:
    enabled = bool(setting.get("enabled", True))
    current = setting.get("weight_profile_id")
    ver = st.session_state.get(PROFILES_VER_KEY, 0)

    toggle_key = f"scoring_toggle:{sid}"
    on = st.toggle("항목 가중치 사용", value=enabled, key=toggle_key,
                   help="끄면 비교표의 적합도 열은 '꺼짐'으로, 적합도 순위는 숨깁니다. 입력한 만족도·프로필은 그대로 남습니다.")
    if on != enabled:
        _save_setting(sid, on, current, "항목 가중치를 켰습니다." if on else "항목 가중치를 껐습니다.", toggle_key)
        return

    options = profile_options(profiles)
    if current not in options:
        current = None
    select_key = f"scoring_profile:{sid}:{ver}"
    chosen = st.selectbox("이 세션에 쓸 가중치 프로필", options, index=options.index(current), key=select_key,
                          format_func=lambda pid: profile_label(pid, profiles), disabled=not on,
                          help="계절·기간마다 프로필을 만들어 두고 세션마다 하나를 고르세요.")
    if on and chosen != current:
        _save_setting(sid, on, chosen, f"'{profile_label(chosen, profiles)}'로 계산합니다.", select_key)
        return

    picked = next((p for p in profiles if p["id"] == current), None)
    st.caption(f"적용 중인 가중치: {weights_summary(picked)}" if on else
               "항목 가중치가 꺼져 있습니다. 켜면 적합도 점수와 순위를 보여 줍니다.")


def _load_items() -> list[str] | None:
    """평가 항목 목록(서버 SCORE_ITEMS). 한 번 받으면 화면 상태에 둔다. 실패하면 None."""
    if ITEMS_KEY not in st.session_state:
        try:
            st.session_state[ITEMS_KEY] = (api_get("/score-items") or {}).get("items") or []
        except ApiError as e:
            show_api_error(e)
            _retry_button("scoring_items_retry")
            return None
    return list(st.session_state[ITEMS_KEY])


def _profile_editor(profiles: list[dict], items: list[str], prefix: str = "sd") -> None:
    ver = st.session_state.get(PROFILES_VER_KEY, 0)
    targets = [NEW_PROFILE] + [p["id"] for p in profiles]
    target = st.selectbox("고칠 프로필", targets, key=f"scoring_edit_target:{prefix}:{ver}",
                          format_func=lambda t: "새 프로필 만들기" if t == NEW_PROFILE else profile_label(t, profiles))
    profile = next((p for p in profiles if p["id"] == target), None)
    base = {w["item_key"]: w["weight"] for w in (profile or {}).get("weights") or []}

    with st.form(f"scoring_profile_form:{prefix}:{target}:{ver}", border=False):
        name = st.text_input("프로필 이름", value=(profile or {}).get("name", ""), max_chars=30,
                             placeholder="예: 여름 6개월")
        st.caption("항목별 중요도 0~100. 합이 100이 아니어도 비율로 맞춰 계산합니다.")
        cols = st.columns(3)
        weights: dict[str, int] = {}
        for i, item in enumerate(items):
            with cols[i % 3]:
                weights[item] = st.slider(item, 0, 100, value=int(base.get(item, 50 if profile is None else 0)),
                                          step=5, key=f"scoring_w:{prefix}:{target}:{ver}:{item}")
        b1, b2 = st.columns(2)
        save = b1.form_submit_button("프로필 저장", type="primary", width="stretch")
        delete = b2.form_submit_button("프로필 삭제", width="stretch", disabled=profile is None,
                                       help="이 프로필을 고른 세션은 '선택 안 함(같은 가중치)'으로 바뀝니다.")
    if save:
        body = weights_body(name, weights)
        if not body["name"]:
            st.error("프로필 이름을 입력하세요.")
            return
        try:
            with st.spinner("저장하는 중…"):
                if profile is None:
                    api_post("/weight-profiles", json=body)
                else:
                    api_put(f"/weight-profiles/{profile['id']}", json=body)
        except ApiError as e:
            show_api_error(e)
            return
        _forget_profiles()
        st.session_state[_flash_key("profiles")] = f"프로필 '{body['name']}'을(를) 저장했습니다."
        st.rerun()
    elif delete and profile is not None:
        try:
            with st.spinner("삭제하는 중…"):
                api_delete(f"/weight-profiles/{profile['id']}")
        except ApiError as e:
            show_api_error(e)
            return
        _forget_profiles()
        st.session_state[_flash_key("profiles")] = f"프로필 '{profile['name']}'을(를) 삭제했습니다."
        st.rerun()


def render_scoring_settings(ctx: dict) -> None:
    session = ctx.get("session") or {}
    sid = session.get("id")
    if not sid:
        return
    with st.container(border=True):
        icon_title("tune", "항목 가중치")
        _show_flash(sid)
        _show_flash("profiles")
        profiles = _load_profiles()
        setting = _load_setting(sid)
        if profiles is None or setting is None:
            return
        _render_setting(sid, setting, profiles)
        with st.expander("가중치 프로필 만들기·고치기"):
            _profile_editor(profiles, list(setting.get("items") or []), prefix="sd")
            st.caption("마이페이지의 '가중치 프로필' 탭에서도 만들고 고칠 수 있습니다.")
        st.caption(RULE_NOTE)


# ------------------------------------------------------------------ 마이페이지 탭
def render_profile_manager() -> None:
    """마이페이지 '가중치 프로필' 탭. 세션과 상관없이 계정의 프로필을 보고 만들고 고친다."""
    st.subheader("가중치 프로필")
    st.caption("계절·기간마다 항목별 중요도를 묶어 두고, 세션 화면의 '항목 가중치'에서 세션마다 하나를 고릅니다.")
    _show_flash("profiles")
    profiles = _load_profiles()
    items = _load_items()
    if profiles is None or items is None:
        return
    if profiles:
        st.markdown(profiles_markdown(profiles))
    else:
        st.info("아직 만든 프로필이 없습니다. 아래에서 첫 프로필을 만드세요(예: 여름 6개월·겨울 6개월).")
    st.divider()
    st.markdown("**만들기·고치기**")
    _profile_editor(profiles, items, prefix="mp")
    st.caption(RULE_NOTE)


# ------------------------------------------------------------------ 적합도 순위 (order 35)
def render_ranking(ctx: dict) -> None:
    session = ctx.get("session") or {}
    sid = session.get("id")
    if not sid:
        return
    filter_on = bool(st.session_state.get(budget_filter_key(sid)))
    params = {"filters": BUDGET_FILTER} if filter_on else None
    try:
        with st.spinner("적합도를 계산하는 중…"):
            data = api_get(f"/sessions/{sid}/scores", params=params)
    except ApiError as e:
        icon_title("emoji_events", "적합도 순위")
        show_api_error(e)
        _retry_button(f"scoring_rank_retry:{sid}")
        return
    if not (data.get("setting") or {}).get("enabled", True):
        return   # 꺼져 있으면 순위를 보여 주지 않는다
    icon_title("emoji_events", "적합도 순위")
    setting = data.get("setting") or {}
    st.caption(f"가중치 프로필: {setting.get('weight_profile_name') or '선택 안 함 (모든 항목 같은 가중치)'}")
    hidden = hidden_message(data) if filter_on else None
    if hidden:
        st.caption(f"예산 필터 적용 중 · {hidden}")
    rows = data.get("rows") or []
    if not rows:
        st.info("순위를 매길 매물이 없습니다." + (" 예산 필터를 끄면 모든 매물을 볼 수 있습니다." if filter_on else ""))
        return
    if all(r.get("score") is None for r in rows):
        st.info("아직 만족도를 입력한 매물이 없습니다. 매물 화면의 '항목 만족도'에서 입력하세요.")
    st.markdown(ranking_markdown(rows))
    st.caption("같은 점수는 같은 순위입니다. 미입력 = 만족도를 하나도 입력하지 않은 매물(순위에서 뺌).")


# ------------------------------------------------------------------ 매물 만족도 (order 45)
def _load_satisfaction(lid: str) -> dict | None:
    key = _sat_key(lid)
    if key not in st.session_state:
        try:
            with st.spinner("만족도를 불러오는 중…"):
                st.session_state[key] = api_get(f"/listings/{lid}/satisfaction")
        except ApiError as e:
            show_api_error(e)
            _retry_button(f"scoring_sat_retry:{lid}")
            return None
    return st.session_state[key]


def _save_satisfaction(lid: str, values: dict, done: str) -> None:
    try:
        with st.spinner("저장하는 중…"):
            saved = api_put(f"/listings/{lid}/satisfaction", json=satisfaction_body(values))
    except ApiError as e:
        show_api_error(e)
        return
    st.session_state[_sat_key(lid)] = saved
    st.session_state[_flash_key(lid)] = done
    _bump(_sat_ver_key(lid))   # 입력칸을 저장된 값으로 새로 그린다
    st.rerun()


def render_satisfaction(ctx: dict) -> None:
    listing = ctx.get("listing") or {}
    lid = listing.get("id")
    if not lid:
        return
    with st.container(border=True):
        icon_title("tune", "항목 만족도")
        _show_flash(lid)
        data = _load_satisfaction(lid)
        if data is None:
            return
        st.caption(SATISFACTION_NOTE)
        if data.get("updated_at"):
            st.caption(f"입력한 항목 {data.get('entered_count', 0)}/{len(data.get('items') or [])} · "
                       f"마지막 저장 {fmt_kst(data.get('updated_at'))}")
        ver = st.session_state.get(_sat_ver_key(lid), 0)
        with st.form(f"scoring_sat_form:{lid}:{ver}", border=False):
            cols = st.columns(3)
            values: dict[str, int | None] = {}
            for i, it in enumerate(data.get("items") or []):
                with cols[i % 3]:
                    values[it["item_key"]] = st.number_input(
                        it["item_key"], min_value=0, max_value=100, step=5, value=it.get("satisfaction"),
                        placeholder="미입력", key=f"scoring_sat:{lid}:{ver}:{it['item_key']}")
            b1, b2 = st.columns(2)
            save = b1.form_submit_button("만족도 저장", type="primary", width="stretch")
            clear = b2.form_submit_button("모두 비우기", width="stretch")
        if save:
            _save_satisfaction(lid, values, "만족도를 저장했습니다. 세션 화면의 적합도 순위에 바로 반영됩니다.")
        elif clear:
            _save_satisfaction(lid, {}, "만족도를 모두 비웠습니다.")


SECTIONS = [
    {"slot": "session_detail", "order": 25, "render": render_scoring_settings},
    {"slot": "session_detail", "order": 35, "render": render_ranking},
    {"slot": "listing_detail", "order": 45, "area": "score", "render": render_satisfaction},   # '내 점수' 탭
]
