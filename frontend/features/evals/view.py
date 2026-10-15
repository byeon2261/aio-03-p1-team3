"""화면에 그릴 표 데이터를 만드는 함수. st 함수를 부르지 않는다(값 → 글자·표 행).

차이는 계산된 그대로 보여 준다. 개선 후가 나빠졌어도 그대로 표시한다.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from core.ui import fmt_kst, fmt_manwon, to_kst

# 서버(runner.STALE_RUNNING_MINUTES)와 같은 값. 이보다 오래 'running'이면 멈춘 실행으로 본다
STALE_MINUTES = 30

PROMPT_VERSIONS = ("v1", "v2")

# (key, 이름, 높을수록 좋은가)
METRICS = (
    ("field_accuracy", "필드 정확도", True),
    ("hallucination_rate", "환각률", False),
    ("missing_check_accuracy", "빠진 항목 정확도", True),
    ("format_error_rate", "형식 실패율", False),
)
FAILURE_CODES = (
    ("NUM", "금액 불일치"),
    ("HAL", "정답 null인데 값 있음"),
    ("MIS", "정답 목록 항목 누락"),
    ("CHK", "빠진 확인 항목 불일치"),
    ("FMT", "형식 실패"),
)
HUMAN_CODES = (("CLS", "장단점 오분류"),)

EVAL_FIELDS = (
    ("deposit_manwon", "보증금"),
    ("monthly_rent_manwon", "월세"),
    ("maintenance_fee_manwon", "관리비"),
    ("maintenance_includes", "관리비 포함"),
    ("unchecked", "확인 못함"),
    ("missing_checks", "빠진 확인 항목"),
    ("floor", "층수"),
    ("direction", "방향"),
)
HUMAN_FIELDS = (
    ("pros", "장점"),
    ("cons", "단점"),
    ("transit", "교통"),
    ("ambiguous", "애매한 구절"),
    ("checks", "체크 근거"),
    ("ambiguous_checks", "애매한 확인 항목"),
    ("mixed_listings", "여러 집 섞임"),
)
MONEY_KEYS = {"deposit_manwon", "monthly_rent_manwon", "maintenance_fee_manwon"}

CONDITION_LABELS = {
    "model": "모델",
    "thinking_level": "thinking_level",
    "schema_version": "스키마 버전",
    "case_list": "사례 목록",
}
STATUS_LABELS = {
    "success": "성공",
    "AI_FORMAT_ERROR": "형식 실패",
    "FMT": "형식 실패",
    "AI_TIMEOUT": "AI 시간 초과",
    "AI_RATE_LIMITED": "AI 한도 초과",
    "missing": "이 실행에 없음",
}
RUN_STATUS_LABELS = {"running": "진행 중", "done": "완료", "failed": "실패"}


def active_running(runs: list[dict], now: dt.datetime | None = None) -> list[dict]:
    """최근에 시작해 아직 진행 중인 실행(멈춘 실행은 빼서 새 실행을 막지 않는다)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    out = []
    for r in runs:
        if r.get("status") != "running":
            continue
        started = to_kst(r.get("created_at"))
        if started is None or now - started < dt.timedelta(minutes=STALE_MINUTES):
            out.append(r)
    return out


# ------------------------------------------------------------------ 값 표시
def fmt_pct(v: float | None) -> str:
    return "계산 안 됨" if v is None else f"{v * 100:.1f}%"


def fmt_diff_pp(before: float | None, after: float | None) -> str:
    if before is None or after is None:
        return "-"
    d = (after - before) * 100
    return "0.0%p" if abs(d) < 0.05 else f"{d:+.1f}%p"


def verdict(before: float | None, after: float | None, higher_is_better: bool) -> str:
    if before is None or after is None:
        return "-"
    d = after - before
    if abs(d) < 1e-9:
        return "같음"
    return "좋아짐" if (d > 0) == higher_is_better else "나빠짐"


def fmt_status(status: str | None) -> str:
    if not status:
        return "-"
    return STATUS_LABELS.get(status, status)


def fmt_value(key: str, value: Any, *, has_output: bool = True) -> str:
    """필드 값 하나를 글자로. 출력이 없으면 '출력 없음', None은 '미기재'(0과 다름)."""
    if not has_output:
        return "출력 없음"
    if key in MONEY_KEYS:
        return fmt_manwon(value)
    if key == "checks":
        if not value:
            return "(없음)"
        return " / ".join(f"{c.get('item')}({c.get('status')}): {c.get('evidence')}" for c in value)
    if key == "mixed_listings":
        return "예" if value else "아니오"
    if isinstance(value, list):
        return ", ".join(str(x) for x in value) if value else "(없음)"
    if value is None or (isinstance(value, str) and not value.strip()):
        return "미기재"
    return str(value)


def fmt_match(v: bool | None) -> str:
    if v is None:
        return "-"
    return "✅" if v else "❌"


def run_label(run: dict) -> str:
    return (f"{fmt_kst(run.get('created_at'))} · {run.get('prompt_version')} · "
            f"{RUN_STATUS_LABELS.get(run.get('status'), run.get('status'))} · 사례 {run.get('case_count', 0)}건")


# ------------------------------------------------------------------ 표 데이터
def metric_rows(before: dict, after: dict) -> list[dict]:
    rows = []
    for key, label, higher in METRICS:
        b, a = before.get(key), after.get(key)
        rows.append({
            "지표": label,
            "기준": "높을수록 좋음" if higher else "낮을수록 좋음",
            "개선 전": fmt_pct(b),
            "개선 후": fmt_pct(a),
            "차이": fmt_diff_pp(b, a),
            "판정": verdict(b, a, higher),
        })
    return rows


