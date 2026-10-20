"""F3 매물 메모·번호 API."""

from __future__ import annotations

import datetime as dt
import uuid

from app.core import events
from app.core.errors import AppError
from app.core.schemas import MEMO_MAX_CHARS
from app.features.drafts.store import listing_draft_key, meta_key
from tests.sessions.helpers import (
    create_listing,
    create_session,
    error_code,
    insert_analysis,
    insert_feedback,
    p1_client,
)


def _t(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


# ------------------------------------------------------------------ 인증·소유
def test_listings_requires_token(client_as):
    c = p1_client(client_as, None)
    sid, lid = str(uuid.uuid4()), str(uuid.uuid4())
    assert c.get(f"/sessions/{sid}/listings").status_code == 401
    assert c.post(f"/sessions/{sid}/listings", json={"memo_text": "메모"}).status_code == 401
    r = c.get(f"/listings/{lid}")
    assert r.status_code == 401 and error_code(r) == "AUTH_REQUIRED"
    assert c.patch(f"/listings/{lid}", json={"memo_text": "메모"}).status_code == 401
    assert c.delete(f"/listings/{lid}").status_code == 401


def test_listings_other_users_resources_are_404(client_as, make_user, memory_db):
    alice, bob = make_user(), make_user()
    cb = p1_client(client_as, bob)
    bs = create_session(cb, "밥의 세션")
    bl = create_listing(cb, bs["id"], "밥의 메모")

    ca = p1_client(client_as, alice)
    r = ca.get(f"/sessions/{bs['id']}/listings")
    assert r.status_code == 404 and error_code(r) == "SESSION_NOT_FOUND"
    r = ca.post(f"/sessions/{bs['id']}/listings", json={"memo_text": "끼어들기"})
    assert r.status_code == 404 and error_code(r) == "SESSION_NOT_FOUND"
    for r in (ca.get(f"/listings/{bl['id']}"),
              ca.patch(f"/listings/{bl['id']}", json={"memo_text": "바꿈"}),
              ca.delete(f"/listings/{bl['id']}")):
        assert r.status_code == 404 and error_code(r) == "LISTING_NOT_FOUND"
    rows = memory_db.select("listings", {"session_id": bs["id"]})
    assert len(rows) == 1 and rows[0]["memo_text"] == "밥의 메모"


def test_listings_bad_id_is_404(client_as, make_user):
    c = p1_client(client_as, make_user())
    r = c.get("/listings/not-a-uuid")
    assert r.status_code == 404 and error_code(r) == "LISTING_NOT_FOUND"


# ------------------------------------------------------------------ 만들기·번호
def test_listings_create_and_get(client_as, make_user):
    c = p1_client(client_as, make_user())
    s = create_session(c)
    lst = create_listing(c, s["id"], "  보증금 500 월세 40  ")
    assert lst["listing_no"] == 1 and lst["label"] == "1번 집"
    assert lst["memo_text"] == "보증금 500 월세 40"
    assert lst["session_id"] == s["id"]
    assert lst["latest_analysis_status"] == "none" and lst["needs_reanalysis"] is False
    got = c.get(f"/listings/{lst['id']}").json()
    assert got == lst


def test_listings_numbers_sequential_without_duplicates(client_as, make_user):
    c = p1_client(client_as, make_user())
    s = create_session(c)
    made = [create_listing(c, s["id"], f"메모 {i}") for i in range(5)]
    assert [m["listing_no"] for m in made] == [1, 2, 3, 4, 5]
    assert [m["label"] for m in made] == ["1번 집", "2번 집", "3번 집", "4번 집", "5번 집"]
    listed = c.get(f"/sessions/{s['id']}/listings").json()
    assert [x["listing_no"] for x in listed] == [1, 2, 3, 4, 5]


def test_listings_deleted_number_is_not_reused(client_as, make_user):
    c = p1_client(client_as, make_user())
    s = create_session(c)
    create_listing(c, s["id"], "하나")
    create_listing(c, s["id"], "둘")
    third = create_listing(c, s["id"], "셋")
    assert c.delete(f"/listings/{third['id']}").status_code == 200   # 마지막 번호 삭제
    fourth = create_listing(c, s["id"], "넷", name="넷째 집")
    assert fourth["listing_no"] == 4 and fourth["label"] == "넷째 집"
    listed = c.get(f"/sessions/{s['id']}/listings").json()
    assert [x["listing_no"] for x in listed] == [1, 2, 4]


def test_listings_numbers_are_per_session(client_as, make_user):
    c = p1_client(client_as, make_user())
    s1, s2 = create_session(c, "하나"), create_session(c, "둘")
    create_listing(c, s1["id"])
    create_listing(c, s1["id"])
    assert create_listing(c, s2["id"])["listing_no"] == 1


def test_listings_client_cannot_choose_number(client_as, make_user):
    c = p1_client(client_as, make_user())
    s = create_session(c)
    r = c.post(f"/sessions/{s['id']}/listings", json={"name": "1번방", "memo_text": "메모", "listing_no": 99})
    assert r.status_code == 200 and r.json()["listing_no"] == 1


# ------------------------------------------------------------------ 검증
def test_listings_blank_memo_422(client_as, make_user, memory_db):
    c = p1_client(client_as, make_user())
    s = create_session(c)
    for body in ({"name": "1번방", "memo_text": ""}, {"name": "1번방", "memo_text": "   \n "}, {"name": "1번방"}):
        r = c.post(f"/sessions/{s['id']}/listings", json=body)
        assert r.status_code == 422 and error_code(r) == "VALIDATION_ERROR", body
    assert memory_db.select("listings") == []

    lst = create_listing(c, s["id"], "원래 메모")
    r = c.patch(f"/listings/{lst['id']}", json={"memo_text": "  "})
    assert r.status_code == 422 and error_code(r) == "VALIDATION_ERROR"
    assert c.get(f"/listings/{lst['id']}").json()["memo_text"] == "원래 메모"


def test_listings_too_long_memo_422_without_echo(client_as, make_user):
    c = p1_client(client_as, make_user())
    s = create_session(c)
    long_memo = "가" * (MEMO_MAX_CHARS + 1)
    r = c.post(f"/sessions/{s['id']}/listings", json={"name": "1번방", "memo_text": long_memo})
    assert r.status_code == 422 and error_code(r) == "VALIDATION_ERROR"
    assert long_memo not in r.text   # 오류 응답에 메모 원문을 담지 않는다


def test_listings_name_required_and_used_as_label(client_as, make_user, memory_db):
    """새 매물 메모는 이름(예: "1번방")이 있어야 저장되고, 그 이름이 화면 이름(label)이 된다."""
    c = p1_client(client_as, make_user())
    s = create_session(c)
    for body in ({"memo_text": "메모"}, {"name": "", "memo_text": "메모"}, {"name": "  ", "memo_text": "메모"}):
        r = c.post(f"/sessions/{s['id']}/listings", json=body)
        assert r.status_code == 422 and error_code(r) == "VALIDATION_ERROR", body
        assert r.json()["error"]["detail"]["fields"][0]["loc"] == ["body", "name"]
        assert r.json()["error"]["message"] == "매물 이름을 입력하세요."
    r = c.post(f"/sessions/{s['id']}/listings", json={"name": "가" * 31, "memo_text": "메모"})
    assert r.status_code == 422 and error_code(r) == "VALIDATION_ERROR"
    assert memory_db.select("listings") == []

    made = c.post(f"/sessions/{s['id']}/listings", json={"name": "  1번방 ", "memo_text": "메모"}).json()
    assert made["label"] == "1번방" and made["listing_no"] == 1
    assert memory_db.select("listings")[0]["name"] == "1번방"            # 앞뒤 공백은 빼고 저장
    assert c.get(f"/sessions/{s['id']}/listings").json()[0]["label"] == "1번방"


def test_listings_without_name_keep_number_label(client_as, make_user, memory_db):
    """이름 열(0009)이 생기기 전에 만든 매물은 지금처럼 "N번 집"."""
    c = p1_client(client_as, make_user())
    s = create_session(c)
    memory_db.insert("listings", {"session_id": s["id"], "memo_text": "예전 메모"})
    assert c.get(f"/sessions/{s['id']}/listings").json()[0]["label"] == "1번 집"


# ------------------------------------------------------------------ 수정·재분석 표시
def test_listings_patch_sets_needs_reanalysis(client_as, make_user, memory_db):
    c = p1_client(client_as, make_user())
    s = create_session(c)
    lst = create_listing(c, s["id"], "보증금 500 월세 40")
    insert_analysis(memory_db, lst["id"], "보증금 500 월세 40")

    before = c.get(f"/listings/{lst['id']}").json()
    assert before["latest_analysis_status"] == "success" and before["needs_reanalysis"] is False

    r = c.patch(f"/listings/{lst['id']}", json={"memo_text": "보증금 1000 월세 35"})
    assert r.status_code == 200
    after = r.json()
    assert after["memo_text"] == "보증금 1000 월세 35"
    assert after["needs_reanalysis"] is True
    assert after["latest_analysis_status"] == "success"
    assert _t(after["memo_updated_at"]) > _t(before["memo_updated_at"])
    listed = c.get(f"/sessions/{s['id']}/listings").json()
    assert listed[0]["needs_reanalysis"] is True


def test_listings_patch_same_memo_keeps_state(client_as, make_user, memory_db):
    c = p1_client(client_as, make_user())
    s = create_session(c)
    lst = create_listing(c, s["id"], "같은 메모")
    insert_analysis(memory_db, lst["id"], "같은 메모")
    r = c.patch(f"/listings/{lst['id']}", json={"memo_text": " 같은 메모 "})
    assert r.status_code == 200
    assert r.json()["needs_reanalysis"] is False
    assert r.json()["memo_updated_at"] == lst["memo_updated_at"]


def test_listings_latest_status_uses_newest_row(client_as, make_user, memory_db):
    c = p1_client(client_as, make_user())
    s = create_session(c)
    lst = create_listing(c, s["id"], "메모")
    insert_analysis(memory_db, lst["id"], "메모", status="success")
    insert_analysis(memory_db, lst["id"], "메모", status="failed")
    got = c.get(f"/listings/{lst['id']}").json()
    assert got["latest_analysis_status"] == "failed"


# ------------------------------------------------------------------ 삭제
def test_listings_delete_cascades_and_emits(client_as, make_user, memory_db, memory_kv, memory_storage):
    alice = make_user()
    c = p1_client(client_as, alice)
    s = create_session(c)
    keep = create_listing(c, s["id"], "남길 집")
    lst = create_listing(c, s["id"], "지울 집")
    a = insert_analysis(memory_db, lst["id"], "지울 집")
    insert_feedback(memory_db, a["id"], alice.profile_id)
    assert c.put(f"/listings/{lst['id']}/draft", json={"memo_text": "초안"}).status_code == 200

    calls = []

    def on_listing_delete(**payload):
        calls.append(payload)

    events.on("listing.before_delete", on_listing_delete)
    r = c.delete(f"/listings/{lst['id']}")
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert len(calls) == 1 and set(calls[0]) == {"db", "user", "listing", "storage"}
    assert calls[0]["storage"] is memory_storage          # 엔드포인트의 Depends(get_storage)
    assert calls[0]["listing"]["id"] == lst["id"]
    assert calls[0]["listing"]["session"]["id"] == s["id"]

    assert memory_db.select("listings", {"id": lst["id"]}) == []
    assert memory_db.select("analyses") == [] and memory_db.select("feedback") == []
    assert memory_db.select("listings", {"id": keep["id"]})
    key = listing_draft_key(alice.auth_user_id, lst["id"])
    assert not memory_kv.exists(key) and not memory_kv.exists(meta_key(key))
    assert c.get(f"/listings/{lst['id']}").status_code == 404


def test_listings_delete_handler_error_keeps_row(client_as, make_user, memory_db, memory_kv):
    alice = make_user()
    c = p1_client(client_as, alice)
    s = create_session(c)
    lst = create_listing(c, s["id"])
    insert_analysis(memory_db, lst["id"], "x")
    assert c.put(f"/listings/{lst['id']}/draft", json={"memo_text": "초안"}).status_code == 200

    def failing_cleanup(**_):
        raise AppError(503, "CLEANUP_FAILED", "사진 정리에 실패했습니다.")

    events.on("listing.before_delete", failing_cleanup)
    r = c.delete(f"/listings/{lst['id']}")
    assert r.status_code == 503 and error_code(r) == "CLEANUP_FAILED"
    assert memory_db.select("listings", {"id": lst["id"]})
    assert len(memory_db.select("analyses")) == 1
    assert memory_kv.exists(listing_draft_key(alice.auth_user_id, lst["id"]))

    events.reset_events()
    assert c.delete(f"/listings/{lst['id']}").status_code == 200
    assert memory_db.select("listings", {"id": lst["id"]}) == []


# ------------------------------------------------------------------ KV 장애에도 저장은 동작
def test_listings_save_works_without_kv(client_as, make_user, memory_kv):
    c = p1_client(client_as, make_user())
    s = create_session(c)
    memory_kv.available = False
    lst = create_listing(c, s["id"], "KV 없이 저장")
    r = c.patch(f"/listings/{lst['id']}", json={"memo_text": "KV 없이 수정"})
    assert r.status_code == 200 and r.json()["memo_text"] == "KV 없이 수정"
    assert c.delete(f"/listings/{lst['id']}").status_code == 200


def test_listing_name_shown_in_other_session_screens(client_as, make_user):
    """비교표·예산 판정·적합도 순위도 같은 매물 이름을 쓴다(core.repo.listing_label)."""
    c = p1_client(client_as, make_user())
    s = create_session(c)
    create_listing(c, s["id"], name="1번방")
    create_listing(c, s["id"], name="역 앞 오피스텔")
    names = ["1번방", "역 앞 오피스텔"]
    assert [r["label"] for r in c.get(f"/sessions/{s['id']}/comparison").json()["rows"]] == names
    assert [r["label"] for r in c.get(f"/sessions/{s['id']}/budget/evaluations").json()["items"]] == names
    assert sorted(r["label"] for r in c.get(f"/sessions/{s['id']}/scores").json()["rows"]) == sorted(names)


def test_listing_patch_updates_name_and_memo(client_as, make_user, memory_db):
    """세션 상세 '매물 수정' 모달: 이름과 메모를 함께 고친다. 이름을 빼면 그대로 둔다."""
    c = p1_client(client_as, make_user())
    s = create_session(c)
    lst = create_listing(c, s["id"], "보증금 500", name="1번방")
    r = c.patch(f"/listings/{lst['id']}", json={"name": " 역 앞 원룸 ", "memo_text": "보증금 500"})
    assert r.status_code == 200 and r.json()["label"] == "역 앞 원룸"
    assert r.json()["needs_reanalysis"] is False                       # 이름만 바뀌면 메모 수정 시각도 그대로
    assert r.json()["memo_updated_at"] == lst["memo_updated_at"]
    r = c.patch(f"/listings/{lst['id']}", json={"memo_text": "보증금 600"})   # 매물 상세 메모 탭: 이름 안 보냄
    assert r.json()["label"] == "역 앞 원룸" and r.json()["memo_text"] == "보증금 600"
    for name in ("", "   "):
        r = c.patch(f"/listings/{lst['id']}", json={"name": name, "memo_text": "보증금 600"})
        assert r.status_code == 422 and r.json()["error"]["detail"]["fields"][0]["loc"] == ["body", "name"]
    r = c.patch(f"/listings/{lst['id']}", json={"name": "가" * 31, "memo_text": "보증금 600"})
    assert r.status_code == 422
    assert memory_db.select("listings", {"id": lst["id"]})[0]["name"] == "역 앞 원룸"


def test_listing_patch_names_listing_made_before_names(client_as, make_user, memory_db):
    """이름 없이 만든 예전 매물("N번 집")에도 이름을 붙일 수 있다."""
    c = p1_client(client_as, make_user())
    s = create_session(c)
    row = memory_db.insert("listings", {"session_id": s["id"], "memo_text": "예전 메모"})[0]
    r = c.patch(f"/listings/{row['id']}", json={"name": "1번방", "memo_text": "예전 메모"})
    assert r.status_code == 200 and r.json()["label"] == "1번방"
