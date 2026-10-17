"""제목·본문의 연락처(전화번호·이메일) 모양 검사. 걸리면 등록·수정을 거절한다."""

from __future__ import annotations

import re

# 010-1234-5678, 010 1234 5678, 01012345678, 02-123-4567, 031.123.4567, +82 10-1234-5678
_PHONE = re.compile(r"(?<!\d)(?:\+?82[\s.-]?)?0?1[016789][\s.-]?\d{3,4}[\s.-]?\d{4}(?!\d)"
                    r"|(?<!\d)0\d{1,2}[\s.-]?\d{3,4}[\s.-]?\d{4}(?!\d)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def contact_reason(text: str) -> str | None:
    """'phone'·'email' 중 걸린 것, 없으면 None."""
    if _EMAIL.search(text or ""):
        return "email"
    if _PHONE.search(text or ""):
        return "phone"
    return None
