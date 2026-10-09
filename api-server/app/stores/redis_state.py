"""사용자·대화별 질문 초안을 Redis에 저장하고 TTL·수정·삭제를 처리한다."""

from uuid import UUID, uuid4

from pydantic import BaseModel, ValidationError
from redis import RedisError
from redis.asyncio import Redis

from app.core.errors import ServiceError
from app.schemas import DraftRecord


class StoredDraft(BaseModel):
    # TTL은 Redis가 관리한다. JSON에는 초안을 식별하는 값과 질문만 넣는다.
    session_id: UUID
    conversation_id: int
    draft_question: str


class WorkSessions:
    def __init__(self, redis: Redis, user_id: str, ttl: int):
        # 연결은 공유하되, 현재 요청의 사용자 ID를 키에 포함한다.
        self.redis, self.user_id, self.ttl = redis, user_id, ttl

    def prefix(self, conversation_id: int) -> str:
        return f"course:work-session:{self.user_id}:{conversation_id}:"

    def key(self, conversation_id: int, session_id: UUID) -> str:
        return self.prefix(conversation_id) + str(session_id)

    async def create(self, conversation_id: int, question: str) -> DraftRecord:
        state = StoredDraft(session_id=uuid4(), conversation_id=conversation_id,
                            draft_question=question)
        try:
            # model_dump_json은 UUID도 JSON 문자열로 바꾼다.
            # ex는 초 단위 만료, nx는 같은 키가 없을 때만 새로 저장하는 조건이다.
            created = await self.redis.set(self.key(conversation_id, state.session_id),
                                           state.model_dump_json(), ex=self.ttl, nx=True)
        except RedisError as error:
            raise ServiceError(503, "DRAFT_UNAVAILABLE", "초안을 저장할 수 없다") from error
        if not created:
            raise ServiceError(409, "SESSION_ID_CONFLICT", "작업 세션 생성을 다시 요청한다")
        return DraftRecord(**state.model_dump(), ttl_seconds=self.ttl)

    async def read(self, conversation_id: int, session_id: UUID) -> DraftRecord:
        try:
            key = self.key(conversation_id, session_id)
            raw = await self.redis.get(key)
            # TTL -2는 키 없음, -1은 만료 설정 없음이다. 이 초안은 양수 TTL이 필요하다.
            ttl = await self.redis.ttl(key) if raw is not None else -2
            if raw is None or ttl < 0:
                raise ServiceError(404, "DRAFT_NOT_FOUND", "작업 세션이 없거나 만료됐다")
            state = StoredDraft.model_validate_json(raw)
            if state.session_id != session_id or state.conversation_id != conversation_id:
                raise ValueError("저장된 작업 세션의 식별자 불일치")
            # **는 dict의 각 항목을 이름 있는 인자로 전달한다. TTL도 응답에 붙인다.
            return DraftRecord(**state.model_dump(), ttl_seconds=ttl)
        except (RedisError, ValueError, ValidationError) as error:
            raise ServiceError(503, "DRAFT_UNAVAILABLE", "작업 세션을 읽을 수 없다") from error

    async def update(self, conversation_id: int, session_id: UUID, question: str) -> DraftRecord:
        await self.read(conversation_id, session_id)
        state = StoredDraft(session_id=session_id, conversation_id=conversation_id,
                            draft_question=question)
        try:
            # xx는 기존 키만 수정한다. 앞의 GET 이후 만료돼도 새 초안으로 되살리지 않는다.
            # 저장 성공 시 ex로 TTL을 다시 설정한다. 동시 수정 버전 검사는 하지 않는다.
            changed = await self.redis.set(self.key(conversation_id, session_id),
                                           state.model_dump_json(), ex=self.ttl, xx=True)
        except RedisError as error:
            raise ServiceError(503, "DRAFT_UNAVAILABLE", "초안을 수정할 수 없다") from error
        if not changed:
            raise ServiceError(404, "DRAFT_NOT_FOUND", "작업 세션이 없거나 만료됐다")
        return DraftRecord(**state.model_dump(), ttl_seconds=self.ttl)

    async def clear(self, conversation_id: int, session_id: UUID) -> str:
        try:
            removed = await self.redis.delete(self.key(conversation_id, session_id))
            return "cleared" if removed else "not_found"
        except RedisError:
            # 원본 저장 후에는 정리 실패 상태를 반환해 메시지 저장 성공을 유지한다.
            return "unavailable"

    async def clear_conversation(self, conversation_id: int) -> bool:
        try:
            # SCAN은 키를 나누어 찾는다. async for는 비동기 결과를 하나씩 기다린다.
            # 본인 대화의 접두어만 검색하므로 다른 사용자·대화의 초안은 남는다.
            async for key in self.redis.scan_iter(match=self.prefix(conversation_id) + "*", count=100):
                await self.redis.delete(key)
            return True
        except RedisError:
            return False
