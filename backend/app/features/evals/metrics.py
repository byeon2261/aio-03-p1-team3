"""채점·지표 계산. 팀이 조정할 수 있게 기준은 모두 위쪽 상수로 둔다.

정답(expected)과 AI 출력(output)을 비교하는 지표다.
P6의 "필드 수정 비율"(사용자가 고친 빈도)과는 다른 지표다.

필드 비교 방법
    금액 3필드                                   정확히 일치(null 포함)
    maintenance_includes·unchecked·missing_checks  집합으로 일치
    floor·direction                              공백을 지운 문자열 일치
    pros·cons·transit·ambiguous·checks 근거·ambiguous_checks·mixed_listings
                                                 자동 채점 제외(화면에서 사람이 판단, mixed_listings는 일치 여부만 표시)

failure_codes 자동 부여: NUM·HAL·MIS·CHK·FMT. CLS(장단점 오분류)는 사람이 판단한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from app.core.analysis_contract import EVAL_FIELDS

# ------------------------------------------------------------------ 비교 대상 (조정 가능)
MONEY_FIELDS = ("deposit_manwon", "monthly_rent_manwon", "maintenance_fee_manwon")
SET_FIELDS = ("maintenance_includes", "unchecked", "missing_checks")
TEXT_FIELDS = ("floor", "direction")

# 환각: 정답이 null인데 출력에 값이 있는 필드. null이 있을 수 있는 단일 값 필드만 본다.
HALLUCINATION_FIELDS = MONEY_FIELDS + TEXT_FIELDS
# MIS: 정답 목록의 항목이 출력에서 빠짐. missing_checks는 CHK가 따로 본다.
MISSING_ITEM_FIELDS = ("maintenance_includes", "unchecked")
# 자동 채점 제외, 화면에서 사람이 판단
HUMAN_REVIEW_FIELDS = ("pros", "cons", "transit", "ambiguous", "checks", "ambiguous_checks", "mixed_listings")

FAILURE_CODES = ("NUM", "HAL", "MIS", "CHK", "FMT")
HUMAN_FAILURE_CODES = ("CLS",)

# 파이프라인이 "재시도 후에도 형식 실패"로 돌려주는 오류 코드
FORMAT_ERROR_CODES = frozenset({"AI_FORMAT_ERROR", "FMT"})
STATUS_SUCCESS = "success"

# 정답 JSON 안에 함께 저장하는 판단 기준(채점에는 쓰지 않는다)
CRITERIA_KEY = "_criteria"


def field_method(name: str) -> str:
    if name in MONEY_FIELDS:
        return "exact"
    if name in SET_FIELDS:
        return "set"
    if name in TEXT_FIELDS:
        return "text"
    return "exact"


# ------------------------------------------------------------------ 값 정리
def normalize_text(value: Any) -> str | None:
    """공백(띄어쓰기·줄바꿈)을 모두 지운다. 지운 뒤 비면 None."""
    if value is None:
        return None
    s = "".join(str(value).split())
    return s or None


def as_set(value: Any) -> set[str]:
    if not value:
        return set()
    if isinstance(value, str):
        value = [value]
    return {str(x).strip() for x in value if str(x).strip()}


def is_empty(value: Any) -> bool:
    """환각 판단용 '값 없음'. None, 빈 문자열, 빈 목록."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set)):
        return len(value) == 0
    return False


def field_match(name: str, expected: Any, output: Any) -> bool:
    method = field_method(name)
    if method == "set":
        return as_set(expected) == as_set(output)
    if method == "text":
        return normalize_text(expected) == normalize_text(output)
    return expected == output


def is_format_failure(status: str | None) -> bool:
    return status in FORMAT_ERROR_CODES


def split_expected(expected_json: dict | None) -> tuple[dict | None, str | None]:
    """저장된 expected_json → (정답, criteria)."""
    if expected_json is None:
        return None, None
    data = dict(expected_json)
    criteria = data.pop(CRITERIA_KEY, None)
    return data, criteria


def mixed_listings_match(expected: dict | None, output: dict | None) -> bool | None:
    """mixed_listings 일치 여부(표시용, 지표에는 넣지 않음). 비교할 수 없으면 None."""
    if expected is None or output is None:
        return None
    return bool(expected.get("mixed_listings")) == bool(output.get("mixed_listings"))


# ------------------------------------------------------------------ 사례 채점
@dataclass
class CaseScore:
    status: str
    field_matches: dict[str, bool]
    failure_codes: list[str]
    has_output: bool
    null_expected: int = 0          # 정답이 null인 환각 대상 필드 수
    hallucinated: int = 0           # 그중 출력에 값이 있는 필드 수
    missing_checks_match: bool = False
    hallucinated_fields: list[str] = field(default_factory=list)


