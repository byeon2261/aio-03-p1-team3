"""기준 세트 적재: 예시 파일 적재, 초안 파일(expected_json null) 거부, 검증 실패 거부, 초안 구성."""

import json
from collections import Counter
from pathlib import Path

from app.core.analysis_contract import AnalysisResult
from app.features.evals.cases import load_cases, read_case_file
from app.features.evals.metrics import CRITERIA_KEY

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = REPO_ROOT / "eval" / "eval_cases.example.json"
DRAFT = REPO_ROOT / "eval" / "eval_cases.draft.json"


def test_evals_example_file_loads_and_reloads(memory_db):
    report = load_cases(memory_db, read_case_file(EXAMPLE))
    assert report.rejected == []
    assert len(report.inserted) == 3
    rows = memory_db.select("eval_cases", order_by="case_key")
    assert len(rows) == 3
    for row in rows:
        AnalysisResult.model_validate({k: v for k, v in row["expected_json"].items() if k != CRITERIA_KEY})
        assert row["expected_json"][CRITERIA_KEY]
        assert row["tags"]

    again = load_cases(memory_db, read_case_file(EXAMPLE))   # case_key 기준 갱신
    assert again.inserted == [] and len(again.updated) == 3
    assert len(memory_db.select("eval_cases")) == 3


def test_evals_example_file_says_not_answer_set():
    assert "정답 세트 아님" in EXAMPLE.read_text(encoding="utf-8")


def test_evals_draft_file_is_rejected(memory_db):
    report = load_cases(memory_db, read_case_file(DRAFT))
    assert report.inserted == [] and report.updated == []
    assert len(report.rejected) == 20
    assert all("expected_json" in reason for _, reason in report.rejected)
    assert memory_db.select("eval_cases") == []


def test_evals_draft_covers_required_types():
    cases = read_case_file(DRAFT)
    assert len(cases) == 20
    assert len({c["case_key"] for c in cases}) == 20
    assert all(c["expected_json"] is None and c["memo_text"] and c["criteria"] for c in cases)
    tags = Counter(t for c in cases for t in c["tags"])
    for t in ("money_idiom", "negation", "explicit_unchecked", "no_maintenance_fee", "vague",
              "mixed_listings", "conflict", "injection"):
        assert tags[t] >= 2, t


def test_evals_invalid_expected_is_rejected_without_memo_text(memory_db):
    bad = json.loads(EXAMPLE.read_text(encoding="utf-8"))["cases"][0]
    bad = {**bad, "case_key": "bad", "memo_text": "아주 비밀스러운 메모",
           "expected_json": {**bad["expected_json"], "missing_checks": []}}   # 네 목록이 CHECKLIST를 못 덮음
    report = load_cases(memory_db, [bad])
    assert report.inserted == []
    key, reason = report.rejected[0]
    assert key == "bad" and "AnalysisResult" in reason
    assert "비밀스러운" not in reason


def test_evals_duplicate_key_in_file_is_rejected(memory_db):
    case = json.loads(EXAMPLE.read_text(encoding="utf-8"))["cases"][0]
    report = load_cases(memory_db, [case, case])
    assert len(report.inserted) == 1 and len(report.rejected) == 1


def test_evals_load_script_exit_codes(memory_db, capsys):
    import importlib.util

    spec = importlib.util.spec_from_file_location("load_eval_cases",
                                                  REPO_ROOT / "backend" / "scripts" / "load_eval_cases.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main([str(EXAMPLE)], db=memory_db) == 0
    assert mod.main([str(DRAFT)], db=memory_db) == 1
    out = capsys.readouterr().out
    assert "money_01" in out and "거부 20건" in out
