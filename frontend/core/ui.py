"""화면 공통 표시 도우미.

icon_title  섹션 제목: 연한 색 원(32px) 안의 Material 아이콘 + 글자. 모든 화면이 같이 쓴다
icon_badge  같은 원만(HTML 문자열). 요약 카드 라벨 등
empty_state 빈 화면: 아이콘 + 한 줄 설명 + 다음 행동 버튼 1개
notify      저장·삭제·AI 정리 완료 같은 결과를 오른쪽 아래 토스트로
show_api_error  오류: "무엇이 잘못됐는지" + "다음에 할 일" 두 줄, 차분한 색(theme.css)
"""

from __future__ import annotations

import datetime as dt
import html
from zoneinfo import ZoneInfo

import streamlit as st

KST = ZoneInfo("Asia/Seoul")

# 오류 코드 → (사용자 문구, 다음에 할 일 한 줄)
ERROR_MESSAGES: dict[str, tuple[str, str]] = {
    "AUTH_REQUIRED": ("로그인이 끝났습니다.", "다시 로그인해 주세요."),
    "INVALID_CREDENTIALS": ("이메일 또는 비밀번호가 맞지 않습니다.", "입력을 확인하고 다시 시도하세요."),
    "EMAIL_NOT_CONFIRMED": ("아직 메일 확인을 하지 않았습니다.", "메일 확인 후 로그인하세요."),
    "FORBIDDEN": ("이 화면을 볼 권한이 없습니다.", "다른 메뉴를 이용하세요."),
    "SESSION_NOT_FOUND": ("세션을 찾을 수 없습니다.", "세션 목록에서 다시 고르세요."),
    "LISTING_NOT_FOUND": ("매물을 찾을 수 없습니다.", "세션 화면에서 다시 고르세요."),
    "ANALYSIS_NOT_FOUND": ("분석 결과가 없습니다.", "분석을 먼저 실행하세요."),
    "PHOTO_NOT_FOUND": ("사진을 찾을 수 없습니다.", "목록을 새로 고치세요."),
    "DRAFT_NOT_FOUND": ("저장된 임시 메모가 없습니다.", "새로 작성하세요."),
    "DRAFT_EXPIRED": ("임시 메모 보관 기간이 지났습니다.", "새로 작성하세요."),
    "VALIDATION_ERROR": ("입력값을 확인해 주세요.", "표시된 칸을 고친 뒤 다시 시도하세요."),
    "AI_RATE_LIMITED": ("분석 요청이 많습니다.", "잠시 후 다시 시도하세요."),
    "AI_FORMAT_ERROR": ("AI 응답을 정리하지 못했습니다.", "다시 시도하세요. 계속되면 메모를 조금 고쳐 보세요."),
    "AI_TIMEOUT": ("AI 응답이 늦습니다.", "잠시 후 다시 시도하세요."),
    "AI_UPSTREAM_ERROR": ("AI 서비스에서 문제가 생겼습니다.", "잠시 후 다시 시도하세요."),
    "STORAGE_UNAVAILABLE": ("사진 저장소에 연결할 수 없습니다.", "잠시 후 다시 올려 주세요."),
    "EVAL_CASES_EMPTY": ("기준 세트가 비어 있습니다.", "scripts/load_eval_cases.py로 사례를 먼저 넣으세요."),
    "EVAL_RUN_IN_PROGRESS": ("이미 진행 중인 평가 실행이 있습니다.", "끝난 뒤 다시 실행하세요."),
    "EVAL_RUN_NOT_FOUND": ("평가 실행을 찾을 수 없습니다.", "실행 목록에서 다시 고르세요."),
    "CONFIG_MISSING": ("서버 설정이 끝나지 않았습니다.", "관리자에게 알려 주세요."),
    "KV_UNAVAILABLE": ("임시 저장소에 연결할 수 없습니다.", "잠시 후 다시 시도하세요. 저장은 본 메모 저장을 이용하세요."),
    "CLEANUP_FAILED": ("파일 정리 중 문제가 생겨 삭제하지 못했습니다.", "다시 삭제를 눌러 주세요."),
    "INTERNAL_ERROR": ("서버에서 문제가 생겼습니다.", "잠시 후 다시 시도하세요."),
    "NETWORK_ERROR": ("서버에 연결할 수 없습니다.", "인터넷 연결을 확인하고 다시 시도하세요."),
    "TIMEOUT": ("서버 응답이 늦습니다.", "잠시 후 다시 시도하세요."),
}


# 아이콘 원 색(바탕, 아이콘). 기본 blue. 의미 있는 곳만 green(예산 안·장점)·orange(확인 필요·단점)
TONES: dict[str, tuple[str, str]] = {
    "blue": ("#EAEEFC", "#3246D3"),
    "green": ("#E7F6EC", "#15803D"),
    "orange": ("#FFF1E0", "#C2410C"),
    "red": ("#FDECEC", "#C93C40"),
    "gray": ("#EEF0F4", "#55596A"),
}
_ICON_FONT = "font-family:'Material Symbols Rounded';font-weight:normal;font-style:normal;line-height:1;" \
             "letter-spacing:normal;text-transform:none;white-space:nowrap;-webkit-font-feature-settings:'liga';" \
             "font-feature-settings:'liga'"


