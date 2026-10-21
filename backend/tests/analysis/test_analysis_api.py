"""분석 API: 저장·오류 응답·로그 필드·캐시·소유 확인·latest·previous_overrides."""

from app.core.analysis_contract import get_pipeline, register_pipeline
from app.features.analysis.pipeline import GeminiAnalysisPipeline
from tests.analysis.conftest import (
    EXAMPLE_MEMO, FakeAiClient, example_ai_text, logs_for, rate_limit_error, timeout_error,
)
from tests.fakes import FakePipeline, failed_outcome


def _post(c, lid, **body):
    return c.post(f"/listings/{lid}/analyses", json=body or None)


def _rows(memory_db, lid):
    return memory_db.select("analyses", {"listing_id": lid}, order_by="created_at")


def _feedback(memory_db, user, analysis_id, field, value, action=None):
    row = {"analysis_id": analysis_id, "profile_id": user.profile_id, "field_name": field, "corrected_value": value}
    if action is not None:
        row["action"] = action
    memory_db.insert("feedback", row)


# ------------------------------------------------------------------ POST 성공·형식 실패
def test_analysis_api_success_saves_row_and_log(client_as, make_user, make_listing, memory_db, use_fake_ai):
    alice = make_user()
    listing = make_listing(alice)
    c = client_as(alice)
    use_fake_ai(FakeAiClient(latency_ms=150))
    r = c.post(f"/listings/{listing['id']}/analyses")          # 본문 생략 가능
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "success" and body["listing_id"] == listing["id"]
    assert body["fields"]["deposit_manwon"] == {"ai_value": 500, "user_value": None, "value": 500, "edited": False}
    assert body["fields"]["label"]["value"] == "2번 집"
    assert body["confirmed_checks"] == ["채광", "곰팡이", "교통"] and body["unchecked"] == ["수압"]
    assert body["missing_checks"] == ["소음", "난방", "층수", "옵션", "보안"]
    assert body["needs_reanalysis"] is False and body["previous_overrides"] == {}
    rows = _rows(memory_db, listing["id"])
    assert len(rows) == 1 and rows[0]["status"] == "success" and rows[0]["error_code"] is None
    assert rows[0]["raw_output"].startswith("--- attempt 1 ---")
    assert rows[0]["schema_version"] == "1" and rows[0]["thinking_level"] == "minimal"
    assert rows[0]["ai_latency_ms"] == 150 and rows[0]["latency_ms"] is not None
    log = logs_for(memory_db, "/analyses")[-1]
    assert log["status_code"] == 200 and log["ai_latency_ms"] == 150
    assert log["prompt_version"] == "v3" and log["cache_hit"] is False and log["error_code"] is None


def test_analysis_api_format_retry_then_success(client_as, make_user, make_listing, memory_db, use_fake_ai):
    alice = make_user()
    listing = make_listing(alice)
    c = client_as(alice)
    ai = use_fake_ai(FakeAiClient("{oops", example_ai_text())).ai_client
    r = _post(c, listing["id"])
    assert r.status_code == 200 and len(ai.calls) == 2
    raw = _rows(memory_db, listing["id"])[0]["raw_output"]
    assert raw.startswith("--- attempt 1 ---\n{oops\n--- attempt 2 ---\n")


def test_analysis_api_two_format_failures_502(client_as, make_user, make_listing, memory_db, use_fake_ai):
    alice = make_user()
    listing = make_listing(alice)
    c = client_as(alice)
    use_fake_ai(FakeAiClient("{oops", "[]"))
    r = _post(c, listing["id"])
    assert r.status_code == 502
    err = r.json()["error"]
    assert err["code"] == "AI_FORMAT_ERROR" and err["detail"]["analysis_id"]
    rows = _rows(memory_db, listing["id"])
    assert len(rows) == 1 and rows[0]["status"] == "failed" and rows[0]["error_code"] == "FMT"
    assert rows[0]["result_json"] is None
    assert rows[0]["raw_output"] == "--- attempt 1 ---\n{oops\n--- attempt 2 ---\n[]"
    log = logs_for(memory_db, "/analyses")[-1]
    assert log["status_code"] == 502 and log["error_code"] == "FMT"
    # 메모 원문은 로그·오류 응답에 없다
    assert "신림역" not in r.text and "신림역" not in str(log)
    # 실패 후 latest는 실패 행을 보여 준다(화면의 '다시 시도')
    latest = c.get(f"/listings/{listing['id']}/analyses/latest").json()
    assert latest["status"] == "failed" and latest["error_code"] == "FMT" and latest["fields"] == {}


def test_analysis_api_timeout_504_and_rate_limit_429(client_as, make_user, make_listing, memory_db, use_fake_ai):
    alice = make_user()
    listing = make_listing(alice)
    c = client_as(alice)
    use_fake_ai(FakeAiClient(timeout_error()))
    r = _post(c, listing["id"])
    assert r.status_code == 504 and r.json()["error"]["code"] == "AI_TIMEOUT"
    use_fake_ai(FakeAiClient(rate_limit_error()))
    r = _post(c, listing["id"])
    assert r.status_code == 429 and r.json()["error"]["code"] == "AI_RATE_LIMITED"
    rows = _rows(memory_db, listing["id"])
    assert [x["error_code"] for x in rows] == ["AI_TIMEOUT", "AI_RATE_LIMITED"]
    assert [x["error_code"] for x in logs_for(memory_db, "/analyses")] == ["AI_TIMEOUT", "AI_RATE_LIMITED"]


