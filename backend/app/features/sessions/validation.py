"""P1 공통 입력 검사. 오류 detail은 R의 VALIDATION_ERROR 모양(fields: loc·type·msg)을 따르고 입력값은 담지 않는다."""

from __future__ import annotations

from app.core.errors import AppError


def blank_field_error(field: str, message: str) -> AppError:
    return AppError(422, "VALIDATION_ERROR", message,
                    {"fields": [{"loc": ["body", field], "type": "blank", "msg": message}]})


def require_text(value: str | None, field: str, message: str) -> str:
    """앞뒤 공백을 뺀 값을 돌려준다. 비었으면 422 VALIDATION_ERROR."""
    text = (value or "").strip()
    if not text:
        raise blank_field_error(field, message)
    return text