def icon_badge(icon: str, tone: str = "blue", size: int = 32) -> str:
    """연한 색 원 안의 Material 아이콘(HTML). icon은 Material Symbols 이름(예: "home")."""
    bg, fg = TONES.get(tone, TONES["blue"])
    name = html.escape(icon.replace(":material/", "").strip(":"))
    return (f'<span aria-hidden="true" style="flex:none;width:{size}px;height:{size}px;border-radius:50%;'
            f'background:{bg};color:{fg};display:inline-flex;align-items:center;justify-content:center">'
            f'<span style="{_ICON_FONT};font-size:{round(size * 0.56)}px">{name}</span></span>')


def icon_title(icon: str, text: str, tone: str = "blue", *, help: str | None = None) -> None:
    """섹션 제목. 원과 글자 사이 8px. help가 있으면 제목 아래 작은 회색 한 줄."""
    st.markdown(
        f'<div class="ht-icon-title" style="display:flex;align-items:center;gap:8px;margin:.5rem 0 .25rem">'
        f'{icon_badge(icon, tone)}<span style="font-size:1.3rem;font-weight:800;color:#110D3C;'
        f'letter-spacing:-.01em">{html.escape(text)}</span></div>',
        unsafe_allow_html=True,
    )
    if help:
        st.caption(help)


def empty_state(icon: str, text: str, *, button: str | None = None, key: str | None = None,
                link: str | None = None, tone: str = "blue") -> bool:
    """빈 화면 카드: 아이콘 + 한 줄 설명 + 다음 행동 1개(버튼, 또는 같은 화면 안 위치로 가는 링크).

    버튼을 누르면 True를 돌려준다(무엇을 할지는 부르는 쪽이 정한다).
    """
    with st.container(border=True, key=f"ht_empty_{key or abs(hash(text))}"):
        st.markdown(
            f'<div style="display:flex;flex-direction:column;align-items:center;gap:.6rem;padding:.75rem 0;'
            f'text-align:center">{icon_badge(icon, tone, 44)}<div style="color:#3d4152">{html.escape(text)}</div>'
            + (f'<a href="{html.escape(link, quote=True)}" target="_self" style="margin-top:.25rem;font-weight:700;'
               f'color:#3246D3;text-decoration:none">{html.escape(button or "")} →</a>' if link else "")
            + '</div>',
            unsafe_allow_html=True,
        )
        if button and not link:
            _, mid, _ = st.columns([1, 1, 1])
            return mid.button(button, key=key, type="primary", width="stretch")
    return False


def notify(message: str, icon: str = ":material/check_circle:") -> None:
    """결과를 화면 오른쪽 아래 짧은 토스트로(기존 안내 문구는 그대로 두고 더한다)."""
    st.toast(message, icon=icon)


def fmt_manwon(v: int | float | None) -> str:
    """None → '미기재', 500 → '500만원'. 0은 '0만원'(미기재와 다르다)."""
    if v is None:
        return "미기재"
    return f"{int(v):,}만원"


def to_kst(value: str | dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(KST)


def fmt_kst(value: str | dt.datetime | None, pattern: str = "%Y-%m-%d %H:%M") -> str:
    """UTC 시각을 서울 시각 문자열로. None이면 '-'."""
    t = to_kst(value)
    return t.strftime(pattern) if t else "-"


def show_api_error(e: Exception) -> None:
    """ApiError를 코드별 문구 + 다음에 할 일 한 줄로 보여 준다."""
    code = getattr(e, "code", "INTERNAL_ERROR")
    message, next_step = ERROR_MESSAGES.get(code, (getattr(e, "message", None) or "요청을 처리하지 못했습니다.",
                                                   "잠시 후 다시 시도하세요."))
    # 한 줄: 무엇이 잘못됐는지 / 다음 줄: 다음에 할 일. 색은 theme.css가 차분하게 바꾼다
    if code in ("NETWORK_ERROR", "TIMEOUT"):
        st.warning(f"{message}  \n{next_step}", icon=":material/wifi_off:")
    elif code == "VALIDATION_ERROR" and getattr(e, "message", None):
        st.error(f"{e.message}  \n{next_step}", icon=":material/error:")
    else:
        st.error(f"{message}  \n{next_step}", icon=":material/error:")
    rid = (getattr(e, "detail", None) or {}).get("request_id")
    if rid:
        st.caption(f"문의 시 요청 번호: {rid}")


PRIVACY_TEXT = ("실제 주소·연락처·실명을 적지 마세요. 메모는 AI(Gemini 무료 등급)로 정리되며, "
                "입력 내용이 Google 제품 개선에 쓰일 수 있습니다.")


def privacy_notice() -> None:
    """모든 화면 맨 위의 개인정보 안내. 작은 회색 한 줄(자물쇠 아이콘 + 문구)."""
    st.caption(f":material/lock: {PRIVACY_TEXT}")