def test_analysis_api_contract_fake_pipeline_failure_maps_to_fmt(client_as, make_user, make_listing, memory_db):
    """다른 대화창 테스트처럼 FakePipeline을 먼저 등록해도 hooks가 덮지 않는다."""
    alice = make_user()
    listing = make_listing(alice)
    fake = FakePipeline(failed_outcome("AI_FORMAT_ERROR"))
    register_pipeline(fake)
    c = client_as(alice)
    assert get_pipeline() is fake
    r = _post(c, listing["id"])
    assert r.status_code == 502 and r.json()["error"]["code"] == "AI_FORMAT_ERROR"
    assert fake.calls[0]["cache_scope"] == alice.auth_user_id and fake.calls[0]["prompt_version"] == "v3"
    assert _rows(memory_db, listing["id"])[0]["error_code"] == "FMT"
    assert logs_for(memory_db, "/analyses")[-1]["error_code"] == "FMT"


def test_analysis_api_hooks_register_real_pipeline(client_as):
    client_as(None)
    assert isinstance(get_pipeline(), GeminiAnalysisPipeline)


# ------------------------------------------------------------------ 캐시
def test_analysis_api_cache_hit_saves_new_row(client_as, make_user, make_listing, memory_db, use_fake_ai):
    alice, bob = make_user(), make_user()
    l1 = make_listing(alice)
    c = client_as(alice)
    ai = use_fake_ai(FakeAiClient()).ai_client
    assert _post(c, l1["id"]).status_code == 200
    r2 = _post(c, l1["id"])
    assert r2.status_code == 200 and len(ai.calls) == 1
    rows = _rows(memory_db, l1["id"])
    assert len(rows) == 2 and rows[1]["ai_latency_ms"] is None
    assert rows[1]["raw_output"] == rows[0]["raw_output"]
    logs = logs_for(memory_db, "/analyses")
    assert [x["cache_hit"] for x in logs] == [False, True]
    # use_cache=false면 다시 부른다
    assert _post(c, l1["id"], use_cache=False).status_code == 200 and len(ai.calls) == 2
    # 다른 사용자는 같은 메모라도 적중하지 않는다(cache_scope)
    l2 = make_listing(bob, memo=EXAMPLE_MEMO)
    assert _post(client_as(bob), l2["id"]).status_code == 200 and len(ai.calls) == 3


# ------------------------------------------------------------------ 소유·입력 검사
def test_analysis_api_other_users_listing_404(client_as, make_user, make_listing, memory_db, use_fake_ai):
    alice, bob = make_user(), make_user()
    listing = make_listing(bob)
    c = client_as(alice)
    ai = use_fake_ai(FakeAiClient()).ai_client
    r = _post(c, listing["id"])
    assert r.status_code == 404 and r.json()["error"]["code"] == "LISTING_NOT_FOUND"
    assert c.get(f"/listings/{listing['id']}/analyses/latest").status_code == 404
    assert c.get("/listings/not-a-uuid/analyses/latest").status_code == 404
    assert ai.calls == [] and _rows(memory_db, listing["id"]) == []


def test_analysis_api_requires_login(client_as, make_user, make_listing):
    listing = make_listing(make_user())
    r = client_as(None).post(f"/listings/{listing['id']}/analyses")
    assert r.status_code == 401


def test_analysis_api_empty_memo_422(client_as, make_user, make_listing, use_fake_ai):
    alice = make_user()
    listing = make_listing(alice, memo="   ")
    c = client_as(alice)
    ai = use_fake_ai(FakeAiClient()).ai_client
    r = _post(c, listing["id"])
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR" and ai.calls == []


# ------------------------------------------------------------------ latest·수정값·재분석
def test_analysis_api_latest_404_when_none(client_as, make_user, make_listing):
    alice = make_user()
    listing = make_listing(alice)
    r = client_as(alice).get(f"/listings/{listing['id']}/analyses/latest")
    assert r.status_code == 404 and r.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"


def test_analysis_api_latest_shows_user_value(client_as, make_user, make_listing, memory_db, use_fake_ai):
    alice = make_user()
    listing = make_listing(alice)
    c = client_as(alice)
    use_fake_ai(FakeAiClient())
    aid = _post(c, listing["id"]).json()["id"]
    _feedback(memory_db, alice, aid, "monthly_rent_manwon", 50)
    _feedback(memory_db, alice, aid, "floor", "3층")
    _feedback(memory_db, alice, aid, "floor", None)                     # 수정 취소
    memory_db.insert("feedback", {"analysis_id": aid, "profile_id": alice.profile_id, "rating": "up"})
    body = c.get(f"/listings/{listing['id']}/analyses/latest").json()
    assert body["id"] == aid
    assert body["fields"]["monthly_rent_manwon"] == {"ai_value": 45, "user_value": 50, "value": 50, "edited": True}
    assert body["fields"]["floor"] == {"ai_value": None, "user_value": None, "value": None, "edited": False}
    assert body["rating"] == "up"


