"""AI 응답 검증과 F5 빠진 확인 항목 후처리.

parse_ai_output(text)        JSON 파싱 → 체크리스트 밖 항목 제거 → AnalysisAIOutput 검증. 실패 시 FormatError(요약)
normalize_checks(ai, memo)   F5 규칙으로 checks 정리
postprocess(ai, memo, prompt_version)  정리한 checks로 AnalysisResult(네 목록은 서버 계산)

F5 규칙(모든 버전)
  1. CHECKLIST 밖의 item은 버린다(검증 전에 원본 JSON에서 뺀다. 원본은 raw_output에 남는다).
  2. evidence가 메모에 없으면(공백을 지우고 부분 문자열로 비교) status를 ambiguous로 바꾼다.
  3. 같은 item이 여러 번 나오면 하나로 합친다. status가 서로 다르면 ambiguous.
  4. floor가 있는데 checks에 "층수"가 없으면 confirmed로 더한다(evidence는 floor 값). transit과 "교통"도 같다.

v3 규칙(프롬프트 v3 이상에서만 켠다. v1·v2 결과는 그대로라 예전 평가 기록을 다시 만들 수 있다)
  프롬프트에 이미 있는 규칙을 모델이 지키지 않은 사례(#57: money_03·mixed_01·mixed_02·conflict_01)를
  서버에서 한 번 더 지킨다.
  S1. 정정 값: 금액이 null이고 메모에 정정 표현("다시 들어보니", "정정", "잘못 들었", "아니고" …)이 있으면
      그 뒤 같은 문장의 "월세/보증금/관리비 N"을 값으로 쓴다. 쓴 구절은 ambiguous에서 뺀다.
  S2. 여러 집: mixed_listings면 금액·층수·방향·교통을 null로 둔다(한 매물 칸에 두 집 값을 담지 않는다).
  S3. 직접 근거: 채광·곰팡이 체크는 근거에 그 말(채광·햇빛·밝다·어둡다 … / 곰팡이)이 있을 때만 남긴다.
      방향("남향")이나 "앞이 트여 있음"만으로는 채광을 넣지 않는다.
  S4. 여러 집의 애매한 구절: mixed_listings면 ambiguous 구절에 층수(N층·반지하·옥탑)나 교통(역·정류장·버스·도보)
      표현이 있을 때 그 항목을 ambiguous로 넣는다(빼면 "언급 안 됨"으로 잘못 보인다).
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

# ------------------------------------------------------------------ v3 규칙 (조정 가능)
STRICT_RULES_FROM_VERSION = 3  # 이 번호 이상의 프롬프트 버전(v3, v4 …)에서 S1~S4를 켠다
_VERSION_NUM_RE = re.compile(r"^v([0-9]{1,3})$")

MONEY_KEYWORDS = {"보증금": "deposit_manwon", "월세": "monthly_rent_manwon", "관리비": "maintenance_fee_manwon"}
# S1: 사용자가 앞의 값을 스스로 고쳤다는 표현
CORRECTION_RE = re.compile(r"다시\s*(들어|물어|확인해|보)\s*보?니|정정|잘못\s*(들었|말했|적었|봤)|아니고|아니라")
_MONEY_AFTER_RE = re.compile(r"(보증금|월세|관리비)\s*([0-9]{1,6})")
_SENTENCE_END_RE = re.compile(r"[.!?\n]")
# S2: 여러 집이 섞이면 비우는 값
MIXED_CLEAR_FIELDS = ("deposit_manwon", "monthly_rent_manwon", "maintenance_fee_manwon", "floor", "direction", "transit")
# S3: 근거에 이 말이 직접 있어야 남기는 항목
DIRECT_EVIDENCE_RE = {
    "채광": re.compile(r"채광|햇빛|햇볕|볕|해가|해\s*들|밝|어둡|어두"),
    "곰팡이": re.compile(r"곰팡"),
}
# S4: 여러 집 메모의 애매한 구절에서 찾는 항목 표현
MIXED_PHRASE_RE = {
    "층수": re.compile(r"[0-9]+\s*층|반지하|옥탑"),
    "교통": re.compile(r"[가-힣]역(?![가-힣])|(?<![가-힣])역\s*(까지|에서|앞|근처|가까|도보|[0-9])|정류장|버스|지하철|도보|걸어서"),
}
_NOT_STATION = ("지역", "구역", "영역")


def strict_rules_enabled(prompt_version: str | None) -> bool:
    """v3 이상이면 True. 버전이 없거나 형식이 다르면 False(예전 동작)."""
    m = _VERSION_NUM_RE.match(prompt_version or "")
    return bool(m) and int(m.group(1)) >= STRICT_RULES_FROM_VERSION


def apply_corrections(ai: AnalysisAIOutput, memo_text: str) -> AnalysisAIOutput:
    """S1: null인 금액을 정정 표현 뒤의 값으로 채운다. 이미 값이 있는 금액은 건드리지 않는다."""
    text = memo_text or ""
    updates: dict[str, Any] = {}
    used: list[str] = []
    for m in CORRECTION_RE.finditer(text):
        rest = text[m.end():]
        end = _SENTENCE_END_RE.search(rest)
        clause = rest[: end.start()] if end else rest
        for word, num in _MONEY_AFTER_RE.findall(clause):
            field_name = MONEY_KEYWORDS[word]
            if getattr(ai, field_name) is None and field_name not in updates:
                updates[field_name] = int(num)
                used.append(m.group(0))
    if not updates:
        return ai
    used_sq = [_squash(u) for u in used]
    ambiguous = [p for p in ai.ambiguous if not any(u in _squash(p) for u in used_sq)]
    return ai.model_copy(update={**updates, "ambiguous": ambiguous})


def clear_mixed_values(ai: AnalysisAIOutput) -> AnalysisAIOutput:
    """S2: 여러 집이 섞인 메모면 금액·층수·방향·교통을 비운다."""
    if not ai.mixed_listings:
        return ai
    return ai.model_copy(update={f: None for f in MIXED_CLEAR_FIELDS})


def drop_indirect_checks(checks: list[CheckItem]) -> list[CheckItem]:
    """S3: 채광·곰팡이 체크 중 근거에 그 말이 없는 것을 뺀다."""
    out = []
    for c in checks:
        pattern = DIRECT_EVIDENCE_RE.get(c.item)
        if pattern is not None and not pattern.search(c.evidence or ""):
            continue
        out.append(c)
    return out


def _mentions(item: str, phrase: str) -> bool:
    pattern = MIXED_PHRASE_RE[item]
    for m in pattern.finditer(phrase):
        if item == "교통" and any(w in phrase[max(0, m.start() - 1): m.end() + 1] for w in _NOT_STATION):
            continue
        return True
    return False


def add_mixed_ambiguous_checks(ai: AnalysisAIOutput, checks: list[CheckItem]) -> list[CheckItem]:
    """S4: 여러 집 메모의 애매한 구절에 층수·교통 표현이 있으면 그 항목을 ambiguous로 넣는다."""
    if not ai.mixed_listings:
        return checks
    present = {c.item for c in checks}
    added: dict[str, list[str]] = {}
    for phrase in ai.ambiguous:
        for item in MIXED_PHRASE_RE:
            if item not in present and _mentions(item, phrase):
                added.setdefault(item, []).append(phrase.strip())
    if not added:
        return checks
    merged = list(checks) + [CheckItem(item=i, status="ambiguous", evidence=" / ".join(p)) for i, p in added.items()]
    return [c for name in CHECKLIST for c in merged if c.item == name]


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


def postprocess(ai: AnalysisAIOutput, memo_text: str, prompt_version: str | None = None) -> AnalysisResult:
    """F5 규칙으로 정리한다. prompt_version이 v3 이상이면 S1~S4도 적용한다(순서: S1 → S2 → F5 → S3 → S4)."""
    strict = strict_rules_enabled(prompt_version)
    if strict:
        ai = clear_mixed_values(apply_corrections(ai, memo_text))
    checks = normalize_checks(ai, memo_text)
    if strict:
        checks = add_mixed_ambiguous_checks(ai, drop_indirect_checks(checks))
    cleaned = ai.model_copy(update={"checks": checks})
    return build_result(cleaned)
