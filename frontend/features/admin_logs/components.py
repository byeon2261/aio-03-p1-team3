"""운영 대시보드 화면 부품. import 시 st 함수를 부르지 않는다(함수 정의만)."""

from __future__ import annotations

from typing import Any

import streamlit as st

from core.ui import fmt_kst, to_kst
from features.admin_logs.logic import (
    RATING_LABELS,
    REASON_LABELS,
    connection_message,
    fmt_ms,
    fmt_pct,
    status_badge,
    version_rows,
)


def connection_banner(snapshot: dict) -> bool:
    """연결 상태 배너. '다시 연결'을 눌렀으면 True."""
    kind, message = connection_message(snapshot)
    if kind == "success":
        st.caption(f"🟢 {message}")
        return False
    getattr(st, kind)(message, icon="📡" if kind == "warning" else None)
    if kind == "warning":
        return st.button("다시 연결", key="admin_logs_reconnect")
    return False


def feed_table(rows: list[dict], *, total: int) -> None:
    if total == 0:
        st.info("아직 기록된 요청이 없습니다. 앱에서 요청이 생기면 여기에 바로 나타납니다.")
        return
    if not rows:
        st.info("조건에 맞는 요청이 없습니다. 위의 상태·버전 필터나 '운영자 요청 포함'을 바꿔 보세요.")
        return
    data = [{
        "시각": fmt_kst(r.get("created_at"), "%m-%d %H:%M:%S"),
        "상태": status_badge(r.get("status_code")),
        "요청": f"{r.get('method', '')} {r.get('endpoint', '')}",
        "처리": fmt_ms(r.get("latency_ms")),
        "AI": fmt_ms(r.get("ai_latency_ms")),
        "오류 코드": r.get("error_code") or "",
        "버전": r.get("prompt_version") or "",
        "캐시": {True: "적중", False: "아님"}.get(r.get("cache_hit"), ""),
        "사용자": r.get("profile_id") or "",
        "id": r.get("id"),
    } for r in rows]
    st.dataframe(data, hide_index=True, width="stretch", height=360)


def metric_cards(m: dict) -> None:
    ex = m.get("extra") or {}
    fe = ex.get("field_edit") or {}
    rating = ex.get("rating") or {}
    row1 = st.columns(4)
    row1[0].metric("요청 수", f"{m.get('request_count', 0):,}건",
                   help="기간 안의 업무 요청 수. /admin 요청은 '운영자 요청 포함'을 켤 때만 셉니다.")
    row1[1].metric("실패율", fmt_pct(m.get("error_rate")),
                   help=f"상태 코드 400 이상 ÷ 전체 요청 ({ex.get('error_count', 0)}건 실패)")
    row1[2].metric("처리 시간 중앙값", fmt_ms(m.get("p50_latency_ms")), help="latency_ms 중앙값")
    row1[3].metric("처리 시간 상위 5%", fmt_ms(m.get("p95_latency_ms")),
                   help="latency_ms를 오름차순으로 놓았을 때 95% 위치 값(nearest-rank)")
    row2 = st.columns(4)
    row2[0].metric("AI 시간 중앙값", fmt_ms(m.get("ai_p50_latency_ms")),
                   help=f"ai_latency_ms가 있는 요청 {ex.get('ai_request_count', 0)}건의 중앙값")
    row2[1].metric("캐시 적중률", fmt_pct(m.get("cache_hit_rate")),
                   help=f"cache_hit True ÷ 분석 요청({ex.get('analysis_request_count', 0)}건)")
    row2[2].metric("필드 수정 비율", fmt_pct(fe.get("ratio")),
                   help=(f"사용자가 고친 상태로 남은 필드 {fe.get('edited_fields', 0)}개 ÷ 분석된 필드 "
                         f"{fe.get('analyzed_fields', 0)}개. 'AI 값으로 되돌리기'한 필드는 빼고 '메모에 없음'으로 "
                         f"고친 필드는 셉니다. 사용자가 고친 빈도이며 정답과 비교한 값이 아닙니다."))
    row2[3].metric("👎 비율", fmt_pct(rating.get("down_rate")),
                   help=f"👎 {rating.get('down_count', 0)}건 ÷ 전체 평가 {rating.get('rating_count', 0)}건(분석별 최신 평가)")
    st.caption(f"형식 실패 비율 {fmt_pct(m.get('format_error_rate'))} "
               f"(AI 응답 형식 실패 ÷ 분석 요청) · 집계 기간 {m.get('window_minutes', 0):,}분")
    if ex.get("truncated"):
        st.warning("기간 안 요청이 너무 많아 앞부분만 계산했습니다. 기간을 줄여 다시 보세요.")


