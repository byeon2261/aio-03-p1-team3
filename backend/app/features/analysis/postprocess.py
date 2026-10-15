"""AI 응답 검증과 F5 빠진 확인 항목 후처리.

parse_ai_output(text)        JSON 파싱 → 체크리스트 밖 항목 제거 → AnalysisAIOutput 검증. 실패 시 FormatError(요약)
normalize_checks(ai, memo)   F5 규칙으로 checks 정리
postprocess(ai, memo)        정리한 checks로 AnalysisResult(네 목록은 서버 계산)

F5 규칙
  1. CHECKLIST 밖의 item은 버린다(검증 전에 원본 JSON에서 뺀다. 원본은 raw_output에 남는다).
  2. evidence가 메모에 없으면(공백을 지우고 부분 문자열로 비교) status를 ambiguous로 바꾼다.
  3. 같은 item이 여러 번 나오면 하나로 합친다. status가 서로 다르면 ambiguous.
  4. floor가 있는데 checks에 "층수"가 없으면 confirmed로 더한다(evidence는 floor 값). transit과 "교통"도 같다.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from app.core.analysis_contract import CHECKLIST, AnalysisAIOutput, AnalysisResult, CheckItem, build_result

ERROR_SUMMARY_MAX = 300
_WS_RE = re.compile(r"\s+")
_QUOTES = "\"'“”‘’「」『』`"

# 서버가 값으로부터 보충하는 항목: (결과 필드, 체크리스트 항목)
DERIVED_CHECKS = (("floor", "층수"), ("transit", "교통"))


class FormatError(Exception):
    """형식 검증 실패. summary는 필드 경로와 이유(300자 이내, 입력값·메모 원문 없음)."""

    def __init__(self, summary: str):
        super().__init__("format error")
        self.summary = summary[:ERROR_SUMMARY_MAX]


def _summarize_validation(exc: ValidationError) -> str:
    parts = []
    for e in exc.errors(include_url=False, include_input=False, include_context=False):
        loc = ".".join(str(x) for x in e.get("loc", ())) or "(전체)"
        parts.append(f"{loc}: {e.get('msg')}")
    return "; ".join(parts)[:ERROR_SUMMARY_MAX]


def prefilter_checks(data: dict) -> tuple[dict, list[str]]:
    """규칙 1: checks에서 CHECKLIST 밖 item을 뺀다. (새 dict, 버린 item 이름 목록)."""
    checks = data.get("checks")
    if not isinstance(checks, list):
        return data, []
    kept, dropped = [], []
    for c in checks:
        if isinstance(c, dict) and isinstance(c.get("item"), str) and c["item"] not in CHECKLIST:
            dropped.append(c["item"])
            continue
        kept.append(c)
    return {**data, "checks": kept}, dropped


def parse_ai_output(text: str | None) -> AnalysisAIOutput:
    if text is None or not text.strip():
        raise FormatError("(전체): 응답이 비어 있음")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FormatError(f"(전체): JSON이 아님 ({exc.msg}, {exc.lineno}행 {exc.colno}열)") from None
    if not isinstance(data, dict):
        raise FormatError("(전체): JSON 객체가 아님")
    data, _ = prefilter_checks(data)
    try:
        return AnalysisAIOutput.model_validate(data)
    except ValidationError as exc:
        raise FormatError(_summarize_validation(exc)) from None


def _squash(s: str) -> str:
    return _WS_RE.sub("", s or "")


def evidence_in_memo(evidence: str, memo_text: str) -> bool:
    """공백을 지우고 부분 문자열로 비교. 앞뒤 따옴표는 무시. 빈 근거는 False."""
    ev = _squash(evidence).strip(_QUOTES)
    if not ev:
        return False
    return ev in _squash(memo_text)


def normalize_checks(ai: AnalysisAIOutput, memo_text: str) -> list[CheckItem]:
    # 규칙 2: 근거 확인
    verified: list[CheckItem] = []
    for c in ai.checks:
        if c.item not in CHECKLIST:          # 규칙 1(안전망)
            continue
        status = c.status if evidence_in_memo(c.evidence, memo_text) else "ambiguous"
        verified.append(CheckItem(item=c.item, status=status, evidence=c.evidence))

    # 규칙 3: 같은 item 합치기
    merged: dict[str, dict[str, Any]] = {}
    for c in verified:
        slot = merged.setdefault(c.item, {"statuses": [], "evidence": []})
        slot["statuses"].append(c.status)
        if c.evidence and c.evidence not in slot["evidence"]:
            slot["evidence"].append(c.evidence)

    # 규칙 4: floor·transit 값으로 보충
    for field, item in DERIVED_CHECKS:
        value = getattr(ai, field, None)
        if isinstance(value, str) and value.strip() and item not in merged:
            merged[item] = {"statuses": ["confirmed"], "evidence": [value.strip()]}

    out: list[CheckItem] = []
    for name in CHECKLIST:
        slot = merged.get(name)
        if slot is None:
            continue
        statuses = set(slot["statuses"])
        status = statuses.pop() if len(statuses) == 1 else "ambiguous"
        out.append(CheckItem(item=name, status=status, evidence=" / ".join(slot["evidence"])))
    return out


def postprocess(ai: AnalysisAIOutput, memo_text: str) -> AnalysisResult:
    cleaned = ai.model_copy(update={"checks": normalize_checks(ai, memo_text)})
    return build_result(cleaned)
