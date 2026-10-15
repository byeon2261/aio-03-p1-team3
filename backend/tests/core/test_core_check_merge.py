"""check_merge.py: tests.fakes import 탐지, requirements 합치기, ZIP 합치기 충돌, 라우트 펼치기.

파일은 항상 utf-8로 쓰고 읽는다(Windows 기본 인코딩 cp949와 무관하게).
"""

import importlib.util
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_merge.py"


@pytest.fixture(scope="module")
def cm():
    spec = importlib.util.spec_from_file_location("check_merge_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_core_check_merge_detects_fakes_import_in_app_code(cm, tmp_path):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "ok.py").write_text("from app.core.db import Database\nimport tests_helpers\n", encoding="utf-8")
    (app_dir / "bad1.py").write_text("from tests.fakes import MemoryDatabase\n", encoding="utf-8")
    (app_dir / "bad2.py").write_text("x = 1\nimport tests.fakes as f\n", encoding="utf-8")
    (app_dir / "bad3.py").write_text("def f():\n    from tests import fakes\n", encoding="utf-8")
    found = cm.find_fakes_imports([app_dir])
    names = sorted(Path(f.rsplit(":", 1)[0]).name for f in found)   # Windows 경로(C:\…)의 ":"를 피해 마지막 ":"로 나눈다
    assert names == ["bad1.py", "bad2.py", "bad3.py"]


def test_core_check_merge_real_app_code_is_clean(cm):
    assert cm.find_fakes_imports([cm.BACKEND / "app", cm.FRONTEND]) == []


def test_core_check_merge_builds_requirements_and_warns(cm, tmp_path):
    side = tmp_path / "backend"
    (side / "requirements").mkdir(parents=True)
    (side / "requirements" / "base.txt").write_text("fastapi==0.143.0\nredis==8.1.0  # 주석\n", encoding="utf-8")
    (side / "requirements" / "p2.txt").write_text("google-genai==2.30.1\nFastAPI==0.143.0\n", encoding="utf-8")
    (side / "requirements" / "p6.txt").write_text("redis==7.0.0\n", encoding="utf-8")
    lines, warns = cm.build_requirements(side)
    assert lines == ["fastapi==0.143.0", "redis==8.1.0", "google-genai==2.30.1"]
    assert len(warns) == 1 and "redis" in warns[0]
    text = (side / "requirements.txt").read_text(encoding="utf-8")
    assert text.startswith("# 자동 생성") and "google-genai==2.30.1" in text


def test_core_check_merge_merge_reports_conflicts(cm, tmp_path):
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "CONTRACT.md").write_text("원본", encoding="utf-8")
    z = tmp_path / "P1_output.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("backend/app/features/sessions/__init__.py", "")
        zf.writestr("docs/CONTRACT.md", "바꾼 내용")
        zf.writestr("../evil.txt", "x")
    res = cm.merge([str(z)], root=root)
    assert res["written"] == ["backend/app/features/sessions/__init__.py"]
    assert len(res["conflicts"]) == 1 and (root / "docs" / "CONTRACT.md").read_text(encoding="utf-8") == "원본"
    assert res["skipped"] and not (tmp_path / "evil.txt").exists()
    res = cm.merge([str(z)], overwrite=True, root=root)
    assert res["overwritten"] == ["docs/CONTRACT.md"]
    assert (root / "docs" / "CONTRACT.md").read_text(encoding="utf-8") == "바꾼 내용"


def test_core_check_merge_duplicate_detection(cm):
    routes = [{"path": "/sessions", "methods": ["GET"], "module": "a"},
              {"path": "/sessions", "methods": ["GET", "POST"], "module": "b"}]
    assert cm.duplicate_routes(routes) == ["GET /sessions  (a / b)"]
    secs = [{"slot": "session_detail", "order": 10, "feature": "sessions"},
            {"slot": "session_detail", "order": 10, "feature": "budget"},
            {"slot": "listing_detail", "order": 10, "feature": "sessions"}]
    assert len(cm.duplicate_orders(secs, "slot", "슬롯")) == 1


def test_core_check_merge_lists_routes_of_included_routers(cm):
    """include_router로 붙인 기능 라우트(중첩 포함)도 목록에 나와야 경로 중복 검사가 기능 라우트를 본다."""
    from fastapi import APIRouter, FastAPI

    app = FastAPI()

    @app.get("/health")
    def health():
        return {}

    outer = APIRouter(prefix="/sessions")

    @outer.get("/{session_id}/comparison")
    def comparison(session_id: str):
        return {}

    inner = APIRouter(prefix="/inner")

    @inner.post("/x", include_in_schema=False)
    def x():
        return {}

    outer.include_router(inner)
    app.include_router(outer)
    found = {(m, r["path"]) for r in cm.list_routes(app) for m in r["methods"]}
    assert {("GET", "/health"), ("GET", "/sessions/{session_id}/comparison"),
            ("POST", "/sessions/inner/x")} <= found
