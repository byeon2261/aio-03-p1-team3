"""스트림 이벤트 생성 함수를 직접 불러 순서·중복 제거·빈 구간 채우기를 확인한다(HTTP 스트리밍 없이)."""

from __future__ import annotations

import asyncio

from app.features.admin_logs.stream import log_event_stream
from tests.admin_logs.helpers import add_log, at

TIMEOUT_SEC = 5


async def _collect(db, broker, last_event_id, max_events, publish_rows):
    """구독이 열리면 publish_rows를 발행하고, max_events개를 모은다(끝없이 기다리지 않게 시간 제한).

    publish_rows가 함수면 구독이 열린 뒤 불러서 행을 만든다(저장 → 발행 순서 흉내).
    """
    events = []

    async def consume():
        async for ev in log_event_stream(db, last_event_id, max_events=max_events):
            events.append(ev)

    async def produce():
        while broker.subscriber_count == 0:
            await asyncio.sleep(0.01)
        rows = publish_rows() if callable(publish_rows) else publish_rows
        for row in rows:
            broker.publish(row)

    task = asyncio.create_task(consume())
    if publish_rows:
        await asyncio.wait_for(produce(), TIMEOUT_SEC)
    await asyncio.wait_for(task, TIMEOUT_SEC)
    return events


def test_admin_logs_stream_db_backlog_then_live(memory_db, memory_broker):
    old = [add_log(memory_db, created_at=at(i)) for i in range(4)]
    # 재연결: old[1]까지 받았다 → old[2], old[3] 먼저, 그 다음 구독 중에 저장·발행된 새 로그
    created = []

    def save_then_publish():
        created.append(add_log(memory_db, created_at=at(10)))
        return created

    events = asyncio.run(_collect(memory_db, memory_broker, old[1]["id"], 3, save_then_publish))
    assert [int(e.id) for e in events] == [old[2]["id"], old[3]["id"], created[0]["id"]]
    assert all(e.event == "log" for e in events)
    assert events[0].data["endpoint"] == "/sessions"


def test_admin_logs_stream_skips_duplicates_and_old_ids(memory_db, memory_broker):
    a = add_log(memory_db, created_at=at(0))
    b = add_log(memory_db, created_at=at(1))
    c = add_log(memory_db, created_at=at(2))
    # a까지 받음 → DB에서 b, c. 이어서 브로커가 b(중복), a(이미 받은 것), d(새 것)를 보낸다
    d = add_log(memory_db, created_at=at(3))
    e = {**d, "id": d["id"] + 1}                      # 재전송 뒤에 새로 발행된 로그
    events = asyncio.run(_collect(memory_db, memory_broker, a["id"], 4, [b, a, c, e]))
    # b, c, d는 DB 재전송으로 이미 나갔으므로 브로커의 b·a·c는 건너뛰고 e만 나온다
    assert [int(ev.id) for ev in events] == [b["id"], c["id"], d["id"], e["id"]]


def test_admin_logs_stream_fills_gap_from_db(memory_db, memory_broker):
    """첫 연결(last_event_id 없음): 새 로그 사이 id가 비면 DB에서 채운다."""
    first = add_log(memory_db, created_at=at(0))
    missed = add_log(memory_db, created_at=at(1))     # 발행을 놓친 로그
    latest = add_log(memory_db, created_at=at(2))
    events = asyncio.run(_collect(memory_db, memory_broker, None, 3, [first, latest]))
    assert [int(e.id) for e in events] == [first["id"], missed["id"], latest["id"]]


def test_admin_logs_stream_masks_profile_and_handles_unsaved_row(memory_db, memory_broker, make_user):
    alice = make_user()
    saved = add_log(memory_db, profile_id=alice.profile_id, created_at=at(0))
    unsaved = {**saved, "id": None}                   # DB 저장 실패 시 R이 id 없이 발행
    events = asyncio.run(_collect(memory_db, memory_broker, None, 2, [saved, unsaved]))
    assert events[0].data["profile_id"] == alice.profile_id[:4] + "****"
    assert events[1].id is None


def test_admin_logs_stream_unsubscribes_when_done(memory_db, memory_broker):
    row = add_log(memory_db, created_at=at(0))
    asyncio.run(_collect(memory_db, memory_broker, None, 1, [row]))
    assert memory_broker.subscriber_count == 0