def test_analysis_api_needs_reanalysis_after_memo_change(client_as, make_user, make_listing, memory_db, use_fake_ai):
    alice = make_user()
    listing = make_listing(alice)
    c = client_as(alice)
    use_fake_ai(FakeAiClient())
    _post(c, listing["id"])
    memory_db.update("listings", {"id": listing["id"]}, {"memo_text": EXAMPLE_MEMO + " 관리비는 다시 확인"})
    assert c.get(f"/listings/{listing['id']}/analyses/latest").json()["needs_reanalysis"] is True


def test_analysis_api_previous_overrides(client_as, make_user, make_listing, memory_db, use_fake_ai):
    alice = make_user()
    listing = make_listing(alice)
    c = client_as(alice)
    lid = listing["id"]
    use_fake_ai(FakeAiClient())
    a1 = _post(c, lid).json()["id"]
    _feedback(memory_db, alice, a1, "monthly_rent_manwon", 50)
    _feedback(memory_db, alice, a1, "maintenance_includes", ["수도", "인터넷"])
    _feedback(memory_db, alice, a1, "direction", "남향")                         # 새 AI 값과 같아질 필드

    # 메모를 고치고 재분석: 새 AI는 관리비 포함을 순서만 바꿔 ["인터넷", "수도"]로 냄
    memory_db.update("listings", {"id": lid}, {"memo_text": EXAMPLE_MEMO + " 수도도 포함"})
    use_fake_ai(FakeAiClient(example_ai_text(maintenance_includes=["인터넷", "수도"])))
    r2 = _post(c, lid).json()
    assert r2["previous_overrides"] == {"monthly_rent_manwon": 50}       # 목록은 순서 무시, 같은 값은 빠짐
    a2 = r2["id"]
    assert c.get(f"/listings/{lid}/analyses/latest").json()["previous_overrides"] == {"monthly_rent_manwon": 50}

    # P3 화면이 피드백 API로 옮긴 뒤에는 빈 dict
    _feedback(memory_db, alice, a2, "monthly_rent_manwon", 50)
    assert c.get(f"/listings/{lid}/analyses/latest").json()["previous_overrides"] == {}


def test_analysis_api_previous_overrides_skips_analyses_without_edits(client_as, make_user, make_listing, memory_db,
                                                                      use_fake_ai):
    alice = make_user()
    listing = make_listing(alice)
    c = client_as(alice)
    lid = listing["id"]
    use_fake_ai(FakeAiClient())
    a1 = _post(c, lid, use_cache=False).json()["id"]
    _feedback(memory_db, alice, a1, "deposit_manwon", 1000)
    _post(c, lid, use_cache=False)                            # 수정값 없는 성공 분석
    use_fake_ai(FakeAiClient("{bad"))
    _post(c, lid, use_cache=False)                            # 실패 분석
    use_fake_ai(FakeAiClient())
    body = _post(c, lid, use_cache=False).json()
    assert body["previous_overrides"] == {"deposit_manwon": 1000}


# ------------------------------------------------------------------ I2: '메모에 없음'(action set + null)
def test_analysis_api_memo_none_override_is_edited_null(client_as, make_user, make_listing, memory_db, use_fake_ai):
    alice = make_user()
    listing = make_listing(alice)
    c = client_as(alice)
    use_fake_ai(FakeAiClient())
    aid = _post(c, listing["id"]).json()["id"]
    _feedback(memory_db, alice, aid, "monthly_rent_manwon", None, action="set")       # 메모에 없음
    _feedback(memory_db, alice, aid, "transit", "버스 10분", action="set")
    _feedback(memory_db, alice, aid, "transit", None, action="revert")                # AI 값으로 되돌림
    fields = c.get(f"/listings/{listing['id']}/analyses/latest").json()["fields"]
    assert fields["monthly_rent_manwon"] == {"ai_value": 45, "user_value": None, "value": None, "edited": True}
    assert fields["transit"]["edited"] is False and fields["transit"]["value"] == fields["transit"]["ai_value"]


def test_analysis_api_previous_overrides_keeps_memo_none(client_as, make_user, make_listing, memory_db, use_fake_ai):
    alice = make_user()
    listing = make_listing(alice)
    c = client_as(alice)
    lid = listing["id"]
    use_fake_ai(FakeAiClient())
    a1 = _post(c, lid, use_cache=False).json()["id"]
    _feedback(memory_db, alice, a1, "monthly_rent_manwon", None, action="set")
    r2 = _post(c, lid, use_cache=False).json()
    assert r2["previous_overrides"] == {"monthly_rent_manwon": None}
    _feedback(memory_db, alice, r2["id"], "monthly_rent_manwon", None, action="set")
    assert c.get(f"/listings/{lid}/analyses/latest").json()["previous_overrides"] == {}
