"""F12 API: 가중치 프로필·만족도·세션 설정·점수, 비교표 열 score."""

from __future__ import annotations

import uuid

from app.features.scoring.items import SCORE_ITEMS
from tests.scoring.scoring_helpers import make_analysis, make_listing, make_session, profile_body, sat_body

# 기능 정리 문서 예시(일조량·습도·소음)를 서비스 체크리스트 항목(채광·곰팡이·소음)에 대응시킨다
A_SAT = {"채광": 90, "곰팡이": 40, "소음": 60}
B_SAT = {"채광": 50, "곰팡이": 90, "소음": 60}
SUMMER = {"채광": 20, "곰팡이": 50, "소음": 30}
WINTER = {"채광": 50, "곰팡이": 20, "소음": 30}


def _two_listings(db, user):
    s = make_session(db, user)
    a, b = make_listing(db, s, "A"), make_listing(db, s, "B")
    return s, a, b


# ------------------------------------------------------------------ 가중치 프로필
def test_scoring_profile_create_list_get(client_as, make_user):
    alice = make_user()
    c = client_as(alice)
    r = c.post("/weight-profiles", json=profile_body(" 여름 6개월 ", **SUMMER))
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "여름 6개월"
    assert [w["item_key"] for w in body["weights"]] == list(SCORE_ITEMS)       # 항상 전체 항목
    weights = {w["item_key"]: w["weight"] for w in body["weights"]}
    assert weights["채광"] == 20 and weights["곰팡이"] == 50 and weights["수압"] == 0   # 빠진 항목은 0
    c.post("/weight-profiles", json=profile_body("겨울 6개월", **WINTER))
    names = [p["name"] for p in c.get("/weight-profiles").json()]
    assert names == ["여름 6개월", "겨울 6개월"]
    assert c.get(f"/weight-profiles/{body['id']}").json()["name"] == "여름 6개월"


def test_scoring_profile_update_replaces_weights(client_as, make_user, memory_db):
    alice = make_user()
    c = client_as(alice)
    pid = c.post("/weight-profiles", json=profile_body("여름", **SUMMER)).json()["id"]
    r = c.put(f"/weight-profiles/{pid}", json=profile_body("한여름", 소음=100))
    assert r.status_code == 200
    weights = {w["item_key"]: w["weight"] for w in r.json()["weights"]}
    assert r.json()["name"] == "한여름" and weights["소음"] == 100 and weights["채광"] == 0
    assert len(memory_db.select("weight_items", {"weight_profile_id": pid})) == 1


def test_scoring_profile_validation_422(client_as, make_user):
    c = client_as(make_user())
    bad = [
        profile_body("", 채광=10),                                   # 이름 없음
        profile_body("   ", 채광=10),                                # 공백뿐
        profile_body("가" * 31, 채광=10),                            # 31자
        profile_body("여름", 엘리베이터=10),                          # 없는 항목
        profile_body("여름", 채광=101),                               # 범위 밖
        profile_body("여름", 채광=-1),
        {"name": "여름", "weights": [{"item_key": "채광", "weight": 1}, {"item_key": "채광", "weight": 2}]},
    ]
    for body in bad:
        r = c.post("/weight-profiles", json=body)
        assert r.status_code == 422, body
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_scoring_profile_of_other_user_is_404(client_as, make_user):
    alice, bob = make_user(), make_user()
    pid = client_as(alice).post("/weight-profiles", json=profile_body("여름", **SUMMER)).json()["id"]
    c = client_as(bob)
    assert c.get("/weight-profiles").json() == []
    for r in (c.get(f"/weight-profiles/{pid}"), c.put(f"/weight-profiles/{pid}", json=profile_body("x")),
              c.delete(f"/weight-profiles/{pid}"), c.get("/weight-profiles/not-a-uuid"),
              c.get(f"/weight-profiles/{uuid.uuid4()}")):
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "WEIGHT_PROFILE_NOT_FOUND"


