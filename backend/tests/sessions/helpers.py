"""P1 테스트 도우미 (tests/sessions·listings·drafts가 함께 쓴다)."""

from __future__ import annotations

from app.core import events
from app.core.analysis_contract import SCHEMA_VERSION, memo_hash


def p1_client(client_as, user):
    """client_as(user)로 만든 뒤 삭제 이벤트 처리기를 비운다.

    합친 뒤에는 다른 기능(P4 사진 등)의 hooks.py가 create_app 때 처리기를 등록한다.
    P1 테스트는 P1 동작만 보도록 처리기를 지우고, 필요한 테스트가 직접 등록한다.
    """
    client = client_as(user)
    events.reset_events()
    return client


def create_session(client, title: str = "토요일 집 보기", visit_date: str | None = "2026-10-17") -> dict:
    r = client.post("/sessions", json={"title": title, "visit_date": visit_date})
    assert r.status_code == 200, r.text
    return r.json()


def create_listing(client, session_id: str, memo: str = "보증금 500 월세 40 관리비 7 채광 좋음",
                   name: str | None = None) -> dict:
    """name을 주지 않으면 지금까지처럼 "N번 집"(이 세션의 다음 번호)으로 저장한다."""
    if name is None:
        name = f"{len(client.get(f'/sessions/{session_id}/listings').json()) + 1}번 집"
    r = client.post(f"/sessions/{session_id}/listings", json={"name": name, "memo_text": memo})
    assert r.status_code == 200, r.text
    return r.json()


def insert_analysis(memory_db, listing_id: str, memo_text: str, status: str = "success") -> dict:
    """분석 행을 직접 넣는다(P2 없이). memo_hash는 그때의 메모로 계산한다."""
    return memory_db.insert("analyses", {
        "listing_id": listing_id,
        "result_json": None,
        "schema_version": SCHEMA_VERSION,
        "prompt_version": "v1",
        "model": "test-model",
        "memo_hash": memo_hash(memo_text),
        "status": status,
        "error_code": None if status == "success" else "AI_FORMAT_ERROR",
    })[0]


def insert_feedback(memory_db, analysis_id: str, profile_id: str) -> dict:
    return memory_db.insert("feedback", {"analysis_id": analysis_id, "profile_id": profile_id,
                                         "field_name": None, "rating": "up"})[0]


def error_code(response) -> str | None:
    return (response.json().get("error") or {}).get("code")
