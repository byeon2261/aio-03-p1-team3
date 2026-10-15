"""분석 화면의 순수 로직(Streamlit 없음). 테스트에서 바로 부를 수 있다."""

from __future__ import annotations

from typing import Any

CHECKLIST = ("채광", "소음", "수압", "곰팡이", "난방", "층수", "옵션", "보안", "교통")

# 미확인·모호함·미기재 항목마다 집주인·중개사에게 물어볼 고정 문장 (AI 호출 없음)
INQUIRY_QUESTIONS: dict[str, str] = {
    "채광": "낮에 햇빛이 얼마나 드나요? 앞 건물에 가리지는 않나요?",
    "소음": "밤이나 주말에 도로·이웃 소음이 심한 편인가요?",
    "수압": "샤워기와 세면대를 함께 틀어도 수압이 괜찮나요?",
    "곰팡이": "벽지·창틀·화장실에 곰팡이나 결로가 생긴 적이 있나요?",
    "난방": "난방은 개별난방인가요? 겨울 난방비는 보통 얼마 나오나요?",
    "층수": "몇 층인가요? 엘리베이터가 있나요?",
    "옵션": "기본으로 있는 옵션(에어컨·세탁기·냉장고 등)은 무엇인가요?",
    "보안": "공동현관 비밀번호나 CCTV가 있나요?",
    "교통": "가장 가까운 역이나 버스 정류장까지 걸어서 몇 분인가요?",
}

STATUS_GROUPS = (
    ("confirmed_checks", "확인됨", True),
    ("unchecked", "미확인", True),
    ("ambiguous_checks", "모호함", True),
    ("missing_checks", "미기재", False),
)

FAILURE_TEXT: dict[str, tuple[str, str]] = {
    "FMT": ("AI 응답 형식이 맞지 않아 정리하지 못했습니다.", "‘다시 시도’를 누르세요. 계속되면 메모를 조금 고쳐 보세요."),
    "AI_FORMAT_ERROR": ("AI 응답 형식이 맞지 않아 정리하지 못했습니다.", "‘다시 시도’를 누르세요. 계속되면 메모를 조금 고쳐 보세요."),
    "AI_TIMEOUT": ("AI 응답이 늦어 분석을 멈췄습니다.", "잠시 후 ‘다시 시도’를 누르세요."),
    "AI_RATE_LIMITED": ("분석 요청이 많아 잠시 막혔습니다.", "1분쯤 뒤에 ‘다시 시도’를 누르세요."),
    "AI_UPSTREAM_ERROR": ("AI 서비스에서 문제가 생겼습니다.", "잠시 후 ‘다시 시도’를 누르세요."),
}

MIXED_LISTINGS_MESSAGE = "이 메모에 집이 둘 이상 섞여 있어요. 집마다 나눠 저장한 뒤 분석하세요"


def evidence_by_item(analysis: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for c in analysis.get("checks") or []:
        item, ev = c.get("item"), c.get("evidence") or ""
        if item and item not in out:
            out[item] = ev
    return out


def status_groups(analysis: dict) -> list[dict[str, Any]]:
    """[{key, title, show_evidence, items: [{item, evidence}]}] — 확인됨·미확인·모호함·미기재 순."""
    ev = evidence_by_item(analysis)
    groups = []
    for key, title, show_evidence in STATUS_GROUPS:
        items = [{"item": name, "evidence": ev.get(name, "") if show_evidence else ""}
                 for name in analysis.get(key) or []]
        groups.append({"key": key, "title": title, "show_evidence": show_evidence, "items": items})
    return groups


def inquiry_questions(analysis: dict) -> list[tuple[str, str]]:
    """미확인·모호함·미기재 항목마다 한 줄. CHECKLIST 순서."""
    targets = set(analysis.get("unchecked") or []) | set(analysis.get("ambiguous_checks") or []) \
        | set(analysis.get("missing_checks") or [])
    return [(name, INQUIRY_QUESTIONS[name]) for name in CHECKLIST if name in targets and name in INQUIRY_QUESTIONS]


def field_value(analysis: dict, name: str) -> Any:
    f = (analysis.get("fields") or {}).get(name) or {}
    return f.get("value")


def field_edited(analysis: dict, name: str) -> bool:
    f = (analysis.get("fields") or {}).get(name) or {}
    return bool(f.get("edited"))


def button_state(listing: dict, analysis: dict | None) -> dict[str, Any]:
    """분석 버튼 표시 여부와 문구.

    - 메모가 비어 있으면 버튼 비활성
    - 분석 없음 → "AI로 정리하기"
    - 최신 분석 실패 → "다시 시도"
    - 메모가 바뀌어 재분석 필요 → "다시 분석" (+ 안내)
    - 최신 성공·메모 그대로 → 버튼 숨김
    """
    memo_empty = not (listing.get("memo_text") or "").strip()
    needs = bool(listing.get("needs_reanalysis")) or bool(analysis and analysis.get("needs_reanalysis"))
    if analysis is None:
        return {"show": True, "label": "AI로 정리하기", "disabled": memo_empty, "needs_reanalysis": False,
                "memo_empty": memo_empty}
    if analysis.get("status") == "failed":
        return {"show": True, "label": "다시 시도", "disabled": memo_empty, "needs_reanalysis": needs,
                "memo_empty": memo_empty}
    if needs:
        return {"show": True, "label": "다시 분석", "disabled": memo_empty, "needs_reanalysis": True,
                "memo_empty": memo_empty}
    return {"show": False, "label": "", "disabled": True, "needs_reanalysis": False, "memo_empty": memo_empty}


def failure_text(error_code: str | None) -> tuple[str, str]:
    return FAILURE_TEXT.get(error_code or "", ("AI 분석에 실패했습니다.", "‘다시 시도’를 누르세요."))


def text_or_missing(v: Any) -> str:
    if v is None or (isinstance(v, str) and not v.strip()):
        return "미기재"
    return str(v)