def test_scoring_profile_delete_resets_session_choice(client_as, make_user, memory_db):
    alice = make_user()
    s = make_session(memory_db, alice)
    c = client_as(alice)
    pid = c.post("/weight-profiles", json=profile_body("여름", **SUMMER)).json()["id"]
    c.put(f"/sessions/{s['id']}/scoring", json={"enabled": True, "weight_profile_id": pid})
    assert c.delete(f"/weight-profiles/{pid}").json() == {"ok": True}
    got = c.get(f"/sessions/{s['id']}/scoring").json()
    assert got["weight_profile_id"] is None and got["enabled"] is True
    assert memory_db.select("weight_items", {"weight_profile_id": pid}) == []
    assert c.get("/weight-profiles").json() == []


# ------------------------------------------------------------------ 만족도
def test_scoring_satisfaction_get_put_clear(client_as, make_user, memory_db):
    alice = make_user()
    s = make_session(memory_db, alice)
    lst = make_listing(memory_db, s)
    c = client_as(alice)
    empty = c.get(f"/listings/{lst['id']}/satisfaction").json()
    assert empty["entered_count"] == 0 and empty["updated_at"] is None
    assert [i["item_key"] for i in empty["items"]] == list(SCORE_ITEMS)
    assert all(i["satisfaction"] is None for i in empty["items"])

    r = c.put(f"/listings/{lst['id']}/satisfaction", json=sat_body(**A_SAT))
    assert r.status_code == 200 and r.json()["entered_count"] == 3 and r.json()["updated_at"]
    got = {i["item_key"]: i["satisfaction"] for i in c.get(f"/listings/{lst['id']}/satisfaction").json()["items"]}
    assert got["채광"] == 90 and got["소음"] == 60 and got["수압"] is None

    # 통째로 바꾸기: 보내지 않은 항목은 미입력이 된다
    c.put(f"/listings/{lst['id']}/satisfaction", json=sat_body(소음=10))
    got = {i["item_key"]: i["satisfaction"] for i in c.get(f"/listings/{lst['id']}/satisfaction").json()["items"]}
    assert got["소음"] == 10 and got["채광"] is None

    cleared = c.put(f"/listings/{lst['id']}/satisfaction", json={"items": []}).json()
    assert cleared["entered_count"] == 0 and cleared["updated_at"] is None
    assert memory_db.select("listing_satisfactions", {"listing_id": lst["id"]}) == []


def test_scoring_satisfaction_validation_and_ownership(client_as, make_user, memory_db):
    alice, bob = make_user(), make_user()
    s = make_session(memory_db, alice)
    lst = make_listing(memory_db, s)
    c = client_as(alice)
    for body in (sat_body(채광=101), sat_body(채광=-1), sat_body(엘리베이터=50),
                 {"items": [{"item_key": "채광", "satisfaction": 1}, {"item_key": "채광", "satisfaction": 2}]}):
        assert c.put(f"/listings/{lst['id']}/satisfaction", json=body).status_code == 422
    other = client_as(bob)
    for r in (other.get(f"/listings/{lst['id']}/satisfaction"),
              other.put(f"/listings/{lst['id']}/satisfaction", json=sat_body(채광=1))):
        assert r.status_code == 404 and r.json()["error"]["code"] == "LISTING_NOT_FOUND"


def test_scoring_requires_login(client_as):
    c = client_as(None)
    assert c.get("/weight-profiles").status_code == 401
    assert c.get(f"/sessions/{uuid.uuid4()}/scores").status_code == 401


