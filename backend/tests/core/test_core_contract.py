"""소유 확인, 분석 계약, 값 계산, 읽기 도우미, 이벤트·등록부."""

import pytest

from app.core import events, registry
from app.core.analysis_contract import (
    CHECKLIST, AnalysisResult, CheckItem, build_result, get_pipeline, memo_hash, needs_reanalysis,
    register_pipeline,
)
from app.core.errors import AppError
from app.core.ownership import get_owned_analysis, get_owned_listing, get_owned_photo, get_owned_session
from app.core.repo import field_overrides, latest_analysis, latest_rating, list_listings
from app.core.values import effective_values, monthly_cost
from tests.fakes import FakePipeline, sample_ai_output


def _chain(db, user):
    s = db.insert("tour_sessions", {"profile_id": user.profile_id, "title": "t"})[0]
    l = db.insert("listings", {"session_id": s["id"], "memo_text": "m"})[0]
    a = db.insert("analyses", {"listing_id": l["id"], "status": "success", "memo_hash": memo_hash("m"),
                               "schema_version": "1", "prompt_version": "v1", "model": "x"})[0]
    p = db.insert("photos", {"listing_id": l["id"], "profile_id": user.profile_id, "storage_path": f"{l['id']}.jpg",
                             "content_type": "image/jpeg", "size_bytes": 3})[0]
    return s, l, a, p


def test_core_owned_resources_and_404_for_others(memory_db, make_user):
    alice, bob = make_user(), make_user()
    s, l, a, p = _chain(memory_db, alice)
    assert get_owned_session(memory_db, alice, s["id"])["id"] == s["id"]
    assert get_owned_listing(memory_db, alice, l["id"])["session"]["id"] == s["id"]
    assert get_owned_analysis(memory_db, alice, a["id"])["listing"]["session"]["id"] == s["id"]
    assert get_owned_photo(memory_db, alice, p["id"])["listing"]["id"] == l["id"]
    cases = [(get_owned_session, s, "SESSION_NOT_FOUND"), (get_owned_listing, l, "LISTING_NOT_FOUND"),
             (get_owned_analysis, a, "ANALYSIS_NOT_FOUND"), (get_owned_photo, p, "PHOTO_NOT_FOUND")]
    for fn, row, code in cases:
        with pytest.raises(AppError) as e:
            fn(memory_db, bob, row["id"])          # 타인 것
        assert (e.value.status, e.value.code) == (404, code)
        with pytest.raises(AppError) as e:
            fn(memory_db, alice, "not-a-uuid")     # 잘못된 id
        assert e.value.status == 404


def test_core_build_result_partitions_checklist():
    ai = sample_ai_output(checks=[
        CheckItem(item="채광", status="confirmed", evidence="밝음"),
        CheckItem(item="수압", status="unchecked", evidence="확인 못함"),
        CheckItem(item="소음", status="ambiguous", evidence="좀?"),
        CheckItem(item="보안", status="confirmed", evidence="도어락"),
        CheckItem(item="보안", status="unchecked", evidence="CCTV 못 봄"),   # 상태 충돌 → 모호
    ])
    r = build_result(ai)
    assert r.confirmed_checks == ["채광"]
    assert r.unchecked == ["수압"]
    assert r.ambiguous_checks == ["소음", "보안"]
    assert set(r.missing_checks) == set(CHECKLIST) - {"채광", "수압", "소음", "보안"}
    with pytest.raises(ValueError):
        AnalysisResult(**{**r.model_dump(), "unchecked": ["수압", "채광"]})   # 겹치면 거부


def test_core_memo_hash_and_needs_reanalysis():
    assert memo_hash("  메모 ") == memo_hash("메모")
    listing = {"memo_text": "새 메모"}
    assert needs_reanalysis(listing, None) is False
    assert needs_reanalysis(listing, {"memo_hash": memo_hash("새 메모")}) is False
    assert needs_reanalysis(listing, {"memo_hash": memo_hash("옛 메모")}) is True


def test_core_values_effective_and_monthly_cost():
    v = effective_values({"monthly_rent_manwon": 45, "maintenance_fee_manwon": None, "label": "a"},
                         {"maintenance_fee_manwon": 5, "label": "무시됨"})
    assert v["maintenance_fee_manwon"] == 5 and v["label"] == "a"
    assert monthly_cost(v) == 50
    assert monthly_cost({"monthly_rent_manwon": 45, "maintenance_fee_manwon": None}) is None
    assert monthly_cost({"monthly_rent_manwon": 0, "maintenance_fee_manwon": 0}) == 0


