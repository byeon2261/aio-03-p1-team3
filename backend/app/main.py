"""FastAPI 앱. 기능은 app/features/<이름>/ 아래에 두면 자동으로 붙는다.

- router.py가 있으면 그 안의 `router`(APIRouter)를 등록한다.
- hooks.py가 있으면 import해서 등록 코드(register_pipeline, register_column_provider, events.on …)를 실행한다.
  create_app()을 다시 부르면 hooks.py를 다시 읽는다(테스트에서 등록부를 초기화한 뒤에도 등록되도록).
패키지는 이름순으로 처리한다. 실행: backend 폴더에서 `uvicorn app.main:app`.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import pkgutil
import sys
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.core.db import get_admin_db
from app.core.deps import resolve
from app.core.errors import install_error_handlers
from app.core.kv import kv_available
from app.core.request_log import RequestLogMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

FEATURES_PACKAGE = "app.features"


def discover_features() -> list[str]:
    pkg = importlib.import_module(FEATURES_PACKAGE)
    return sorted(m.name for m in pkgutil.iter_modules(pkg.__path__) if m.ispkg)


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False


def _load_hooks(module_name: str) -> None:
    if module_name in sys.modules:
        importlib.reload(sys.modules[module_name])
    else:
        importlib.import_module(module_name)


def register_features(app: FastAPI) -> list[dict[str, Any]]:
    loaded = []
    for name in discover_features():
        info = {"feature": name, "router": False, "hooks": False}
        router_mod = f"{FEATURES_PACKAGE}.{name}.router"
        hooks_mod = f"{FEATURES_PACKAGE}.{name}.hooks"
        if _has_module(router_mod):
            mod = importlib.import_module(router_mod)
            router = getattr(mod, "router", None)
            if router is None:
                raise RuntimeError(f"{router_mod}에 router가 없습니다")
            app.include_router(router)
            info["router"] = True
        if _has_module(hooks_mod):
            _load_hooks(hooks_mod)
            info["hooks"] = True
        loaded.append(info)
    return loaded


def create_app() -> FastAPI:
    app = FastAPI(title="집 보기 메모 비교 서비스 API", version="0.1.0")
    install_error_handlers(app)
    app.add_middleware(RequestLogMiddleware)

    @app.get("/health", tags=["ops"])
    def health() -> dict:
        """프로세스가 살아 있으면 항상 200. 외부 서비스를 보지 않는다."""
        return {"status": "ok"}

    @app.get("/ready", tags=["ops"])
    async def ready(request: Request):
        """DB·Redis 확인. db가 false면 503, redis만 false면 200."""

        def _check_db() -> bool:
            try:
                db = resolve(request.app, get_admin_db)
                db.select("profiles", limit=1)
                return True
            except Exception:
                return False

        db_ok = await run_in_threadpool(_check_db)
        redis_ok = await run_in_threadpool(kv_available)
        body = {"db": db_ok, "redis": redis_ok}
        return JSONResponse(body, status_code=200 if db_ok else 503)

    app.state.features = register_features(app)
    return app


app = create_app()