# ------------------------------------------------------------------ 세션 설정
def test_scoring_setting_default_and_save(client_as, make_user, memory_db):
    alice = make_user()
    s = make_session(memory_db, alice)
    c = client_as(alice)
    d = c.get(f"/sessions/{s['id']}/scoring").json()
    assert d == {"session_id": s["id"], "enabled": True, "weight_profile_id": None, "weight_profile_name": None,
                 "updated_at": None, "items": list(SCORE_ITEMS)}
    pid = c.post("/weight-profiles", json=profile_body("여름", **SUMMER)).json()["id"]
    r = c.put(f"/sessions/{s['id']}/scoring", json={"enabled": False, "weight_profile_id": pid})
    assert r.status_code == 200
    assert r.json()["enabled"] is False and r.json()["weight_profile_name"] == "여름"
    c.put(f"/sessions/{s['id']}/scoring", json={"enabled": True, "weight_profile_id": None})
    assert c.get(f"/sessions/{s['id']}/scoring").json()["weight_profile_id"] is None
    assert len(memory_db.select("session_scoring", {"session_id": s["id"]})) == 1


def test_scoring_setting_rejects_other_users_profile(client_as, make_user, memory_db):
    alice, bob = make_user(), make_user()
    s = make_session(memory_db, alice)
    bob_pid = client_as(bob).post("/weight-profiles", json=profile_body("남의 것", **SUMMER)).json()["id"]
    c = client_as(alice)
    r = c.put(f"/sessions/{s['id']}/scoring", json={"enabled": True, "weight_profile_id": bob_pid})
    assert r.status_code == 404 and r.json()["error"]["code"] == "WEIGHT_PROFILE_NOT_FOUND"
    r = client_as(bob).get(f"/sessions/{s['id']}/scoring")
    assert r.status_code == 404 and r.json()["error"]["code"] == "SESSION_NOT_FOUND"


# ------------------------------------------------------------------ 점수·순위
def test_scoring_scores_follow_selected_season_profile(client_as, make_user, memory_db):
    alice = make_user()
    s, a, b = _two_listings(memory_db, alice)
    c = client_as(alice)
    c.put(f"/listings/{a['id']}/satisfaction", json=sat_body(**A_SAT))
    c.put(f"/listings/{b['id']}/satisfaction", json=sat_body(**B_SAT))
    summer = c.post("/weight-profiles", json=profile_body("여름 6개월", **SUMMER)).json()["id"]
    winter = c.post("/weight-profiles", json=profile_body("겨울 6개월", **WINTER)).json()["id"]

    c.put(f"/sessions/{s['id']}/scoring", json={"enabled": True, "weight_profile_id": summer})
    data = c.get(f"/sessions/{s['id']}/scores").json()
    assert [(r["label"], r["score"], r["rank"]) for r in data["rows"]] == [("2번 집", 73, 1), ("1번 집", 56, 2)]
    assert data["setting"]["weight_profile_name"] == "여름 6개월"
    assert data["rows"][0]["entered_count"] == 3 and data["rows"][0]["total_items"] == len(SCORE_ITEMS)

    c.put(f"/sessions/{s['id']}/scoring", json={"enabled": True, "weight_profile_id": winter})
    data = c.get(f"/sessions/{s['id']}/scores").json()
    assert [(r["label"], r["score"], r["rank"]) for r in data["rows"]] == [("1번 집", 71, 1), ("2번 집", 61, 2)]


def test_scoring_scores_without_profile_use_equal_weights_and_unrated_last(client_as, make_user, memory_db):
    alice = make_user()
    s, a, b = _two_listings(memory_db, alice)
    make_listing(memory_db, s, "C")   # 만족도 미입력
    c = client_as(alice)
    c.put(f"/listings/{a['id']}/satisfaction", json=sat_body(**A_SAT))   # (90+40+60)/3 = 63
    c.put(f"/listings/{b['id']}/satisfaction", json=sat_body(**B_SAT))   # (50+90+60)/3 = 67
    rows = c.get(f"/sessions/{s['id']}/scores").json()["rows"]
    assert [(r["label"], r["score"], r["rank"]) for r in rows] == [("2번 집", 67, 1), ("1번 집", 63, 2),
                                                                     ("3번 집", None, None)]


