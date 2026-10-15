"""테스트 전용 가짜 구현. 앱 코드(backend/app, frontend)는 이 파일을 import하지 않는다.

MemoryDatabase  Database 구현. id·created_at 자동, unique 제약, CASCADE, listing_no 트리거,
                memo_updated_at 트리거, 트리거 전용 열 UPDATE 거부를 흉내 낸다. RLS는 흉내 내지 않는다.
MemoryKV        KV 구현. advance(초)로 시계를 앞당긴다. available=False면 503 KV_UNAVAILABLE.
MemoryStorage   Storage 구현. fail_uploads/fail_deletes/fail_signed_urls로 실패를 흉내 낸다.
MemoryBroker    publish된 행은 .published에 쌓이고, subscribe()로 받을 수 있다.
FakeAuthProvider  메모리 사용자·토큰. issue_token()으로 유효한 토큰을 만든다.
FakePipeline    정해 둔 AnalysisOutcome을 돌려주고 받은 인자를 .calls에 기록한다.
"""

from __future__ import annotations

import asyncio
import copy
import datetime as dt
import itertools
import threading
import time
import uuid
from typing import Any

from app.core.analysis_contract import AnalysisAIOutput, AnalysisOutcome, CheckItem, build_result
from app.core.auth_provider import AuthSession, SignUpResult
from app.core.db import UniqueViolation, classify_filter, to_json_value
from app.core.errors import AppError
from app.core.kv import kv_unavailable
from app.core.storage import StorageError


class ForeignKeyViolation(Exception):
    """부모 행이 없을 때(테스트용)."""


# ---------------------------------------------------------------- MemoryDatabase
UNIQUE = {
    "profiles": [("auth_user_id",)],
    "listings": [("session_id", "listing_no")],
    "photos": [("storage_path",)],
    "eval_cases": [("case_key",)],
}
PRIMARY_KEY = {"session_budgets": "session_id"}
# (자식 테이블, 외래키 열, 부모 테이블, 삭제 동작)
FOREIGN_KEYS = [
    ("tour_sessions", "profile_id", "profiles", "cascade"),
    ("listings", "session_id", "tour_sessions", "cascade"),
    ("analyses", "listing_id", "listings", "cascade"),
    ("feedback", "analysis_id", "analyses", "cascade"),
    ("feedback", "profile_id", "profiles", "cascade"),
    ("photos", "listing_id", "listings", "cascade"),
    ("photos", "profile_id", "profiles", "cascade"),
    ("session_budgets", "session_id", "tour_sessions", "cascade"),
    ("request_logs", "profile_id", "profiles", "set_null"),
    ("eval_results", "run_id", "eval_runs", "cascade"),
    ("eval_results", "case_id", "eval_cases", "cascade"),
]
DEFAULTS = {
    "profiles": {"role": "user", "nickname": "사용자"},
    "tour_sessions": {"last_listing_no": 0, "visit_date": None},
    "listings": {"memo_text": ""},
    "photos": {"visibility": "private"},
    "eval_cases": {"tags": []},
    "eval_runs": {"status": "running", "case_count": 0, "finished_at": None},
    "eval_results": {"failure_codes": []},
}
NOW_COLUMNS = {"listings": ("memo_updated_at",), "session_budgets": ("updated_at",)}
# 실제 DB에서 트리거만 바꾸는 열(사용자 권한으로 UPDATE 불가)
PROTECTED_UPDATE_COLUMNS = {
    "tour_sessions": {"last_listing_no", "id", "profile_id"},
    "listings": {"listing_no", "memo_updated_at", "id", "session_id"},
}


def _cmp_key(v: Any) -> Any:
    if isinstance(v, str):
        try:
            return dt.datetime.fromisoformat(v)
        except ValueError:
            return v
    return v


