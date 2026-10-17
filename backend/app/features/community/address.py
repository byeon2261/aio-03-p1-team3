"""주소 정리 규칙. 발품 후기가 쓰고, F13(지도) 등 주소를 다루는 다른 기능도 그대로 가져다 쓸 수 있다.

- normalize_address: 화면에 보여 줄 주소. 앞뒤 공백을 지우고 연속 공백을 하나로 줄인다.
- address_key: 검색용 키. 공백과 "번지"를 지우고 소문자로 바꾼다.
  "123번지 45"는 "123-45"로, "123번지"는 "123"으로 맞춘다.
  예) "예시시 예시구 예시동 123번지 45" → "예시시예시구예시동123-45"
- address_matches: 검색어 키가 주소 키 안에 들어 있으면(부분 일치) True.
"""

from __future__ import annotations

import re

_SPACES = re.compile(r"\s+")
# "123번지 45" → "123-45", "123번지" → "123"
_BUNJI_WITH_SUB = re.compile(r"(\d+)\s*번지\s+(\d+)")
_BUNJI = re.compile(r"(\d+)\s*번지")


def normalize_address(value: str) -> str:
    return _SPACES.sub(" ", (value or "").strip())


def address_key(value: str) -> str:
    v = normalize_address(value)
    v = _BUNJI_WITH_SUB.sub(r"\1-\2", v)
    v = _BUNJI.sub(r"\1", v)
    return _SPACES.sub("", v).lower()


def address_matches(query: str, key: str) -> bool:
    q = address_key(query)
    return bool(q) and q in (key or "")
