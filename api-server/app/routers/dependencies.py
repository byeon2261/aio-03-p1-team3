"""현재 사용자와 공유 연결을 받아 데이터·캐시·초안 저장소를 서비스에 연결한다."""

from app.core.errors import ServiceError

from typing import Annotated

from fastapi import Depends

from app.core.dependencies import Authenticated, SharedResources
# from app.services.chat import ChatService
from app.stores.cache import ConversationCache
from app.stores.database import Database
from app.stores.redis_state import WorkSessions



