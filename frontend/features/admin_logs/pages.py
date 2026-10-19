"""F8 운영 대시보드 페이지 (key admin_logs, order 90, admin_only).

- 실시간 로그 피드: sse_listener의 백그라운드 스레드가 받은 로그를 @st.fragment(run_every="2s")가 큐에서 꺼내 표시.
- 지표 카드·차트·실패 유형·프롬프트 버전별 비교: GET /admin/metrics (필터가 바뀌거나 '지표 새로 고침'을 누를 때)
- 사용자 평가 사례: GET /admin/feedback(전체는 rating=up·down을 각각 받아 합침), 👎 사유별 개수는 metrics extra.feedback_reason_counts
import 시 st 함수를 부르지 않는다.
"""

from __future__ import annotations

import time

import streamlit as st

from core import state
from core.api import ApiError, api_get, base_url
from core.ui import show_api_error
from features.admin_logs import components
from features.admin_logs.logic import (
    ALL_VERSIONS,
    DEFAULT_FEEDBACK_FILTER,
    DEFAULT_PERIOD,
    FEEDBACK_FILTERS,
    PERIODS,
    STATUS_OPTIONS,
    filter_feed,
    merge_feedback,
    period_range,
)
from features.admin_logs.sse_listener import FORBIDDEN, UNAUTHORIZED, FeedBuffer, Listener

# session_state 키 (이 기능 전용)
K_LISTENER = "admin_logs:listener"
K_FEED = "admin_logs:feed"
K_SEEN_CONNECT = "admin_logs:seen_connect"
K_VERSIONS = "admin_logs:versions"
K_REFRESH_TRY = "admin_logs:refresh_try_at"
K_LOADED = "admin_logs:initial_loaded"
K_FEEDBACK_FILTER = "admin_logs:feedback_filter"
REFRESH_RETRY_SEC = 10
FEEDBACK_LIMIT = 20
FEEDBACK_EMPTY = {
    "전체": "아직 사용자 평가가 없습니다. 사용자가 분석 결과에 👍·👎를 누르면 여기에 모입니다.",
    "👍 좋은 평가": "아직 👍 평가가 없습니다. 사용자가 분석 결과에 👍를 누르면 여기에 모입니다.",
    "👎 낮은 평가": "아직 👎 평가가 없습니다. 사용자가 분석 결과에 👎를 누르면 여기에 모입니다.",
}
INITIAL_LOGS = 100
GAP_LIMIT = 500


# ------------------------------------------------------------------ 실시간 수신
def _feed() -> FeedBuffer:
    feed = st.session_state.get(K_FEED)
    if feed is None:
        feed = FeedBuffer()
        st.session_state[K_FEED] = feed
    return feed


def _start_listener() -> Listener:
    listener = Listener(base_url(), state.access_token()).start()
    st.session_state[K_LISTENER] = listener
    return listener


def _ensure_listener() -> Listener | None:
    """세션당 스레드 1개. 없거나 끝났으면 현재 토큰으로 새로 띄우고, 살아 있으면 토큰만 넘긴다."""
    listener: Listener | None = st.session_state.get(K_LISTENER)
    token = state.access_token()
    if listener is not None and listener.is_alive():
        listener.shared.set_token(token)
        return listener
    if listener is not None:
        snap = listener.shared.snapshot()
        if snap["status"] == FORBIDDEN:
            return listener                      # 운영자가 아니면 다시 띄우지 않는다
        if snap["status"] == UNAUTHORIZED and snap["failed_token"] == token:
            # 같은 토큰으로 401 → 토큰 갱신(api가 401이면 한 번 갱신 후 재시도). 너무 자주 시도하지 않는다.
            last_try = st.session_state.get(K_REFRESH_TRY, 0.0)
            if time.time() - last_try < REFRESH_RETRY_SEC:
                return listener
            st.session_state[K_REFRESH_TRY] = time.time()
            try:
                api_get("/me")
            except ApiError as e:
                if e.code == "AUTH_REQUIRED" and not state.is_logged_in():
                    st.rerun(scope="app")        # 갱신 실패 → 로그인 화면으로
                return listener
            if state.access_token() == token:
                return listener
    return _start_listener()


def _fill_gap(feed: FeedBuffer) -> None:
    """(다시) 연결되면 마지막 id 뒤를 GET /admin/logs?after_id로 채운다. 피드는 id로 중복을 거른다."""
    params: dict = {"include_admin": "true"}
    try:
        if feed.max_id is None:
            feed.add(api_get("/admin/logs", params={**params, "limit": INITIAL_LOGS}) or [])
            return
        rows = api_get("/admin/logs", params={**params, "after_id": feed.max_id, "limit": GAP_LIMIT}) or []
        feed.add(rows)
        if len(rows) >= GAP_LIMIT:               # 빈 구간이 너무 길면 최신 것도 가져온다
            feed.add(api_get("/admin/logs", params={**params, "limit": INITIAL_LOGS}) or [])
    except ApiError as e:
        show_api_error(e)


