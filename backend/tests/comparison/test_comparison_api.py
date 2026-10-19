"""F6 매물 비교표: GET /sessions/{session_id}/comparison"""

from __future__ import annotations

import pytest

from app.core.analysis_contract import CheckItem
from app.core.errors import AppError
from app.core.registry import ColumnProvider, ColumnValue, register_column_provider, register_row_filter
from app.features.comparison.service import FIELD_KEYS, build_comparison, parse_filters
from tests.comparison.seed import add_failed, add_override, add_success, make_listing, make_session

EXPECTED_FIELDS = [
    "deposit_manwon", "monthly_rent_manwon", "maintenance_fee_manwon", "monthly_cost_manwon",
    "maintenance_includes", "transit", "floor", "direction", "pros", "cons", "followup_checks",
]


def _rows_by_no(out) -> dict[int, object]:
    return {r.listing_no: r for r in out.rows}


# ------------------------------------------------------------------ API
def test_comparison_api_fields_order_and_values(client_as, make_user, memory_db):
    alice = make_user()
    s = make_session(memory_db, alice)
    a1, a2 = make_listing(memory_db, s, "1번 메모"), make_listing(memory_db, s, "2번 메모")
    add_success(memory_db, a1)
    add_success(memory_db, a2, monthly_rent_manwon=50)
    r = client_as(alice).get(f"/sessions/{s['id']}/comparison")
    assert r.status_code == 200
    body = r.json()
    assert body["enough_listings"] is True and body["message"] is None
    assert [f["key"] for f in body["fields"]] == EXPECTED_FIELDS
    assert [f["title"] for f in body["fields"]][:4] == ["보증금", "월세", "관리비", "월 고정비"]
    assert body["fields"][4] == {"key": "maintenance_includes", "title": "포함 내역"}
    row1 = body["rows"][0]
    assert row1["label"] == "1번 집" and row1["analysis_status"] == "success"
    assert list(row1["values"]) == EXPECTED_FIELDS          # 응답 values는 열 순서 그대로
    assert row1["values"]["monthly_cost_manwon"] == 52       # 45 + 7
    assert body["lowest"]["monthly_rent_manwon"] == [a1["id"]]


def test_comparison_api_single_listing_not_enough(client_as, make_user, memory_db):
    alice = make_user()
    s = make_session(memory_db, alice)
    add_success(memory_db, make_listing(memory_db, s))
    body = client_as(alice).get(f"/sessions/{s['id']}/comparison").json()
    assert body["enough_listings"] is False
    assert body["message"] == "매물을 하나 더 추가하세요"


def test_comparison_api_empty_session_not_enough(client_as, make_user, memory_db):
    alice = make_user()
    s = make_session(memory_db, alice)
    body = client_as(alice).get(f"/sessions/{s['id']}/comparison").json()
    assert body["enough_listings"] is False and body["rows"] == []


def test_comparison_api_other_users_session_404(client_as, make_user, memory_db):
    alice, bob = make_user(), make_user()
    s = make_session(memory_db, bob)
    make_listing(memory_db, s), make_listing(memory_db, s)
    r = client_as(alice).get(f"/sessions/{s['id']}/comparison")
    assert r.status_code == 404 and r.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_comparison_api_requires_login(client_as, make_user, memory_db):
    s = make_session(memory_db, make_user())
    assert client_as(None).get(f"/sessions/{s['id']}/comparison").status_code == 401