class MemoryDatabase:
    def __init__(self) -> None:
        self.tables: dict[str, list[dict]] = {}
        self.fail_all = False          # True면 모든 호출이 ConnectionError (DB 장애 흉내)
        self._lock = threading.RLock()
        self._log_ids = itertools.count(1)
        self._last_ts: dt.datetime | None = None

    # 같은 순간에 만든 행도 created_at 순서가 정해지도록 1µs씩 늘린다
    def _now(self) -> str:
        now = dt.datetime.now(dt.timezone.utc)
        if self._last_ts is not None and now <= self._last_ts:
            now = self._last_ts + dt.timedelta(microseconds=1)
        self._last_ts = now
        return now.isoformat()

    def _check(self) -> None:
        if self.fail_all:
            raise ConnectionError("database unavailable (fake)")

    def _rows(self, table: str) -> list[dict]:
        return self.tables.setdefault(table, [])

    @staticmethod
    def _match(row: dict, filters: dict | None) -> bool:
        for col, raw in (filters or {}).items():
            op, v = classify_filter(raw)
            cur = row.get(col)
            if op == "eq":
                if cur != v:
                    return False
            elif op == "in":
                if cur not in v:
                    return False
            elif op == "is":
                if cur is not None:
                    return False
            else:
                if cur is None:
                    return False
                a, b = _cmp_key(cur), _cmp_key(v)
                if op == "gte" and not a >= b:
                    return False
                if op == "lte" and not a <= b:
                    return False
                if op == "gt" and not a > b:
                    return False
                if op == "lt" and not a < b:
                    return False
        return True

    def _check_unique(self, table: str, row: dict, ignore: dict | None = None) -> None:
        pk = PRIMARY_KEY.get(table, "id")
        keys = [(pk,)] + UNIQUE.get(table, [])
        for cols in keys:
            vals = tuple(row.get(c) for c in cols)
            if any(v is None for v in vals):
                continue
            for other in self._rows(table):
                if other is ignore:
                    continue
                if tuple(other.get(c) for c in cols) == vals:
                    raise UniqueViolation(f"{table}{cols} duplicate")

    def _check_parents(self, table: str, row: dict) -> None:
        for child, col, parent, _ in FOREIGN_KEYS:
            if child != table or row.get(col) is None:
                continue
            if not any(p.get("id") == row[col] for p in self._rows(parent)):
                raise ForeignKeyViolation(f"{table}.{col} → {parent} 없음")

    def select(self, table, filters=None, *, order_by=None, desc=False, limit=None):
        with self._lock:
            self._check()
            rows = [r for r in self._rows(table) if self._match(r, filters)]
            if order_by:
                present = [r for r in rows if r.get(order_by) is not None]
                missing = [r for r in rows if r.get(order_by) is None]
                present.sort(key=lambda r: _cmp_key(r[order_by]), reverse=desc)
                # Postgres: ASC는 NULLS LAST, DESC는 NULLS FIRST
                rows = missing + present if desc else present + missing
            if limit is not None:
                rows = rows[:limit]
            return copy.deepcopy(rows)

    def insert(self, table, rows):
        with self._lock:
            self._check()
            items = rows if isinstance(rows, list) else [rows]
            out = []
            for raw in items:
                row = {**DEFAULTS.get(table, {}), **to_json_value(dict(raw))}
                if table == "request_logs":
                    row.setdefault("id", next(self._log_ids))
                elif PRIMARY_KEY.get(table) is None:
                    row.setdefault("id", str(uuid.uuid4()))
                ts = self._now()
                if table not in ("eval_cases", "session_budgets"):
                    row.setdefault("created_at", ts)
                for col in NOW_COLUMNS.get(table, ()):
                    row.setdefault(col, ts)
                self._check_parents(table, row)
                if table == "listings":
                    session = next(s for s in self._rows("tour_sessions") if s["id"] == row["session_id"])
                    session["last_listing_no"] = int(session.get("last_listing_no") or 0) + 1
                    row["listing_no"] = session["last_listing_no"]   # 트리거: 보낸 값은 무시
                self._check_unique(table, row)
                self._rows(table).append(row)
                out.append(copy.deepcopy(row))
            return out

    def update(self, table, filters, values):
        if not filters:
            raise ValueError("update에는 filters가 필요합니다")
        with self._lock:
            self._check()
            values = to_json_value(dict(values))
            blocked = set(values) & PROTECTED_UPDATE_COLUMNS.get(table, set())
            if blocked:
                raise PermissionError(f"{table}.{sorted(blocked)}은(는) 트리거만 바꾼다(UPDATE 금지)")
            out = []
            for row in self._rows(table):
                if not self._match(row, filters):
                    continue
                new = {**row, **values}
                if table == "listings" and new.get("memo_text") != row.get("memo_text"):
                    new["memo_updated_at"] = self._now()
                self._check_unique(table, new, ignore=row)
                row.clear()
                row.update(new)
                out.append(copy.deepcopy(row))
            return out

    def delete(self, table, filters):
        if not filters:
            raise ValueError("delete에는 filters가 필요합니다")
        with self._lock:
            self._check()
            victims = [r for r in self._rows(table) if self._match(r, filters)]
            for r in victims:
                self._delete_row(table, r)
            return copy.deepcopy(victims)

    def _delete_row(self, table: str, row: dict) -> None:
        rows = self._rows(table)
        if row in rows:
            rows.remove(row)
        key = row.get("id")
        for child, col, parent, action in FOREIGN_KEYS:
            if parent != table or key is None:
                continue
            for c in [r for r in self._rows(child) if r.get(col) == key]:
                if action == "cascade":
                    self._delete_row(child, c)
                else:
                    c[col] = None


