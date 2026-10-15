# 배포 가이드

위에서부터 순서대로 따라 한다. 0절은 배포 전에 내 컴퓨터에서 돌려 보는 절차이고, 1~7절이 배포다.

## 구성

| 구성 요소 | 배포처 | 연결 |
| --- | --- | --- |
| 화면 | Streamlit Community Cloud | GitHub 저장소, 진입점 `frontend/app.py`, secrets에 `API_BASE_URL`, 설정 파일은 저장소 루트 `.streamlit/config.toml` |
| 서버 | Render Free Web Service | GitHub 저장소, 루트 폴더 `backend`, uvicorn 실행, 헬스체크 `/health`(프로세스만 확인해 항상 200). DB·Redis 확인은 `/ready` |
| Redis | Render Key Value Free (Valkey 8) | 서버와 **같은 리전**의 내부 URL을 `REDIS_URL`로 (`render.yaml`이 자동 연결) |
| DB·인증·파일 | Supabase Free | 마이그레이션을 번호 순서로 실행 |

## 무료 등급 제약

| 서비스 | 제약 | 대응 |
| --- | --- | --- |
| Render Web Service | 15분간 들어오는 요청이 없으면 잠들고, 깨는 데 약 1분. 워크스페이스당 월 750시간(다 쓰면 그달 남은 기간 정지). 재시작·재배포·잠들 때 로컬 파일 삭제 | 시연 전 `/health` 호출. 파일은 Supabase Storage에만 저장 |
| Render Key Value | 메모리 전용, 재시작하면 데이터 삭제. 워크스페이스당 무료 1개 | 초안이 사라지면 화면이 “초안 만료”로 안내 |
| Streamlit Community Cloud | 12시간 접속이 없으면 잠듦 | 시연 전 앱 접속 |
| Supabase | 1주 비활성 시 일시정지, 업로드 파일당 50MB, 저장 1GB | 시연 주에 대시보드 접속 확인 |

