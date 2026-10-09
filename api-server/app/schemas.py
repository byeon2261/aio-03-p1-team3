"""API 입력을 검증하고 프로필·대화·메시지·초안 응답의 모양을 정한다."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Path
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

# Annotated는 int에 FastAPI 검증 조건을 붙인다. 경로의 ID는 0보다 커야 한다.
PositiveId = Annotated[int, Path(gt=0)]


class Input(BaseModel):
    # 예상하지 않은 입력은 거절하고, 문자열 양끝의 공백을 제거한다.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProfileInput(Input):
    display_name: str = Field(min_length=1, max_length=40)


class ProfileRecord(BaseModel):
    id: int
    auth_user_id: UUID
    display_name: str


class ConversationInput(Input):
    title: str = Field(min_length=1, max_length=100)


class ConversationRecord(BaseModel):
    id: int
    user_id: int
    title: str
    created_at: datetime


class ConversationPage(BaseModel):
    conversations: list[ConversationRecord]
    next_before_id: int | None


class MessageInput(Input):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=5000)
    # 선택적인 초안 ID는 저장 후 정리할 대상이다. 메시지 본문은 항상 content를 쓴다.
    session_id: UUID | None = None


class MessageUpdate(Input):
    content: str = Field(min_length=1, max_length=5000)


class MessageRecord(BaseModel):
    id: int
    conversation_id: int
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime


class MessagePage(BaseModel):
    messages: list[MessageRecord]
    next_before_id: int | None
    source: Literal["cache", "supabase", "supabase_fallback"]


class MessageWrite(BaseModel):
    message: MessageRecord
    cache_cleared: bool


class Cleanup(BaseModel):
    deleted: bool = True
    cache_cleared: bool
    drafts_cleared: bool | None = None


class DraftInput(Input):
    draft_question: str = Field(min_length=1, max_length=5000)


class DraftRecord(BaseModel):
    session_id: UUID
    conversation_id: int
    draft_question: str
    ttl_seconds: int


class MessageCreated(MessageWrite):
    # session_id가 없으면 None이다. 원본 저장 성공과 초안 정리 결과를 구분한다.
    draft_cleanup: Literal["cleared", "not_found", "unavailable"] | None = None


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class SignupInput(LoginInput):
    @field_validator("password")
    @classmethod
    def password_policy(cls, value: str) -> str:
        groups = ("abcdefghijklmnopqrstuvwxyz", "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "0123456789",
                  "!@#$%^&*()_+-=[]{};'\":\\|<>?,./`~")
        if len(value) < 12 or len(value.encode("utf-8")) > 72 or not all(
            any(character in group for character in value) for group in groups
        ):
            raise ValueError("12자 이상이며 영문 대문자·소문자·숫자·기호를 포함하고 72바이트 이하여야 한다")
        return value


class SignupResponse(BaseModel):
    user_id: UUID
    email_confirmation_required: bool


class Tokens(BaseModel):
    user_id: UUID
    token_type: Literal["bearer"] = "bearer"
    access_token: str
    refresh_token: str
    expires_in: int


class RefreshInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refresh_token: str = Field(min_length=1)
