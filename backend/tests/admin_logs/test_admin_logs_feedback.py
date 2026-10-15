"""GET /admin/feedback: 낮은 평가 사례(분석별 최신 평가만), 메모 앞부분·분석 요약."""

from __future__ import annotations

from app.features.admin_logs.feedback_cases import analysis_summary, memo_head
from tests.admin_logs.helpers import add_analysis, add_feedback, at, make_listing


def test_admin_logs_feedback_lists_latest_down_only(client_as, make_user, memory_db):
    admin, alice = make_user("admin"), make_user()
    memo = "역앞 원룸.\n500에 45, 관리비 7(수도 포함). 3층 남향. 채광 좋음, 곰팡이 없음. 수압 확인 못함."
    listing = make_listing(memory_db, alice.profile_id, memo)
    a1 = add_analysis(memory_db, listing["id"], prompt_version="v1")
    a2 = add_analysis(memory_db, listing["id"], prompt_version="v2")
    add_feedback(memory_db, a1["id"], alice.profile_id, rating="down", reason="amount", created_at=at(0))
    add_feedback(memory_db, a1["id"], alice.profile_id, rating="up", created_at=at(1))   # a1은 마음을 바꿈
    keep = add_feedback(memory_db, a2["id"], alice.profile_id, rating="down", reason="not_in_memo",
                        comment="메모에 없는 내용", created_at=at(2))

    r = client_as(admin).get("/admin/feedback", params={"rating": "down", "limit": 10})
    assert r.status_code == 200
    body = r.json()
    assert [x["id"] for x in body] == [keep["id"]]
    item = body[0]
    assert item["reason"] == "not_in_memo" and item["comment"] == "메모에 없는 내용"
    assert item["listing_id"] == listing["id"] and item["prompt_version"] == "v2"
    assert item["memo_head"].startswith("역앞 원룸. 500에 45") and item["memo_head"].endswith("…")
    assert "보증금 500만원" in item["analysis_summary"] and "관리비 미기재" in item["analysis_summary"]


def test_admin_logs_feedback_empty(client_as, make_user):
    assert client_as(make_user("admin")).get("/admin/feedback").json() == []


def test_admin_logs_memo_head_and_summary_helpers():
    assert memo_head(None) is None
    assert memo_head("짧은\n메모") == "짧은 메모"
    assert len(memo_head("가" * 100)) == 41
    assert analysis_summary(None) is None
    s = analysis_summary({"label": "역앞", "deposit_manwon": 0, "monthly_rent_manwon": None})
    assert s.startswith("역앞 · 보증금 0만원 · 월세 미기재")
