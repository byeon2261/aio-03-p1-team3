"""최근 메시지 페이지를 Redis에 캐싱하고 실패 시 DB 조회를 계속하게 한다."""
import logging

from pydantic import ValidationError
from redis import RedisError
from redis.asyncio import Redis

from app.core.errors import ServiceError
from app.schemas import MessagePage

logger = logging.getLogger("course.cache")


class ConversationCache:
    def __init__(self, redis: Redis, user_id: str, ttl: int, page_size: int = 30):
        self.redis, self.user_id, self.ttl, self.page_size = redis, user_id, ttl, page_size

    def key(self, conversation_id: int) -> str:
        # 사용자·대화·페이지 크기를 구분해 다른 조회 결과가 같은 키에 섞이지 않게 한다.
        return f"course:conversation-cache:{self.user_id}:{conversation_id}:{self.page_size}"
    
    async def read(self, conversation_id: int) -> tuple[MessagePage | None, bool]:
        try:
            raw = await self.redis.get(self.key(conversation_id))
            if raw is None:
                return None, False
            # JSON 문자열을 응답 모델로 복원한다. 비어 있는 메시지 목록도 캐시할 수 있다.
            page = MessagePage.model_validate_json(raw)
            return page.model_copy(update={"source": "cache"}), False
        except (RedisError, ValueError, ValidationError):
            logger.warning("cache_read_failed conversation_id=%s", conversation_id)
            return None, True

    async def write(self, conversation_id: int, page: MessagePage) -> bool:
        try:
            raw = page.model_dump_json()
            # ex는 저장과 만료 시간 설정을 SET 한 명령으로 처리한다.
            await self.redis.set(self.key(conversation_id), raw, ex=self.ttl)
            return True
        except RedisError:
            logger.warning("cache_write_failed conversation_id=%s", conversation_id)
            return False

    async def clear(self, conversation_id: int) -> bool:
        try:
            await self.redis.delete(self.key(conversation_id))
            return True
        except RedisError:
            logger.warning("cache_clear_failed conversation_id=%s", conversation_id)
            return False
