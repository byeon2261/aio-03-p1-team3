"""기준 세트(eval_cases) 파일 읽기·검증·적재. scripts/load_eval_cases.py와 테스트가 쓴다.

파일 형식: 사례 목록, 또는 {"cases": [...]} (다른 키는 설명용으로 무시).
사례 항목: {case_key, memo_text, expected_json(AnalysisResult 모양), tags, criteria}
- expected_json이 비었거나 AnalysisResult로 검증되지 않으면 넣지 않고 이유를 돌려준다.
- criteria는 eval_cases에 열이 없어 expected_json 안의 "_criteria" 키로 함께 저장한다(채점에는 쓰지 않음).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.core.analysis_contract import AnalysisResult
from app.core.schemas import MEMO_MAX_CHARS
from app.features.evals.metrics import CRITERIA_KEY

CASE_KEY_MAX_CHARS = 100


@dataclass
class CaseLoadReport:
    inserted: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)   # (case_key, 이유)


def read_case_file(path: str | Path) -> list[Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("cases")
    if not isinstance(data, list):
        raise ValueError("사례 목록(list) 또는 {\"cases\": [...]} 형식이어야 합니다")
    return data


def _validation_reason(exc: ValidationError) -> str:
    """입력값은 빼고 위치·메시지만(메모 원문이 섞이지 않게)."""
    parts = []
    for e in exc.errors()[:3]:
        loc = ".".join(str(x) for x in e.get("loc", ())) or "(전체)"
        parts.append(f"{loc}: {e.get('msg')}")
    more = len(exc.errors()) - 3
    return "AnalysisResult 검증 실패 — " + "; ".join(parts) + (f" 외 {more}건" if more > 0 else "")


def _criteria_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        value = "\n".join(str(x) for x in value)
    text = str(value).strip()
    return text or None


def validate_case(item: Any, index: int) -> tuple[str, dict | None, str | None]:
    """항목 하나 → (case_key, DB에 넣을 행 또는 None, 거부 이유 또는 None)."""
    if not isinstance(item, dict):
        return f"#{index + 1}", None, "항목이 객체가 아닙니다"
    key = item.get("case_key")
    if not isinstance(key, str) or not key.strip():
        return f"#{index + 1}", None, "case_key가 비었습니다"
    key = key.strip()
    if len(key) > CASE_KEY_MAX_CHARS:
        return key[:CASE_KEY_MAX_CHARS], None, f"case_key는 {CASE_KEY_MAX_CHARS}자 이하로 씁니다"

    memo = item.get("memo_text")
    if not isinstance(memo, str) or not memo.strip():
        return key, None, "memo_text가 비었습니다"
    if len(memo) > MEMO_MAX_CHARS:
        return key, None, f"memo_text가 {MEMO_MAX_CHARS}자를 넘습니다"

    tags = item.get("tags", [])
    if tags is None:
        tags = []
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        return key, None, "tags는 문자열 목록이어야 합니다"

    expected = item.get("expected_json")
    if expected is None or expected == {} or expected == "":
        return key, None, "expected_json이 비었습니다(정답을 채운 뒤 넣으세요)"
    if not isinstance(expected, dict):
        return key, None, "expected_json은 객체여야 합니다"
    try:
        result = AnalysisResult.model_validate({k: v for k, v in expected.items() if k != CRITERIA_KEY})
    except ValidationError as exc:
        return key, None, _validation_reason(exc)

    stored = result.model_dump(mode="json")
    criteria = _criteria_text(item.get("criteria"))
    if criteria:
        stored[CRITERIA_KEY] = criteria
    row = {"case_key": key, "memo_text": memo, "expected_json": stored, "tags": [t.strip() for t in tags if t.strip()]}
    return key, row, None


def load_cases(db: Any, items: list[Any]) -> CaseLoadReport:
    """case_key 기준으로 넣거나 갱신한다. 파일 안에 같은 case_key가 또 나오면 뒤의 것은 거부."""
    report = CaseLoadReport()
    seen: set[str] = set()
    for i, item in enumerate(items):
        key, row, reason = validate_case(item, i)
        if row is None:
            report.rejected.append((key, reason or "알 수 없는 이유"))
            continue
        if key in seen:
            report.rejected.append((key, "파일 안에 같은 case_key가 이미 있습니다"))
            continue
        seen.add(key)
        existing = db.select("eval_cases", {"case_key": key}, limit=1)
        if existing:
            db.update("eval_cases", {"id": existing[0]["id"]},
                      {"memo_text": row["memo_text"], "expected_json": row["expected_json"], "tags": row["tags"]})
            report.updated.append(key)
        else:
            db.insert("eval_cases", row)
            report.inserted.append(key)
    return report
