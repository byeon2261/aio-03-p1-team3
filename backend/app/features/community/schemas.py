"""F14 발품 후기 요청·응답 모델. 공통 core/schemas.py는 건드리지 않고 이 폴더에 둔다.

- 필수: address(지번 주소), topic, title, body / 선택: floor, visit_date (사진은 따로 올린다)
- 응답에는 작성자 id·이메일을 넣지 않는다. 닉네임과 is_mine(내 글 여부)만 준다.
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field, field_validator

TOPICS: tuple[str, ...] = ("구조·설비", "소음", "채광", "주변 환경", "기타")
ADDRESS_MAX = 200
TITLE_MAX = 100
BODY_MAX = 3000
FLOOR_MIN, FLOOR_MAX = -10, 200


def _strip_required(v: str) -> str:
    v = (v or "").strip()
    if not v:
        raise ValueError("빈 값은 저장할 수 없습니다.")
    return v


def _check_topic(v: str) -> str:
    if v not in TOPICS:
        raise ValueError(f"주제는 {', '.join(TOPICS)} 중 하나입니다.")
    return v


def _check_floor(v: int | None) -> int | None:
    if v == 0:
        raise ValueError("0층은 없습니다. 지하는 -1부터 적습니다.")
    return v


class PostIn(BaseModel):
    address: str = Field(min_length=1, max_length=ADDRESS_MAX, examples=["예시시 예시구 예시동 123-45"])
    topic: str = Field(examples=["구조·설비"])
    title: str = Field(min_length=1, max_length=TITLE_MAX, examples=["보일러가 욕실 안쪽에 있어요"])
    body: str = Field(min_length=1, max_length=BODY_MAX, examples=["보일러실이 욕실 안에 있어 점검 때 불편합니다."])
    floor: int | None = Field(default=None, ge=FLOOR_MIN, le=FLOOR_MAX, examples=[3])
    visit_date: dt.date | None = Field(default=None, examples=["2026-10-17"])

    @field_validator("address", "title", "body")
    @classmethod
    def _strip(cls, v: str) -> str:
        return _strip_required(v)

    @field_validator("topic")
    @classmethod
    def _topic(cls, v: str) -> str:
        return _check_topic(v)

    @field_validator("floor")
    @classmethod
    def _floor(cls, v: int | None) -> int | None:
        return _check_floor(v)


class PostUpdateIn(BaseModel):
    """보낸 칸만 바꾼다(model_fields_set). 필수 칸은 null로 비울 수 없고, floor·visit_date는 null로 비운다."""
    address: str | None = Field(default=None, min_length=1, max_length=ADDRESS_MAX)
    topic: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=TITLE_MAX)
    body: str | None = Field(default=None, min_length=1, max_length=BODY_MAX)
    floor: int | None = Field(default=None, ge=FLOOR_MIN, le=FLOOR_MAX)
    visit_date: dt.date | None = None

    @field_validator("address", "title", "body", "topic")
    @classmethod
    def _required_not_null(cls, v: str | None, info):
        if v is None:
            raise ValueError("필수 칸은 비울 수 없습니다.")
        v = _strip_required(v)
        return _check_topic(v) if info.field_name == "topic" else v

    @field_validator("floor")
    @classmethod
    def _floor(cls, v: int | None) -> int | None:
        return _check_floor(v)


class PostPhotoOut(BaseModel):
    id: str
    content_type: str
    size_bytes: int
    url: str | None = None               # 서명 URL(만들지 못하면 null)
    url_expires_at: dt.datetime | None = None


class PostSummaryOut(BaseModel):
    id: str
    address: str
    floor: int | None
    topic: str
    visit_date: dt.date | None
    title: str
    nickname: str
    is_mine: bool
    has_photo: bool
    created_at: dt.datetime
    updated_at: dt.datetime


class PostOut(PostSummaryOut):
    body: str
    photo: PostPhotoOut | None = None


class TopicsOut(BaseModel):
    topics: list[str] = Field(examples=[list(TOPICS)])