def test_core_repo_helpers(memory_db, make_user):
    alice = make_user()
    s, l, a, _ = _chain(memory_db, alice)
    memory_db.insert("listings", {"session_id": s["id"]})
    assert [x["listing_no"] for x in list_listings(memory_db, s["id"])] == [1, 2]
    failed = memory_db.insert("analyses", {"listing_id": l["id"], "status": "failed", "memo_hash": "h",
                                           "schema_version": "1", "prompt_version": "v1", "model": "x"})[0]
    assert latest_analysis(memory_db, l["id"])["id"] == a["id"]
    assert latest_analysis(memory_db, l["id"], status=None)["id"] == failed["id"]
    fb = lambda **kw: memory_db.insert("feedback", {"analysis_id": a["id"], "profile_id": alice.profile_id, **kw})
    fb(field_name="deposit_manwon", corrected_value=400)
    fb(field_name="deposit_manwon", corrected_value=450)
    fb(field_name="floor", corrected_value="2층")
    fb(field_name="floor", corrected_value=None)          # 수정 취소
    assert field_overrides(memory_db, a["id"]) == {"deposit_manwon": 450}
    assert latest_rating(memory_db, a["id"]) is None
    fb(rating="up")
    fb(rating="down", reason="amount")
    assert latest_rating(memory_db, a["id"]) == "down"


def test_core_events_emit_raises_and_dedupes():
    calls = []

    def handler(**kw):
        calls.append(kw)

    events.on("listing.before_delete", handler)
    events.on("listing.before_delete", handler)      # 다시 등록해도 한 번만
    events.emit("listing.before_delete", db=None, user=None, listing={"id": "x"})
    assert len(calls) == 1

    def failing(**kw):
        raise AppError(503, "CLEANUP_FAILED", "정리 실패")

    events.on("listing.before_delete", failing)
    with pytest.raises(AppError):
        events.emit("listing.before_delete", db=None, user=None, listing={"id": "x"})
    with pytest.raises(ValueError):
        events.on("unknown.event", handler)


def test_core_registry_and_pipeline():
    from app.core.registry import ColumnProvider, ColumnValue

    registry.register_column_provider(ColumnProvider("budget", "예산", lambda **kw: {"l1": ColumnValue(display="OK")}))
    registry.register_row_filter("within_budget", lambda **kw: {"l1"})
    assert [p.key for p in registry.get_column_providers()] == ["budget"]
    assert registry.get_row_filter("within_budget")() == {"l1"}
    assert registry.get_row_filter("nope") is None
    with pytest.raises(AppError) as e:
        get_pipeline()
    assert e.value.code == "CONFIG_MISSING"
    p = FakePipeline()
    register_pipeline(p)
    assert get_pipeline() is p


def test_core_overrides_from_rows_action_rules():
    """I2(0008): set+null = 메모에 없음(키 남음), revert = 수정 취소(키 빠짐), action 없는 옛 행은 null = 취소."""
    from app.core.repo import is_revert, overrides_from_rows
    from app.core.values import effective_values

    rows = [
        {"field_name": "deposit_manwon", "corrected_value": 300, "action": "set"},
        {"field_name": "monthly_rent_manwon", "corrected_value": None, "action": "set"},
        {"field_name": "floor", "corrected_value": "3층", "action": "set"},
        {"field_name": "floor", "corrected_value": None, "action": "revert"},
        {"field_name": "transit", "corrected_value": "버스"},
        {"field_name": "transit", "corrected_value": None},                 # 옛 행: 취소
        {"field_name": None, "corrected_value": None, "rating": "up"},      # 전체 평가
    ]
    ov = overrides_from_rows(rows)
    assert ov == {"deposit_manwon": 300, "monthly_rent_manwon": None}
    assert is_revert({"corrected_value": None}) and not is_revert({"corrected_value": None, "action": "set"})
    vals = effective_values({"deposit_manwon": 500, "monthly_rent_manwon": 45, "floor": "2층"}, ov)
    assert vals == {"deposit_manwon": 300, "monthly_rent_manwon": None, "floor": "2층"}
