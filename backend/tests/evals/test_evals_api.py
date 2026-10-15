"""평가 실행 API: FakePipeline·간격 0으로 실행 → 저장·지표·done, 예외 → failed,
compare_to 짝짓기, failure_counts 집계, 권한(403)."""

import datetime as dt

import pytest

from app.core.analysis_contract import SCHEMA_VERSION, build_result, register_pipeline, reset_pipeline
from app.core.config import settings
from tests.fakes import FakePipeline, failed_outcome, sample_ai_output, success_outcome


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_MIN_INTERVAL_SEC", 0)


def add_case(db, key, memo="메모", **overrides):
    expected = build_result(sample_ai_output()).model_dump(mode="json")
    expected.update(overrides)
    expected["_criteria"] = f"{key} 기준"
    return db.insert("eval_cases", {"case_key": key, "memo_text": memo, "expected_json": expected,
                                    "tags": ["money_idiom"]})[0]


def run_eval(client, version="v1", **body):
    r = client.post("/admin/eval-runs", json={"prompt_version": version, **body})
    assert r.status_code == 200, r.text
    return r.json()


def test_evals_run_saves_results_metrics_and_done(client_as, make_user, memory_db):
    admin = make_user(role="admin")
    add_case(memory_db, "c1", memo="첫 메모")
    add_case(memory_db, "c2", memo="둘째 메모", monthly_rent_manwon=50)   # 출력(45)과 달라 NUM
    pipeline = FakePipeline(success_outcome())
    register_pipeline(pipeline)

    started = run_eval(client_as(admin), "v1")
    assert started["status"] == "running" and started["case_count"] == 2

    run = memory_db.select("eval_runs", {"id": started["id"]})[0]
    assert run["status"] == "done"
    assert run["model"] == settings.GEMINI_MODEL
    assert run["thinking_level"] == settings.GEMINI_THINKING_LEVEL
    assert run["schema_version"] == SCHEMA_VERSION
    assert run["finished_at"] is not None
    assert run["missing_check_accuracy"] == pytest.approx(1.0)
    assert run["format_error_rate"] == pytest.approx(0.0)
    assert run["field_accuracy"] == pytest.approx(15 / 16)

    results = memory_db.select("eval_results", {"run_id": started["id"]})
    assert len(results) == 2
    assert sorted(r["failure_codes"] for r in results) == [[], ["NUM"]]
    assert all(r["status"] == "success" and r["output_json"]["deposit_manwon"] == 500 for r in results)

    # 사례 순서(case_key)대로, 캐시 없이, 같은 프롬프트 버전으로
    assert [c["memo_text"] for c in pipeline.calls] == ["첫 메모", "둘째 메모"]
    assert all(c["use_cache"] is False and c["cache_scope"] is None and c["prompt_version"] == "v1"
               for c in pipeline.calls)


def test_evals_run_waits_between_calls(client_as, make_user, memory_db, monkeypatch):
    import app.features.evals.runner as runner_mod

    slept = []

    async def fake_sleep(sec):
        slept.append(sec)

    monkeypatch.setattr(settings, "GEMINI_MIN_INTERVAL_SEC", 4)
    monkeypatch.setattr(runner_mod.asyncio, "sleep", fake_sleep)
    add_case(memory_db, "c1")
    add_case(memory_db, "c2")
    add_case(memory_db, "c3")
    register_pipeline(FakePipeline())
    run_eval(client_as(make_user(role="admin")))
    assert slept == [4, 4]   # 호출 사이에만


def test_evals_format_failure_is_recorded(client_as, make_user, memory_db):
    add_case(memory_db, "c1")
    register_pipeline(FakePipeline(failed_outcome("AI_FORMAT_ERROR")))
    started = run_eval(client_as(make_user(role="admin")))
    run = memory_db.select("eval_runs", {"id": started["id"]})[0]
    assert run["status"] == "done"
    assert run["format_error_rate"] == pytest.approx(1.0)
    assert run["field_accuracy"] == pytest.approx(0.0)
    assert run["hallucination_rate"] is None
    res = memory_db.select("eval_results", {"run_id": started["id"]})[0]
    assert res["status"] == "AI_FORMAT_ERROR" and res["failure_codes"] == ["FMT"] and res["output_json"] is None