def _series_frame(series: dict) -> Any:
    import pandas as pd

    points = series.get("points") or []
    if not points:
        return None
    df = pd.DataFrame(points)
    df["시각"] = [to_kst(p["start"]).replace(tzinfo=None) for p in points]
    return df.set_index("시각")


def charts(m: dict) -> None:
    series = (m.get("extra") or {}).get("series") or {}
    df = _series_frame(series)
    if df is None or int(df["count"].sum()) == 0:
        st.info("이 기간에는 요청이 없어 차트를 그리지 않았습니다. 기간을 늘려 보세요.")
        return
    unit = "시간" if series.get("unit") == "hour" else "일"
    left, right = st.columns(2)
    with left:
        st.markdown(f"**처리 시간 ({unit} 단위, ms)**")
        st.line_chart(df[["p50_latency_ms", "p95_latency_ms"]].rename(
            columns={"p50_latency_ms": "중앙값", "p95_latency_ms": "상위 5%"}))
    with right:
        st.markdown(f"**실패율 ({unit} 단위, %)**")
        rate = (df["error_rate"].astype(float) * 100).rename("실패율")
        st.line_chart(rate)
        st.caption("요청 수")
        st.bar_chart(df["count"].rename("요청 수"), height=140)


def error_breakdown(m: dict) -> None:
    counts = (m.get("extra") or {}).get("error_code_counts") or {}
    if not counts:
        st.caption("이 기간에 실패한 요청이 없습니다.")
        return
    st.dataframe([{"오류 코드": k, "건수": v} for k, v in counts.items()], hide_index=True, width="stretch")


def version_table(m: dict) -> None:
    rows = version_rows((m.get("extra") or {}).get("by_prompt_version") or {})
    if not rows:
        st.caption("프롬프트 버전이 기록된 요청·분석이 아직 없습니다. 분석을 실행하면 버전별로 나뉩니다.")
        return
    st.dataframe(rows, hide_index=True, width="stretch")


def reason_counts(m: dict) -> None:
    counts = (m.get("extra") or {}).get("feedback_reason_counts") or {}
    total = sum(counts.values())
    if total == 0:
        st.caption("이 기간에 👎 평가가 없습니다.")
        return
    cols = st.columns(len(REASON_LABELS))
    for col, (key, label) in zip(cols, REASON_LABELS.items()):
        col.metric(label, f"{counts.get(key, 0)}건")


def feedback_cases(items: list[dict], *, empty_message: str) -> None:
    if not items:
        st.info(empty_message)
        return
    st.dataframe([{
        "시각": fmt_kst(x.get("created_at")),
        "평가": RATING_LABELS.get(x.get("rating") or "", x.get("rating") or ""),
        "사유": REASON_LABELS.get(x.get("reason") or "none", x.get("reason") or "")
        if x.get("rating") == "down" else "",
        "의견": x.get("comment") or "",
        "메모 앞부분": x.get("memo_head") or "",
        "분석 요약": x.get("analysis_summary") or "",
        "버전": x.get("prompt_version") or "",
    } for x in items], hide_index=True, width="stretch")
