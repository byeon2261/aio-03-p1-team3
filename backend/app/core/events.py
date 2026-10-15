"""삭제 전 이벤트. 다른 기능의 정리 작업(예: 사진 Storage 파일 삭제)을 끼워 넣는다.

이벤트와 인자
    "session.before_delete"  (db, user, session, listing_ids, storage)
    "listing.before_delete"  (db, user, listing, storage)

    on("listing.before_delete", handler)         # hooks.py에서 등록
    emit("listing.before_delete", db=db, user=user, listing=listing, storage=storage)   # 삭제하는 쪽(P1)

storage는 삭제 엔드포인트가 Depends(get_storage)로 받은 것을 넘긴다(테스트의 dependency_overrides를 따른다).
처리기는 동기 함수이고 키워드 인자로 받는다. 나중에 인자가 늘어도 깨지지 않게 **kw를 함께 받는다.
처리기가 예외를 내면 emit이 그대로 올린다.
삭제하는 쪽은 DB 삭제를 멈추고 그 오류를 응답한다(행이 남아 있으므로 다시 삭제할 수 있다).
같은 모듈·이름의 처리기를 다시 등록하면 바꿔 끼운다(hooks.py를 다시 읽어도 두 번 돌지 않는다).
"""

from __future__ import annotations

from typing import Any, Callable

EVENTS = ("session.before_delete", "listing.before_delete")

_handlers: dict[str, list[Callable[..., Any]]] = {}


def _ident(fn: Callable[..., Any]) -> tuple[str, str]:
    return getattr(fn, "__module__", ""), getattr(fn, "__qualname__", repr(fn))


def on(event: str, handler: Callable[..., Any]) -> None:
    if event not in EVENTS:
        raise ValueError(f"알 수 없는 이벤트: {event}")
    lst = _handlers.setdefault(event, [])
    ident = _ident(handler)
    lst[:] = [h for h in lst if _ident(h) != ident]
    lst.append(handler)


def emit(event: str, **payload: Any) -> None:
    if event not in EVENTS:
        raise ValueError(f"알 수 없는 이벤트: {event}")
    for handler in list(_handlers.get(event, [])):
        handler(**payload)


def handlers(event: str) -> list[Callable[..., Any]]:
    return list(_handlers.get(event, []))


def reset_events() -> None:
    """테스트용."""
    _handlers.clear()
