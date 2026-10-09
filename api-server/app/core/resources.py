"""서버 시작·종료에 맞춰 공유 HTTP·Redis 연결 풀을 준비하고 정리한다."""

from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
from fastapi import FastAPI
from redis.asyncio import Redis

from app.core.settings import Settings, get_settings


# dataclass는 설정·HTTP·Redis를 함께 전달하는 객체의 초기화를 만든다.
@dataclass
class Resources:
    settings: Settings
    http: httpx.AsyncClient
    redis: Redis


# asynccontextmanager는 yield 전의 준비와 뒤의 정리를 하나의 수명으로 묶는다.
@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = app.state.settings_override or get_settings()
    # 연결 풀은 서버 프로세스마다 하나다. 여러 요청이 같은 연결들을 재사용한다.
    async with httpx.AsyncClient(
        timeout=settings.http_timeout_seconds,
        limits=httpx.Limits(
            max_connections=settings.http_max_connections,
            max_keepalive_connections=settings.http_max_connections,
        ),
    ) as http:
        redis = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_timeout=settings.redis_timeout_seconds,
            socket_connect_timeout=settings.redis_timeout_seconds,
            max_connections=settings.redis_max_connections,
        )
        app.state.resources = Resources(settings, http, redis)
        try:
            # yield 전은 서버 준비, 뒤는 종료다. 요청별 정리와 구분한다.
            yield
        finally:
            await redis.aclose()
            app.state.resources = None
    # async with를 나가면서 HTTP 연결 풀도 닫힌다.