@st.fragment(run_every="2s")
def _live_feed(include_admin: bool, status: str | None, prompt_version: str | None) -> None:
    listener = _ensure_listener()
    feed = _feed()
    if listener is None:
        return
    listener.shared.touch()                      # 하트비트: 이 값이 10초 넘게 멈추면 스레드가 끝난다
    feed.add(listener.drain())
    snap = listener.shared.snapshot()
    reconnected = snap["connect_count"] != st.session_state.get(K_SEEN_CONNECT, 0)
    if reconnected or not st.session_state.get(K_LOADED):
        # 처음 들어왔을 때(실시간 연결 전이라도) 최근 로그를 보이고, (다시) 연결될 때마다 빈 구간을 채운다
        st.session_state[K_SEEN_CONNECT] = snap["connect_count"]
        st.session_state[K_LOADED] = True
        _fill_gap(feed)
    if components.connection_banner(snap):
        listener.request_reconnect()              # 스레드는 그대로 두고 대기만 건너뛴다
    rows = filter_feed(feed.rows(), include_admin=include_admin, status=status, prompt_version=prompt_version)
    components.feed_table(rows[:100], total=len(feed))
    for r in feed.rows():
        if r.get("prompt_version"):
            st.session_state.setdefault(K_VERSIONS, set()).add(r["prompt_version"])


# ------------------------------------------------------------------ 페이지
def _filters() -> tuple[str, str | None, str | None, bool]:
    versions = sorted(st.session_state.get(K_VERSIONS) or set())
    c1, c2, c3, c4 = st.columns([1.2, 1.2, 1, 1])
    period = c1.selectbox("기간", list(PERIODS), index=list(PERIODS).index(DEFAULT_PERIOD), key="admin_logs_period")
    status_label = c2.selectbox("상태", list(STATUS_OPTIONS), key="admin_logs_status")
    version = c3.selectbox("프롬프트 버전", [ALL_VERSIONS] + versions, key="admin_logs_version")
    include_admin = c4.toggle("운영자 요청 포함", value=False, key="admin_logs_include_admin",
                              help="끄면 /admin 으로 시작하는 요청(이 화면이 부른 요청)을 피드와 지표에서 뺍니다.")
    return period, STATUS_OPTIONS[status_label], (None if version == ALL_VERSIONS else version), include_admin


def _load_metrics(period: str, version: str | None, include_admin: bool) -> dict | None:
    f, t = period_range(period)
    params = {"from": f.isoformat(), "to": t.isoformat(), "include_admin": str(include_admin).lower()}
    if version:
        params["prompt_version"] = version
    try:
        with st.spinner("지표를 계산하는 중…"):
            m = api_get("/admin/metrics", params=params)
    except ApiError as e:
        show_api_error(e)
        return None
    vs = st.session_state.setdefault(K_VERSIONS, set())
    vs.update((m.get("extra") or {}).get("by_prompt_version", {}).keys())
    return m


def render_dashboard() -> None:
    st.title("운영 대시보드")
    if not state.is_admin():
        st.error("운영자만 볼 수 있습니다. 다른 메뉴를 이용하세요.")
        return
    st.caption("요청 로그를 실시간으로 보고, 처리 시간·실패율·평가 지표를 확인합니다. 시각은 서울 기준입니다.")

    period, status, version, include_admin = _filters()

    st.subheader("실시간 로그")
    _live_feed(include_admin, status, version)

    head, btn = st.columns([4, 1])
    head.subheader(f"지표 · {period}")
    btn.button("지표 새로 고침", key="admin_logs_refresh_metrics", width="stretch")   # 누르면 다시 실행되며 새로 계산
    m = _load_metrics(period, version, include_admin)
    if m is not None:
        components.metric_cards(m)
        components.charts(m)
        left, right = st.columns([1, 2])
        with left:
            st.markdown("**실패 유형 분포**")
            components.error_breakdown(m)
        with right:
            st.markdown("**프롬프트 버전별 비교**")
            components.version_table(m)

    st.subheader("사용자 평가 사례")
    if m is not None:
        st.markdown(f"**👎 사유별 개수 · {period}**")
        components.reason_counts(m)
    choice = st.radio("평가", list(FEEDBACK_FILTERS), horizontal=True, key=K_FEEDBACK_FILTER,
                      index=list(FEEDBACK_FILTERS).index(DEFAULT_FEEDBACK_FILTER), label_visibility="collapsed")
    st.markdown(f"**최근 {FEEDBACK_LIMIT}건** (기간과 상관없이 최신순, 분석별 최신 평가만)")
    try:
        lists = [api_get("/admin/feedback", params={"rating": r, "limit": FEEDBACK_LIMIT}) or []
                 for r in FEEDBACK_FILTERS[choice]]
    except ApiError as e:
        show_api_error(e)
    else:
        components.feedback_cases(merge_feedback(lists, FEEDBACK_LIMIT), empty_message=FEEDBACK_EMPTY[choice])


PAGES = [
    {"key": "admin_logs", "title": "운영 대시보드", "order": 90, "admin_only": True, "render": render_dashboard},
]
