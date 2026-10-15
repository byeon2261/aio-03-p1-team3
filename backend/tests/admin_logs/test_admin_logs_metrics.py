"""지표 계산 단위 테스트와 /admin/metrics 집계 범위(/admin 제외, include_admin)."""

from __future__ import annotations

import pytest

from app.core.analysis_contract import EDITABLE_FIELDS
from app.features.admin_logs.metrics import (
    build_series,
    field_edit_summary,
    latest_overall_feedback,
    median,
    p95,
    rating_summary,
    request_summary,
)
from tests.admin_logs.helpers import (
    add_analysis,
    add_analysis_request,
    add_feedback,
    add_log,
    at,
    make_listing,
)


# ------------------------------------------------------------------ 순수 함수
def test_admin_logs_median_and_p95():
    assert median([]) is None
    assert median([3, 1, 2]) == 2.0
    assert median([1, 2, 3, 4]) == 2.5
    assert median([None, 5]) == 5.0
    values = list(range(1, 101))          # 1..100 → ceil(95)=95번째 = 95
    assert p95(values) == 95.0
    assert p95([10]) == 10.0
    assert p95(list(range(1, 20)) + [1000]) == 19.0    # n=20 → 19번째
    assert p95(list(range(1, 10)) + [1000]) == 1000.0  # n=10 → ceil(9.5)=10번째
    assert p95([None]) is None


def test_admin_logs_request_summary_counts():
    rows = [
        {"endpoint": "/sessions", "method": "GET", "status_code": 200, "latency_ms": 100},
        {"endpoint": "/listings/{listing_id}/analyses", "method": "POST", "status_code": 200, "latency_ms": 900,
         "ai_latency_ms": 800, "cache_hit": False},
        {"endpoint": "/listings/{listing_id}/analyses", "method": "POST", "status_code": 200, "latency_ms": 50,
         "ai_latency_ms": None, "cache_hit": True},
        {"endpoint": "/listings/{listing_id}/analyses", "method": "POST", "status_code": 502, "latency_ms": 700,
         "ai_latency_ms": 600, "cache_hit": False, "error_code": "AI_FORMAT_ERROR"},
        {"endpoint": "/listings/{listing_id}", "method": "GET", "status_code": 404, "latency_ms": 30,
         "error_code": "LISTING_NOT_FOUND"},
    ]
    s = request_summary(rows)
    assert s["request_count"] == 5
    assert s["error_count"] == 2 and s["error_rate"] == pytest.approx(0.4)
    assert s["p50_latency_ms"] == 100.0
    assert s["ai_request_count"] == 2 and s["ai_p50_latency_ms"] == 700.0
    assert s["error_code_counts"] == {"AI_FORMAT_ERROR": 1, "LISTING_NOT_FOUND": 1}
    assert s["analysis_request_count"] == 3
    assert s["cache_hit_rate"] == pytest.approx(1 / 3)
    assert s["format_error_rate"] == pytest.approx(1 / 3)


def test_admin_logs_request_summary_empty_is_none():
    s = request_summary([])
    assert s["request_count"] == 0
    assert s["error_rate"] is None and s["p50_latency_ms"] is None and s["cache_hit_rate"] is None


def test_admin_logs_field_edit_ratio_uses_editable_fields_denominator():
    fb = [
        {"analysis_id": "a1", "field_name": "deposit_manwon", "corrected_value": 300, "action": "set"},
        {"analysis_id": "a1", "field_name": "deposit_manwon", "corrected_value": 350, "action": "set"},  # 다시 수정 → 1번
        {"analysis_id": "a1", "field_name": "transit", "corrected_value": "버스", "action": "set"},
        {"analysis_id": "a2", "field_name": "pros", "corrected_value": ["역세권"], "action": "set"},
        {"analysis_id": "a1", "field_name": None},                 # 전체 평가 → 제외
        {"analysis_id": "a1", "field_name": "label", "corrected_value": "x", "action": "set"},  # EDITABLE 아님 → 제외
        {"analysis_id": "zz", "field_name": "pros", "corrected_value": [], "action": "set"},    # 기간 밖 분석 → 제외
    ]
    s = field_edit_summary(["a1", "a2"], fb)
    assert s["analyzed_fields"] == 2 * len(EDITABLE_FIELDS)
    assert s["edited_fields"] == 3
    assert s["ratio"] == pytest.approx(3 / (2 * len(EDITABLE_FIELDS)))
    assert s["by_field"]["deposit_manwon"] == 1
    assert field_edit_summary([], fb)["ratio"] is None


