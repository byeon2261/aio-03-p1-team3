"""메모 초안(KV) 키와 저장·복원·삭제.

키
    draft:{auth_user_id}:{listing_id}          기존 메모 수정 초안  {"text", "saved_at"}  TTL settings.DRAFT_TTL_SEC
    draft:{auth_user_id}:new:{session_id}      새 메모 초안          {"text", "saved_at"}  TTL settings.DRAFT_TTL_SEC
    draftmeta:{초안 키}                         마지막 저장 시각(ISO) TTL 7일

초안은 없고 draftmeta만 남아 있으면 "만료"(410 DRAFT_EXPIRED), 둘 다 없으면 404 DRAFT_NOT_FOUND.
sessions·listings 기능도 정식 저장·삭제 뒤 discard_drafts()로 초안을 지운다.
"""

from __future__ import annotations

import datetime as dt
import json
import logging

from app.core.config import settings
from app.core.errors import AppError
from app.core.kv import KV, get_kv, kv_available, kv_unavailable
from app.core.schemas import DraftOut

logger = logging.getLogger("app.features.drafts")

DRAFT_META_TTL_SEC = 7 * 24 * 3600


def listing_draft_key(auth_user_id: str, listing_id: str) -> str:
    return f"draft:{auth_user_id}:{listing_id}"


def new_draft_key(auth_user_id: str, session_id: str) -> str:
    return f"draft:{auth_user_id}:new:{session_id}"


def meta_key(draft_key: str) -> str:
    return f"draftmeta:{draft_key}"


def require_kv() -> KV:
    """초안 엔드포인트용. KV를 쓸 수 없으면 503 KV_UNAVAILABLE."""
    if not kv_available():
        raise kv_unavailable()
    return get_kv()


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _parse_time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        t = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def _draft_out(text: str, saved_at: dt.datetime) -> DraftOut:
    return DraftOut(memo_text=text, saved_at=saved_at,
                    expires_at=saved_at + dt.timedelta(seconds=int(settings.DRAFT_TTL_SEC)))


def save_draft(kv: KV, key: str, text: str) -> DraftOut:
    saved_at = _utcnow()
    kv.set(key, json.dumps({"text": text, "saved_at": saved_at.isoformat()}, ensure_ascii=False),
           int(settings.DRAFT_TTL_SEC))
    kv.set(meta_key(key), saved_at.isoformat(), DRAFT_META_TTL_SEC)
    return _draft_out(text, saved_at)


def load_draft(kv: KV, key: str) -> DraftOut:
    raw = kv.get(key)
    if raw is not None:
        try:
            data = json.loads(raw)
        except ValueError:
            data = None
        if isinstance(data, dict):
            saved_at = _parse_time(data.get("saved_at")) or _utcnow()
            return _draft_out(str(data.get("text") or ""), saved_at)
        # 깨진 값은 없는 것으로 본다(원문을 로그에 남기지 않는다)
        logger.warning("draft value unreadable; ignored")
    meta = kv.get(meta_key(key))
    if meta is not None:
        detail = {"saved_at": meta} if _parse_time(meta) else None
        raise AppError(410, "DRAFT_EXPIRED", "임시 저장한 메모의 보관 기간(24시간)이 지났습니다.", detail)
    raise AppError(404, "DRAFT_NOT_FOUND", "저장된 임시 메모가 없습니다.")


def delete_draft(kv: KV, key: str) -> None:
    """사용자가 초안을 버릴 때. 초안과 draftmeta를 함께 지운다(KV 오류는 그대로 올린다)."""
    kv.delete(key, meta_key(key))


def discard_drafts(keys: list[str]) -> None:
    """정식 저장·삭제 뒤 초안과 draftmeta를 지운다. 실패해도 무시한다(초안은 24시간 뒤 만료)."""
    if not keys:
        return
    all_keys = [k for key in keys for k in (key, meta_key(key))]
    try:
        if not kv_available():
            logger.warning("draft discard skipped: kv unavailable")
            return
        get_kv().delete(*all_keys)
    except Exception as exc:  # KV_UNAVAILABLE, CONFIG_MISSING, redis 오류 등
        logger.warning("draft discard skipped: %s", type(exc).__name__)
