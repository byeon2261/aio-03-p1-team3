"""docs/API_DESIGN.md가 코드와 맞는지 확인한다(Issue #3).

1) 4절 '엔드포인트 전체 목록' 표의 (메서드, 경로) = 앱의 OpenAPI (메서드, 경로)
2) 7.2절 '오류 코드 전체' 표 = 코드에서 내는 오류 코드와 HTTP 상태
3) 6절 '데이터 모델' 표마다 필드 이름·순서와 필수/선택 = 앱의 OpenAPI 스키마(Pydantic 모델)

API를 바꾸는 PR(엔드포인트 추가·삭제·경로 변경, 새 오류 코드, 모델 필드 추가·삭제·필수 여부 변경)은 이 문서도 함께 고쳐야 통과한다.
실패 메시지에 고칠 위치와 항목이 나온다.

오류 코드는 소스에서 `<상태>, "<코드>"`(AppError(404, "X", …), (502, "X", …)), `<상태>: "<코드>"`
(errors.py의 _HTTP_CODES), `_nf("<코드>"`(ownership.py, 404) 모양을 찾는다. 이 모양을 벗어나 오류를 내는
코드를 새로 만들면 이 검사가 놓칠 수 있으므로, 그때는 아래 정규식도 함께 고친다.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
APP_DIR = BACKEND / "app"
DOC = BACKEND.parent / "docs" / "API_DESIGN.md"
DOC_NAME = "docs/API_DESIGN.md"

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
ENDPOINT_ROW = re.compile(r"^\|\s*E\d+\s*\|\s*(GET|POST|PUT|PATCH|DELETE)\s*\|\s*`([^`]+)`\s*\|", re.MULTILINE)
ERROR_ROW = re.compile(r"^\|\s*`([A-Z][A-Z0-9_]+)`\s*\|\s*([^|]*?)\s*\|", re.MULTILINE)
CODE_WITH_STATUS = re.compile(r'\b([1-5]\d\d)\s*[,:]\s*"([A-Z][A-Z0-9_]{2,})"')
NOT_FOUND_HELPER = re.compile(r'\b_nf\(\s*"([A-Z][A-Z0-9_]{2,})"')
FALLBACK_CODES = {"HTTP_ERROR"}   # errors.py의 기본값. 상태 코드가 정해져 있지 않다


def _doc_text() -> str:
    assert DOC.exists(), f"{DOC_NAME}이 없습니다. API 설계 문서를 지우거나 옮겼다면 이 테스트의 DOC 경로도 고치세요."
    return DOC.read_text(encoding="utf-8")


def _section(text: str, heading: str, level: str, title: str) -> str:
    """'## 4.' 또는 '### 7.2' 제목부터 같은 수준 이상의 다음 제목 앞까지."""
    m = re.search(rf"^{level} {re.escape(heading)}\s.*$", text, re.MULTILINE)
    assert m, (f"{DOC_NAME}에서 '{level} {heading} {title}' 제목을 찾지 못했습니다. "
               f"제목 번호를 바꿨다면 backend/tests/core/test_api_design_doc.py도 함께 고치세요.")
    rest = text[m.end():]
    nxt = re.search(rf"^#{{1,{len(level)}}} ", rest, re.MULTILINE)
    return rest[: nxt.start()] if nxt else rest


def _code_endpoints() -> set[tuple[str, str]]:
    from app.main import create_app

    spec = create_app().openapi()
    return {(m.upper(), path) for path, ops in spec["paths"].items() for m in ops if m in HTTP_METHODS}


def _code_errors() -> dict[str, dict[int, set[str]]]:
    """오류 코드 → {HTTP 상태 → 나오는 파일들}."""
    found: dict[str, dict[int, set[str]]] = {}
    for f in sorted(APP_DIR.rglob("*.py")):
        src = f.read_text(encoding="utf-8")
        rel = f.relative_to(BACKEND.parent).as_posix()
        for status, code in CODE_WITH_STATUS.findall(src):
            found.setdefault(code, {}).setdefault(int(status), set()).add(rel)
        for code in NOT_FOUND_HELPER.findall(src):
            found.setdefault(code, {}).setdefault(404, set()).add(rel)
    return found


def test_doc_lists_every_endpoint_in_code():
    table = _section(_doc_text(), "4.", "##", "엔드포인트 전체 목록")
    rows = [(m, p) for m, p in ENDPOINT_ROW.findall(table)]
    assert rows, (f"{DOC_NAME} 4절 표에서 엔드포인트 행을 읽지 못했습니다. "
                  "행 모양은 '| E01 | GET | `/health` | … |'이어야 합니다.")

    dupes = sorted(k for k, n in Counter(rows).items() if n > 1)
    assert not dupes, (f"{DOC_NAME} 4절 표에 같은 엔드포인트가 두 번 있습니다. 한 행만 남기세요: "
                       + ", ".join(f"{m} {p}" for m, p in dupes))

    documented = set(rows)
    code = _code_endpoints()
    missing = sorted(code - documented, key=lambda x: (x[1], x[0]))
    extra = sorted(documented - code, key=lambda x: (x[1], x[0]))
    problems = []
    if missing:
        problems.append(
            f"{DOC_NAME} 4절 '엔드포인트 전체 목록' 표에 다음 엔드포인트를 추가하세요"
            f"(5절 기능별 상세와 6절 모델 표도 함께, 0절 엔드포인트 수도 고침):\n"
            + "\n".join(f"  - {m} {p}" for m, p in missing))
    if extra:
        problems.append(
            f"{DOC_NAME} 4절 표에 코드에 없는 엔드포인트가 있습니다. 행을 지우거나 메서드·경로를 코드와 같게 고치세요"
            f"(5절도 함께):\n" + "\n".join(f"  - {m} {p}" for m, p in extra))
    assert not problems, "\n\n".join(problems) + f"\n\n(코드 기준 {len(code)}개, 문서 표 {len(documented)}개)"


def test_doc_lists_every_error_code_in_code():
    table = _section(_doc_text(), "7.2", "###", "오류 코드 전체")
    doc_rows = ERROR_ROW.findall(table)
    assert doc_rows, (f"{DOC_NAME} 7.2절 표에서 오류 코드 행을 읽지 못했습니다. "
                      "행 모양은 '| `SESSION_NOT_FOUND` | 404 | … |'이어야 합니다.")
    doc: dict[str, str] = {}
    dupes = []
    for code, status in doc_rows:
        if code in doc:
            dupes.append(code)
        doc[code] = status
    assert not dupes, f"{DOC_NAME} 7.2절 표에 같은 오류 코드가 두 번 있습니다. 한 행만 남기세요: {', '.join(dupes)}"

    found = _code_errors()
    assert {"AUTH_REQUIRED", "VALIDATION_ERROR", "SESSION_NOT_FOUND", "INTERNAL_ERROR"} <= set(found), (
        "코드에서 오류 코드를 거의 찾지 못했습니다. 오류를 내는 방식이 바뀌었다면 "
        "backend/tests/core/test_api_design_doc.py의 정규식을 고치세요.")
    errors_src = (APP_DIR / "core" / "errors.py").read_text(encoding="utf-8")
    fallback = {c for c in FALLBACK_CODES if f'"{c}"' in errors_src}

    problems = []
    missing = sorted(set(found) - set(doc))
    if missing:
        problems.append(
            f"{DOC_NAME} 7.2절 '오류 코드 전체' 표에 다음 오류 코드를 추가하세요"
            f"(필요하면 5절 해당 엔드포인트의 주요 오류와 7.3·8절도 함께):\n"
            + "\n".join(f"  - {c} (HTTP {'·'.join(str(s) for s in sorted(found[c]))}, "
                        f"{', '.join(sorted(set().union(*found[c].values())))})" for c in missing))
    for c in sorted(fallback - set(doc)):
        problems.append(f"{DOC_NAME} 7.2절 표에 {c}(core/errors.py의 기본 오류 코드) 행을 추가하세요.")

    wrong = []
    for c in sorted(set(found) & set(doc)):
        doc_status = {int(x) for x in re.findall(r"\d{3}", doc[c])}
        if doc_status != set(found[c]):
            wrong.append(f"  - {c}: 표 '{doc[c]}' → 코드 {'·'.join(str(s) for s in sorted(found[c]))}")
    if wrong:
        problems.append(f"{DOC_NAME} 7.2절 표의 HTTP 상태를 코드와 같게 고치세요:\n" + "\n".join(wrong))

    extra = sorted(set(doc) - set(found) - fallback)
    if extra:
        problems.append(
            f"{DOC_NAME} 7.2절 표에 코드에서 내지 않는 오류 코드가 있습니다. 행을 지우거나 이름을 코드와 같게 고치세요:\n"
            + "\n".join(f"  - {c}" for c in extra))
    assert not problems, "\n\n".join(problems)


MODEL_HEAD = re.compile(r"^#### (\w+)", re.MULTILINE)
FIELD_ROW = re.compile(r"^\| `(\w+)` \| (?:[^|\\]|\\\|)+ \| (필수|선택) \|", re.MULTILINE)   # 타입 칸의 `\|`(예: string \| null) 허용


def test_doc_models_match_pydantic_models():
    """6절의 모델 표마다 필드 이름·순서·필수 여부가 실제 Pydantic 모델(OpenAPI 스키마)과 같은지."""
    from app.main import create_app

    schemas = create_app().openapi()["components"]["schemas"]
    section = _doc_text().split("## 6. 데이터 모델", 1)[1].split("\n## 7.", 1)[0]
    parts = re.split(r"\n(?=#### )", section)[1:]
    assert parts, f"{DOC_NAME} 6절에서 '#### 모델이름' 표를 찾지 못했습니다."
    problems = []
    for part in parts:
        name = MODEL_HEAD.match(part).group(1)
        if name not in schemas:
            problems.append(f"{name}: 코드에 없는 모델입니다(이름을 바꿨거나 지웠다면 6절도 고치세요)")
            continue
        rows = FIELD_ROW.findall(part)
        code_fields = list(schemas[name].get("properties", {}))
        required = set(schemas[name].get("required", []))
        if [f for f, _ in rows] != code_fields:
            problems.append(f"{name}: 문서 필드 {[f for f, _ in rows]} ≠ 코드 필드 {code_fields}")
            continue
        wrong = [f"{f}(문서 {need}, 코드 {'필수' if f in required else '선택'})"
                 for f, need in rows if (need == "필수") != (f in required)]
        if wrong:
            problems.append(f"{name}: 필수/선택이 다릅니다 {wrong}")
    assert not problems, f"{DOC_NAME} 6절 모델 표가 코드와 다릅니다:\n- " + "\n- ".join(problems)
