"""지표 계산 (GET /admin/metrics). 정의는 docs/METRICS.md와 같다.

계산은 기간 조건으로 행을 가져와 서버 Python에서 한다. 순수 함수(median, p95, request_summary,
field_edit_summary, rating_summary, build_series)는 DB 없이 단위 테스트한다.
"""

from __future__ import annotations

import datetime as dt
import math
import statistics
from collections import Counter
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from app.core.analysis_contract import EDITABLE_FIELDS
from app.core.repo import overrides_from_rows
from app.core.schemas import MetricsOut
from app.features.admin_logs.common import UTC, parse_ts, select_in
from app.features.admin_logs.queries import METRIC_ROW_CAP, logs_in_period

KST = ZoneInfo("Asia/Seoul")
ANALYSIS_ENDPOINT = "/listings/{listing_id}/analyses"   # P2 분석 요청(POST) 경로
FORMAT_ERROR_CODES = frozenset({"FMT", "AI_FORMAT_ERROR"})
FEEDBACK_REASONS = ("amount", "not_in_memo", "missing_info", "pros_cons", "check_error", "other")
HOURLY_MAX_SPAN = dt.timedelta(hours=48)   # 이 길이까지는 시간 단위, 넘으면 일(서울 날짜) 단위


# ------------------------------------------------------------------ 기본 통계
def median(values: Iterable[float | int | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return float(statistics.median(vals)) if vals else None


def p95(values: Iterable[float | int | None]) -> float | None:
    """상위 5% 경계(nearest-rank): 오름차순 정렬 후 ceil(0.95·n)번째 값."""
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    k = max(1, math.ceil(0.95 * len(vals)))
    return float(vals[k - 1])


def rate(num: int, den: int) -> float | None:
    """분모가 0이면 None(화면에서 '데이터 없음')."""
    return (num / den) if den else None


# ------------------------------------------------------------------ 요청 로그 지표
def is_analysis_request(row: dict) -> bool:
    return row.get("method") == "POST" and row.get("endpoint") == ANALYSIS_ENDPOINT


def is_error(row: dict) -> bool:
    return int(row.get("status_code") or 0) >= 400


def request_summary(rows: list[dict]) -> dict[str, Any]:
    """요청 수·처리 시간·AI 시간·실패율·실패 유형·캐시 적중률·형식 오류율."""
    total = len(rows)
    errors = [r for r in rows if is_error(r)]
    analysis = [r for r in rows if is_analysis_request(r)]
    ai_values = [r.get("ai_latency_ms") for r in rows if r.get("ai_latency_ms") is not None]
    cache_hits = sum(1 for r in analysis if r.get("cache_hit") is True)
    fmt_errors = sum(1 for r in analysis if r.get("error_code") in FORMAT_ERROR_CODES)
    code_counts = Counter((r.get("error_code") or "UNKNOWN") for r in errors)
    return {
        "request_count": total,
        "error_count": len(errors),
        "error_rate": rate(len(errors), total),
        "p50_latency_ms": median(r.get("latency_ms") for r in rows),
        "p95_latency_ms": p95(r.get("latency_ms") for r in rows),
        "ai_request_count": len(ai_values),
        "ai_p50_latency_ms": median(ai_values),
        "ai_p95_latency_ms": p95(ai_values),
        "error_code_counts": dict(sorted(code_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        "analysis_request_count": len(analysis),
        "cache_hit_count": cache_hits,
        "cache_hit_rate": rate(cache_hits, len(analysis)),
        "format_error_count": fmt_errors,
        "format_error_rate": rate(fmt_errors, len(analysis)),
    }


def bucket_unit(from_: dt.datetime, to: dt.datetime) -> str:
    return "hour" if (to - from_) <= HOURLY_MAX_SPAN else "day"


def bucket_start(t: dt.datetime, unit: str) -> dt.datetime:
    """구간 시작(UTC). 일 단위는 서울 날짜 0시 기준."""
    if unit == "hour":
        return t.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    local = t.astimezone(KST).replace(hour=0, minute=0, second=0, microsecond=0)
    return local.astimezone(UTC)


def _next_bucket(t: dt.datetime, unit: str) -> dt.datetime:
    if unit == "hour":
        return t + dt.timedelta(hours=1)
    local = t.astimezone(KST)
    return (local + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


def build_series(rows: list[dict], from_: dt.datetime, to: dt.datetime, unit: str | None = None) -> dict[str, Any]:
    """기간별 요청 수·실패율·처리 시간. 요청이 없는 구간도 0으로 채운다(차트가 끊기지 않게)."""
    unit = unit or bucket_unit(from_, to)
    groups: dict[dt.datetime, list[dict]] = {}
    for r in rows:
        t = parse_ts(r.get("created_at"))
        if t is None:
            continue
        groups.setdefault(bucket_start(t, unit), []).append(r)
    points = []
    cur = bucket_start(from_, unit)
    end = bucket_start(to, unit)
    guard = 0
    while cur <= end and guard < 2000:
        items = groups.get(cur, [])
        errs = sum(1 for r in items if is_error(r))
        points.append({
            "start": cur.isoformat(),
            "count": len(items),
            "error_count": errs,
            "error_rate": rate(errs, len(items)),
            "p50_latency_ms": median(r.get("latency_ms") for r in items),
            "p95_latency_ms": p95(r.get("latency_ms") for r in items),
        })
        cur = _next_bucket(cur, unit)
        guard += 1
    return {"unit": unit, "points": points}


# ------------------------------------------------------------------ 필드 수정 비율
def field_edit_summary(success_analysis_ids: Iterable[str], feedback_rows: list[dict]) -> dict[str, Any]:
    """필드 수정 비율 = 최종 상태가 '수정'인 고유 (analysis_id, field_name) 수 ÷ (성공 분석 수 × len(EDITABLE_FIELDS)).

    분석마다 feedback 행을 created_at 순으로 놓고 core.repo.overrides_from_rows(field_overrides와 같은 규칙)로
    필드별 최종 상태를 구한다. 마지막 행이 수정 취소(action "revert")면 세지 않고, '메모에 없음'(set + null)은 센다.
    사용자가 고친 빈도이지 정답 기반 오류율이 아니다. field_name이 EDITABLE_FIELDS에 있는 행만 센다.
    """
    ids = {str(a) for a in success_analysis_ids}
    floor = dt.datetime.min.replace(tzinfo=UTC)
    per_analysis: dict[str, list[dict]] = {}
    for f in feedback_rows:
        aid = str(f.get("analysis_id"))
        if f.get("field_name") in EDITABLE_FIELDS and aid in ids:
            per_analysis.setdefault(aid, []).append(f)
    edited: set[tuple[str, str]] = set()
    for aid, rows in per_analysis.items():
        rows.sort(key=lambda r: parse_ts(r.get("created_at")) or floor)   # 같은 시각이면 받은 순서 유지
        edited.update((aid, name) for name in overrides_from_rows(rows))
    analyzed_fields = len(ids) * len(EDITABLE_FIELDS)
    by_field = Counter(name for _, name in edited)
    return {
        "analysis_count": len(ids),
        "analyzed_fields": analyzed_fields,
        "edited_fields": len(edited),
        "ratio": rate(len(edited), analyzed_fields),
        "by_field": {name: by_field.get(name, 0) for name in EDITABLE_FIELDS},
    }


# ------------------------------------------------------------------ 평가(👍/👎)
def latest_overall_feedback(rows: list[dict]) -> dict[str, dict]:
    """전체 평가(field_name null) 행 중 분석별 최신 행. feedback은 새 행 추가 방식이라 최신 행이 유효하다."""
    latest: dict[str, dict] = {}
    for r in rows:
        if r.get("field_name") is not None:
            continue
        aid = str(r.get("analysis_id"))
        cur = latest.get(aid)
        if cur is None or (parse_ts(r.get("created_at")) or dt.datetime.min.replace(tzinfo=UTC)) >= \
                (parse_ts(cur.get("created_at")) or dt.datetime.min.replace(tzinfo=UTC)):
            latest[aid] = r
    return latest


def rating_summary(latest_rows: Iterable[dict]) -> dict[str, Any]:
    """👎 비율 = down 평가 수 ÷ 전체 평가 수(분석별 최신 평가 기준). 사유별 개수는 down만 센다."""
    rated = [r for r in latest_rows if r.get("rating") in ("up", "down")]
    down = [r for r in rated if r.get("rating") == "down"]
    reasons = Counter(r.get("reason") for r in down)
    reason_counts = {k: reasons.get(k, 0) for k in FEEDBACK_REASONS}
    reason_counts["none"] = reasons.get(None, 0)
    return {
        "rating_count": len(rated),
        "down_count": len(down),
        "down_rate": rate(len(down), len(rated)),
        "reason_counts": reason_counts,
    }


# ------------------------------------------------------------------ DB에서 모아 계산
def _in_period(row: dict, from_: dt.datetime, to: dt.datetime) -> bool:
    t = parse_ts(row.get("created_at"))
    return t is not None and from_ <= t <= to


def _rating_rows(db: Any, from_: dt.datetime, to: dt.datetime) -> list[dict]:
    """기간 안에 남긴 전체 평가 행 중 분석별 최신 행(기간 끝 시점 기준)."""
    rows = db.select("feedback", {"field_name": ("is", None), "created_at": ("gte", from_)},
                     order_by="created_at", limit=METRIC_ROW_CAP)
    rows = [r for r in rows if _in_period(r, from_, to)]
    return list(latest_overall_feedback(rows).values())


def compute_metrics(db: Any, *, from_: dt.datetime, to: dt.datetime, prompt_version: str | None = None,
                    include_admin: bool = False) -> MetricsOut:
    logs, truncated = logs_in_period(db, from_=from_, to=to, prompt_version=prompt_version,
                                     include_admin=include_admin)
    summary = request_summary(logs)
    series = build_series(logs, from_, to)

    # 성공 분석(기간 내) → 필드 수정 비율
    a_filters: dict = {"status": "success", "created_at": ("gte", from_)}
    if prompt_version:
        a_filters["prompt_version"] = prompt_version
    analyses = [a for a in db.select("analyses", a_filters, limit=METRIC_ROW_CAP) if _in_period(a, from_, to)]
    analysis_ids = [str(a["id"]) for a in analyses]
    # field_name이 있는 행만 필요하지만 'IS NOT NULL' 필터가 없어 가져온 뒤 field_edit_summary가 거른다
    edit_feedback = select_in(db, "feedback", "analysis_id", analysis_ids)
    edit_all = field_edit_summary(analysis_ids, edit_feedback)

    # 평가(👎 비율·사유별 개수): 평가 대상 분석의 prompt_version으로 버전 조건·버전별 비교
    ratings = _rating_rows(db, from_, to)
    rated_ids = sorted({str(r["analysis_id"]) for r in ratings})
    version_of = {str(a["id"]): a.get("prompt_version") for a in select_in(db, "analyses", "id", rated_ids)}
    if prompt_version:
        ratings = [r for r in ratings if version_of.get(str(r["analysis_id"])) == prompt_version]
    rating_all = rating_summary(ratings)

    # 프롬프트 버전별 비교
    versions = sorted(
        {r.get("prompt_version") for r in logs if r.get("prompt_version")}
        | {a.get("prompt_version") for a in analyses if a.get("prompt_version")}
        | {v for v in (version_of.get(str(r["analysis_id"])) for r in ratings) if v}
    )
    by_version: dict[str, Any] = {}
    for v in versions:
        v_logs = [r for r in logs if r.get("prompt_version") == v]
        v_ids = [str(a["id"]) for a in analyses if a.get("prompt_version") == v]
        v_ratings = [r for r in ratings if version_of.get(str(r["analysis_id"])) == v]
        by_version[v] = {
            **request_summary(v_logs),
            "field_edit": field_edit_summary(v_ids, edit_feedback),
            "rating": rating_summary(v_ratings),
        }

    window_minutes = max(0, int((to - from_).total_seconds() // 60))
    return MetricsOut(
        window_minutes=window_minutes,
        request_count=summary["request_count"],
        error_rate=summary["error_rate"],
        p50_latency_ms=summary["p50_latency_ms"],
        p95_latency_ms=summary["p95_latency_ms"],
        ai_p50_latency_ms=summary["ai_p50_latency_ms"],
        ai_p95_latency_ms=summary["ai_p95_latency_ms"],
        cache_hit_rate=summary["cache_hit_rate"],
        format_error_rate=summary["format_error_rate"],
        extra={
            "from": from_.isoformat(),
            "to": to.isoformat(),
            "prompt_version": prompt_version,
            "include_admin": include_admin,
            "truncated": truncated,
            "error_count": summary["error_count"],
            "error_code_counts": summary["error_code_counts"],
            "ai_request_count": summary["ai_request_count"],
            "analysis_request_count": summary["analysis_request_count"],
            "cache_hit_count": summary["cache_hit_count"],
            "format_error_count": summary["format_error_count"],
            "series": series,
            "field_edit": edit_all,
            "rating": {k: rating_all[k] for k in ("rating_count", "down_count", "down_rate")},
            "feedback_reason_counts": rating_all["reason_counts"],
            "by_prompt_version": by_version,
        },
    )