def test_evals_pipeline_exception_marks_failed(client_as, make_user, memory_db):
    add_case(memory_db, "c1", memo="비밀스러운 메모 원문")
    register_pipeline(FakePipeline(raises=RuntimeError("비밀스러운 메모 원문")))
    started = run_eval(client_as(make_user(role="admin")))
    run = memory_db.select("eval_runs", {"id": started["id"]})[0]
    assert run["status"] == "failed"
    assert run["finished_at"] is not None
    assert "RuntimeError" in run["error_message"] and "c1" in run["error_message"]
    assert "비밀스러운" not in run["error_message"]   # 메모 원문을 남기지 않는다


def test_evals_create_without_pipeline_is_503_and_no_run(client_as, make_user, memory_db):
    add_case(memory_db, "c1")
    c = client_as(make_user(role="admin"))
    reset_pipeline()   # 앱을 만들 때 P2 hooks가 실제 Gemini 파이프라인을 등록하므로 '미등록' 상태를 다시 만든다
    r = c.post("/admin/eval-runs", json={"prompt_version": "v1"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "CONFIG_MISSING"
    assert memory_db.select("eval_runs") == []


def test_evals_create_without_cases_is_409(client_as, make_user):
    register_pipeline(FakePipeline())
    r = client_as(make_user(role="admin")).post("/admin/eval-runs", json={"prompt_version": "v1"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "EVAL_CASES_EMPTY"


def test_evals_create_with_unknown_case_key_is_422(client_as, make_user, memory_db):
    add_case(memory_db, "c1")
    register_pipeline(FakePipeline())
    r = client_as(make_user(role="admin")).post("/admin/eval-runs",
                                                json={"prompt_version": "v1", "case_keys": ["c1", "없음"]})
    assert r.status_code == 422
    assert r.json()["error"]["detail"]["unknown_case_keys"] == ["없음"]


def test_evals_create_with_case_keys_runs_only_those(client_as, make_user, memory_db):
    add_case(memory_db, "c1")
    add_case(memory_db, "c2")
    register_pipeline(FakePipeline())
    started = run_eval(client_as(make_user(role="admin")), case_keys=["c2"])
    assert started["case_count"] == 1
    assert len(memory_db.select("eval_results", {"run_id": started["id"]})) == 1


def test_evals_create_blocked_while_recent_run_is_running(client_as, make_user, memory_db):
    add_case(memory_db, "c1")
    register_pipeline(FakePipeline())
    memory_db.insert("eval_runs", {"prompt_version": "v1", "model": "m", "schema_version": "1", "status": "running"})
    r = client_as(make_user(role="admin")).post("/admin/eval-runs", json={"prompt_version": "v2"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "EVAL_RUN_IN_PROGRESS"


def test_evals_stale_running_run_does_not_block():
    from app.features.evals import runner
    from tests.fakes import MemoryDatabase

    db = MemoryDatabase()
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=runner.STALE_RUNNING_MINUTES + 1)).isoformat()
    db.insert("eval_runs", {"prompt_version": "v1", "model": "m", "schema_version": "1", "status": "running",
                            "created_at": old})
    runner.ensure_no_active_run(db)   # 예외 없음


def test_evals_list_includes_failure_counts(client_as, make_user, memory_db):
    admin = make_user(role="admin")
    add_case(memory_db, "c1", monthly_rent_manwon=50)            # NUM
    add_case(memory_db, "c2", maintenance_fee_manwon=None)       # NUM + HAL
    add_case(memory_db, "c3")
    register_pipeline(FakePipeline())
    started = run_eval(client_as(admin))

    r = client_as(admin).get("/admin/eval-runs")
    assert r.status_code == 200
    run = next(x for x in r.json() if x["id"] == started["id"])
    assert run["status"] == "done"
    assert run["failure_counts"] == {"NUM": 2, "HAL": 1, "MIS": 0, "CHK": 0, "FMT": 0}
    assert run["result_count"] == 3 and run["error_case_count"] == 0


def test_evals_results_compare_to_pairs_by_case(client_as, make_user, memory_db):
    admin = make_user(role="admin")
    c = client_as(admin)
    add_case(memory_db, "c1")
    add_case(memory_db, "c2")
    register_pipeline(FakePipeline(success_outcome(sample_ai_output(monthly_rent_manwon=50))))
    v1 = run_eval(c, "v1")
    register_pipeline(FakePipeline(success_outcome()))
    v2 = run_eval(c, "v2")

    r = c.get(f"/admin/eval-runs/{v2['id']}/results", params={"compare_to": v1["id"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["run"]["prompt_version"] == "v2" and body["compare_run"]["prompt_version"] == "v1"
    assert body["condition_mismatches"] == []
    assert [x["case_key"] for x in body["results"]] == ["c1", "c2"]
    first = body["results"][0]
    assert first["memo_text"] == "메모"
    assert first["criteria"] == "c1 기준"
    assert "_criteria" not in first["expected_json"]
    assert first["output_json"]["monthly_rent_manwon"] == 45
    assert first["compare_output_json"]["monthly_rent_manwon"] == 50
    assert first["failure_codes"] == [] and first["compare_failure_codes"] == ["NUM"]
    assert first["field_matches"]["monthly_rent_manwon"] is True
    assert first["compare_field_matches"]["monthly_rent_manwon"] is False
    assert first["mixed_listings_match"] is True
    # 같은 사례끼리 짝지어졌는지
    v1_case_ids = {x["case_id"] for x in memory_db.select("eval_results", {"run_id": v1["id"]})}
    assert {x["case_id"] for x in body["results"]} == v1_case_ids


def test_evals_results_reports_case_list_mismatch(client_as, make_user, memory_db):
    admin = make_user(role="admin")
    c = client_as(admin)
    add_case(memory_db, "c1")
    add_case(memory_db, "c2")
    register_pipeline(FakePipeline())
    v1 = run_eval(c, "v1", case_keys=["c1"])
    v2 = run_eval(c, "v2")
    body = c.get(f"/admin/eval-runs/{v2['id']}/results", params={"compare_to": v1["id"]}).json()
    assert body["condition_mismatches"] == ["case_list"]
    c2 = next(x for x in body["results"] if x["case_key"] == "c2")
    assert c2["compare_status"] == "missing"


def test_evals_results_reports_model_mismatch(client_as, make_user, memory_db, monkeypatch):
    admin = make_user(role="admin")
    c = client_as(admin)
    add_case(memory_db, "c1")
    register_pipeline(FakePipeline())
    v1 = run_eval(c, "v1")
    monkeypatch.setattr(settings, "GEMINI_MODEL", "other-model")
    v2 = run_eval(c, "v2")
    body = c.get(f"/admin/eval-runs/{v2['id']}/results", params={"compare_to": v1["id"]}).json()
    assert body["condition_mismatches"] == ["model"]


def test_evals_results_without_compare(client_as, make_user, memory_db):
    admin = make_user(role="admin")
    add_case(memory_db, "c1")
    register_pipeline(FakePipeline())
    v1 = run_eval(client_as(admin))
    body = client_as(admin).get(f"/admin/eval-runs/{v1['id']}/results").json()
    assert body["compare_run"] is None and body["condition_mismatches"] == []
    assert body["results"][0]["compare_status"] is None


def test_evals_results_unknown_run_is_404(client_as, make_user):
    c = client_as(make_user(role="admin"))
    assert c.get("/admin/eval-runs/not-a-uuid/results").status_code == 404
    r = c.get("/admin/eval-runs/00000000-0000-0000-0000-000000000000/results")
    assert r.status_code == 404 and r.json()["error"]["code"] == "EVAL_RUN_NOT_FOUND"


@pytest.mark.parametrize("method,path", [
    ("get", "/admin/eval-runs"),
    ("post", "/admin/eval-runs"),
    ("get", "/admin/eval-runs/00000000-0000-0000-0000-000000000000/results"),
])
def test_evals_normal_user_is_403(client_as, make_user, memory_db, method, path):
    register_pipeline(FakePipeline())
    add_case(memory_db, "c1")
    c = client_as(make_user())
    kwargs = {"json": {"prompt_version": "v1"}} if method == "post" else {}
    r = getattr(c, method)(path, **kwargs)
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN"
    assert memory_db.select("eval_runs") == []


def test_evals_anonymous_is_401(client_as):
    assert client_as(None).get("/admin/eval-runs").status_code == 401
