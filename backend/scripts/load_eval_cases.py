"""기준 세트 적재. backend 폴더에서 실행한다.

    python scripts/load_eval_cases.py ../eval/eval_cases.json
    python scripts/load_eval_cases.py ../eval/eval_cases.example.json   # 형식 확인용 3건

eval_cases에 case_key 기준으로 넣거나 갱신한다(secret key 필요: backend/.env의 SUPABASE_URL·SUPABASE_SECRET_KEY).
expected_json이 비었거나 AnalysisResult로 검증되지 않는 사례는 넣지 않고 case_key와 이유를 출력한다.
종료 코드: 모두 들어가면 0, 거부된 사례가 있으면 1, 파일·설정 문제면 2.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.db import get_admin_db  # noqa: E402
from app.core.errors import AppError  # noqa: E402
from app.features.evals.cases import load_cases, read_case_file  # noqa: E402


def main(argv: list[str] | None = None, db=None) -> int:
    parser = argparse.ArgumentParser(description="평가 사례(eval_cases) 적재")
    parser.add_argument("path", help="사례 JSON 파일 경로")
    args = parser.parse_args(argv)

    try:
        items = read_case_file(args.path)
    except (OSError, ValueError) as exc:
        print(f"[오류] 파일을 읽지 못했습니다: {type(exc).__name__} — {exc}")
        return 2
    try:
        db = db or get_admin_db()
        report = load_cases(db, items)
    except AppError as exc:
        print(f"[오류] {exc.code}: {exc.message} {exc.detail or ''}")
        return 2

    print(f"새로 넣음 {len(report.inserted)}건, 갱신 {len(report.updated)}건, 거부 {len(report.rejected)}건")
    for key in report.inserted:
        print(f"  + {key}")
    for key in report.updated:
        print(f"  ~ {key}")
    for key, reason in report.rejected:
        print(f"  ✗ {key}: {reason}")
    return 1 if report.rejected else 0


if __name__ == "__main__":
    sys.exit(main())
