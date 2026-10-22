# 집 보기 메모 비교 서비스

월세·전세 집을 여러 곳 보러 다니는 사람이 집마다 흩어진 메모를 입력하면, AI(Gemini)가 보증금·월세·관리비·장단점·체크리스트 9개 항목(채광·소음·수압·곰팡이·난방·층수·옵션·보안·교통)을 정해진 JSON으로 정리하고 매물 비교표와 빠진 확인 항목을 보여 준다.
과제 주제 "실시간 로그 대시보드 인터페이스"에 맞춰 요청 로그 수집·실시간 전달(SSE)·지표·사용자 피드백·개선 전후 비교를 함께 갖춘다.

- 과제: 웹 서비스 기초 및 AI 백엔드 개발 · 단위 프로젝트 1 (팀 3)
- 구성: 화면 Streamlit(`frontend/`) · 서버 FastAPI(`backend/`) · DB·인증·사진 Supabase · 초안·캐시·실시간 로그 Redis 호환 저장소(배포 Render Key Value, 로컬 Valkey)
- AI: `gemini-3.5-flash-lite`(무료 등급), 프롬프트 `backend/app/features/analysis/prompts/`

## 1. 최종 결과

| 항목 | 위치 |
| --- | --- |
| 저장소 | https://github.com/byeon2261/aio-03-p1-team3 |
| 배포 화면 (Streamlit Community Cloud) | https://aio-03-p1-team3-xqmxzsnatycg7fxy9agfvg.streamlit.app/ |
| 배포 서버 (Render) | https://house-tour-notes-api-6bb5.onrender.com (`/health`, `/ready`) |
| API 설계 문서 | [`docs/API_DESIGN.md`](docs/API_DESIGN.md) |
| 화면 설계서 | [`docs/SCREEN_DESIGN.md`](docs/SCREEN_DESIGN.md) |
| 데이터베이스 설계서 | [`docs/DB_DESIGN.md`](docs/DB_DESIGN.md) |
| 개선 전후 기록 | [`docs/IMPROVEMENT.md`](docs/IMPROVEMENT.md) |
| 배포 환경 검증 기록 | [Issue #9](https://github.com/byeon2261/aio-03-p1-team3/issues/9) |
| 발표 자료 | [`docs/presentation/골라방_발표_v3최종.pdf`](docs/presentation/골라방_발표_v3최종.pdf) |

무료 서버는 잠들어 있으면 첫 요청이 최대 1분 걸린다. 시연 전 깨우는 순서는 [`docs/DEPLOY.md`](docs/DEPLOY.md) 7절.

그 밖의 문서: [`docs/PROJECT_CONTEXT.md`](docs/PROJECT_CONTEXT.md)(과제 배경·현재 상태) · [`docs/CONTRACT.md`](docs/CONTRACT.md)(개발 계약) · [`docs/OWNERS.md`](docs/OWNERS.md)(폴더 담당) · [`docs/DEPLOY.md`](docs/DEPLOY.md)(배포) · [`docs/DEMO_CHECKLIST.md`](docs/DEMO_CHECKLIST.md)(시연) · [`docs/METRICS.md`](docs/METRICS.md)(지표 정의) · [`docs/EXTENSION.md`](docs/EXTENSION.md)(F12~F14) · [`docs/USABILITY_EVAL.md`](docs/USABILITY_EVAL.md)(체감 평가 양식)

## 2. 기능

| 기능 | 내용 |
| --- | --- |
| F1 인증 | 가입·로그인·토큰 갱신, 일반 사용자 / 운영자 역할 |
| F2 세션·매물 | 하루 동안 본 집을 세션으로 묶고 매물별 메모 저장 |
| F3 초안 | 저장 전 입력 내용을 Redis에 임시 보관·복원 |
| F4 AI 분석 | 메모 → 정해진 JSON(금액·장단점·체크리스트), 형식 검증, 형식 실패 시 1회 재시도, 캐시 |
| F5 재분석 | 메모가 바뀌면 다시 분석 필요 표시, 이전 수정값 안내 |
| F6 비교표 | 세션의 매물을 한 표로, 빠진 확인 항목 표시 |
| F7 수정·피드백 | AI 결과 칸 수정, 👍·👎 평가와 이유 |
| F8 운영 대시보드 | 요청 로그 실시간 전달(SSE·재연결·놓친 로그 재조회), 지표, 사용자 평가 사례 (운영자만) |
| F9 개선 전후 비교 | 같은 20개 평가 사례·모델·설정으로 프롬프트 버전별 정확도 비교 (운영자만) |
| F10 사진·마이페이지 | 매물 사진, 내 정보·내 사진·요약 |
| F11 예산 | 예산 필터, 숨긴 매물의 사유별 개수·다음 행동 안내 |
| F12 항목 가중치화 | 항목별 만족도 × 가중치 프로필 → 적합도 0~100점·순위 |
| F13 지도 | 매물 위치 저장, 세션 매물 지도, 전체 매물 지도 (카카오 지도) |
| F14 발품 후기 | 지번 주소별 후기 쓰기·목록·주소 검색·좋아요 |

## 3. 실행 명령

자세한 절차와 문제 해결은 [`docs/DEPLOY.md`](docs/DEPLOY.md). 명령은 모두 **저장소 루트**에서 시작한다(Python 3.12).

### 3-1. 설치

```bash
python -m venv .venv
source .venv/bin/activate            # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt -r frontend/requirements.txt
```

`requirements.txt`는 손으로 고치지 않는다. 패키지는 `backend/requirements/<단계>.txt`·`frontend/requirements/<단계>.txt`에 버전을 고정해 넣고 `python backend/scripts/check_merge.py check`로 다시 만든다.

### 3-2. 설정 파일 (git에 올리지 않음)

| 파일 | 만드는 법 | 넣을 값 |
| --- | --- | --- |
| `backend/.env` | `backend/.env.example` 복사 | Supabase URL·키, `GEMINI_API_KEY`, `REDIS_URL` |
| `.streamlit/secrets.toml` (저장소 루트) | `.streamlit/secrets.toml.example` 복사 | `API_BASE_URL = "http://localhost:8000"`, (지도) `KAKAO_JAVASCRIPT_KEY` |

### 3-3. DB 준비 (Supabase SQL Editor)

`supabase/migrations/`의 파일을 번호 순서대로 실행한다(여러 번 실행해도 안전).

`0001_core` → `0002_ops` → `0003_rls` → `0006_photos` → `0007_budget` → `0008_feedback_action` → `0009_listing_name` → `0010_listing_name_update` → `0011_comments` → `0120_scoring` → `0131_listing_locations` → `0132_drop_map_listings` → `0140_community` → `0141_community_likes`

운영자 지정:

```sql
update public.profiles
   set role = 'admin'
 where auth_user_id = (select id from auth.users where email = 'admin@example.com');
```

### 3-4. 로컬 실행 (터미널 3개)

```bash
docker compose up -d                                    # Redis 호환 저장소(Valkey)
cd backend && uvicorn app.main:app --reload --port 8000  # 서버
streamlit run frontend/app.py                           # 화면 (저장소 루트에서)
```

확인: `curl http://localhost:8000/health` → `{"status":"ok"}`, `curl http://localhost:8000/ready` → `{"db":true,"redis":true}`

### 3-5. 테스트 (PR 전에 반드시)

```bash
python backend/scripts/check_merge.py check   # requirements 생성 · 앱 import·등록 점검 · pytest
```

외부 서비스(Supabase·Redis·Gemini) 없이 돈다. PR마다 GitHub Actions가 같은 점검을 다시 돌린다.

### 3-6. 배포 서버 점검 (스모크 테스트)

```bash
export API_BASE_URL="https://house-tour-notes-api-6bb5.onrender.com"
export SMOKE_USER_EMAIL="user@example.com"   SMOKE_USER_PASSWORD="…"
export SMOKE_ADMIN_EMAIL="admin@example.com" SMOKE_ADMIN_PASSWORD="…"
python backend/scripts/smoke_test.py
```

Windows PowerShell은 `$env:API_BASE_URL = "…"`처럼 설정한다. 하는 일은 `docs/DEPLOY.md` 6-2.

## 4. 협업 방식

작업 등록(Issue) → 최신 `main`에서 브랜치(`feat/`·`fix/`·`docs/`) → PR(`.github/pull_request_template.md`) → GitHub Actions `check_merge` 통과 + 다른 팀원 1명 승인 → 병합 담당자(byeon2261)가 병합.
`main`에 병합되면 Render·Streamlit이 바로 자동 배포되므로, 새 마이그레이션이 든 PR은 병합 **전에** PR 작성자가 SQL을 실행한다. 규칙 전체는 [`CLAUDE.md`](CLAUDE.md).

## 5. 팀 기록 (결정 사항·문제 해결)

저장소의 커밋·PR 기록을 바탕으로 정리했다. 날짜는 병합일(서울 기준), 담당은 PR을 연 GitHub 아이디다.

| 날짜 | 구분 | 내용 | 관련 PR | 담당 |
| --- | --- | --- | --- | --- |
| 10-15 | 결정 | 기능 F1~F11을 단계별 작업으로 나눠 만든 뒤 하나로 합쳐 첫 커밋. 합칠 때는 `check_merge.py`로 파일 충돌·기능 등록·테스트를 한 번에 점검 | 첫 커밋 `e6ac9dc` | doomdiver100T |
| 10-16 | 결정 | Issue → 브랜치 → PR → 1명 승인 → 병합 담당자 병합 흐름과 PR 템플릿, PR마다 GitHub Actions로 `check_merge` 자동 점검 | #2 | doomdiver100T |
| 10-16 | 결정 | 새 마이그레이션이 든 PR은 병합 전에 PR 작성자가 배포 DB에서 SQL 실행(병합 즉시 자동 배포되므로) | #17 | doomdiver100T |
| 10-16 | 결정 | 적합도 점수는 만족도를 넣은 항목만 남은 가중치 비율로 계산, 프로필이 없으면 모든 항목 같은 비중. 평가 항목은 F12 안에 따로 두어 AI 분석·평가에 영향 없게 | #15, #19 | doomdiver100T |
| 10-17 | 결정 | 발품 후기는 개인 매물·메모와 연결하지 않고 지번 주소 단위로 공유. 제목·내용에 전화번호·이메일 모양이 있으면 거절, 응답에는 작성자 닉네임만 | #22 | youngeun3148437 |
| 10-18 | 문제 해결 | 배포 앱에서 '예산 안만 보기'가 숨긴 이유를 알려 주지 않음 → 판정 규칙은 그대로 두고 숨긴 사유별 개수와 다음 행동(예: "관리비 n만원 이하면 예산 안") 안내 | #24 | ej-park-dev |
| 10-18 | 결정 | 매물 주소는 메모와 따로 저장하고 AI에 보내지 않음. 지도 작업 PR 4개(#25~#28)를 하나로 합쳐 병합 | #29 | byeon2261 |
| 10-18 | 문제 해결 | 지도 컴포넌트를 모듈에 캐시해 'is not registered' 오류 → 캐시하지 않도록 수정 | #29 | byeon2261 |
| 10-19 | 결정 | 설계 문서가 코드와 어긋나지 않도록 문서·코드 일치 테스트 추가(API 설계서의 엔드포인트·오류 코드, DB 설계서의 컬럼·관계·인덱스) | #30, #35 | ej-park-dev, byeon2261 |
| 10-19 | 결정 | 과제 조건에 따라 새 Render 워크스페이스 주소 사용(화면 코드는 Secrets에서 주소를 읽으므로 코드 변경 없음) | #34 | doomdiver100T |
| 10-19 | 문제 해결 | 사이드바에 상세 화면까지 보여 메뉴가 복잡함 → 상세·쓰기 화면은 메뉴에서 숨기고 '←' 뒤로가기 버튼으로 이동 | #32 | byeon2261 |
| 10-19 | 문제 해결 | 전체 매물 지도의 정보 카드가 긴 글이면 밖으로 넘침 → 줄바꿈, 핀 이름표에 세션 이름 표시 | #33 | byeon2261 |
| 10-19 | 문제 해결 | 운영 대시보드에 👎만 보여 좋은 평가를 확인할 수 없음 → 👍·👎 필터 | #36 | youngeun3148437 |
| 10-19 | 문제 해결 | 매물마다 분석 버튼을 눌러야 비교표가 채워짐(같은 날 👎 피드백 "AI 정리를 눌러야 비교표가 완성되는 게 불편") → 세션 화면 [AI 정리] 일괄 버튼 | #37 | youngeun3148437 |
| 10-19 | 문제 해결 | 비교표 '관리비 포함' 칸이 예/아니오로 읽힘 → '포함 내역'으로 바꾸고 도움말 추가 | #39 | youngeun3148437 |
| 10-20 | 문제 해결 | v2 프롬프트가 v1 복사본이라 개선 전후 차이가 같은 프롬프트의 실행 편차였음 → 👎 사례·실패 사례를 근거로 v2를 실제로 고치고 서비스 기본 버전을 v2로 | #41 | doomdiver100T |
| 10-20 | 결정 | 세션 상세 매물 입력·수정 방식: 새 매물 메모는 '매물' 제목 옆 버튼과 모달로, 매물 이름 필수(`0009`), 매물 카드 연필 버튼으로 이름·메모 수정(`0010`), 세션 만들기 폼에 예산 입력. 섹션 순서는 매물 → 비교표 → 항목 가중치 → 적합도 순위 → 예산 | #43, #44, #46, #47, #48 | byeon2261 |
| 10-20 | 문제 해결 | 발품 후기 상세가 목록 페이지 안에 그려져 사이드바·뒤로가기가 마지막에 본 후기나 다른 페이지로 감 → 상세를 숨긴 별도 페이지로 나눠 연 곳의 목록으로 돌아가게 | #45 | byeon2261 |
| 10-20 | 문제 해결 | 화면 한 번에 같은 조회를 여러 번 함(세션 상세의 비교표 API 2번, 매물마다 분석·수정값·사진 서명 URL을 따로 조회, 요청마다 새 연결) → 한 번에 묶어 조회하고 연결을 재사용(응답·화면은 그대로) | #49~#54 | youngeun3148437 |
| 10-21 | 결정 | DB 설계서를 최신 마이그레이션에 맞추고, 모든 컬럼 코멘트를 실제 DB에도 반영(`0011_comments.sql`, 병합 전 배포 DB에서 실행). 코멘트가 빠지면 실패하는 검사 추가 | #55 | byeon2261 |
| 10-21 | 결정 | API·화면 설계서가 코드와 어긋나지 않도록 자동 일치 검사 추가(API 모델 필드, 화면 목록·섹션 순서·오류 코드) | #56 | byeon2261 |
| 10-21 | 문제 해결 | 수정된 v2도 남은 실패 4건이 모두 프롬프트에 있는 규칙을 모델이 따르지 않은 경우 → v3 프롬프트와 서버 후처리 규칙 S1~S4(v3 이상만), 서비스 기본 버전 v3. 같은 20건에서 필드 정확도 95.6→98.8%, 빠진 항목 정확도 75.0→95.0%(v1 대비, [`docs/IMPROVEMENT.md`](docs/IMPROVEMENT.md)) | #58 | doomdiver100T |
| 10-21 | 문제 해결 | 평가 실행 중 서버가 재배포되면 실행이 running으로 남아 30분 동안 새 실행이 막힘 → Supabase SQL로 failed 처리 후 재실행, 평가 중에는 병합·환경변수 저장을 하지 않음(코드 변경 없음, 팀 결정). SQL: `update public.eval_runs set status='failed', finished_at=now(), error_message='서버 재배포로 중단(수동 정리)' where status='running';` | 없음 | — |
| 10-21 | 문제 해결 | 배포 서버 스모크 테스트가 #46 이후 필수가 된 매물 이름을 보내지 않아 422로 실패 → 스크립트가 이름을 보내도록 고치고 테스트용 가짜 서버도 실제 서버처럼 이름을 검사 | #59 | doomdiver100T |

## 6. 배포 환경 검증 (2026-10-21)

최신 main(`8656167`)을 배포 서버(`https://house-tour-notes-api-6bb5.onrender.com`)에 대고 확인했다.

| 항목 | 결과 |
| --- | --- |
| 배포 서버 스모크 테스트 | 통과 12 · 경고 0 · 실패 0 (첫 실행은 스크립트 문제로 실패 → #59로 고친 뒤 재실행) |
| 의도한 오류 요청(없는 세션 조회 404)을 운영 로그에서 같은 요청 ID로 확인 | 확인 |
| 일반 계정의 `/admin` API 차단(403) | 확인 (화면 사이드바 차단은 10-20 확인) |
| 서비스 분석의 프롬프트 버전 | 최근 분석 요청 2건 모두 v3 |
| 서버 재시작 후 기록 유지 | 생략(팀 판단). 서비스 정상 동작은 위 스모크 테스트로 확인 |

상세 기록: [Issue #9](https://github.com/byeon2261/aio-03-p1-team3/issues/9)

## 7. 개인정보

화면 맨 위에 "실제 주소·연락처·실명을 적지 마세요"를 띄운다. Gemini 무료 등급은 입력 내용이 Google 제품 개선에 쓰일 수 있다.
서버 로그·요청 로그·오류 응답에는 메모 원문·비밀번호·토큰·키를 남기지 않는다. 키·`.env`·`secrets.toml`은 저장소에 올리지 않는다.
