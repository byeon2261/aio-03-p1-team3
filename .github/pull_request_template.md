## 관련 Issue

<!-- 예: Closes #3 · 없으면 "없음" -->

## 병합 전에 할 일

<!-- supabase/migrations/에 파일을 추가하거나 바꿨다면: 실행할 파일(번호 순서).
     main에 병합되면 바로 자동 배포되므로, PR을 연 사람이 병합하기 전에 Supabase SQL Editor에서 실행하고
     PR에 "마이그레이션 실행 완료: 파일" 댓글을 남긴다(CLAUDE.md 3절). 없으면 "없음" -->

없음

## 변경 내용

<!-- 무엇을, 왜 바꿨는지 -->

-

## 실행 방법

<!-- 리뷰어가 같은 결과를 재현하는 방법 (명령, 눌러 볼 화면 등) -->

```bash
pip install -r backend/requirements.txt -r frontend/requirements.txt
python backend/scripts/check_merge.py check
```

## 확인 결과

<!-- 예: check_merge 통과, 427 passed / 화면에서 확인한 내용 -->

-

## 공통 파일 변경

<!-- CLAUDE.md 3절의 공통 파일을 고쳤다면: 파일, 이유, 영향 받는 기능. 없으면 "없음" -->

없음

## 리뷰어 확인 요청

<!-- 리뷰어가 특히 봐 줬으면 하는 부분 -->

-

---
병합 규칙: 다른 팀원 1명 승인 후 병합 담당자(변건형님)가 병합합니다.
