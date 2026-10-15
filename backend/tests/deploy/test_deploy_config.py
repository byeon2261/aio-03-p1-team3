"""배포 설정 파일 점검 — render.yaml·compose.yaml이 YAML로 읽히는지, 계약(설정 키·헬스체크)과 맞는지."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]


def _load_yaml(name: str):
    return yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))


def _env_example_keys() -> set[str]:
    """backend/.env.example에서 주석이 아닌 키(값을 꼭 넣어야 하는 것)."""
    keys = set()
    for line in (ROOT / "backend" / ".env.example").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Z][A-Z0-9_]*)=", line.strip())
        if m:
            keys.add(m.group(1))
    return keys


def _services():
    data = _load_yaml("render.yaml")
    assert isinstance(data, dict) and isinstance(data.get("services"), list)
    web = [s for s in data["services"] if s.get("type") == "web"]
    kv = [s for s in data["services"] if s.get("type") == "keyvalue"]
    assert len(web) == 1 and len(kv) == 1
    return web[0], kv[0]


def test_deploy_render_yaml_parses_and_matches_contract():
    web, kv = _services()
    assert web["runtime"] == "python" and web["plan"] == "free"
    assert web["rootDir"] == "backend"
    assert web["healthCheckPath"] == "/health"            # /ready는 DB 장애 때 503이라 헬스체크로 쓰지 않는다
    assert "app.main:app" in web["startCommand"] and "$PORT" in web["startCommand"]
    assert "0.0.0.0" in web["startCommand"]
    assert web["buildCommand"] == "pip install -r requirements.txt"
    assert kv["plan"] == "free"
    assert kv["ipAllowList"] == []                         # 외부 접속 막음
    assert web.get("region") == kv.get("region")           # 내부 주소는 같은 리전에서만


def test_deploy_render_env_vars_cover_env_example():
    web, kv = _services()
    env = {e["key"]: e for e in web["envVars"]}
    missing = _env_example_keys() - set(env)
    assert not missing, f"render.yaml에 없는 환경변수: {missing}"
    redis = env["REDIS_URL"]["fromService"]
    assert redis == {"type": "keyvalue", "name": kv["name"], "property": "connectionString"}
    for secret in ("SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_SECRET_KEY", "GEMINI_API_KEY"):
        assert env[secret].get("sync") is False and "value" not in env[secret]   # 비밀값은 파일에 넣지 않는다
    assert re.fullmatch(r"3\.12\.\d+", str(env["PYTHON_VERSION"]["value"]))      # Render는 패치 버전까지 요구


def test_deploy_compose_yaml_has_one_valkey8():
    data = _load_yaml("compose.yaml")
    services = data["services"]
    assert list(services) == ["valkey"]
    svc = services["valkey"]
    assert re.fullmatch(r"valkey/valkey:8\.\d+\.\d+(-[a-z0-9.]+)?", svc["image"])
    assert any(str(p).endswith(":6379") for p in svc["ports"])
    assert "version" not in data


def test_deploy_streamlit_config_toml_parses():
    data = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
    assert data["client"]["showErrorDetails"] in {"full", "stacktrace", "type", "none"}
    assert data["browser"]["gatherUsageStats"] is False
    assert isinstance(data["server"]["maxUploadSize"], int)


def test_deploy_docs_list_migrations_in_order():
    """DEPLOY.md가 supabase/migrations의 파일을 빠짐없이 번호 순서대로 적는지."""
    text = (ROOT / "docs" / "DEPLOY.md").read_text(encoding="utf-8")
    files = sorted(p.name for p in (ROOT / "supabase" / "migrations").glob("*.sql"))
    assert files
    positions = [text.find(f) for f in files]
    assert all(p >= 0 for p in positions), f"DEPLOY.md에 없는 마이그레이션: {[f for f, p in zip(files, positions) if p < 0]}"
    assert positions == sorted(positions)
