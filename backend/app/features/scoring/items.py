"""F12 평가 항목 목록.

기본은 서비스 체크리스트(core.analysis_contract.CHECKLIST)와 같다. F12 안에 따로 두었으므로
여기만 바꾸면 점수 계산 항목만 바뀌고, AI 분석 프롬프트·평가(개선 전후 비교)에는 영향이 없다.

항목을 바꿀 때
- 추가: 기존 프로필에는 새 항목의 가중치 행이 없으므로 가중치 0으로 본다(사용자가 프로필을 고쳐 정한다).
- 삭제: DB에 남은 그 항목의 만족도·가중치 행은 계산·응답에서 무시한다(지우지 않는다).
- 이름은 1~30자(DB CHECK).
"""

from __future__ import annotations

from app.core.analysis_contract import CHECKLIST

SCORE_ITEMS: tuple[str, ...] = tuple(CHECKLIST)

__all__ = ["SCORE_ITEMS"]
