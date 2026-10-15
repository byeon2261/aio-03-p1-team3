"""F7 요청·응답 모델. core.schemas의 FeedbackIn·FeedbackOut을 상속해 넓힌다(REPORT '계약 변경 요청' 참고).

요청 본문(단계 파일 모양)
    {"corrections": [{"field_name": "monthly_rent_manwon", "corrected_value": 40}],
     "rating": "up" | "down", "reason": "amount" | ..., "comment": "..."}
계약(FeedbackIn)의 한 필드 모양 {"field_name", "corrected_value", "action", ...}도 그대로 받는다(corrections 한 개로 본다).

action 규칙(I2, 0008)
    - "set"(생략 시 기본): corrected_value로 고친다. corrected_value 키는 꼭 보낸다.
      null은 '메모에 없음(미기재)'이다. null을 받을 수 있는 필드(금액 3개·transit·floor·direction)만 허용하고,
      목록 필드는 빈 목록 []이 '메모에 없음'이다.
    - "revert": 수정 취소(AI 값으로 되돌림). corrected_value는 보내지 않거나 null이어야 한다.

corrected_value 규칙
    - field_name은 EDITABLE_FIELDS만.
    - 값은 AnalysisResult의 그 필드 타입으로 엄격 검증: 금액은 정수(0 이상) 또는 null, 목록은 문자열 배열,
      글은 문자열 또는 null. 문자열 "45"·실수 45.5·true는 금액으로 받지 않는다.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from pydantic import BaseModel, Field, TypeAdapter, ValidationError, model_validator

from app.core.analysis_contract import EDITABLE_FIELDS, AnalysisResult
from app.core.schemas import FeedbackAction, FeedbackIn, FeedbackOut
from app.core.values import MONEY_FIELDS

LIST_FIELDS = ("maintenance_includes", "pros", "cons")


@lru_cache(maxsize=None)
def _adapter(field_name: str) -> TypeAdapter:
    return TypeAdapter(AnalysisResult.model_fields[field_name].annotation)


def check_correction(field_name: str, value: Any, action: str = "set", *, value_sent: bool = True) -> Any:
    """검증한 값을 돌려준다. 틀리면 ValueError(메시지에 입력값을 넣지 않는다).

    action "revert"면 값은 None이어야 하고 None을 돌려준다. "set"이면 value_sent가 False일 때 거부한다.
    """
    if field_name not in EDITABLE_FIELDS:
        raise ValueError(f"고칠 수 없는 항목입니다. 고칠 수 있는 항목: {', '.join(EDITABLE_FIELDS)}")
    if action == "revert":
        if value is not None:
            raise ValueError("AI 값으로 되돌릴 때는 corrected_value를 보내지 않거나 null로 보내야 합니다.")
        return None
    if not value_sent:
        raise ValueError("corrected_value를 보내야 합니다. 메모에 없음은 null, AI 값으로 되돌리기는 action \"revert\"입니다.")
    if value is None and field_name in LIST_FIELDS:
        raise ValueError(f"{field_name} 항목은 목록이라 null로 고칠 수 없습니다. 메모에 없으면 빈 목록 []을 보내세요.")
    try:
        checked = _adapter(field_name).validate_python(value, strict=True)
    except ValidationError:
        if field_name in MONEY_FIELDS:
            kind = "정수(만원) 또는 null"
        elif field_name in LIST_FIELDS:
            kind = "문자열 배열"
        else:
            kind = "문자열 또는 null"
        raise ValueError(f"{field_name} 값의 형식이 맞지 않습니다. {kind}이어야 합니다.") from None
    if field_name in MONEY_FIELDS and checked is not None and checked < 0:
        raise ValueError(f"{field_name} 값은 0 이상이어야 합니다.")
    return checked


class CorrectionIn(BaseModel):
    field_name: str
    corrected_value: Any = None   # action "set"이면 키를 꼭 보낸다. null이면 메모에 없음
    action: FeedbackAction = "set"

    @model_validator(mode="after")
    def _check(self) -> "CorrectionIn":
        self.corrected_value = check_correction(self.field_name, self.corrected_value, self.action,
                                                value_sent="corrected_value" in self.model_fields_set)
        return self


class FeedbackCreateIn(FeedbackIn):
    corrections: list[CorrectionIn] = Field(default_factory=list, max_length=len(EDITABLE_FIELDS))

    @model_validator(mode="after")
    def _check(self) -> "FeedbackCreateIn":
        if self.field_name is not None:  # 계약의 한 필드 모양
            action = self.action or "set"
            value = check_correction(self.field_name, self.corrected_value, action,
                                     value_sent="corrected_value" in self.model_fields_set)
            self.corrections = [CorrectionIn.model_construct(field_name=self.field_name, corrected_value=value,
                                                             action=action),
                                *self.corrections]
            self.field_name, self.corrected_value, self.action = None, None, None
        elif self.action is not None:
            raise ValueError("action은 field_name과 함께 보낼 때만 씁니다.")
        names = [c.field_name for c in self.corrections]
        if len(names) != len(set(names)):
            raise ValueError("같은 항목을 한 번에 두 번 고칠 수 없습니다.")
        if self.comment is not None and not self.comment.strip():
            self.comment = None
        if not self.corrections and self.rating is None and self.reason is None and self.comment is None:
            raise ValueError("수정값·평가·사유·의견 중 하나는 보내야 합니다.")
        return self

    @property
    def has_summary(self) -> bool:
        return self.rating is not None or self.reason is not None or self.comment is not None


class FeedbackSaveOut(FeedbackOut):
    """대표 행(평가 행이 있으면 그것, 없으면 첫 수정 행) + 이번에 저장한 모든 행."""

    items: list[FeedbackOut] = Field(default_factory=list)
