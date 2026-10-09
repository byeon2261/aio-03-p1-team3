"""요청 사용자의 Supabase 클라이언트로 chat_lab 테이블의 CRUD를 실행한다."""

from app.core.errors import ServiceError

from app.core.dependencies import UserContext
from app.core.errors import first, query_rows

PROFILE_COLUMNS = "id,auth_user_id,display_name"
CONVERSATION_COLUMNS = "id,user_id,title,created_at"
MESSAGE_COLUMNS = "id,conversation_id,role,content,created_at"


class Database:
    def __init__(self, context: UserContext):
        self.context = context
        self.client = context.client
        # schema는 클라이언트 생성 시 지정한다. 요청 중 별도 HTTP 풀을 만들지 않는다.

    async def profile(self) -> dict:
        return first(await query_rows(self.client.table("users").select(PROFILE_COLUMNS)
                    .eq("auth_user_id", str(self.context.auth_user_id)).limit(1)), "프로필")

    async def create_profile(self, name: str) -> dict:
        return first(await query_rows(self.client.table("users").insert({
            "display_name": name, "auth_user_id": str(self.context.auth_user_id),
        }).select(PROFILE_COLUMNS)), "생성된 프로필")

    async def update_profile(self, name: str) -> dict:
        return first(await query_rows(self.client.table("users").update({"display_name": name})
                    .eq("auth_user_id", str(self.context.auth_user_id)).select(PROFILE_COLUMNS)), "프로필")

    async def conversation(self, conversation_id: int) -> dict:
        # Redis 조회 전에도 RLS를 통과한 현재 대화인지 확인한다.
        return first(await query_rows(self.client.table("conversations").select(CONVERSATION_COLUMNS)
                    .eq("id", conversation_id).limit(1)), "대화")

    async def conversations(self, before_id: int | None, limit: int) -> list[dict]:
        query = self.client.table("conversations").select(CONVERSATION_COLUMNS).order("id", desc=True)
        if before_id is not None:
            query = query.lt("id", before_id)
        return await query_rows(query.limit(limit))

    async def create_conversation(self, title: str) -> dict:
        profile = await self.profile()
        return first(await query_rows(self.client.table("conversations").insert({
            "user_id": profile["id"], "title": title,
        }).select(CONVERSATION_COLUMNS)), "생성된 대화")

    async def update_conversation(self, conversation_id: int, title: str) -> dict:
        return first(await query_rows(self.client.table("conversations").update({"title": title})
                    .eq("id", conversation_id).select(CONVERSATION_COLUMNS)), "대화")

    async def delete_conversation(self, conversation_id: int) -> None:
        first(await query_rows(self.client.table("conversations").delete()
              .eq("id", conversation_id).select("id")), "대화")

    async def messages(self, conversation_id: int, before_id: int | None, limit: int) -> list[dict]:
        query = self.client.table("messages").select(MESSAGE_COLUMNS).eq("conversation_id", conversation_id)
        if before_id is not None:
            query = query.lt("id", before_id)
        # limit+1개를 읽어 다음 페이지가 있는지 판단한다. API는 시간 대신 ID로 이어 읽는다.
        return await query_rows(query.order("id", desc=True).limit(limit + 1))

    async def create_message(self, conversation_id: int, values: dict) -> dict:
        return first(await query_rows(self.client.table("messages").insert({
            "conversation_id" : conversation_id, **values
        }).select(MESSAGE_COLUMNS)), "생성된 메세지")

    async def update_message(self, message_id: int, content: str) -> dict:
        return first(await query_rows(self.client.table("messages").update({"content": content})
                    .eq("id", message_id).select(MESSAGE_COLUMNS)), "메시지")

    async def delete_message(self, message_id: int) -> dict:
        return first(await query_rows(self.client.table("messages").delete()
                    .eq("id", message_id).select(MESSAGE_COLUMNS)), "메시지")
