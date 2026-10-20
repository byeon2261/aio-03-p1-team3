"""비교표·피드백 화면의 표시 도우미(Streamlit 함수를 부르지 않는 순수 함수).

표는 st.markdown 표로 그린다. 색은 Streamlit 마크다운 색 문법(:red[…] 등)을 쓴다.
    미기재  분석은 했지만 메모에 없는 값(None). 0과 다르다.
    —       아직 값이 없음(분석 전·성공한 분석 없음).
"""

from __future__ import annotations

from typing import Any

from core.ui import fmt_manwon

MONEY_KEYS = ("deposit_manwon", "monthly_rent_manwon", "maintenance_fee_manwon", "monthly_cost_manwon")
LIST_KEYS = ("maintenance_includes", "pros", "cons", "followup_checks")
TONE_COLORS = {"bad": "red", "good": "green", "muted": "gray"}
NO_VALUE = "—"
BUDGET_FILTER = "within_budget"
COST_NOTE = "월 고정비 = 월세 + 관리비. 전기·가스·수도 같은 별도 공과금은 포함하지 않습니다."

# 수정·피드백 화면
EDIT_FIELDS: tuple[tuple[str, str], ...] = (
    ("deposit_manwon", "보증금"),
    ("monthly_rent_manwon", "월세"),
    ("maintenance_fee_manwon", "관리비"),
    ("maintenance_includes", "관리비 포함"),
    ("transit", "교통"),
    ("floor", "층수"),
    ("direction", "방향"),
    ("pros", "장점"),
    ("cons", "단점"),
)
EDIT_TITLES = dict(EDIT_FIELDS)
# '메모에 없음(null)'으로 고칠 수 있는 항목. 목록 항목은 빈 목록이 '메모에 없음'이라 빠진다.
NULLABLE_EDIT_KEYS = tuple(k for k, _ in EDIT_FIELDS if k not in LIST_KEYS)
REASONS: tuple[tuple[str, str], ...] = (
    ("amount", "금액 오류"),
    ("not_in_memo", "없는 내용"),
    ("missing_info", "정보 누락"),
    ("pros_cons", "장단점 오류"),
    ("check_error", "확인 항목 오류"),
    ("other", "기타"),
)
REASON_LABELS = dict(REASONS)

_MD_SPECIAL = "\\`*_{}[]<>()#+-.!|$~:"


def md(text: Any) -> str:
    """마크다운·LaTeX 특수문자를 이스케이프하고 줄바꿈을 없앤다(표 칸이 깨지지 않게)."""
    s = " ".join(str(text).split())
    return "".join("\\" + ch if ch in _MD_SPECIAL else ch for ch in s)


def color(text: str, name: str | None) -> str:
    """이미 이스케이프한 text에 색을 입힌다."""
    return f":{name}[{text}]" if name else text


def plain_value(key: str, value: Any) -> str:
    """값 하나를 사람이 읽는 글로(이스케이프 전)."""
    if key in MONEY_KEYS:
        return fmt_manwon(value)
    if key in LIST_KEYS:
        items = [str(x) for x in (value or []) if str(x).strip()]
        if key == "followup_checks":
            return ", ".join(items) if items else "없음"
        return ", ".join(items) if items else "미기재"
    if value is None or (isinstance(value, str) and not value.strip()):
        return "미기재"
    return str(value)


def value_cell(key: str, value: Any, *, has_values: bool, lowest: bool = False) -> str:
    if not has_values:
        return color(NO_VALUE, "gray")
    text = md(plain_value(key, value))
    if lowest:
        return f":blue[**{text}** 최저]"
    if value is None or (key in LIST_KEYS and key != "followup_checks" and not value):
        return color(text, "gray")
    return text


def column_cell(cv: dict | None) -> str:
    if not cv:
        return color(NO_VALUE, "gray")
    return color(md(cv.get("display", "")), TONE_COLORS.get(cv.get("tone") or "default"))


