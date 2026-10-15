"""의존성 함수를 Depends 밖(미들웨어·/ready·인증 내부)에서 부를 때 쓴다.

테스트의 `app.dependency_overrides`를 그대로 따른다.
    db = resolve(request.app, get_admin_db)
"""

from __future__ import annotations

from typing import Any, Callable


def resolve(app: Any, dependency: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    overrides = getattr(app, "dependency_overrides", None) or {}
    fn = overrides.get(dependency, dependency)
    return fn(*args, **kwargs)