def test_admin_logs_field_edit_counts_final_state_only():
    """(나) 최종 상태 기준: 마지막 행이 되돌림이면 빼고, '메모에 없음'(set + null)은 센다. 행 순서는 created_at."""
    fb = [
        {"analysis_id": "a1", "field_name": "floor", "corrected_value": None, "action": "revert",
         "created_at": "2026-10-15T01:00:02+00:00"},
        {"analysis_id": "a1", "field_name": "floor", "corrected_value": "3층", "action": "set",
         "created_at": "2026-10-15T01:00:01+00:00"},                                   # 고친 뒤 되돌림 → 0
        {"analysis_id": "a1", "field_name": "monthly_rent_manwon", "corrected_value": None, "action": "set",
         "created_at": "2026-10-15T01:00:03+00:00"},                                   # 메모에 없음 → 1
        {"analysis_id": "a2", "field_name": "transit", "corrected_value": "버스",
         "created_at": "2026-10-15T01:00:01+00:00"},                                   # 옛 행(action 없음) 값 → 1
        {"analysis_id": "a2", "field_name": "direction", "corrected_value": None,
         "created_at": "2026-10-15T01:00:01+00:00"},                                   # 옛 행 null = 취소 → 0
    ]
    s = field_edit_summary(["a1", "a2"], fb)
    assert s["edited_fields"] == 2
    assert s["by_field"]["monthly_rent_manwon"] == 1 and s["by_field"]["transit"] == 1
    assert s["by_field"]["floor"] == 0 and s["by_field"]["direction"] == 0


def test_admin_logs_down_rate_uses_latest_rating_and_reason_counts():
    rows = [
        {"id": "1", "analysis_id": "a1", "field_name": None, "rating": "down", "reason": "amount",
         "created_at": at(0).isoformat()},
        {"id": "2", "analysis_id": "a1", "field_name": None, "rating": "up", "reason": None,
         "created_at": at(5).isoformat()},                         # a1은 최신이 up
        {"id": "3", "analysis_id": "a2", "field_name": None, "rating": "down", "reason": "not_in_memo",
         "created_at": at(1).isoformat()},
        {"id": "4", "analysis_id": "a3", "field_name": None, "rating": "down", "reason": None,
         "created_at": at(2).isoformat()},
        {"id": "5", "analysis_id": "a4", "field_name": "transit", "rating": None, "created_at": at(3).isoformat()},
    ]
    latest = latest_overall_feedback(rows)
    assert latest["a1"]["id"] == "2" and "a4" not in latest
    s = rating_summary(latest.values())
    assert s["rating_count"] == 3 and s["down_count"] == 2
    assert s["down_rate"] == pytest.approx(2 / 3)
    assert s["reason_counts"] == {"amount": 0, "not_in_memo": 1, "missing_info": 0, "pros_cons": 0,
                                  "check_error": 0, "other": 0, "none": 1}


def test_admin_logs_series_fills_empty_hours():
    rows = [
        {"created_at": at(minutes=5).isoformat(), "status_code": 200, "latency_ms": 100},
        {"created_at": at(minutes=10).isoformat(), "status_code": 500, "latency_ms": 300},
        {"created_at": at(hours=2, minutes=1).isoformat(), "status_code": 200, "latency_ms": 50},
    ]
    s = build_series(rows, at(0), at(hours=3))
    assert s["unit"] == "hour"
    counts = [p["count"] for p in s["points"]]
    assert counts == [2, 0, 1, 0]
    assert s["points"][0]["error_rate"] == 0.5 and s["points"][1]["error_rate"] is None


def test_admin_logs_series_uses_seoul_days_for_long_ranges():
    s = build_series([], at(0), at(days=5))
    assert s["unit"] == "day"
    # 서울 0시 = UTC 15시(전날)
    assert s["points"][0]["start"].endswith("15:00:00+00:00")