# ---------------------------------------------------------------- MemoryKV
class MemoryKV:
    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float]] = {}
        self._clock = 0.0
        self.available = True

    def advance(self, seconds: float) -> None:
        self._clock += seconds

    def _guard(self) -> None:
        if not self.available:
            raise kv_unavailable()

    def _alive(self, key: str) -> bool:
        item = self._data.get(key)
        if item is None:
            return False
        if item[1] <= self._clock:
            del self._data[key]
            return False
        return True

    def get(self, key: str) -> str | None:
        self._guard()
        return self._data[key][0] if self._alive(key) else None

    def set(self, key: str, value: str, ttl_sec: int) -> None:
        self._guard()
        if not isinstance(value, str):
            raise TypeError("KV 값은 문자열이어야 합니다(json.dumps 사용)")
        self._data[key] = (value, self._clock + max(1, int(ttl_sec)))

    def delete(self, *keys: str) -> int:
        self._guard()
        n = 0
        for k in keys:
            if self._alive(k):
                del self._data[k]
                n += 1
        return n

    def exists(self, key: str) -> bool:
        self._guard()
        return self._alive(key)

    def ping(self) -> bool:
        return self.available

    def ttl(self, key: str) -> float | None:
        """테스트 확인용: 남은 초."""
        return self._data[key][1] - self._clock if self._alive(key) else None


# ---------------------------------------------------------------- MemoryStorage
class MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, dict] = {}
        self.fail_uploads = False
        self.fail_deletes = False
        self.fail_signed_urls = False
        self.calls: list[tuple[str, Any]] = []

    def upload(self, path: str, data: bytes, content_type: str, access_token: str) -> None:
        self.calls.append(("upload", path))
        if self.fail_uploads:
            raise StorageError("upload failed (fake)")
        if path in self.objects:
            raise StorageError("upload failed: exists")
        self.objects[path] = {"data": bytes(data), "content_type": content_type, "token": access_token}

    def signed_url(self, path: str, ttl_sec: int, access_token: str) -> str:
        self.calls.append(("signed_url", path))
        if self.fail_signed_urls or path not in self.objects:
            raise StorageError("signed_url failed (fake)")
        return f"https://storage.test/listing-photos/{path}?ttl={int(ttl_sec)}"

    def delete(self, paths: list[str], access_token: str) -> None:
        self.calls.append(("delete", list(paths)))
        if self.fail_deletes:
            raise StorageError("delete failed (fake)")
        for p in paths:
            self.objects.pop(p, None)


# ---------------------------------------------------------------- MemoryBroker
class MemoryBroker:
    def __init__(self) -> None:
        self.published: list[dict] = []
        self._subs: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []
        self._lock = threading.Lock()
        self.fail_publish = False

    def publish(self, row: dict) -> None:
        if self.fail_publish:
            raise ConnectionError("publish failed (fake)")
        row = copy.deepcopy(row)
        with self._lock:
            self.published.append(row)
            subs = list(self._subs)
        for loop, q in subs:
            try:
                loop.call_soon_threadsafe(q.put_nowait, row)
            except RuntimeError:
                pass  # 닫힌 루프

    async def subscribe(self):
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()
        entry = (loop, q)
        with self._lock:
            self._subs.append(entry)
        try:
            while True:
                yield await q.get()
        finally:
            with self._lock:
                if entry in self._subs:
                    self._subs.remove(entry)

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)