def test_comparison_api_fake_provider_and_row_filter(client_as, make_user, memory_db):
    alice = make_user()
    s = make_session(memory_db, alice)
    l1, l2, l3 = (make_listing(memory_db, s, f"메모{i}") for i in range(3))
    add_success(memory_db, l1, monthly_rent_manwon=40)
    add_success(memory_db, l2, monthly_rent_manwon=60)
    seen: dict = {}

    def compute(*, db, user, session, rows):
        seen["rows"] = rows
        seen["session_id"] = session["id"]
        out = {}
        for r in rows:
            cost = r["values"].get("monthly_cost_manwon")
            if cost is None:
                out[r["listing_id"]] = ColumnValue(display="판단 불가", status="unknown", tone="muted")
            else:
                out[r["listing_id"]] = ColumnValue(display=f"{cost}", status="ok", tone="good" if cost < 60 else "bad")
        return out

    def keep(*, db, user, session, rows):
        return {r["listing_id"] for r in rows if (r["values"].get("monthly_cost_manwon") or 999) < 60}

    # client_as()가 앱을 만들 때 실제 P5 hooks가 같은 key(budget·within_budget)를 다시 등록하므로,
    # 가짜는 앱을 만든 뒤에 등록해 바꿔 끼운다(같은 key는 교체).
    c = client_as(alice)
    register_column_provider(ColumnProvider(key="budget", title="예산", compute=compute, order=10))
    register_row_filter("within_budget", keep)

    full = c.get(f"/sessions/{s['id']}/comparison").json()
    # 다른 기능(F12 score 등)의 열도 함께 붙으므로 자기 key만 확인한다(CONTRACT 7절)
    assert {"key": "budget", "title": "예산"} in full["providers"]
    assert full["hidden_count"] == {}
    cols = {r["listing_no"]: r["columns"]["budget"] for r in full["rows"]}
    assert cols[1]["tone"] == "good" and cols[2]["tone"] == "bad" and cols[3]["display"] == "판단 불가"
    # 제공자는 행 정보(값 포함)를 받는다
    assert seen["session_id"] == s["id"]
    assert {"listing_id", "listing_no", "label", "analysis_status", "needs_reanalysis", "values"} <= set(seen["rows"][0])
    assert seen["rows"][2]["values"] == {} and seen["rows"][2]["analysis_status"] == "none"

    filtered = c.get(f"/sessions/{s['id']}/comparison", params={"filters": "within_budget,nope"}).json()
    assert [r["listing_no"] for r in filtered["rows"]] == [1]
    assert filtered["hidden_count"] == {"within_budget": 2}     # 등록 안 된 nope은 무시
    assert filtered["lowest"]["monthly_rent_manwon"] == [l1["id"]]


# ------------------------------------------------------------------ 계산 규칙 (서비스 직접)
def test_comparison_user_override_beats_ai(memory_db, make_user):
    alice = make_user()
    s = make_session(memory_db, alice)
    l1, l2 = make_listing(memory_db, s, "a"), make_listing(memory_db, s, "b")
    a1 = add_success(memory_db, l1, monthly_rent_manwon=45)
    add_success(memory_db, l2, monthly_rent_manwon=42)
    add_override(memory_db, alice, a1, "monthly_rent_manwon", 40)
    add_override(memory_db, alice, a1, "pros", ["직접 고친 장점"])
    out = build_comparison(memory_db, alice, s["id"])
    row = _rows_by_no(out)[1]
    assert row.values["monthly_rent_manwon"] == 40
    assert row.values["pros"] == ["직접 고친 장점"]
    assert row.values["monthly_cost_manwon"] == 47           # 수정값으로 다시 계산
    assert out.lowest["monthly_rent_manwon"] == [l1["id"]]


def test_comparison_override_cancel_returns_ai_value(memory_db, make_user):
    alice = make_user()
    s = make_session(memory_db, alice)
    l1, l2 = make_listing(memory_db, s, "a"), make_listing(memory_db, s, "b")
    a1 = add_success(memory_db, l1, monthly_rent_manwon=45)
    add_success(memory_db, l2)
    add_override(memory_db, alice, a1, "monthly_rent_manwon", 40)
    add_override(memory_db, alice, a1, "monthly_rent_manwon", None)     # 수정 취소
    assert _rows_by_no(build_comparison(memory_db, alice, s["id"]))[1].values["monthly_rent_manwon"] == 45


