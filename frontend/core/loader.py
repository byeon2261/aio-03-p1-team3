"""frontend/features/*/pages.py의 PAGES와 sections.py의 SECTIONS를 읽는다.

pages.py·sections.py는 import할 때 st 함수를 부르지 않는다(함수 정의만).
    PAGES    = [{"key": str, "title": str, "order": int, "admin_only": bool, "render": callable}]
    SECTIONS = [{"slot": str, "order": int, "render": callable(ctx: dict)}]
key는 영어 소문자·숫자·밑줄(URL 경로로 쓴다).
"""

from __future__ import annotations

import importlib
import importlib.util
import pkgutil
import re
import sys
from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parents[1]
_KEY_RE = re.compile(r"^[a-z0-9_]+$")


def _ensure_path(base_dir: Path) -> None:
    p = str(base_dir)
    if p not in sys.path:
        sys.path.append(p)  # 앞에 넣으면 backend의 app 패키지가 frontend/app.py에 가려질 수 있다


def _features(package: str, base_dir: Path) -> list[str]:
    _ensure_path(base_dir)
    pkg = importlib.import_module(package)
    return sorted(m.name for m in pkgutil.iter_modules(pkg.__path__) if m.ispkg)


def _load(package: str, base_dir: Path, module: str, attr: str) -> list[dict]:
    out: list[dict] = []
    for name in _features(package, base_dir):
        full = f"{package}.{name}.{module}"
        if importlib.util.find_spec(full) is None:
            continue
        items = getattr(importlib.import_module(full), attr, None)
        if items is None:
            raise ValueError(f"{full}에 {attr}가 없습니다")
        for item in items:
            out.append({**item, "feature": name})
    return out


def load_pages(package: str = "features", base_dir: Path = FRONTEND_DIR) -> list[dict]:
    pages = _load(package, base_dir, "pages", "PAGES")
    for p in pages:
        missing = {"key", "title", "order", "admin_only", "render"} - set(p)
        if missing:
            raise ValueError(f"{p['feature']}/pages.py 항목에 {sorted(missing)}가 없습니다")
        if not _KEY_RE.match(str(p["key"])):
            raise ValueError(f"{p['feature']}/pages.py key '{p['key']}'는 영어 소문자·숫자·밑줄만 씁니다")
        if not callable(p["render"]):
            raise ValueError(f"{p['feature']}/pages.py '{p['key']}'의 render가 함수가 아닙니다")
    return sorted(pages, key=lambda p: (p["order"], p["key"]))


def load_sections(package: str = "features", base_dir: Path = FRONTEND_DIR) -> list[dict]:
    sections = _load(package, base_dir, "sections", "SECTIONS")
    for s in sections:
        missing = {"slot", "order", "render"} - set(s)
        if missing:
            raise ValueError(f"{s['feature']}/sections.py 항목에 {sorted(missing)}가 없습니다")
        if not callable(s["render"]):
            raise ValueError(f"{s['feature']}/sections.py의 render가 함수가 아닙니다")
    return sorted(sections, key=lambda s: (s["slot"], s["order"]))