# ---------------------------------------------------------------- FakeAuthProvider
class FakeAuthProvider:
    def __init__(self, require_email_confirm: bool = False) -> None:
        self.require_email_confirm = require_email_confirm
        self.users: dict[str, dict] = {}          # email → {id, password, confirmed}
        self.tokens: dict[str, dict] = {}         # access_token → {sub, email}
        self.refresh_tokens: dict[str, str] = {}  # refresh_token → email
        self.signed_out: list[str] = []

    def add_user(self, email: str, password: str, *, confirmed: bool = True, auth_user_id: str | None = None) -> str:
        uid = auth_user_id or str(uuid.uuid4())
        self.users[email] = {"id": uid, "password": password, "confirmed": confirmed}
        return uid

    def issue_token(self, auth_user_id: str, email: str | None = None) -> str:
        token = f"test-token-{uuid.uuid4()}"
        self.tokens[token] = {"sub": auth_user_id, "email": email, "role": "authenticated"}
        return token

    def _session(self, email: str) -> AuthSession:
        u = self.users[email]
        access = self.issue_token(u["id"], email)
        refresh = f"test-refresh-{uuid.uuid4()}"
        self.refresh_tokens[refresh] = email
        return AuthSession(access_token=access, refresh_token=refresh, expires_at=int(time.time()) + 3600,
                           auth_user_id=u["id"], email=email)

    def sign_up(self, email: str, password: str) -> SignUpResult:
        if email in self.users:
            raise AppError(422, "VALIDATION_ERROR", "이미 가입된 이메일입니다. 로그인해 주세요.", {"reason": "user_already_exists"})
        uid = self.add_user(email, password, confirmed=not self.require_email_confirm)
        if self.require_email_confirm:
            return SignUpResult(needs_email_confirm=True, auth_user_id=uid, email=email)
        return SignUpResult(needs_email_confirm=False, auth_user_id=uid, email=email, session=self._session(email))

    def sign_in(self, email: str, password: str) -> AuthSession:
        u = self.users.get(email)
        if u is None or u["password"] != password:
            raise AppError(401, "INVALID_CREDENTIALS", "이메일 또는 비밀번호가 맞지 않습니다.")
        if not u["confirmed"]:
            raise AppError(403, "EMAIL_NOT_CONFIRMED", "메일 확인 후 로그인하세요.")
        return self._session(email)

    def sign_out(self, access_token: str) -> None:
        self.signed_out.append(access_token)
        self.tokens.pop(access_token, None)

    def refresh(self, refresh_token: str) -> AuthSession:
        email = self.refresh_tokens.pop(refresh_token, None)
        if email is None:
            raise AppError(401, "AUTH_REQUIRED", "로그인이 필요합니다. 다시 로그인해 주세요.")
        return self._session(email)

    def verify(self, access_token: str) -> dict[str, Any]:
        claims = self.tokens.get(access_token)
        if claims is None:
            raise AppError(401, "AUTH_REQUIRED", "로그인이 필요합니다. 다시 로그인해 주세요.")
        return dict(claims)

    def update_password(self, access_token: str, new_password: str) -> None:
        claims = self.verify(access_token)
        for u in self.users.values():
            if u["id"] == claims["sub"]:
                u["password"] = new_password
                return
        raise AppError(401, "AUTH_REQUIRED", "로그인이 필요합니다.")


# ---------------------------------------------------------------- FakePipeline
SAMPLE_MEMO = "역앞 원룸. 500에 45, 관리비 7(수도·인터넷 포함). 3층 남향. 채광 좋음, 곰팡이 없음. 수압 확인 못함."


def sample_ai_output(**overrides: Any) -> AnalysisAIOutput:
    data = dict(
        label="역앞 원룸",
        deposit_manwon=500, monthly_rent_manwon=45, maintenance_fee_manwon=7,
        maintenance_includes=["수도", "인터넷"],
        transit="역앞", floor="3층", direction="남향",
        pros=["채광 좋음"], cons=[],
        checks=[
            CheckItem(item="채광", status="confirmed", evidence="채광 좋음"),
            CheckItem(item="곰팡이", status="confirmed", evidence="곰팡이 없음"),
            CheckItem(item="수압", status="unchecked", evidence="수압 확인 못함"),
            CheckItem(item="층수", status="confirmed", evidence="3층"),
            CheckItem(item="교통", status="confirmed", evidence="역앞"),
        ],
        ambiguous=[], mixed_listings=False,
    )
    data.update(overrides)
    return AnalysisAIOutput(**data)


def success_outcome(ai: AnalysisAIOutput | None = None, **kw: Any) -> AnalysisOutcome:
    ai = ai or sample_ai_output()
    base = dict(result=build_result(ai), raw_output=ai.model_dump_json(), ai_latency_ms=120, status="success",
                error_code=None, cache_hit=False, prompt_version="v1", model="gemini-3.5-flash-lite",
                thinking_level="minimal")
    base.update(kw)
    return AnalysisOutcome(**base)


def failed_outcome(error_code: str = "AI_FORMAT_ERROR", raw_output: str | None = "{not json", **kw: Any) -> AnalysisOutcome:
    base = dict(result=None, raw_output=raw_output, ai_latency_ms=95, status="failed", error_code=error_code,
                cache_hit=False, prompt_version="v1", model="gemini-3.5-flash-lite", thinking_level="minimal")
    base.update(kw)
    return AnalysisOutcome(**base)


class FakePipeline:
    def __init__(self, outcome: AnalysisOutcome | None = None, *, raises: Exception | None = None) -> None:
        self.outcome = outcome or success_outcome()
        self.raises = raises
        self.calls: list[dict] = []

    async def run(self, memo_text: str, prompt_version: str, *, use_cache: bool = True,
                  cache_scope: str | None = None) -> AnalysisOutcome:
        self.calls.append({"memo_text": memo_text, "prompt_version": prompt_version,
                           "use_cache": use_cache, "cache_scope": cache_scope})
        if self.raises is not None:
            raise self.raises
        return self.outcome.model_copy(update={"prompt_version": prompt_version})
