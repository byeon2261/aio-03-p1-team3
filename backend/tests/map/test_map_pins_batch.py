"""지도 핀·매물 목록을 한 번에 조회: 응답은 매물마다 따로 묻던 때와 같고, 분석·수정값 조회는 한 번씩."""

from __future__ import annotations

from app.core.analysis_contract import needs_reanalysis
from app.core.repo import latest_analysis, list_listings
from app.features.listings.router import listing_out
from app.features.map import locations
from app.features.map.schemas import LocationOut, MyPinOut, MyPinsOut, SessionPinOut
from tests.sessions.helpers import insert_analysis

LOC = {"road_address": "가상시 예시구 샘플로 1", "latitude": 37.55, "longitude": 126.97}


def _session(db, user, title):
    return db.insert("tour_sessions", {"profile_id": user.profile_id, "title": title})[0]


def _listing(db, session, memo):
    return db.insert("listings", {"session_id": session["id"], "memo_text": memo})[0]


def _success(db, listing, **money):
    a = insert_analysis(db, listing["id"], listing["memo_text"])
    return db.update("analyses", {"id": a["id"]}, {"result_json": dict(money)})[0]


def _fix(db, user, analysis, field, value, action="set"):
    db.insert("feedback", {"analysis_id": analysis["id"], "profile_id": user.profile_id,
                           "field_name": field, "action": action, "corrected_value": value})


def _locate(db, listing):
    db.insert(locations.TABLE, {"listing_id": listing["id"], **LOC})


def _data(db, user):
    """세션 2개. 성공+수정·취소 / 성공 뒤 실패 / 분석 없음 / 메모 바뀜(재분석 필요) / 위치 없음 섞기."""
    s1, s2 = _session(db, user, "토요일"), _session(db, user, "일요일")
    l1 = _listing(db, s1, "보증금 500 월세 40")
    a1 = _success(db, l1, deposit_manwon=500, monthly_rent_manwon=40, maintenance_fee_manwon=7)
    _fix(db, user, a1, "deposit_manwon", 1000)
    _fix(db, user, a1, "monthly_rent_manwon", 45)
    _fix(db, user, a1, "monthly_rent_manwon", None, action="revert")       # 취소 → AI 값 40
    _fix(db, user, a1, "maintenance_fee_manwon", None)                      # 메모에 없음
    l2 = _listing(db, s1, "보증금 300 월세 50")
    _success(db, l2, deposit_manwon=300, monthly_rent_manwon=50)
    insert_analysis(db, l2["id"], l2["memo_text"], status="failed")        # 최신은 실패
    l3 = _listing(db, s1, "분석 전 메모")
    l4 = _listing(db, s1, "옛 메모")
    _success(db, l4, deposit_manwon=100)
    l4 = db.update("listings", {"id": l4["id"]}, {"memo_text": "바뀐 메모"})[0]   # 재분석 필요
    l5 = _listing(db, s2, "보증금 200")
    a5 = _success(db, l5, deposit_manwon=200)
    _fix(db, user, a5, "deposit_manwon", 250)
    for lst in (l1, l2, l3, l5):
        _locate(db, lst)                                                    # l4는 위치 없음
    return s1, s2


def _counting(db):
    tables: list[str] = []
    original = db.select

    def counting(table, *args, **kwargs):
        tables.append(table)
        return original(table, *args, **kwargs)

    db.select = counting
    return tables, original


# 바꾸기 전 방식(매물마다 따로 묻기) — 결과 비교용
def _old_session_pins(db, session_id):
    listings = list_listings(db, session_id)
    by_listing = {str(r["listing_id"]): r for r in db.select(locations.TABLE)}
    return [SessionPinOut(listing_id=str(x["id"]), listing_no=int(x["listing_no"]), label=locations.label_of(x),
                          location=LocationOut.model_validate(by_listing[str(x["id"])]),
                          **locations.money_of(db, x["id"]))
            for x in sorted(listings, key=lambda x: int(x["listing_no"])) if str(x["id"]) in by_listing]


