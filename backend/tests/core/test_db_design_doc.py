"""docs/DB_DESIGN.md가 마이그레이션과 맞는지 확인한다(Issue #5).

1) 5절 테이블 명세: 테이블마다 컬럼 이름·순서·타입 = 마이그레이션의 최종 컬럼(ALTER ADD COLUMN 포함)
2) 3절 물리 ERD: 테이블마다 컬럼 이름·순서 = 마이그레이션, 관계선 수 = `references` 수
3) 2절 논리 ERD: 엔티티 속성 = 물리 테이블에서 FK 컬럼(`*_id`, request_id 제외)을 뺀 컬럼
4) 마이그레이션의 인덱스·이름 있는 제약이 문서에 모두 나온다
5) 모든 테이블·컬럼에 DB 코멘트(COMMENT ON)가 있다(Issue #6, 0011)

DB를 바꾸는 PR(테이블·컬럼·인덱스·FK 추가나 삭제)은 이 문서도 함께 고쳐야 통과한다.
마이그레이션에서 나중에 지운 테이블(`drop table if exists`)은 비교에서 뺀다.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS = ROOT / "supabase" / "migrations"
DOC = ROOT / "docs" / "DB_DESIGN.md"
DOC_NAME = "docs/DB_DESIGN.md"

TYPES = r"uuid|text\[\]|text|integer|smallint|bigint|timestamptz|date|jsonb|boolean|double precision"
CREATE = re.compile(r"create table if not exists public\.(\w+) \((.*?)\n\);", re.S)
COLUMN = re.compile(rf"^(\w+)\s+({TYPES})(?![\w\[])")
ADD_COLUMN = re.compile(rf"alter table public\.(\w+) add column if not exists (\w+) ({TYPES})(?![\w\[])")
DROP = re.compile(r"drop table if exists public\.(\w+)")
ERD_BLOCK = re.compile(r"^    (\w+) \{\n(.*?)\n    \}", re.S | re.M)
ERD_REL = re.compile(r"^    \w+ [|o}{]+--[|o}{]+ \w+ :", re.M)
SPEC_ROW = re.compile(r"^\| `(\w+)` \| ([^|]+?) \|", re.M)

LOGICAL_TO_PHYSICAL = {
    "AuthAccount": "auth_users", "User": "profiles", "TourSession": "tour_sessions", "Listing": "listings",
    "Analysis": "analyses", "Feedback": "feedback", "Photo": "photos", "SessionBudget": "session_budgets",
    "WeightProfile": "weight_profiles", "WeightItem": "weight_items",
    "ListingSatisfaction": "listing_satisfactions", "SessionScoring": "session_scoring",
    "ListingLocation": "listing_locations", "CommunityPost": "community_posts",
    "CommunityPostPhoto": "community_post_photos", "CommunityPostLike": "community_post_likes", "RequestLog": "request_logs", "EvalCase": "eval_cases",
    "EvalRun": "eval_runs", "EvalResult": "eval_results",
}


def _sql() -> str:
    return "\n".join(f.read_text(encoding="utf-8") for f in sorted(MIGRATIONS.glob("*.sql")))


def _tables(sql: str) -> dict[str, dict[str, str]]:
    tables: dict[str, dict[str, str]] = {}
    for m in CREATE.finditer(sql):
        cols: dict[str, str] = {}
        for line in m.group(2).splitlines():
            c = COLUMN.match(line.strip())
            if c and c.group(1) not in ("constraint", "primary"):
                cols[c.group(1)] = c.group(2)
        tables[m.group(1)] = cols
    for m in ADD_COLUMN.finditer(sql):
        tables[m.group(1)][m.group(2)] = m.group(3)
    for name in DROP.findall(sql):
        tables.pop(name, None)
    return tables


def _doc() -> str:
    assert DOC.exists(), f"{DOC_NAME}이 없습니다. DB 설계서를 옮겼다면 이 테스트의 DOC 경로도 고치세요."
    return DOC.read_text(encoding="utf-8")


def _between(text: str, start: str, end: str) -> str:
    assert start in text and end in text, f"{DOC_NAME}에서 '{start}' 또는 '{end}' 제목을 찾지 못했습니다."
    return text.split(start, 1)[1].split(end, 1)[0]


def _erd_blocks(section: str) -> dict[str, list[str]]:
    return {m.group(1): [line.split()[1] for line in m.group(2).splitlines()] for m in ERD_BLOCK.finditer(section)}


def test_spec_tables_match_migrations():
    tables = _tables(_sql())
    spec = _between(_doc(), "## 5. 테이블 명세", "## 6.")
    documented: dict[str, dict[str, str]] = {}
    for part in re.split(r"\n### 5\.\d+ ", spec)[1:]:
        name = re.match(r"`(\w+)`", part)
        assert name, f"{DOC_NAME} 5절 소제목은 '### 5.N `테이블` — 설명' 모양이어야 합니다: {part[:40]!r}"
        documented[name.group(1)] = {c: t.strip() for c, t in SPEC_ROW.findall(part)}
    assert set(documented) == set(tables), (
        f"{DOC_NAME} 5절 테이블 목록이 마이그레이션과 다릅니다. 문서에만: {sorted(set(documented) - set(tables))}, "
        f"마이그레이션에만: {sorted(set(tables) - set(documented))}")
    for name, cols in tables.items():
        assert list(documented[name]) == list(cols), f"{DOC_NAME} 5절 `{name}` 컬럼(순서 포함)이 다릅니다: {list(cols)}"
        wrong = {c: (t, documented[name][c]) for c, t in cols.items() if documented[name][c] != t}
        assert not wrong, f"{DOC_NAME} 5절 `{name}` 타입이 다릅니다(마이그레이션, 문서): {wrong}"


def test_physical_erd_matches_migrations():
    sql = _sql()
    tables = _tables(sql)
    erd = _between(_doc(), "## 3. 물리 ERD", "### 3.1")
    blocks = _erd_blocks(erd)
    blocks.pop("auth_users", None)
    assert set(blocks) == set(tables), f"{DOC_NAME} 물리 ERD 테이블이 다릅니다: {sorted(set(blocks) ^ set(tables))}"
    for name, cols in tables.items():
        assert blocks[name] == list(cols), f"{DOC_NAME} 물리 ERD `{name}` 컬럼(순서 포함)이 다릅니다: {list(cols)}"
    live = "\n".join(f.read_text(encoding="utf-8") for f in sorted(MIGRATIONS.glob("*.sql"))
                     if not any(t not in tables for t in re.findall(r"create table if not exists public\.(\w+)",
                                                                    f.read_text(encoding="utf-8"))))
    assert len(ERD_REL.findall(erd)) == live.count("references "), (
        f"{DOC_NAME} 물리 ERD 관계선 수가 마이그레이션의 FK(references) 수와 다릅니다.")


def test_logical_erd_matches_physical():
    doc = _doc()
    logical = _erd_blocks(_between(doc, "## 2. 논리 ERD", "### 2.1"))
    physical = _erd_blocks(_between(doc, "## 3. 물리 ERD", "### 3.1"))
    assert set(logical) == set(LOGICAL_TO_PHYSICAL), f"{DOC_NAME} 논리 ERD 엔티티가 다릅니다: {sorted(logical)}"
    for entity, table in LOGICAL_TO_PHYSICAL.items():
        expected = {c for c in physical[table] if not c.endswith("_id") or c == "request_id"}
        assert set(logical[entity]) == expected, (
            f"{DOC_NAME} 논리 엔티티 {entity}의 속성이 물리 테이블 `{table}`(FK 제외)과 다릅니다: {sorted(expected)}")


def test_indexes_and_named_constraints_documented():
    sql, doc = _sql(), _doc()
    dropped = set(DROP.findall(sql))
    names = re.findall(r"create index if not exists (\w+) on public\.(\w+)", sql)
    names += re.findall(r"add constraint (\w+)()", sql) + re.findall(r"constraint (\w+) (?:check|unique)()", sql)
    missing = sorted({n for n, t in names if t not in dropped and f"`{n}`" not in doc})
    assert not missing, f"{DOC_NAME}에 마이그레이션의 인덱스·제약 이름이 없습니다: {missing}"


COMMENT_TABLE = re.compile(r"comment on table public\.(\w+) is")
COMMENT_COLUMN = re.compile(r"comment on column public\.(\w+)\.(\w+) is")


def test_every_table_and_column_has_db_comment():
    """과제 기준 '모든 컬럼의 코멘트': 설계서뿐 아니라 실제 DB에도 COMMENT ON이 있어야 한다(Issue #6, 0011)."""
    sql = _sql()
    tables = _tables(sql)
    commented_tables = set(COMMENT_TABLE.findall(sql))
    commented_cols = set(COMMENT_COLUMN.findall(sql))
    missing_tables = sorted(set(tables) - commented_tables)
    missing_cols = sorted(f"{t}.{c}" for t, cols in tables.items() for c in cols if (t, c) not in commented_cols)
    assert not missing_tables, f"테이블 코멘트가 없습니다: {missing_tables}. 새 마이그레이션에 COMMENT ON TABLE을 넣으세요."
    assert not missing_cols, (f"컬럼 코멘트가 없습니다: {missing_cols}. {DOC_NAME} 5절과 같은 문장으로 "
                              "새 마이그레이션에 COMMENT ON COLUMN을 넣으세요.")