def status_cell(row: dict) -> str:
    status = row.get("analysis_status")
    has_values = bool(row.get("values"))
    if status == "none":
        parts = [color("분석 전", "gray")]
    elif status == "failed":
        parts = [color("분석 실패", "red") + (" · 이전 결과" if has_values else "")]
    else:
        parts = ["분석 완료"]
    if row.get("needs_reanalysis"):
        parts.append(color("재분석 필요", "orange"))
    return " · ".join(parts)


def needs_action(row: dict) -> bool:
    return row.get("analysis_status") != "success" or bool(row.get("needs_reanalysis"))


def comparison_markdown(data: dict) -> str:
    """ComparisonOut(dict) → 마크다운 표. 행 = 매물, 열 = 매물·상태·항목·추가 열."""
    fields = data.get("fields") or []
    providers = data.get("providers") or []
    lowest = {k: set(v) for k, v in (data.get("lowest") or {}).items()}
    headers = ["매물", "상태"] + [md(f["title"]) for f in fields] + [md(p["title"]) for p in providers]
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for row in data.get("rows") or []:
        values = row.get("values") or {}
        has_values = bool(values)
        cells = [f"**{md(row.get('label', ''))}**", status_cell(row)]
        for f in fields:
            key = f["key"]
            cells.append(value_cell(key, values.get(key), has_values=has_values,
                                    lowest=row.get("listing_id") in lowest.get(key, set())))
        columns = row.get("columns") or {}
        cells += [column_cell(columns.get(p["key"])) for p in providers]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def hidden_message(data: dict) -> str | None:
    n = int((data.get("hidden_count") or {}).get(BUDGET_FILTER) or 0)
    return f"{n}건 숨김 · 사유는 아래 '예산' 섹션에서 확인" if n > 0 else None


# ------------------------------------------------------------------ 수정·피드백
def kind_of(key: str) -> str:
    if key in MONEY_KEYS:
        return "money"
    if key in LIST_KEYS:
        return "list"
    return "text"


def parse_list(text: str) -> list[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def correction_for(key: str, raw: Any, current: Any) -> tuple[bool, Any]:
    """입력값 raw를 현재 값과 비교해 (보낼지, 보낼 값)을 정한다.
    금액·글 칸을 비우면 바꾸지 않는다('메모에 없음'과 'AI 값으로 되돌리기'는 따로 체크로 한다). 목록은 빈 목록도 값이다."""
    kind = kind_of(key)
    if kind == "money":
        if raw is None:
            return False, None
        value = int(raw)
        return value != current, value
    if kind == "list":
        value = parse_list(raw)
        return value != list(current or []), value
    value = (raw or "").strip()
    if not value:
        return False, None
    return value != current, value


def correction_entry(key: str, raw: Any, fv: dict | None, *, revert: bool = False,
                     memo_none: bool = False) -> dict | None:
    """한 항목의 입력 → POST /analyses/{id}/feedback의 corrections 항목(보낼 것이 없으면 None).

    revert     AI 값으로 되돌리기 → {"action": "revert"}
    memo_none  메모에 없음으로 표시 → {"action": "set", "corrected_value": None}. 지금 값이 이미 없으면 보내지 않는다.
    그 밖      입력값이 지금 값과 다를 때만 {"action": "set", "corrected_value": 값}.
    두 체크를 함께 고르는 경우는 화면에서 먼저 막는다.
    """
    fv = fv or {}
    if revert:
        return {"field_name": key, "action": "revert"}
    if memo_none:
        if key not in NULLABLE_EDIT_KEYS or fv.get("value") is None:
            return None
        return {"field_name": key, "action": "set", "corrected_value": None}
    send, value = correction_for(key, raw, fv.get("value"))
    return {"field_name": key, "action": "set", "corrected_value": value} if send else None


def pending_previous(previous: dict | None, fields: dict | None) -> dict:
    """이전 분석의 수정값 중 아직 이번 분석에 적용되지 않은 것.

    값이 None인 수정('메모에 없음')도 있으므로 값만 비교하지 않고 이번 분석에서 고친 상태(edited)인지도 본다.
    """
    fields = fields or {}
    out = {}
    for k, v in (previous or {}).items():
        if k not in EDIT_TITLES:
            continue
        fv = fields.get(k) or {}
        if not fv.get("edited") or fv.get("user_value") != v:
            out[k] = v
    return out
