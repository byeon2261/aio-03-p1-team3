"""실시간 로그 브로커 (Redis Pub/Sub 채널 `logs`).

    publish_log(row)               # 동기. 실패해도 예외를 던지지 않는다
    async for row in subscribe_logs():   # dict(request_logs 행 모양)
        ...

테스트: `use_broker(MemoryBroker())` (conftest의 memory_broker 픽스처).
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Protocol

from app.core.config import settings

CHANNEL = "logs"
logger = logging.getLogger("app.broker")


class Broker(Protocol):
    def publish(self, row: dict) -> None: ...
    def subscribe(self) -> AsyncIterator[dict]: ...


class RedisBroker:
    def __init__(self, url: str):
        import redis

        self._url = url
        self._redis = redis.Redis.from_url(url, decode_responses=True, socket_timeout=2, socket_connect_timeout=2)

    def publish(self, row: dict) -> None:
        self._redis.publish(CHANNEL, json.dumps(row, ensure_ascii=False, default=str))

    async def subscribe(self) -> AsyncIterator[dict]:
        import redis.asyncio as aioredis

        client = aioredis.Redis.from_url(self._url, decode_responses=True)
        pubsub = client.pubsub()
        await pubsub.subscribe(CHANNEL)
        try:
            async for msg in pubsub.listen():
                if msg.get("type") != "message":
                    continue
                try:
                    yield json.loads(msg["data"])
                except (TypeError, ValueError):
                    continue
        finally:
            try:
                await pubsub.unsubscribe(CHANNEL)
                await pubsub.aclose()
                await client.aclose()
            except Exception:
                pass


_override: Any = None
_redis_broker: RedisBroker | None = None


def use_broker(broker: Any) -> None:
    """테스트용: publish_log·subscribe_logs가 이 객체를 쓰게 한다. None이면 원래대로."""
    global _override
    _override = broker


def get_broker() -> Broker | None:
    global _redis_broker
    if _override is not None:
        return _override
    if not settings.REDIS_URL:
        return None
    if _redis_broker is None:
        _redis_broker = RedisBroker(settings.REDIS_URL)
    return _redis_broker


def publish_log(row: dict) -> None:
    try:
        b = get_broker()
        if b is not None:
            b.publish(row)
    except Exception as exc:  # 발행 실패는 응답·저장을 막지 않는다
        logger.warning("publish_log failed: %s", type(exc).__name__)


async def subscribe_logs() -> AsyncIterator[dict]:
    """REDIS_URL이 없으면 503 KV_UNAVAILABLE. 연결이 끊기면 iterator가 예외로 끝난다."""
    b = get_broker()
    if b is None:
        from app.core.errors import AppError

        raise AppError(503, "KV_UNAVAILABLE", "실시간 로그를 받을 수 없습니다(임시 저장소 없음).")
    async for row in b.subscribe():
        yield row