def failure_rows(before: dict, after: dict) -> list[dict]:
    fb, fa = before.get("failure_counts") or {}, after.get("failure_counts") or {}
    rows = []
    for code, desc in FAILURE_CODES:
        b, a = int(fb.get(code, 0)), int(fa.get(code, 0))
        rows.append({"유형": code, "뜻": desc, "개선 전(사례 수)": str(b), "개선 후(사례 수)": str(a),
                     "차이": f"{a - b:+d}" if a != b else "0"})
    for code, desc in HUMAN_CODES:
        rows.append({"유형": code, "뜻": desc, "개선 전(사례 수)": "사람 판단", "개선 후(사례 수)": "사람 판단",
                     "차이": "-"})
    return rows


def run_list_rows(runs: list[dict]) -> list[dict]:
    rows = []
    for r in runs:
        fc = r.get("failure_counts") or {}
        rows.append({
            "시작": fmt_kst(r.get("created_at")),
            "프롬프트": r.get("prompt_version"),
            "상태": RUN_STATUS_LABELS.get(r.get("status"), r.get("status")),
            "진행": f"{r.get('result_count', 0)}/{r.get('case_count', 0)}",
            "모델": r.get("model"),
            "thinking": r.get("thinking_level") or "-",
            "스키마": r.get("schema_version"),
            "필드 정확도": fmt_pct(r.get("field_accuracy")),
            "환각률": fmt_pct(r.get("hallucination_rate")),
            "빠진 항목 정확도": fmt_pct(r.get("missing_check_accuracy")),
            "형식 실패율": fmt_pct(r.get("format_error_rate")),
            "실패 유형": " ".join(f"{c}{fc.get(c, 0)}" for c, _ in FAILURE_CODES),
            "AI 오류": str(r.get("error_case_count", 0)),
        })
    return rows


def case_field_rows(item: dict) -> list[dict]:
    """평가 필드: 정답 · 개선 전 출력/일치 · 개선 후 출력/일치."""
    expected = item.get("expected_json") or {}
    before = item.get("compare_output_json") or {}
    after = item.get("output_json") or {}
    has_before = item.get("compare_output_json") is not None
    has_after = item.get("output_json") is not None
    mb = item.get("compare_field_matches") or {}
    ma = item.get("field_matches") or {}
    rows = []
    for key, label in EVAL_FIELDS:
        rows.append({
            "필드": label,
            "정답": fmt_value(key, expected.get(key)),
            "개선 전": fmt_value(key, before.get(key), has_output=has_before),
            "전 일치": fmt_match(mb.get(key)) if mb else "-",
            "개선 후": fmt_value(key, after.get(key), has_output=has_after),
            "후 일치": fmt_match(ma.get(key)) if ma else "-",
        })
    return rows


def case_human_rows(item: dict) -> list[dict]:
    """자동 채점 제외 필드: 사람이 나란히 보고 판단한다(mixed_listings는 일치 여부만)."""
    expected = item.get("expected_json") or {}
    before = item.get("compare_output_json") or {}
    after = item.get("output_json") or {}
    has_before = item.get("compare_output_json") is not None
    has_after = item.get("output_json") is not None
    rows = []
    for key, label in HUMAN_FIELDS:
        row = {
            "필드": label,
            "정답": fmt_value(key, expected.get(key)),
            "개선 전": fmt_value(key, before.get(key), has_output=has_before),
            "개선 후": fmt_value(key, after.get(key), has_output=has_after),
        }
        if key == "mixed_listings":
            row["개선 전"] += f" {fmt_match(item.get('compare_mixed_listings_match'))}"
            row["개선 후"] += f" {fmt_match(item.get('mixed_listings_match'))}"
        rows.append(row)
    return rows


def case_changed(item: dict) -> bool:
    """개선 전후 결과가 달라진 사례인가(상태·일치 필드·실패 유형 중 하나라도)."""
    return (item.get("status") != item.get("compare_status")
            or (item.get("field_matches") or {}) != (item.get("compare_field_matches") or {})
            or sorted(item.get("failure_codes") or []) != sorted(item.get("compare_failure_codes") or []))


def case_title(item: dict) -> str:
    before = ",".join(item.get("compare_failure_codes") or []) or "없음"
    after = ",".join(item.get("failure_codes") or []) or "없음"
    tags = ", ".join(item.get("tags") or [])
    return (f"{item.get('case_key')} [{tags}] — 전 {fmt_status(item.get('compare_status'))}·실패 {before} "
            f"→ 후 {fmt_status(item.get('status'))}·실패 {after}")


def default_pair(done_runs: list[dict]) -> tuple[int, int]:
    """기본 선택(목록은 최신순): 개선 전 = 가장 최근 v1, 개선 후 = 가장 최근 v2. 없으면 최근 두 개."""
    idx_v1 = next((i for i, r in enumerate(done_runs) if r.get("prompt_version") == "v1"), None)
    idx_v2 = next((i for i, r in enumerate(done_runs) if r.get("prompt_version") == "v2"), None)
    if idx_v1 is not None and idx_v2 is not None:
        return idx_v1, idx_v2
    return (1, 0) if len(done_runs) >= 2 else (0, 0)
