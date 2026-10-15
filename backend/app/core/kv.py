"""Redis 호환 임시 저장소 어댑터 (초안·캐시용).

값은 문자열이다. dict는 json.dumps 해서 넣고 json.loads 해서 꺼낸다.
    kv = get_kv()            # Depends(get_kv)로 받아도 된다
    kv.set("draft:...", json.dumps(d), settings.DRAFT_TTL_SEC)
    kv.get("draft:...")       # 없거나 만료면 None

Redis가 꺼져 있으면 메서드가 503 KV_UNAVAILABLE을 던진다. 캐시처럼 없어도 되는 기능은
먼저 `kv_available()`을 보고 건너뛴다. REDIS_URL이 없으면 get_kv()가 503 CONFIG_MISSING.

테스트: `use_kv(MemoryKV())`로 바꾸고 `use_kv(None)`으로 되돌린다(conftest의 memory_kv 픽스처가 해 준다).
"""

from __future__ import annotations

from typing import Any, Protocol

from app.core.config import settings
from app.core.errors import AppError


class KV(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str, ttl_sec: int) -> None: ...
    def delete(self, *keys: str) -> int: ...
    def exists(self, key: str) -> bool: ...
    def ping(self) -> bool: ...


def kv_unavailable() -> AppError:
    return AppError(503, "KV_UNAVAILABLE", "임시 저장소에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.")


class RedisKV:
    def __init__(self, url: str):
        import redis

        self._redis = redis.Redis.from_url(url, decode_responses=True, socket_timeout=2,
                                           socket_connect_timeout=2, health_check_interval=30)

    def _call(self, fn, *args):
        import redis

        try:
            return fn(*args)
        except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError):
            raise kv_unavailable() from None

    def get(self, key: str) -> str | None:
        return self._call(self._redis.get, key)

    def set(self, key: str, value: str, ttl_sec: int) -> None:
        if not isinstance(value, str):
            raise TypeError("KV 값은 문자열이어야 합니다(json.dumps 사용)")
        self._call(lambda: self._redis.set(key, value, ex=max(1, int(ttl_sec))))

    def delete(self, *keys: str) -> int:
        if not keys:
            return 0
        return int(self._call(self._redis.delete, *keys))

    def exists(self, key: str) -> bool:
        return bool(self._call(self._redis.exists, key))

    def ping(self) -> bool:
        try:
            return bool(self._redis.ping())
        except Exception:
            return False


_override: Any = None
_redis_kv: RedisKV | None = None


def use_kv(kv: Any) -> None:
    """테스트용: get_kv()·kv_available()이 이 객체를 쓰게 한다. None이면 원래대로."""
    global _override
    _override = kv


def get_kv() -> KV:
    global _redis_kv
    if _override is not None:
        return _override
    settings.require("REDIS_URL")
    if _redis_kv is None:
        _redis_kv = RedisKV(settings.REDIS_URL)
    return _redis_kv


def kv_available() -> bool:
    try:
        return get_kv().ping()
    except AppError:
        return False