# ------------------------------------------------------------------ /admin/metrics
def test_admin_logs_metrics_excludes_admin_requests_by_default(client_as, make_user, memory_db):
    admin = make_user("admin")
    add_log(memory_db, endpoint="/sessions", latency_ms=100, created_at=at(1))
    add_log(memory_db, endpoint="/admin/logs", latency_ms=5000, created_at=at(2))
    add_log(memory_db, endpoint="/admin/feedback", status_code=500, error_code="INTERNAL_ERROR", created_at=at(3))
    c = client_as(admin)
    period = {"from": at(0).isoformat(), "to": at(10).isoformat()}

    m = c.get("/admin/metrics", params=period).json()
    assert m["request_count"] == 1 and m["error_rate"] == 0.0 and m["p95_latency_ms"] == 100.0
    assert m["window_minutes"] == 10
    assert m["extra"]["include_admin"] is False

    m2 = c.get("/admin/metrics", params={**period, "include_admin": "true"}).json()
    assert m2["request_count"] == 3
    assert m2["extra"]["error_code_counts"] == {"INTERNAL_ERROR": 1}


def test_admin_logs_metrics_end_to_end_with_versions(client_as, make_user, memory_db):
    admin, alice = make_user("admin"), make_user()
    listing = make_listing(memory_db, alice.profile_id)
    a1 = add_analysis(memory_db, listing["id"], prompt_version="v1", created_at=at(1))
    a2 = add_analysis(memory_db, listing["id"], prompt_version="v2", created_at=at(2))
    add_analysis(memory_db, listing["id"], status="failed", prompt_version="v2", created_at=at(3))   # 분모 제외
    add_feedback(memory_db, a1["id"], alice.profile_id, field_name="deposit_manwon", corrected_value=550,
                 created_at=at(4))
    add_feedback(memory_db, a2["id"], alice.profile_id, rating="down", reason="amount", created_at=at(5))
    add_feedback(memory_db, a1["id"], alice.profile_id, rating="up", created_at=at(6))
    add_analysis_request(memory_db, prompt_version="v1", cache_hit=True, ai_latency_ms=None, created_at=at(1))
    add_analysis_request(memory_db, prompt_version="v2", created_at=at(2))
    add_analysis_request(memory_db, prompt_version="v2", status_code=502, error_code="AI_FORMAT_ERROR",
                         created_at=at(3))

    c = client_as(admin)
    period = {"from": at(0).isoformat(), "to": at(30).isoformat()}
    m = c.get("/admin/metrics", params=period).json()
    ex = m["extra"]
    assert m["request_count"] == 3
    assert m["cache_hit_rate"] == pytest.approx(1 / 3)
    assert m["format_error_rate"] == pytest.approx(1 / 3)
    assert ex["field_edit"]["analysis_count"] == 2
    assert ex["field_edit"]["edited_fields"] == 1
    assert ex["field_edit"]["ratio"] == pytest.approx(1 / (2 * len(EDITABLE_FIELDS)))
    assert ex["rating"] == {"rating_count": 2, "down_count": 1, "down_rate": 0.5}
    assert ex["feedback_reason_counts"]["amount"] == 1
    assert set(ex["by_prompt_version"]) == {"v1", "v2"}
    v1, v2 = ex["by_prompt_version"]["v1"], ex["by_prompt_version"]["v2"]
    assert v1["field_edit"]["edited_fields"] == 1 and v2["field_edit"]["edited_fields"] == 0
    assert v1["rating"]["down_rate"] == 0.0 and v2["rating"]["down_rate"] == 1.0
    assert v2["error_rate"] == 0.5

    only_v2 = c.get("/admin/metrics", params={**period, "prompt_version": "v2"}).json()
    assert only_v2["request_count"] == 2
    assert only_v2["extra"]["field_edit"]["analysis_count"] == 1
    assert only_v2["extra"]["rating"]["down_count"] == 1 and only_v2["extra"]["rating"]["rating_count"] == 1


def test_admin_logs_metrics_default_window_is_24h(client_as, make_user):
    m = client_as(make_user("admin")).get("/admin/metrics").json()
    assert m["window_minutes"] == 24 * 60
    assert m["request_count"] == 0 and m["error_rate"] is None
