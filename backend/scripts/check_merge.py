"""대화창 결과 합치기·점검. 저장소 루트에서 실행한다. 표준 라이브러리만 쓴다.

    python backend/scripts/check_merge.py merge P1_output.zip P2_output.zip ...
    python backend/scripts/check_merge.py merge --overwrite I1_patch.zip
    python backend/scripts/check_merge.py check

merge   ZIP을 저장소 루트에 푼다. 이미 있는 파일은 덮어쓰지 않고 '충돌'로 적는다(--overwrite면 덮어씀).
check   1) requirements/*.txt → requirements.txt 생성(버전 충돌 경고)
        2) 앱 import, 등록된 라우터·hooks·페이지·섹션 출력
        3) 기능 폴더 누락, 같은 메서드·경로 중복, 슬롯·페이지 순서 중복, 앱 코드의 tests.fakes import 검사
        4) pytest -q
        5) 결과를 merge_report.txt에 쓴다
종료 코드: 문제가 없으면 0, 오류가 있으면 1.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
REPO_PREFIX = "house-tour-notes/"

BACKEND_FEATURES = ["auth", "sessions", "listings", "drafts", "analysis", "comparison", "feedback",
                    "photos", "mypage", "budget", "admin_logs", "evals"]
FRONTEND_FEATURES = ["auth", "sessions", "analysis", "comparison", "photos", "mypage", "budget",
                     "admin_logs", "evals"]
INSTALL_HINT = ("pip install -r backend/requirements.txt -r frontend/requirements.txt"
                "(uv를 쓰면 uv pip install -r backend/requirements.txt -r frontend/requirements.txt) 후 다시 실행")


# ------------------------------------------------------------------ merge
def _safe_member(name: str) -> str | None:
    """ZIP 안 경로를 저장소 기준 상대 경로로. 위험한 경로(절대·..)는 None."""
    name = name.replace("\\", "/")
    if name.startswith(REPO_PREFIX):
        name = name[len(REPO_PREFIX):]
    p = PurePosixPath(name)
    if not name or name.endswith("/") or p.is_absolute() or ".." in p.parts:
        return None
    if p.parts and (p.parts[0].endswith(":") or "__MACOSX" in p.parts):
        return None
    return str(p)


def merge(zips: list[str], overwrite: bool = False, root: Path = ROOT) -> dict:
    result = {"written": [], "conflicts": [], "overwritten": [], "skipped": []}
    for z in zips:
        with zipfile.ZipFile(z) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                rel = _safe_member(info.filename)
                if rel is None:
                    result["skipped"].append(f"{z}: {info.filename}")
                    continue
                target = root / rel
                data = zf.read(info)
                if target.exists():
                    if target.read_bytes() == data:
                        continue  # 같은 내용(예: 공통 __init__.py)은 충돌 아님
                    if not overwrite:
                        result["conflicts"].append(f"{rel}  ← {Path(z).name}")
                        continue
                    result["overwritten"].append(rel)
                else:
                    result["written"].append(rel)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
    return result


# ------------------------------------------------------------------ requirements
_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def _req_name(line: str) -> str | None:
    m = _NAME_RE.match(line)
    return re.sub(r"[-_.]+", "-", m.group(1)).lower() if m else None


def _req_key(line: str) -> str:
    """이름은 정규화하고 버전 조건은 공백만 뺀 비교용 문자열."""
    m = _NAME_RE.match(line)
    rest = line[m.end():] if m else line
    return f"{_req_name(line)}{rest.replace(' ', '')}"


def build_requirements(side_dir: Path) -> tuple[list[str], list[str]]:
    """side_dir/requirements/*.txt(base 먼저) → side_dir/requirements.txt. (줄 목록, 경고) 반환."""
    req_dir = side_dir / "requirements"
    files = sorted(req_dir.glob("*.txt"), key=lambda p: (p.name != "base.txt", p.name))
    seen: dict[str, tuple[str, str]] = {}
    lines: list[str] = []
    warnings: list[str] = []
    for f in files:
        for raw in f.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            name = _req_name(line)
            if name is None:
                continue
            if name in seen:
                if _req_key(seen[name][0]) != _req_key(line):
                    warnings.append(f"{side_dir.name}: {name} 버전 충돌 — {seen[name][1]}의 '{seen[name][0]}'을 쓰고 "
                                    f"{f.name}의 '{line}'은 무시")
                continue
            seen[name] = (line, f.name)
            lines.append(line)
    header = ["# 자동 생성 파일 — check_merge.py가 requirements/*.txt를 합쳐 만든다. 직접 고치지 않는다."]
    (side_dir / "requirements.txt").write_text("\n".join(header + lines) + "\n", encoding="utf-8")
    return lines, warnings


# ------------------------------------------------------------------ fakes import 검사
def _imports_fakes(tree: ast.AST) -> list[int]:
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(a.name == "tests.fakes" or a.name.startswith("tests.fakes.") for a in node.names):
                hits.append(node.lineno)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module == "tests.fakes" or node.module.startswith("tests.fakes."):
                hits.append(node.lineno)
            elif node.module == "tests" and any(a.name == "fakes" for a in node.names):
                hits.append(node.lineno)
    return hits


def find_fakes_imports(dirs: list[Path]) -> list[str]:
    found = []
    for d in dirs:
        if not d.exists():
            continue
        for py in sorted(d.rglob("*.py")):
            try:
                tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
            except SyntaxError as exc:
                found.append(f"{py}: 문법 오류로 검사 못 함 ({exc.lineno}행)")
                continue
            for line in _imports_fakes(tree):
                found.append(f"{py.relative_to(ROOT) if py.is_relative_to(ROOT) else py}:{line}")
    return found


# ------------------------------------------------------------------ 앱 import(별도 프로세스)
_INSPECT = r"""
import json, sys
backend, frontend, scripts = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, backend)
out = {}
try:
    from app.main import create_app
    app = create_app()
    sys.path.insert(0, scripts)
    from check_merge import list_routes
    out["routes"] = list_routes(app)
    out["features"] = app.state.features
    sys.path.append(frontend)
    from core.loader import load_pages, load_sections
    out["pages"] = [{k: p[k] for k in ("key", "title", "order", "admin_only", "feature")} for p in load_pages()]
    out["sections"] = [{k: s[k] for k in ("slot", "order", "feature")} for s in load_sections()]
except ModuleNotFoundError as exc:
    out = {"missing_module": exc.name}
print("@@JSON@@" + json.dumps(out, ensure_ascii=False))
"""


def list_routes(app) -> list[dict]:
    """앱의 모든 라우트(메서드·경로·모듈). include_router로 붙인 기능 라우트까지 펼친다.

    FastAPI 0.143은 include_router 결과를 app.routes에 `_IncludedRouter` 하나로 넣어서
    app.routes만 보면 기능 라우트가 빠진다. fastapi.routing.iter_route_contexts가 있으면 그것으로 펼친다
    (include_in_schema=False 라우트도 포함). 없는 옛 버전은 app.routes가 이미 펼쳐져 있다.
    """
    try:
        from fastapi.routing import iter_route_contexts
        items = list(iter_route_contexts(app.routes))
    except ImportError:
        items = list(app.routes)
    routes = []
    for r in items:
        methods = sorted(m for m in (getattr(r, "methods", None) or []) if m not in ("HEAD", "OPTIONS"))
        if methods:
            routes.append({"path": r.path, "methods": methods, "module": getattr(r.endpoint, "__module__", "")})
    return routes


def inspect_apps() -> dict:
    proc = subprocess.run([sys.executable, "-c", _INSPECT, str(BACKEND), str(FRONTEND), str(Path(__file__).parent)],
                          capture_output=True, text=True, cwd=str(ROOT))
    marker = [l for l in proc.stdout.splitlines() if l.startswith("@@JSON@@")]
    if not marker:
        return {"crash": (proc.stderr or proc.stdout)[-4000:]}
    return json.loads(marker[-1][len("@@JSON@@"):])


def duplicate_routes(routes: list[dict]) -> list[str]:
    seen: dict[tuple[str, str], str] = {}
    dups = []
    for r in routes:
        for m in r["methods"]:
            key = (m, r["path"])
            if key in seen:
                dups.append(f"{m} {r['path']}  ({seen[key]} / {r['module']})")
            else:
                seen[key] = r["module"]
    return dups


def duplicate_orders(items: list[dict], group_key: str | None, label: str) -> list[str]:
    seen: dict[tuple, str] = {}
    dups = []
    for it in items:
        key = (it.get(group_key) if group_key else label, it["order"])
        who = it.get("feature", "?")
        if key in seen:
            dups.append(f"{label} {key[0]} order {it['order']}: {seen[key]} / {who}")
        else:
            seen[key] = who
    return dups


def missing_features() -> list[str]:
    out = []
    for name in BACKEND_FEATURES:
        if not (BACKEND / "app" / "features" / name / "__init__.py").exists():
            out.append(f"backend/app/features/{name}/")
    for name in FRONTEND_FEATURES:
        if not (FRONTEND / "features" / name / "__init__.py").exists():
            out.append(f"frontend/features/{name}/")
    return out


# ------------------------------------------------------------------ check
def check() -> int:
    report: list[str] = []
    errors = 0

    def say(line: str = "") -> None:
        print(line)
        report.append(line)

    say("# check_merge 결과")
    say("\n## 1. requirements.txt 생성")
    for side in (BACKEND, FRONTEND):
        lines, warns = build_requirements(side)
        say(f"- {side.name}/requirements.txt: {len(lines)}개 패키지")
        for w in warns:
            say(f"  - 경고: {w}")

    say("\n## 2. 앱 import·등록 목록")
    info = inspect_apps()
    if "missing_module" in info:
        say(f"- 설치되지 않은 패키지: {info['missing_module']}")
        say(f"- {INSTALL_HINT}")
        _write_report(report)
        return 1
    if "crash" in info:
        say("- 앱 import 실패:")
        say("```\n" + info["crash"] + "\n```")
        _write_report(report)
        return 1
    for f in info["features"]:
        say(f"- 기능 {f['feature']}: router={'O' if f['router'] else '-'} hooks={'O' if f['hooks'] else '-'}")
    say(f"- 라우트 {len(info['routes'])}개")
    for r in sorted(info["routes"], key=lambda r: r["path"]):
        say(f"  - {','.join(r['methods'])} {r['path']}")
    for p in info["pages"]:
        say(f"- 페이지 {p['order']:>3} {p['key']} ({p['feature']}){' [운영자]' if p['admin_only'] else ''}")
    for s in info["sections"]:
        say(f"- 섹션 {s['slot']} {s['order']:>3} ({s['feature']})")

    say("\n## 3. 점검")
    problems: list[tuple[str, list[str], bool]] = [
        ("기능 폴더 누락(경고)", missing_features(), False),
        ("같은 메서드·경로 중복", duplicate_routes(info["routes"]), True),
        ("슬롯 순서 중복", duplicate_orders(info["sections"], "slot", "슬롯"), True),
        ("페이지 순서 중복", duplicate_orders(info["pages"] + [
            {"order": 20, "feature": "core(세션 상세)"}, {"order": 30, "feature": "core(매물 상세)"}], None, "페이지"), True),
        ("앱 코드의 tests.fakes import", find_fakes_imports([BACKEND / "app", FRONTEND]), True),
    ]
    for title, items, is_error in problems:
        if items:
            say(f"- {title}: {len(items)}건")
            for it in items:
                say(f"  - {it}")
            if is_error:
                errors += 1
        else:
            say(f"- {title}: 없음")

    say("\n## 4. pytest -q")
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q"], capture_output=True, text=True, cwd=str(BACKEND))
    tail = (proc.stdout + proc.stderr).strip().splitlines()[-25:]
    say("```\n" + "\n".join(tail) + "\n```")
    if proc.returncode != 0:
        errors += 1

    say(f"\n## 결과: {'통과' if errors == 0 else f'문제 {errors}종'}")
    _write_report(report)
    return 0 if errors == 0 else 1


def _write_report(lines: list[str]) -> None:
    (ROOT / "merge_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n→ {ROOT / 'merge_report.txt'}")


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "merge":
        overwrite = "--overwrite" in rest
        zips = [a for a in rest if a != "--overwrite"]
        if not zips:
            print("ZIP 파일을 하나 이상 주세요.")
            return 1
        res = merge(zips, overwrite=overwrite)
        print(f"새 파일 {len(res['written'])}개")
        if overwrite:
            print(f"덮어쓴 파일 {len(res['overwritten'])}개")
            for f in res["overwritten"]:
                print(f"  - {f}")
        if res["conflicts"]:
            print(f"충돌 {len(res['conflicts'])}개(덮어쓰지 않음):")
            for f in res["conflicts"]:
                print(f"  - {f}")
        for f in res["skipped"]:
            print(f"  건너뜀(위험한 경로): {f}")
        return 1 if res["conflicts"] else 0
    if cmd == "check":
        return check()
    print(f"알 수 없는 명령: {cmd}\n{__doc__}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