def _old_my_pins(db, user, sessions):
    by_listing = {str(r["listing_id"]): r for r in db.select(locations.TABLE)}
    pins, count = [], 0
    for s in sessions:
        listings = sorted(db.select("listings", {"session_id": s["id"]}), key=lambda x: int(x["listing_no"]))
        count += len(listings)
        for x in listings:
            if str(x["id"]) not in by_listing:
                continue
            newest = latest_analysis(db, x["id"], status=None)
            pins.append(MyPinOut(listing_id=str(x["id"]), listing_no=int(x["listing_no"]),
                                 label=locations.label_of(x),
                                 location=LocationOut.model_validate(by_listing[str(x["id"])]),
                                 session_id=str(s["id"]), session_title=s.get("title") or "",
                                 memo_text=x.get("memo_text") or "",
                                 analysis_status=(newest or {}).get("status") or "none",
                                 needs_reanalysis=needs_reanalysis(x, newest),
                                 **locations.money_of(db, x["id"])))
    return MyPinsOut(pins=pins, listing_count=count)


def test_session_pins_same_as_before_and_query_once(memory_db, make_user):
    alice = make_user()
    s1, _ = _data(memory_db, alice)
    expected = _old_session_pins(memory_db, s1["id"])
    tables, original = _counting(memory_db)
    try:
        got = locations.session_pins(memory_db, s1["id"])
    finally:
        memory_db.select = original
    assert [p.model_dump() for p in got] == [p.model_dump() for p in expected]
    assert len(got) == 3
    assert got[0].deposit_manwon == 1000 and got[0].monthly_rent_manwon == 40
    assert got[0].maintenance_fee_manwon is None
    assert got[2].analyzed is False
    assert tables.count("analyses") == 1 and tables.count("feedback") == 1


def test_my_pins_same_as_before_and_query_once(memory_db, make_user):
    alice = make_user()
    s1, s2 = _data(memory_db, alice)
    sessions = memory_db.select("tour_sessions", {"profile_id": alice.profile_id}, order_by="created_at", desc=True)
    expected = _old_my_pins(memory_db, alice, sessions)
    tables, original = _counting(memory_db)
    try:
        got = locations.my_pins(memory_db, alice.profile_id)
    finally:
        memory_db.select = original
    assert got.model_dump() == expected.model_dump()
    assert got.listing_count == 5 and len(got.pins) == 4
    status = {p.memo_text: p.analysis_status for p in got.pins}
    assert status == {"보증금 500 월세 40": "success", "보증금 300 월세 50": "failed",
                      "분석 전 메모": "none", "보증금 200": "success"}
    assert tables.count("analyses") == 1 and tables.count("feedback") == 1


def test_my_pins_without_any_analysis(memory_db, make_user):
    alice = make_user()
    s = _session(memory_db, alice, "토요일")
    _locate(memory_db, _listing(memory_db, s, "메모"))
    pins = locations.my_pins(memory_db, alice.profile_id).pins
    assert len(pins) == 1 and pins[0].analyzed is False and pins[0].analysis_status == "none"


def test_session_listings_same_as_before_and_query_once(client_as, make_user, memory_db):
    alice = make_user()
    s1, _ = _data(memory_db, alice)
    expected = [listing_out(memory_db, r).model_dump(mode="json") for r in list_listings(memory_db, s1["id"])]
    c = client_as(alice)
    tables, original = _counting(memory_db)
    try:
        r = c.get(f"/sessions/{s1['id']}/listings")
    finally:
        memory_db.select = original
    assert r.status_code == 200, r.text
    assert r.json() == expected
    assert [x["latest_analysis_status"] for x in r.json()] == ["success", "failed", "none", "success"]
    assert [x["needs_reanalysis"] for x in r.json()] == [False, False, False, True]
    assert tables.count("analyses") == 1