def score_case(expected: dict, output: dict | None, status: str = STATUS_SUCCESS) -> CaseScore:
    """사례 하나를 채점한다.

    output이 None(형식 실패·AI 오류)이면 평가 필드는 모두 불일치로 센다.
    이때 failure_codes는 형식 실패면 ["FMT"], 그 밖의 오류면 [].
    """
    expected = split_expected(expected)[0] or {}
    if output is None:
        return CaseScore(
            status=status,
            field_matches={f: False for f in EVAL_FIELDS},
            failure_codes=["FMT"] if is_format_failure(status) else [],
            has_output=False,
        )

    matches = {f: field_match(f, expected.get(f), output.get(f)) for f in EVAL_FIELDS}

    null_expected = 0
    hallucinated_fields: list[str] = []
    for f in HALLUCINATION_FIELDS:
        if is_empty(expected.get(f)):
            null_expected += 1
            if not is_empty(output.get(f)):
                hallucinated_fields.append(f)

    codes: set[str] = set()
    if any(not matches[f] for f in MONEY_FIELDS if f in matches):
        codes.add("NUM")
    if hallucinated_fields:
        codes.add("HAL")
    for f in MISSING_ITEM_FIELDS:
        if as_set(expected.get(f)) - as_set(output.get(f)):
            codes.add("MIS")
    missing_ok = as_set(expected.get("missing_checks")) == as_set(output.get("missing_checks"))
    if not missing_ok:
        codes.add("CHK")

    return CaseScore(
        status=status,
        field_matches=matches,
        failure_codes=[c for c in FAILURE_CODES if c in codes],
        has_output=True,
        null_expected=null_expected,
        hallucinated=len(hallucinated_fields),
        missing_checks_match=missing_ok,
        hallucinated_fields=hallucinated_fields,
    )


# ------------------------------------------------------------------ 실행 지표
def _rate(num: int, den: int) -> float | None:
    return num / den if den else None


def aggregate(scores: Iterable[CaseScore]) -> dict[str, float | None]:
    """실행 지표 4개.

    필드 정확도     일치한 평가 필드 ÷ 전체 평가 필드(전체 사례 × EVAL_FIELDS, 출력 없는 사례는 모두 불일치)
    환각률          정답 null인데 값 있는 필드 ÷ 정답 null 필드(출력이 있는 사례만)
    빠진 항목 정확도 missing_checks 집합이 맞은 사례 ÷ 전체 사례
    형식 실패율     재시도 후에도 형식 실패한 사례 ÷ 전체 사례
    사례가 없으면 모두 None.
    """
    scores = list(scores)
    n = len(scores)
    total_fields = n * len(EVAL_FIELDS)
    matched = sum(sum(1 for v in s.field_matches.values() if v) for s in scores)
    null_expected = sum(s.null_expected for s in scores if s.has_output)
    hallucinated = sum(s.hallucinated for s in scores if s.has_output)
    missing_ok = sum(1 for s in scores if s.missing_checks_match)
    fmt = sum(1 for s in scores if "FMT" in s.failure_codes)
    return {
        "field_accuracy": _rate(matched, total_fields),
        "hallucination_rate": _rate(hallucinated, null_expected),
        "missing_check_accuracy": _rate(missing_ok, n),
        "format_error_rate": _rate(fmt, n),
    }


def failure_counts(code_lists: Iterable[Iterable[str] | None]) -> dict[str, int]:
    """eval_results.failure_codes 목록들 → 코드별 사례 수(한 사례에 같은 코드가 여럿이어도 1)."""
    counts = {c: 0 for c in FAILURE_CODES}
    for codes in code_lists:
        for c in set(codes or []):
            if c in counts:
                counts[c] += 1
    return counts


CONDITION_KEYS = ("model", "thinking_level", "schema_version")


def condition_mismatches(run_a: dict, run_b: dict, case_ids_a: Iterable[str],
                         case_ids_b: Iterable[str]) -> list[str]:
    """비교 조건(model·thinking_level·schema_version·사례 목록) 중 서로 다른 것의 이름. 같으면 []."""
    out = [k for k in CONDITION_KEYS if (run_a or {}).get(k) != (run_b or {}).get(k)]
    if {str(x) for x in case_ids_a} != {str(x) for x in case_ids_b}:
        out.append("case_list")
    return out
