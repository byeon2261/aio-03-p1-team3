"""설정. 환경변수 또는 backend/.env에서 읽는다.

필수 값이 없어도 앱은 뜬다. 그 값을 쓰는 기능만 503 CONFIG_MISSING을 낸다
(`settings.require("GEMINI_API_KEY")`).
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 외부 서비스 (없으면 해당 기능 503 CONFIG_MISSING)
    SUPABASE_URL: str | None = None
    SUPABASE_PUBLISHABLE_KEY: str | None = None
    SUPABASE_SECRET_KEY: str | None = None
    REDIS_URL: str | None = None
    GEMINI_API_KEY: str | None = None

    # AI
    GEMINI_MODEL: str = "gemini-3.5-flash-lite"
    GEMINI_THINKING_LEVEL: str = "minimal"
    GEMINI_TIMEOUT_SEC: int = 30
    GEMINI_MIN_INTERVAL_SEC: int = 4
    ACTIVE_PROMPT_VERSION: str = "v2"

    # 파일·임시 저장
    SIGNED_URL_TTL_SEC: int = 600
    MAX_PHOTO_MB: int = 10
    DRAFT_TTL_SEC: int = 86400
    CACHE_TTL_SEC: int = 604800

    def require(self, *names: str) -> None:
        """이름 중 하나라도 비어 있으면 503 CONFIG_MISSING. detail에는 값이 아니라 이름만 담는다."""
        missing = [n for n in names if not getattr(self, n, None)]
        if missing:
            from app.core.errors import AppError

            raise AppError(
                503,
                "CONFIG_MISSING",
                "서버 설정이 끝나지 않았습니다. 관리자에게 알려 주세요.",
                {"missing": missing},
            )


settings = Settings()