def test_scoring_scores_disabled_hides_rows(client_as, make_user, memory_db):
    alice = make_user()
    s, a, _ = _two_listings(memory_db, alice)
    c = client_as(alice)
    c.put(f"/listings/{a['id']}/satisfaction", json=sat_body(**A_SAT))
    c.put(f"/sessions/{s['id']}/scoring", json={"enabled": False, "weight_profile_id": None})
    data = c.get(f"/sessions/{s['id']}/scores").json()
    assert data["setting"]["enabled"] is False and data["rows"] == []
    # 꺼도 입력한 만족도는 남는다
    assert c.get(f"/listings/{a['id']}/satisfaction").json()["entered_count"] == 3


def test_scoring_scores_rank_only_candidates_left_by_budget_filter(client_as, make_user, memory_db):
    alice = make_user()
    s, a, b = _two_listings(memory_db, alice)
    make_analysis(memory_db, a, monthly_rent_manwon=40, maintenance_fee_manwon=5)    # 월 45 → 예산 안
    make_analysis(memory_db, b, monthly_rent_manwon=70, maintenance_fee_manwon=5)    # 월 75 → 초과
    c = client_as(alice)
    c.put(f"/sessions/{s['id']}/budget", json={"monthly_max_manwon": 60})
    c.put(f"/listings/{a['id']}/satisfaction", json=sat_body(**A_SAT))
    c.put(f"/listings/{b['id']}/satisfaction", json=sat_body(**B_SAT))   # 점수는 더 높지만 예산 초과

    full = c.get(f"/sessions/{s['id']}/scores").json()
    assert [r["label"] for r in full["rows"]] == ["2번 집", "1번 집"] and full["hidden_count"] == {}

    filtered = c.get(f"/sessions/{s['id']}/scores", params={"filters": "within_budget,nope"}).json()
    assert [(r["label"], r["rank"]) for r in filtered["rows"]] == [("1번 집", 1)]
    assert filtered["hidden_count"] == {"within_budget": 1}      # 등록 안 된 nope은 무시


def test_scoring_comparison_column(client_as, make_user, memory_db):
    alice = make_user()
    s, a, b = _two_listings(memory_db, alice)
    c = client_as(alice)
    pid = c.post("/weight-profiles", json=profile_body("여름 6개월", **SUMMER)).json()["id"]
    c.put(f"/sessions/{s['id']}/scoring", json={"enabled": True, "weight_profile_id": pid})
    c.put(f"/listings/{a['id']}/satisfaction", json=sat_body(**A_SAT))

    data = c.get(f"/sessions/{s['id']}/comparison").json()
    assert {"key": "score", "title": "적합도"} in data["providers"]
    cols = {r["listing_no"]: r["columns"]["score"] for r in data["rows"]}
    assert cols[1]["display"] == "56점" and cols[1]["status"] == "scored"
    assert cols[2]["display"] == "만족도 미입력" and cols[2]["tone"] == "muted"

    c.put(f"/sessions/{s['id']}/scoring", json={"enabled": False, "weight_profile_id": pid})
    cols = {r["listing_no"]: r["columns"]["score"] for r in c.get(f"/sessions/{s['id']}/comparison").json()["rows"]}
    assert cols[1]["display"] == "꺼짐" and cols[2]["display"] == "꺼짐"


def test_scoring_stale_item_rows_are_ignored(client_as, make_user, memory_db):
    """항목 목록에서 빠진 항목의 행이 DB에 남아 있어도 계산·응답에서 무시한다."""
    alice = make_user()
    s, a, b = _two_listings(memory_db, alice)
    memory_db.insert("listing_satisfactions", {"listing_id": a["id"], "item_key": "옛 항목", "satisfaction": 0})
    c = client_as(alice)
    c.put(f"/listings/{b['id']}/satisfaction", json=sat_body(채광=80))
    sat = c.get(f"/listings/{a['id']}/satisfaction").json()
    assert sat["entered_count"] == 0 and "옛 항목" not in [i["item_key"] for i in sat["items"]]
    rows = {r["label"]: r["score"] for r in c.get(f"/sessions/{s['id']}/scores").json()["rows"]}
    assert rows == {"1번 집": None, "2번 집": 80}