def test_comparison_null_is_not_zero_and_lowest_only_known(memory_db, make_user):
    alice = make_user()
    s = make_session(memory_db, alice)
    l1, l2, l3 = (make_listing(memory_db, s, x) for x in "abc")
    add_success(memory_db, l1, monthly_rent_manwon=None, maintenance_fee_manwon=None)
    add_success(memory_db, l2, monthly_rent_manwon=50, maintenance_fee_manwon=10)
    add_success(memory_db, l3, monthly_rent_manwon=55, maintenance_fee_manwon=None)
    out = build_comparison(memory_db, alice, s["id"])
    rows = _rows_by_no(out)
    assert rows[1].values["monthly_rent_manwon"] is None      # 0이 아니라 None
    assert rows[1].values["maintenance_fee_manwon"] is None
    assert out.lowest["monthly_rent_manwon"] == [l2["id"]]     # None인 1번은 비교에서 빠짐
    assert out.lowest["maintenance_fee_manwon"] == [l2["id"]]


def test_comparison_lowest_zero_fee_counts_and_ties(memory_db, make_user):
    alice = make_user()
    s = make_session(memory_db, alice)
    l1, l2, l3 = (make_listing(memory_db, s, x) for x in "abc")
    add_success(memory_db, l1, monthly_rent_manwon=45, maintenance_fee_manwon=0)   # '관리비 없음' = 0
    add_success(memory_db, l2, monthly_rent_manwon=45, maintenance_fee_manwon=5)
    add_success(memory_db, l3, monthly_rent_manwon=50, maintenance_fee_manwon=0)
    out = build_comparison(memory_db, alice, s["id"])
    assert out.lowest["monthly_rent_manwon"] == [l1["id"], l2["id"]]      # 같으면 모두
    assert out.lowest["maintenance_fee_manwon"] == [l1["id"], l3["id"]]


def test_comparison_lowest_empty_when_no_known_values(memory_db, make_user):
    alice = make_user()
    s = make_session(memory_db, alice)
    make_listing(memory_db, s, "a"), make_listing(memory_db, s, "b")
    out = build_comparison(memory_db, alice, s["id"])
    assert out.lowest == {"monthly_rent_manwon": [], "maintenance_fee_manwon": []}


def test_comparison_monthly_cost_only_when_both_known(memory_db, make_user):
    alice = make_user()
    s = make_session(memory_db, alice)
    l1, l2, l3 = (make_listing(memory_db, s, x) for x in "abc")
    add_success(memory_db, l1, monthly_rent_manwon=45, maintenance_fee_manwon=None)
    add_success(memory_db, l2, monthly_rent_manwon=45, maintenance_fee_manwon=0)
    add_success(memory_db, l3, monthly_rent_manwon=None, maintenance_fee_manwon=7)
    rows = _rows_by_no(build_comparison(memory_db, alice, s["id"]))
    assert rows[1].values["monthly_cost_manwon"] is None
    assert rows[2].values["monthly_cost_manwon"] == 45
    assert rows[3].values["monthly_cost_manwon"] is None


def test_comparison_followup_checks_in_checklist_order(memory_db, make_user):
    alice = make_user()
    s = make_session(memory_db, alice)
    l1, l2 = make_listing(memory_db, s, "a"), make_listing(memory_db, s, "b")
    add_success(memory_db, l1, checks=[
        CheckItem(item="교통", status="confirmed", evidence="역앞"),
        CheckItem(item="수압", status="unchecked", evidence="수압 확인 못함"),
        CheckItem(item="소음", status="ambiguous", evidence="조금 시끄러운 듯?"),
        CheckItem(item="채광", status="confirmed", evidence="채광 좋음"),
        CheckItem(item="곰팡이", status="confirmed", evidence="곰팡이 없음"),
        CheckItem(item="층수", status="confirmed", evidence="3층"),
    ])
    add_success(memory_db, l2)
    rows = _rows_by_no(build_comparison(memory_db, alice, s["id"]))
    # 소음(애매) · 수압(확인 못함) · 난방·옵션·보안(언급 없음) — CHECKLIST 순서
    assert rows[1].values["followup_checks"] == ["소음", "수압", "난방", "옵션", "보안"]


