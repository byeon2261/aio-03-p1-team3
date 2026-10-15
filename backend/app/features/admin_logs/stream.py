"""실시간 로그 이벤트 생성 (GET /admin/logs/stream 본체).

순서
    1) last_event_id가 있으면 그 뒤의 DB 로그를 id 오름차순으로 먼저 보낸다(재연결 때 놓친 로그).
    2) subscribe_logs()로 새 로그를 보낸다.
       - 이미 보낸 id는 건너뛴다(재전송·중복 발행).
       - 새 로그 id가 마지막으로 보낸 id+1보다 크면 그 사이를 DB에서 찾아 먼저 보낸다
         (1)과 구독 시작 사이에 저장된 로그, 동시 요청의 발행 순서 뒤바뀜을 메운다).
테스트는 HTTP 대신 이 함수를 직접 부르고 max_events로 개수를 제한한다.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any, AsyncIterator, Callable

from fastapi.sse import ServerSentEvent
from starlette.concurrency import run_in_threadpool

from app.core.broker import subscribe_logs
from app.features.admin_logs.common import log_payload
from app.features.admin_logs.queries import MAX_LIMIT, logs_after

logger = logging.getLogger("app.admin_logs.stream")
EVENT_NAME = "log"
SEEN_KEEP = 2000   # 중복 확인용으로 기억하는 최근 id 수


class _Seen:
    """최근에 보낸 id 기억(메모리 상한)."""

    def __init__(self, keep: int = SEEN_KEEP) -> None:
        self._order: deque[int] = deque()
        self._set: set[int] = set()
        self._keep = keep
        self.last: int | None = None

    def __contains__(self, rid: int) -> bool:
        return rid in self._set

    def add(self, rid: int) -> None:
        self._order.append(rid)
        self._set.add(rid)
        if len(self._order) > self._keep:
            self._set.discard(self._order.popleft())
        self.last = rid if self.last is None else max(self.last, rid)


def to_event(row: dict) -> ServerSentEvent:
    rid = row.get("id")
    return ServerSentEvent(data=log_payload(row), id=str(rid) if rid is not None else None, event=EVENT_NAME)


async def log_event_stream(db: Any, last_event_id: int | None, *, max_events: int | None = None,
                           backlog_limit: int = MAX_LIMIT,
                           subscribe: Callable[[], AsyncIterator[dict]] = subscribe_logs,
                           ) -> AsyncIterator[ServerSentEvent]:
    seen = _Seen()
    if last_event_id is not None:
        seen.last = last_event_id
    sent = 0

    def done() -> bool:
        return max_events is not None and sent >= max_events

    # 1) 재연결 때 놓친 로그
    if last_event_id is not None:
        for row in await run_in_threadpool(logs_after, db, last_event_id, limit=backlog_limit):
            rid = row.get("id")
            if rid is None or rid in seen:
                continue
            seen.add(rid)
            yield to_event(row)
            sent += 1
            if done():
                return

    # 2) 새 로그
    async for row in subscribe():
        rid = row.get("id")
        if rid is not None:
            if rid in seen or (last_event_id is not None and rid <= last_event_id):
                continue
            if seen.last is not None and rid > seen.last + 1:
                try:
                    gap = await run_in_threadpool(logs_after, db, seen.last, before_id=rid, limit=backlog_limit)
                except Exception as exc:  # 빈 구간 채우기 실패는 스트림을 끊지 않는다(화면이 after_id로 다시 채운다)
                    logger.warning("gap fill failed: %s", type(exc).__name__)
                    gap = []
                for g in gap:
                    gid = g.get("id")
                    if gid is None or gid in seen:
                        continue
                    seen.add(gid)
                    yield to_event(g)
                    sent += 1
                    if done():
                        return
            seen.add(rid)
        yield to_event(row)
        sent += 1
        if done():
            return
