"""자동 등록: 가짜 기능 폴더(임시 폴더에만 만든다)의 router·hooks·PAGES·SECTIONS가 붙는지."""

import sys
import textwrap
from pathlib import Path

import pytest

import app.features as features_pkg
from app.core import events, registry

FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"

ROUTER = textwrap.dedent('''
    from fastapi import APIRouter
    router = APIRouter()

    @router.get("/_fake/ping")
    def ping():
        return {"pong": True}
''')
HOOKS = textwrap.dedent('''
    from app.core import events
    from app.core.registry import ColumnProvider, ColumnValue, register_column_provider

    def _compute(**kw):
        return {}

    def _on_delete(**kw):
        pass

    register_column_provider(ColumnProvider(key="zz_fake", title="가짜 열", compute=_compute))
    events.on("listing.before_delete", _on_delete)
''')


@pytest.fixture
def fake_backend_feature(tmp_path):
    root = tmp_path / "extra_features"
    pkg = root / "zz_fake"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "router.py").write_text(ROUTER, encoding="utf-8")
    (pkg / "hooks.py").write_text(HOOKS, encoding="utf-8")
    features_pkg.__path__.append(str(root))
    yield
    features_pkg.__path__.remove(str(root))
    for name in [m for m in sys.modules if m.startswith("app.features.zz_fake")]:
        del sys.modules[name]


FAKE_HOOKS_MODULE = "app.features.zz_fake.hooks"


def _fake_provider_keys() -> list[str]:
    """실제 기능(P5 budget 등)도 함께 등록되므로 zz_fake 것만 센다."""
    return [p.key for p in registry.get_column_providers() if p.key == "zz_fake"]


def _fake_delete_handlers() -> list:
    """실제 기능(P4 사진 삭제 등)도 함께 등록되므로 zz_fake 모듈의 처리기만 센다."""
    return [h for h in events.handlers("listing.before_delete") if h.__module__ == FAKE_HOOKS_MODULE]


def test_core_backend_autoregisters_router_and_hooks(fake_backend_feature, client_as):
    c = client_as(None)
    assert c.get("/_fake/ping").json() == {"pong": True}
    assert {"feature": "zz_fake", "router": True, "hooks": True} in c.app.state.features
    assert _fake_provider_keys() == ["zz_fake"]
    assert len(_fake_delete_handlers()) == 1
    # 등록부를 비운 뒤 앱을 다시 만들어도 hooks가 다시 등록되고, 처리기는 중복되지 않는다
    registry.reset_registry()
    client_as(None)
    client_as(None)
    assert _fake_provider_keys() == ["zz_fake"]
    assert len(_fake_delete_handlers()) == 1


def test_core_frontend_loads_pages_and_sections(tmp_path):
    sys.path.append(str(FRONTEND_DIR))
    from core.loader import load_pages, load_sections

    base = tmp_path
    pkg = base / "zz_test_features"
    (pkg / "demo").mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "demo" / "__init__.py").write_text("")
    (pkg / "demo" / "pages.py").write_text(textwrap.dedent('''
        def render():
            pass
        PAGES = [{"key": "demo", "title": "데모", "order": 50, "admin_only": True, "render": render}]
    '''), encoding="utf-8")
    (pkg / "demo" / "sections.py").write_text(textwrap.dedent('''
        def render(ctx):
            pass
        SECTIONS = [{"slot": "listing_detail", "order": 99, "render": render}]
    '''), encoding="utf-8")
    try:
        pages = load_pages(package="zz_test_features", base_dir=base)
        sections = load_sections(package="zz_test_features", base_dir=base)
    finally:
        for name in [m for m in sys.modules if m.startswith("zz_test_features")]:
            del sys.modules[name]
        sys.path.remove(str(base))
    assert [(p["key"], p["order"], p["admin_only"], p["feature"]) for p in pages] == [("demo", 50, True, "demo")]
    assert [(s["slot"], s["order"], s["feature"]) for s in sections] == [("listing_detail", 99, "demo")]


def test_core_frontend_slot_isolates_failing_section(tmp_path):
    sys.path.append(str(FRONTEND_DIR))
    from core import slots

    seen = []

    def bad(ctx):
        raise RuntimeError("boom")

    def good(ctx):
        seen.append(ctx["listing"])

    slots.register_sections([
        {"slot": "listing_detail", "order": 10, "render": bad, "feature": "a"},
        {"slot": "listing_detail", "order": 20, "render": good, "feature": "b"},
    ])
    slots.render_slot("listing_detail", {"listing": "L"})
    assert seen == ["L"]
    slots.register_sections([])