def test_comparison_latest_failed_keeps_previous_success(memory_db, make_user):
    alice = make_user()
    s = make_session(memory_db, alice)
    l1, l2 = make_listing(memory_db, s, "a"), make_listing(memory_db, s, "b")
    a1 = add_success(memory_db, l1, monthly_rent_manwon=45)
    add_override(memory_db, alice, a1, "deposit_manwon", 300)
    add_failed(memory_db, l1)                         # 최신이 실패
    add_failed(memory_db, l2)                         # 실패만 있음
    rows = _rows_by_no(build_comparison(memory_db, alice, s["id"]))
    assert rows[1].analysis_status == "failed"
    assert rows[1].values["monthly_rent_manwon"] == 45      # 이전 성공 값
    assert rows[1].values["deposit_manwon"] == 300          # 이전 성공 분석의 수정값도 유지
    assert rows[2].analysis_status == "failed" and rows[2].values == {}


def test_comparison_no_analysis_has_empty_values(memory_db, make_user):
    alice = make_user()
    s = make_session(memory_db, alice)
    l1, l2 = make_listing(memory_db, s, "a"), make_listing(memory_db, s, "b")
    add_success(memory_db, l2)
    rows = _rows_by_no(build_comparison(memory_db, alice, s["id"]))
    assert rows[1].analysis_status == "none" and rows[1].values == {} and rows[1].needs_reanalysis is False


def test_comparison_needs_reanalysis_when_memo_changed(memory_db, make_user):
    alice = make_user()
    s = make_session(memory_db, alice)
    l1, l2 = make_listing(memory_db, s, "고친 메모"), make_listing(memory_db, s, "b")
    add_success(memory_db, l1, memo="예전 메모")
    add_success(memory_db, l2)
    rows = _rows_by_no(build_comparison(memory_db, alice, s["id"]))
    assert rows[1].needs_reanalysis is True and rows[1].values["monthly_rent_manwon"] == 45
    assert rows[2].needs_reanalysis is False


def test_comparison_fields_constant_order():
    assert list(FIELD_KEYS) == EXPECTED_FIELDS


def test_comparison_provider_error_marks_column_only(memory_db, make_user):
    alice = make_user()
    s = make_session(memory_db, alice)
    l1, l2 = make_listing(memory_db, s, "a"), make_listing(memory_db, s, "b")
    add_success(memory_db, l1), add_success(memory_db, l2)

    def broken(**_):
        raise RuntimeError("boom")

    register_column_provider(ColumnProvider(key="budget", title="예산", compute=broken))
    out = build_comparison(memory_db, alice, s["id"])
    assert len(out.rows) == 2
    assert all(r.columns["budget"].display == "불러오지 못함" and r.columns["budget"].tone == "muted" for r in out.rows)


def test_comparison_filters_counted_independently(memory_db, make_user):
    alice = make_user()
    s = make_session(memory_db, alice)
    ls = [make_listing(memory_db, s, x) for x in "abc"]
    for l in ls:
        add_success(memory_db, l)
    register_row_filter("only_first", lambda **kw: {ls[0]["id"]})
    register_row_filter("not_last", lambda **kw: {ls[0]["id"], ls[1]["id"]})
    out = build_comparison(memory_db, alice, s["id"], ["only_first", "not_last"])
    assert [r.listing_id for r in out.rows] == [ls[0]["id"]]
    assert out.hidden_count == {"only_first": 2, "not_last": 1}


def test_comparison_other_user_raises_404(memory_db, make_user):
    alice, bob = make_user(), make_user()
    s = make_session(memory_db, bob)
    with pytest.raises(AppError) as e:
        build_comparison(memory_db, alice, s["id"])
    assert e.value.status == 404


def test_comparison_parse_filters():
    assert parse_filters(None) == []
    assert parse_filters(" within_budget, ,within_budget,x ") == ["within_budget", "x"]
