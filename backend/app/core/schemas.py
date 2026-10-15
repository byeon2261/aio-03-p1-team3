"""요청·응답 모델(계약). 필드가 더 필요하면 자기 폴더에서 상속해 쓰고 REPORT에 적는다.

시각(datetime)은 UTC, 금액은 만원 단위 정수, None은 '미기재'.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.analysis_contract import CheckItem
from app.core.registry import ColumnValue

MEMO_MAX_CHARS = 5000
TITLE_MAX_CHARS = 100
NICKNAME_MAX_CHARS = 30
PASSWORD_MIN_CHARS = 6

AnalysisStatus = Literal["none", "success", "failed"]
Rating = Literal["up", "down"]
FeedbackReason = Literal["amount", "not_in_memo", "missing_info", "pros_cons", "check_error", "other"]
FeedbackAction = Literal["set", "revert"]   # 필드 수정 행의 동작(0008). set+null = 메모에 없음


class OkOut(BaseModel):
    ok: bool = True


# ------------------------------------------------------------------ F1 인증 (R)
class SignupIn(BaseModel):
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=PASSWORD_MIN_CHARS, max_length=72)


class LoginIn(SignupIn):
    pass


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=1)


class ProfileOut(BaseModel):
    id: str
    nickname: str
    role: Literal["user", "admin"]


class AuthTokensOut(BaseModel):
    access_token: str
    refresh_token: str
    expires_at: int            # Unix 초(UTC)
    profile: ProfileOut


class SignupOut(BaseModel):
    needs_email_confirm: bool
    access_token: str | None = None
    refresh_token: str | None = None
    expires_at: int | None = None
    profile: ProfileOut | None = None


# ------------------------------------------------------------------ F2·F3 세션·매물·초안 (P1)
class SessionCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=TITLE_MAX_CHARS)
    visit_date: dt.date | None = None


class SessionUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=TITLE_MAX_CHARS)
    visit_date: dt.date | None = None


class SessionOut(BaseModel):
    id: str
    title: str
    visit_date: dt.date | None = None
    created_at: dt.datetime
    listing_count: int = 0


class ListingCreateIn(BaseModel):
    memo_text: str = Field(default="", max_length=MEMO_MAX_CHARS)


class ListingUpdateIn(BaseModel):
    memo_text: str = Field(max_length=MEMO_MAX_CHARS)


class ListingOut(BaseModel):
    id: str
    session_id: str
    listing_no: int
    label: str                 # "N번 집"
    memo_text: str
    memo_updated_at: dt.datetime
    created_at: dt.datetime
    latest_analysis_status: AnalysisStatus = "none"
    needs_reanalysis: bool = False


class DraftIn(BaseModel):
    memo_text: str = Field(max_length=MEMO_MAX_CHARS)


class DraftOut(BaseModel):
    memo_text: str
    saved_at: dt.datetime
    expires_at: dt.datetime


# ------------------------------------------------------------------ F4·F5 분석 (P2)
class AnalysisCreateIn(BaseModel):
    use_cache: bool = True


class FieldValue(BaseModel):
    ai_value: Any = None
    user_value: Any = None
    value: Any = None           # 화면에 보일 값(edited면 user_value, 아니면 ai_value)
    edited: bool = False        # 사용자 수정 적용 중. edited이고 user_value가 None이면 '메모에 없음'으로 고친 것


class AnalysisOut(BaseModel):
    id: str
    listing_id: str
    status: Literal["success", "failed"]
    error_code: str | None = None
    prompt_version: str
    model: str
    thinking_level: str | None = None
    schema_version: str
    created_at: dt.datetime
    fields: dict[str, FieldValue] = Field(default_factory=dict)   # EDITABLE_FIELDS + label
    checks: list[CheckItem] = Field(default_factory=list)
    confirmed_checks: list[str] = Field(default_factory=list)
    unchecked: list[str] = Field(default_factory=list)
    ambiguous_checks: list[str] = Field(default_factory=list)
    missing_checks: list[str] = Field(default_factory=list)
    ambiguous: list[str] = Field(default_factory=list)
    mixed_listings: bool = False
    rating: Rating | None = None
    needs_reanalysis: bool = False
    previous_overrides: dict[str, Any] = Field(default_factory=dict)


# ------------------------------------------------------------------ F6·F7 비교·피드백 (P3)
class FieldTitle(BaseModel):
    key: str
    title: str


class ComparisonRow(BaseModel):
    listing_id: str
    listing_no: int
    label: str
    analysis_status: AnalysisStatus
    needs_reanalysis: bool = False
    values: dict[str, Any] = Field(default_factory=dict)
    columns: dict[str, ColumnValue] = Field(default_factory=dict)


class ComparisonOut(BaseModel):
    session_id: str
    enough_listings: bool
    message: str | None = None
    fields: list[FieldTitle] = Field(default_factory=list)
    providers: list[FieldTitle] = Field(default_factory=list)
    rows: list[ComparisonRow] = Field(default_factory=list)
    lowest: dict[str, list[str]] = Field(default_factory=dict)       # monthly_rent_manwon·maintenance_fee_manwon
    hidden_count: dict[str, int] = Field(default_factory=dict)       # 필터 이름 → 숨긴 행 수


class FeedbackIn(BaseModel):
    field_name: str | None = None          # None이면 전체 평가
    corrected_value: Any = None            # field_name이 있을 때 수정값. action "set"이면 None = 메모에 없음
    action: FeedbackAction | None = None   # field_name이 있을 때만. 생략하면 "set", "revert"는 AI 값으로 되돌림
    rating: Rating | None = None
    reason: FeedbackReason | None = None
    comment: str | None = Field(default=None, max_length=500)


class FeedbackOut(BaseModel):
    id: str
    analysis_id: str
    field_name: str | None = None
    corrected_value: Any = None
    action: FeedbackAction | None = None   # 필드 수정 행만 set/revert, 전체 평가 행은 None
    rating: Rating | None = None
    reason: FeedbackReason | None = None
    comment: str | None = None
    created_at: dt.datetime


# ------------------------------------------------------------------ F10 사진·마이페이지 (P4)
class PhotoOut(BaseModel):
    id: str
    listing_id: str
    content_type: str
    size_bytes: int
    visibility: Literal["private", "public"] = "private"
    created_at: dt.datetime
    url: str | None = None                 # 서명 URL (SIGNED_URL_TTL_SEC 동안 유효)
    url_expires_at: dt.datetime | None = None


class MyPhotoOut(PhotoOut):
    session_id: str
    session_title: str
    listing_no: int


class MeUpdateIn(BaseModel):
    nickname: str = Field(min_length=1, max_length=NICKNAME_MAX_CHARS)


class PasswordChangeIn(BaseModel):
    new_password: str = Field(min_length=PASSWORD_MIN_CHARS, max_length=72)


class MySummaryOut(BaseModel):
    session_count: int = 0
    listing_count: int = 0
    analysis_count: int = 0
    photo_count: int = 0
    feedback_count: int = 0


# ------------------------------------------------------------------ F11 예산 (P5)
class BudgetIn(BaseModel):
    deposit_max_manwon: int | None = Field(default=None, ge=0)
    monthly_max_manwon: int | None = Field(default=None, ge=0)   # 월세 + 관리비 기준


class BudgetOut(BaseModel):
    session_id: str
    deposit_max_manwon: int | None = None
    monthly_max_manwon: int | None = None
    updated_at: dt.datetime | None = None   # 설정한 적 없으면 None


# ------------------------------------------------------------------ F8 운영 로그 (P6)
class RequestLogOut(BaseModel):
    id: int | None = None
    request_id: str
    profile_id: str | None = None
    endpoint: str
    method: str
    status_code: int
    latency_ms: int
    ai_latency_ms: int | None = None
    error_code: str | None = None
    prompt_version: str | None = None
    cache_hit: bool | None = None
    created_at: dt.datetime


class MetricsOut(BaseModel):
    window_minutes: int
    request_count: int = 0
    error_rate: float | None = None
    p50_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    ai_p50_latency_ms: float | None = None
    ai_p95_latency_ms: float | None = None
    cache_hit_rate: float | None = None
    format_error_rate: float | None = None
    extra: dict[str, Any] = Field(default_factory=dict)   # 구간별·엔드포인트별 등 P6가 정함(METRICS.md)


class FeedbackAdminOut(FeedbackOut):
    listing_id: str | None = None
    prompt_version: str | None = None


# ------------------------------------------------------------------ F9 평가 (P7)
class EvalRunCreateIn(BaseModel):
    prompt_version: str = Field(min_length=1, max_length=50)
    case_keys: list[str] | None = None     # None이면 전체 케이스


class EvalRunOut(BaseModel):
    id: str
    prompt_version: str
    model: str
    thinking_level: str | None = None
    schema_version: str
    status: Literal["running", "done", "failed"]
    case_count: int = 0
    field_accuracy: float | None = None
    hallucination_rate: float | None = None
    missing_check_accuracy: float | None = None
    format_error_rate: float | None = None
    error_message: str | None = None
    created_at: dt.datetime
    finished_at: dt.datetime | None = None


class EvalResultOut(BaseModel):
    case_key: str
    tags: list[str] = Field(default_factory=list)
    status: str
    field_matches: dict[str, Any] = Field(default_factory=dict)
    failure_codes: list[str] = Field(default_factory=list)
    output_json: dict[str, Any] | None = None
    compare_status: str | None = None                 # compare_to 실행의 같은 케이스
    compare_field_matches: dict[str, Any] | None = None
    compare_failure_codes: list[str] | None = None


class EvalResultsOut(BaseModel):
    run: EvalRunOut
    compare_run: EvalRunOut | None = None
    results: list[EvalResultOut] = Field(default_factory=list)
