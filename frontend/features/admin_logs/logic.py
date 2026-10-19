"""운영 대시보드의 순수 함수(Streamlit 없이 테스트): 기간 프리셋, 피드 필터, 표시 형식, 문구."""

from __future__ import annotations

import datetime as dt
from typing import Any

UTC = dt.timezone.utc

PERIODS: dict[str, dt.timedelta] = {
    "최근 1시간": dt.timedelta(hours=1),
    "최근 6시간": dt.timedelta(hours=6),
    "최근 24시간": dt.timedelta(hours=24),
    "최근 7일": dt.timedelta(days=7),
    "최근 30일": dt.timedelta(days=30),
}
DEFAULT_PERIOD = "최근 24시간"

STATUS_OPTIONS: dict[str, str | None] = {
    "전체": None,
    "성공(400 미만)": "success",
    "실패(400 이상)": "error",
    "4xx": "4xx",
    "5xx": "5xx",
}
ALL_VERSIONS = "전체"

REASON_LABELS: dict[str, str] = {
    "amount": "금액이 틀림",
    "not_in_memo": "메모에 없는 내용",
    "missing_info": "빠진 정보",
    "pros_cons": "장단점 정리",
    "check_error": "확인 항목 판단",
    "other": "기타",
    "none": "사유 안 고름",
}

# 사용자 평가 사례 필터: 라벨 → 서버에 물을 rating 목록(전체는 👍·👎를 각각 받아 합친다)
FEEDBACK_FILTERS: dict[str, tuple[str, ...]] = {
    "전체": ("up", "down"),
    "👍 좋은 평가": ("up",),
    "👎 낮은 평가": ("down",),
}
DEFAULT_FEEDBACK_FILTER = "전체"
RATING_LABELS: dict[str, str] = {"up": "👍", "down": "👎"}


def merge_feedback(lists: list[list[dict]], limit: int) -> list[dict]:
    """rating별로 받은 평가 목록을 합쳐 최신순 limit건. 같은 id는 한 번만."""
    seen: set[str] = set()
    merged: list[dict] = []
    for items in lists:
        for x in items or []:
            key = str(x.get("id"))
            if key in seen:
                continue
            seen.add(key)
            merged.append(x)
    merged.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    return merged[:limit]


def period_range(label: str, now: dt.datetime | None = None) -> tuple[dt.datetime, dt.datetime]:
    to = (now or dt.datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
    return to - PERIODS.get(label, PERIODS[DEFAULT_PERIOD]), to


def is_admin_endpoint(endpoint: Any) -> bool:
    e = str(endpoint or "")
    return e == "/admin" or e.startswith("/admin/")


def status_matches(code: Any, status: str | None) -> bool:
    if status is None:
        return True
    c = int(code or 0)
    if status == "success":
        return c < 400
    if status == "error":
        return c >= 400
    if status == "4xx":
        return 400 <= c < 500
    if status == "5xx":
        return c >= 500
    return str(c) == str(status)


def filter_feed(rows: list[dict], *, include_admin: bool = False, status: str | None = None,
                prompt_version: str | None = None) -> list[dict]:
    """실시간 피드 표시용 필터. 운영자 요청 포함이 꺼져 있으면 /admin 요청을 뺀다."""
    out = []
    for r in rows:
        if not include_admin and is_admin_endpoint(r.get("endpoint")):
            continue
        if not status_matches(r.get("status_code"), status):
            continue
        if prompt_version and r.get("prompt_version") != prompt_version:
            continue
        out.append(r)
    return out


def fmt_pct(v: float | None, digits: int = 1) -> str:
    return "데이터 없음" if v is None else f"{v * 100:.{digits}f}%"


def fmt_ms(v: float | None) -> str:
    return "-" if v is None else f"{v:,.0f}ms"


def status_badge(code: Any) -> str:
    c = int(code or 0)
    if c >= 500:
        return f"🛑 {c}"
    if c >= 400:
        return f"⚠️ {c}"
    return f"✅ {c}"


def connection_message(snapshot: dict) -> tuple[str, str]:
    """(종류, 문구). 종류: info·success·warning·error. 문구 끝에 다음에 할 일 한 줄."""
    status = snapshot.get("status")
    error = snapshot.get("error") or ""
    if status == "connected":
        return "success", "실시간 연결됨. 새 요청이 생기면 바로 아래에 나타납니다."
    if status == "connecting":
        return "info", "실시간 연결 중입니다. 잠시 기다려 주세요."
    if status == "forbidden":
        return "error", "운영자 권한이 없어 실시간 로그를 받을 수 없습니다. 운영자 계정으로 로그인하세요."
    if status == "unauthorized":
        return "info", "로그인 정보를 새로 고치는 중입니다. 계속되면 다시 로그인하세요."
    if status == "stopped":
        return "info", "실시간 연결을 쉬고 있습니다. 곧 다시 연결합니다."
    if "503" in error:
        return "warning", "연결 끊김: 실시간 저장소(Redis)에 연결할 수 없습니다. 자동으로 다시 연결하는 중입니다."
    return "warning", "연결 끊김: 자동으로 다시 연결하는 중입니다(1·2·4·8초 간격). 계속되면 '다시 연결'을 누르세요."


def version_rows(by_version: dict[str, dict]) -> list[dict]:
    """프롬프트 버전별 비교 표."""
    rows = []
    for v, m in sorted(by_version.items()):
        rows.append({
            "버전": v,
            "요청 수": m.get("request_count", 0),
            "실패율": fmt_pct(m.get("error_rate")),
            "처리 시간 중앙값": fmt_ms(m.get("p50_latency_ms")),
            "처리 시간 상위 5%": fmt_ms(m.get("p95_latency_ms")),
            "AI 시간 중앙값": fmt_ms(m.get("ai_p50_latency_ms")),
            "캐시 적중률": fmt_pct(m.get("cache_hit_rate")),
            "형식 실패 비율": fmt_pct(m.get("format_error_rate")),
            "필드 수정 비율": fmt_pct((m.get("field_edit") or {}).get("ratio")),
            "👎 비율": fmt_pct((m.get("rating") or {}).get("down_rate")),
        })
    return rows
