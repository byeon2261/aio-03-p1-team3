"""기존 환경 변수에서 서비스 설정을 읽고 자료형·범위를 검사한다."""

from functools import lru_cache

from dotenv import find_dotenv
from pydantic import Field, HttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # BaseSettings는 환경 변수 이름을 필드 이름에 연결하고 자료형을 검증한다.
    model_config = SettingsConfigDict(extra="ignore", hide_input_in_errors=True)

    supabase_url: HttpUrl
    supabase_publishable_key: str = Field(min_length=1, repr=False)
    redis_url: str = Field(min_length=1, repr=False)
    work_session_ttl_seconds: int = Field(default=1800, ge=1, le=86400)
    cache_ttl_seconds: int = Field(default=60, ge=1, le=3600)
    message_page_size: int = Field(default=30, ge=1, le=100)
    http_timeout_seconds: float = Field(default=10, gt=0, le=60)
    redis_timeout_seconds: float = Field(default=2, gt=0, le=30)
    http_max_connections: int = Field(default=50, ge=1, le=500)
    redis_max_connections: int = Field(default=20, ge=1, le=200)
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])


# lru_cache는 설정 객체를 재사용한다. 사용자별 토큰을 이 캐시에 넣지는 않는다.
@lru_cache
def get_settings() -> Settings:
    # 기존 uv 프로젝트의 .env를 찾는다. 요청마다 파일을 다시 읽지 않는다.
    return Settings(_env_file=find_dotenv(usecwd=True) or None)
