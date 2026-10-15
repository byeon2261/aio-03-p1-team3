"""평가 실행(터미널). backend 폴더에서 실행한다. POST /admin/eval-runs와 같은 일을 한다.

    python scripts/run_eval.py v1
    python scripts/run_eval.py v2 --cases money_01,neg_01

필요: backend/.env의 SUPABASE_URL·SUPABASE_SECRET_KEY·GEMINI_API_KEY, P2 분석 파이프라인(hooks.py에서 등록).
사례 사이에 GEMINI_MIN_INTERVAL_SEC(기본 4초)만큼 쉰다. 20건이면 1~3분쯤 걸린다.
종료 코드: done이면 0, failed면 1, 시작하지 못하면 2.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.analysis_contract import get_pipeline  # noqa: E402
from app.core.db import get_admin_db  # noqa: E402
from app.core.errors import AppError  # noqa: E402
from app.features.evals import runner  # noqa: E402
from app.features.evals.metrics import FAILURE_CODES  # noqa: E402

METRIC_LABELS = (
    ("field_accuracy", "필드 정확도"),
    ("hallucination_rate", "환각률"),
    ("missing_check_accuracy", "빠진 항목 정확도"),
    ("format_error_rate", "형식 실패율"),
)


def _pct(v) -> str:
    return "계산 안 됨" if v is None else f"{v * 100:.1f}%"


def _progress(done: int, total: int, case: dict, score) -> None:
    codes = ",".join(score.failure_codes) or "-"
    print(f"  [{done}/{total}] {case.get('case_key')}  {score.status}  실패유형={codes}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="평가 실행(개선 전후 비교용)")
    parser.add_argument("prompt_version", help="프롬프트 버전(예: v1, v2)")
    parser.add_argument("--cases", default=None, help="쉼표로 구분한 case_key(생략하면 전체)")
    args = parser.parse_args(argv)
    case_keys = [k for k in args.cases.split(",")] if args.cases else None

    try:
        from app.main import create_app   # features/*/hooks.py를 읽어 파이프라인을 등록한다

        create_app()
        db = get_admin_db()
        pipeline = get_pipeline()
        cases = runner.select_cases(db, case_keys)
        runner.ensure_no_active_run(db)
        run = runner.create_run(db, args.prompt_version, cases)
    except AppError as exc:
        print(f"[시작 못 함] {exc.code}: {exc.message} {exc.detail or ''}")
        return 2

    print(f"실행 {run['id']} 시작 — 프롬프트 {args.prompt_version}, 모델 {run['model']}, "
          f"thinking {run.get('thinking_level')}, 스키마 {run['schema_version']}, 사례 {len(cases)}건")
    final = asyncio.run(runner.execute_run(db, str(run["id"]), cases, args.prompt_version,
                                           pipeline=pipeline, on_progress=_progress))
    print(f"상태: {final.get('status')}")
    if final.get("status") != "done":
        print(f"오류: {final.get('error_message')}")
        return 1
    for key, label in METRIC_LABELS:
        print(f"  {label}: {_pct(final.get(key))}")
    results = db.select("eval_results", {"run_id": str(run["id"])})
    counts = {c: sum(1 for r in results if c in (r.get("failure_codes") or [])) for c in FAILURE_CODES}
    print("  실패 유형(사례 수): " + ", ".join(f"{c} {n}" for c, n in counts.items()) + ", CLS 사람 판단")
    return 0


if __name__ == "__main__":
    sys.exit(main())