확인일: 단계 파일 기준 2026-10-13. Render 두 항목은 2026-10-14에 [Render 무료 등급 문서](https://render.com/docs/free)로 다시 확인했다.

---

## 0. 로컬 실행 (배포 전 확인용)

준비물: Python 3.12, (선택) Docker. 명령은 모두 **저장소 루트**에서 시작한다.

### 0-1. 설치

```bash
python -m venv .venv
source .venv/bin/activate                         # Windows PowerShell: .venv\Scripts\Activate.ps1
python backend/scripts/check_merge.py check       # requirements.txt를 다시 만든다(설치 전이면 import 단계에서 멈추는 게 정상)
pip install -r backend/requirements.txt -r frontend/requirements.txt
# uv를 쓰면: uv pip install -r backend/requirements.txt -r frontend/requirements.txt
```

### 0-2. 설정 파일

| 파일 | 만드는 법 | 넣을 값 |
| --- | --- | --- |
| `backend/.env` | `backend/.env.example` 복사 | Supabase URL·키, `GEMINI_API_KEY`, `REDIS_URL=redis://localhost:6379` |
| `.streamlit/secrets.toml` (저장소 루트) | `.streamlit/secrets.toml.example` 복사 | `API_BASE_URL = "http://localhost:8000"` |

Supabase·Gemini 값은 2·3절에서 받는다. 두 파일은 git에 올리지 않는다(`.gitignore`에 있음).

### 0-3. 실행 (터미널 3개)

```bash
# 터미널 1 — Redis 호환 저장소(Valkey 8) 하나
docker compose up -d
docker compose ps                                 # valkey가 running(healthy)이면 된다

# 터미널 2 — 서버
cd backend && uvicorn app.main:app --reload --port 8000

# 터미널 3 — 화면 (저장소 루트에서 실행해야 루트의 .streamlit/을 읽는다)
streamlit run frontend/app.py
```

확인:

```bash
curl http://localhost:8000/health    # {"status":"ok"}
curl http://localhost:8000/ready     # {"db":true,"redis":true}
```

끄기: `docker compose down` (Valkey 데이터는 남기지 않는다. 초안·캐시가 지워지는 것은 정상).

### 0-4. Docker가 없을 때

`backend/.env`에서 `REDIS_URL` 줄을 지우거나 `#`으로 막고 서버를 띄운다.

- 되는 것: 로그인, 세션·메모 저장, 분석, 비교표, 수정·평가, 사진
- 안 되는 것: 초안 저장(503 `KV_UNAVAILABLE`), 분석 캐시, 운영 화면의 실시간 로그(목록·지표 조회는 DB에서 읽으므로 됨)
- `/ready`는 `{"db":true,"redis":false}`(200)

---

## 1. 계정 만들기

| 서비스 | 용도 | 주소 |
| --- | --- | --- |
| GitHub | 저장소(Render·Streamlit이 여기서 코드를 가져감) | https://github.com |
| Supabase | DB·인증·파일 | https://supabase.com |
| Render | 서버·Key Value | https://render.com |
| Streamlit Community Cloud | 화면 | https://share.streamlit.io |
| Google AI Studio | Gemini API 키 | https://aistudio.google.com |

Render와 Streamlit은 GitHub 계정으로 로그인하면 저장소 연결이 쉽다. 저장소에 모든 대화창 결과를 합친 뒤(`check_merge.py merge` → `check`) 커밋·푸시해 둔다. **`backend/requirements.txt`·`frontend/requirements.txt`는 `check_merge.py check`가 만든 최신본을 커밋해야** Render·Streamlit이 그 목록으로 설치한다.

---

## 2. Supabase

1. **New project**로 프로젝트를 만든다. 리전은 서버(Render `singapore`)와 가까운 **Southeast Asia (Singapore)**를 권한다. 사용자는 서버만 거치고 DB에 직접 붙지 않으므로, 서버↔DB 거리가 응답 속도를 좌우한다. DB 비밀번호는 따로 적어 둔다(앱 설정에는 쓰지 않음).
2. **SQL Editor**에서 아래 파일 내용을 하나씩 붙여 넣고 **번호 순서대로** 실행한다. 여러 번 실행해도 안전하다.
   1. `supabase/migrations/0001_core.sql`
   2. `supabase/migrations/0002_ops.sql`
   3. `supabase/migrations/0003_rls.sql`
   4. `supabase/migrations/0006_photos.sql`
   5. `supabase/migrations/0007_budget.sql`
   6. `supabase/migrations/0008_feedback_action.sql`

   0004·0005는 비워 둔 번호, 0120~·0130~·0140~은 이후 기능(F12~F14)용 예약 번호다.

   **이미 배포한 DB를 올릴 때**: 새 마이그레이션만 번호 순서대로 실행한 **뒤에** 새 서버를 배포한다. 예를 들어 `0008_feedback_action.sql`(feedback에 `action` 열 추가)을 실행하기 전에 새 서버가 뜨면, 수정·평가 저장이 “action 열 없음”으로 실패한다.
3. **버킷 확인**: Storage 화면에 비공개 버킷 `listing-photos`가 있는지 본다. 없거나 실행 결과에 `bucket insert skipped` 알림이 있으면 **Storage → New bucket**에서 이름 `listing-photos`, Public bucket 끔으로 만들고 `0006_photos.sql`을 한 번 더 실행한다.
4. **API 키 확인**: **Settings → API Keys**에서 publishable key(`sb_publishable_…`)와 secret key(`sb_secret_…`)를 복사한다. 레거시 `anon`·`service_role` 키는 쓰지 않는다. secret key는 서버(Render) 환경변수에만 넣고, 화면(Streamlit) secrets나 저장소에는 절대 넣지 않는다. 프로젝트 URL(`https://<프로젝트 ref>.supabase.co`)도 함께 적어 둔다.
5. **이메일 확인 설정**: Authentication의 **Sign In / Providers → Email**에 있는 **Confirm email**.
   - 끄면: 가입 직후 바로 로그인된다(시연용으로 권장).
   - 켜 두면: 가입 후 “메일 확인 후 로그인하세요”가 나오고, 메일의 링크를 눌러야 로그인된다.
6. **계정 2개 만들기**: 배포가 끝난 뒤(5절 이후) 앱 화면에서 가입한다. 스모크 테스트용 일반 계정 1개, 운영자 계정 1개.
7. **운영자 지정**: SQL Editor에서 운영자 계정의 이메일로 실행한다.

   ```sql
   update public.profiles
      set role = 'admin'
    where auth_user_id = (select id from auth.users where email = 'admin@example.com');
   ```

   되돌리기는 `set role = 'user'`. 바뀐 역할은 다음 로그인(또는 `/me` 조회)부터 화면에 반영된다.

---

## 3. Google AI Studio

1. AI Studio에 로그인해 API 키를 발급한다. 키는 Render 환경변수 `GEMINI_API_KEY`에만 넣는다.
2. **무료 등급 한도 확인**: [AI Studio의 Rate Limit 화면](https://aistudio.google.com/rate-limit)에서 `gemini-3.5-flash-lite`의 분당 요청 수(RPM)·일일 요청 수(RPD)·분당 토큰 수(TPM)를 본다. 무료 등급 수치는 [Gemini API 한도 문서](https://ai.google.dev/gemini-api/docs/rate-limits)에 고정값으로 나와 있지 않고 AI Studio에서만 보인다.
3. **`GEMINI_MIN_INTERVAL_SEC` 정하기**: 분석 요청 사이의 최소 간격(초)이다.

   `GEMINI_MIN_INTERVAL_SEC = 60 ÷ RPM` 을 올림한 값 (여러 명이 동시에 쓰는 시연이면 +1)

   예: RPM이 15면 60 ÷ 15 = 4 → `4`(기본값). RPM이 10이면 `6`. Render 환경변수에서 바꾸고 서버를 재시작하면 적용된다. 하루 한도(RPD)도 함께 본다. 분석 1건 = 호출 1번(캐시 적중은 0번), 스모크 테스트 1회 = 2번, 개선 전후 평가(P7)는 평가 사례 수만큼 쓴다.
4. **데이터 사용 안내**: 무료 등급(Unpaid Services)에서는 보낸 내용과 생성된 응답이 Google 제품을 제공·개선·개발하는 데 쓰이고, 사람 검토자가 입력·출력을 읽을 수 있다([Gemini API 추가 약관](https://ai.google.dev/terms)). 그래서 화면 맨 위에 “실제 주소·연락처·실명을 적지 마세요”를 띄우고, 시연·평가 메모도 가상의 내용으로 쓴다.

---

## 4. Render (서버 + Key Value)

### 4-1. Blueprint로 만들기 (권장)

저장소 루트의 `render.yaml`이 서버(`house-tour-notes-api`)와 Key Value(`house-tour-notes-kv`)를 함께 만든다.

1. Render 대시보드에서 **New → Blueprint**를 고르고 GitHub 저장소를 연결한다.
2. `render.yaml`을 읽어 두 서비스를 보여 준다. 입력 칸이 뜨는 값(아래 표의 “직접 입력”)을 채우고 적용한다. 이 입력 칸은 처음 만들 때만 뜬다. 나중에 바꿀 때는 서비스의 **Environment** 화면에서 고친다.
3. 첫 빌드가 끝나면 서버 주소(`https://house-tour-notes-api.onrender.com` 꼴, 이름이 이미 쓰였으면 뒤에 글자가 붙음)를 복사해 둔다.

`render.yaml`에 정한 것: 두 서비스 모두 리전 `singapore`(같은 리전이어야 내부 주소로 연결), 루트 폴더 `backend`, 빌드 `pip install -r requirements.txt`, 시작 `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, 헬스체크 `/health`, Key Value는 외부 접속 막음(`ipAllowList: []`).

### 4-2. 환경변수 (`backend/.env.example` 기준)

| 키 | 값 | 넣는 법 |
| --- | --- | --- |
| `SUPABASE_URL` | 2-4의 프로젝트 URL | 직접 입력 |
| `SUPABASE_PUBLISHABLE_KEY` | `sb_publishable_…` | 직접 입력 |
| `SUPABASE_SECRET_KEY` | `sb_secret_…` | 직접 입력 |
| `GEMINI_API_KEY` | 3-1의 키 | 직접 입력 |
| `REDIS_URL` | Key Value 내부 URL | 자동(`fromService`) |
| `PYTHON_VERSION` | `3.12.13` | 자동(Render는 패치 버전까지 요구) |
| `GEMINI_MIN_INTERVAL_SEC` | `4` | 자동, 3-3에서 정한 값으로 바꿀 수 있음 |
| `GEMINI_MODEL`, `GEMINI_THINKING_LEVEL`, `GEMINI_TIMEOUT_SEC`, `ACTIVE_PROMPT_VERSION`, `SIGNED_URL_TTL_SEC`, `MAX_PHOTO_MB`, `DRAFT_TTL_SEC`, `CACHE_TTL_SEC` | 코드 기본값(`gemini-3.5-flash-lite`, `minimal`, 30, `v1`, 600, 10, 86400, 604800) | 바꿀 때만 Environment에 추가 |

값이 빠지면 서버는 뜨지만 그 값을 쓰는 기능이 503 `CONFIG_MISSING`을 낸다.

### 4-3. 손으로 만들 때 (Blueprint를 못 쓸 때)

1. **New → Key Value**: 이름 `house-tour-notes-kv`, 리전 Singapore, 플랜 Free. 만든 뒤 **Internal URL**을 복사한다.
2. **New → Web Service**: 같은 저장소, 리전 **Singapore(Key Value와 같게)**, 플랜 Free, Root Directory `backend`, Build Command `pip install -r requirements.txt`, Start Command `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, Health Check Path `/health`.
3. 4-2의 환경변수를 넣고 `REDIS_URL`에는 1에서 복사한 Internal URL을 넣는다.

---

## 5. Streamlit Community Cloud (화면)

1. https://share.streamlit.io 에서 **Create app** → “Yup, I have an app”.
2. Repository·Branch를 고르고 **Main file path**에 `frontend/app.py`.
3. **Advanced settings**
   - Python version: **3.12**
   - Secrets: 아래 한 줄(4-1에서 복사한 서버 주소, 끝에 `/` 없이)

     ```toml
     API_BASE_URL = "https://house-tour-notes-api.onrender.com"
     ```
4. **Save** → **Deploy**.

알아 둘 것:

- 의존성 파일은 진입점 옆의 `frontend/requirements.txt`를 쓴다(Community Cloud는 저장소 루트 또는 진입점 옆의 파일을 읽는다). 저장소 루트에 `requirements.txt`를 따로 두지 않는다.
- 설정 파일은 저장소 루트의 `.streamlit/config.toml`이 적용된다(진입점이 하위 폴더여도 루트에 있어야 함). 작업 폴더도 항상 저장소 루트다.
- secrets를 나중에 바꿀 때는 앱의 **Settings → Secrets**에서 고친다.

---

## 6. 배포 후 확인

### 6-1. `/ready`로 DB·Redis 연결 확인

```bash
curl https://house-tour-notes-api.onrender.com/health   # 잠들어 있으면 1분쯤 걸린다 → {"status":"ok"}
curl https://house-tour-notes-api.onrender.com/ready    # {"db":true,"redis":true}
```

| 결과 | 뜻 | 할 일 |
| --- | --- | --- |
| 503, `db:false` | DB에 못 붙음 | Supabase 일시정지 여부, `SUPABASE_URL`·`SUPABASE_SECRET_KEY` 확인 |
| 200, `redis:false` | Key Value에 못 붙음 | `REDIS_URL`, 두 서비스의 리전이 같은지 확인 |

### 6-2. 스모크 테스트 (`backend/scripts/smoke_test.py`)

2-6·2-7에서 만든 일반 계정과 운영자 계정이 필요하다. 저장소 루트에서:

```bash
# bash
export API_BASE_URL="https://house-tour-notes-api.onrender.com"
export SMOKE_USER_EMAIL="user@example.com"   SMOKE_USER_PASSWORD="…"
export SMOKE_ADMIN_EMAIL="admin@example.com" SMOKE_ADMIN_PASSWORD="…"
python backend/scripts/smoke_test.py
```

```powershell
# Windows PowerShell
$env:API_BASE_URL = "https://house-tour-notes-api.onrender.com"
$env:SMOKE_USER_EMAIL = "user@example.com";   $env:SMOKE_USER_PASSWORD = "…"
$env:SMOKE_ADMIN_EMAIL = "admin@example.com"; $env:SMOKE_ADMIN_PASSWORD = "…"
python backend/scripts/smoke_test.py
```

하는 일: `/health`(최대 90초 대기) → `/ready` → 로그인 → 세션 생성 → 가상 메모 2개 → 각각 분석 → 월세 한 칸 수정 + 비추천(down) 평가 → 비교표에 수정값 반영 확인 → 운영자 로그인 → `/admin/logs`에서 분석 요청의 `X-Request-ID` 찾기 → `/admin/logs/stream`에 붙어 새 요청 이벤트 확인 → 테스트 세션 삭제.

- 단계마다 `[PASS]`·`[WARN]`·`[FAIL]`·`[SKIP]`과 걸린 시간을 찍는다. 한 단계가 실패하면 뒤 단계는 건너뛰지만 테스트 세션 삭제는 항상 시도한다.
- `/ready`에서 `redis:false`면 경고만 하고 계속하며, 실시간 스트림 단계는 경고로 건너뛴다.
- 종료 코드 0이면 통과(경고 허용), 1이면 실패가 있음, 2면 환경변수 누락.
- Gemini 호출을 2번 쓴다(캐시 끔). 선택: `SMOKE_FIRST_WAIT_SEC`(기본 90), `SMOKE_STREAM_WAIT_SEC`(기본 20).
- 출력에 토큰·비밀번호·메모 원문은 찍지 않는다. 로그아웃은 부르지 않는다(같은 계정으로 열어 둔 시연 화면이 풀리지 않게).

### 6-3. Redis Pub/Sub 동작 확인

스모크 테스트 11단계가 자동으로 확인한다. 화면으로도 본다.

1. 운영자 계정으로 **운영 대시보드**를 연다.
2. 다른 브라우저(또는 시크릿 창)에서 일반 계정으로 세션 목록을 열거나 메모를 저장한다.
3. 운영 대시보드의 실시간 로그에 방금 요청이 몇 초 안에 새 줄로 나타나면 된다.

---

## 7. 시연 전 깨우기 순서

시연 10분 전에 차례로:

1. **Supabase** 대시보드에 접속해 프로젝트가 일시정지(Paused)가 아닌지 본다. 일시정지면 Restore 후 몇 분 기다린다.
2. 서버 **`/health`** 호출(깨우기, 최대 1분).
3. **`/ready`**가 `{"db":true,"redis":true}`인지 확인.
4. **Streamlit 앱**에 접속(잠들어 있으면 깨우기 버튼이 나온다). 화면이 “서버를 깨우는 중”을 띄우면 1분 안에 넘어간다.
5. (권장) 스모크 테스트를 한 번 돌려 전체 흐름을 확인한다.

자세한 시연 순서는 `docs/DEMO_CHECKLIST.md`.

---

## 문제 해결

| 증상 | 원인 | 할 일 |
| --- | --- | --- |
| 화면이 “서버에 연결할 수 없습니다” | 서버가 잠들었거나 `API_BASE_URL`이 틀림 | `/health` 직접 호출, Streamlit secrets의 주소 확인(끝에 `/` 없이) |
| 분석이 429 `AI_RATE_LIMITED` | Gemini 무료 한도 초과 | 잠시 후 다시, `GEMINI_MIN_INTERVAL_SEC` 늘리기, AI Studio에서 RPD 확인 |
| 503 `CONFIG_MISSING` | 환경변수 빠짐 | 오류 detail의 `missing` 이름을 Render Environment에 추가 |
| 초안이 “초안 만료” | Key Value 재시작으로 내용 삭제(무료 등급은 메모리 전용) | 정상 동작. 메모는 저장 버튼으로 DB에 저장된 것만 남는다 |
| Render 서비스가 정지됨 | 월 750시간 소진 | 다음 달까지 기다리거나 다른 워크스페이스 사용 |
| 운영 화면에 실시간 로그가 안 옴 | `/ready`의 `redis:false` | `REDIS_URL`·리전 확인 |
| 수정·평가 저장이 실패(서버 로그에 `action` 열 없음) | `0008_feedback_action.sql`을 실행하지 않고 새 서버를 배포 | 2-2처럼 SQL Editor에서 `0008_feedback_action.sql` 실행(여러 번 실행해도 안전) |

## 확인 필요 (공식 문서로 끝까지 확인하지 못한 것)

- `PYTHON_VERSION=3.12.13`: 3.12.13이 나온 것은 확인했고, docs.python.org에는 3.12.15 문서가 올라와 있으나 python.org 배포 페이지에서 3.12.15를 직접 확인하지 못해 3.12.13으로 두었다. 더 새 패치로 올려도 된다(형식은 `3.12.x`).
- 무료 Web Service에서 헬스체크(`healthCheckPath`)가 동작하는지: Render 문서에 무료 등급 제외 문구는 없지만 지원한다는 문구도 찾지 못했다.
- Supabase 화면 이름: **Confirm email**이 Email 제공자 설정에 있다는 것은 문서로 확인했고, 메뉴 이름(“Sign In / Providers”)은 문서의 링크 경로에서 옮긴 것이다. 프로젝트 URL을 보여 주는 화면 이름도 확인하지 못했다.
- Render·Streamlit 버튼 이름(New → Blueprint, Settings → Secrets 등)은 문서 문구 기준이며 화면 개편으로 바뀔 수 있다.
- Streamlit Community Cloud 서버 위치(화면↔서버 거리)는 확인하지 못했다.

참고 문서(2026-10-14 확인): [Render Blueprint 문법](https://render.com/docs/blueprint-spec), [Render Python 버전](https://render.com/docs/python-version), [Render Key Value](https://render.com/docs/key-value), [Render 헬스체크](https://render.com/docs/health-checks), [Render FastAPI 배포](https://render.com/docs/deploy-fastapi), [Streamlit 파일 구성](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/file-organization), [Streamlit 앱 배포](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy), [Streamlit config.toml](https://docs.streamlit.io/develop/api-reference/configuration/config.toml), [Valkey 다운로드(도커 이미지)](https://valkey.io/download/), [Supabase API 키](https://supabase.com/docs/guides/api/api-keys), [Supabase Auth 설정](https://supabase.com/docs/guides/auth/general-configuration).
