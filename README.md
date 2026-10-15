# 집 보기 메모 비교 서비스

집 보기 메모를 입력하면 AI(Gemini)가 매물별 항목을 정해진 JSON으로 정리하고, 매물 비교표와 빠진 확인 항목을 보여 준다.
요청 로그 수집·실시간 전달·지표 계산·개선 전후 비교(“실시간 로그 대시보드 인터페이스”)를 함께 갖춘다.

- 화면: Streamlit (`frontend/`) · 서버: FastAPI (`backend/`) · DB·인증·파일: Supabase · 임시 상태: Redis 호환 저장소
- 개발 계약: [`docs/CONTRACT.md`](docs/CONTRACT.md) · 폴더 담당: [`docs/OWNERS.md`](docs/OWNERS.md)

## 1. 설치 (Python 3.12)

저장소 루트에서:

```bash
python -m venv .venv
source .venv/bin/activate            # Windows PowerShell: .venv\Scripts\Activate.ps1
python backend/scripts/check_merge.py check   # requirements.txt를 다시 만든다(첫 설치 전엔 import 단계에서 멈추는 게 정상)
pip install -r backend/requirements.txt -r frontend/requirements.txt
# uv를 쓰면: uv pip install -r backend/requirements.txt -r frontend/requirements.txt
```

`requirements.txt`는 손으로 고치지 않는다. 각 대화창이 `requirements/<단계>.txt`에 넣고 `check_merge.py check`가 합친다.

## 2. Supabase 준비

1. 프로젝트를 만들고 API 키 화면에서 **publishable key(`sb_publishable_…`)와 secret key(`sb_secret_…`)**를 확인한다. 레거시 `anon`·`service_role` 키는 쓰지 않는다.
2. SQL 편집기에 아래 파일을 **번호 순서대로** 붙여 실행한다(여러 번 실행해도 안전).
   `supabase/migrations/0001_core.sql` → `0002_ops.sql` → `0003_rls.sql` → `0006_photos.sql` → `0007_budget.sql`
   (0004·0005는 비워 둔 번호, 0120~·0130~·0140~은 이후 기능용 예약)
3. 가입 직후 바로 로그인하게 하려면 Auth의 이메일 확인(Confirm email) 설정을 끈다. 켜 두면 가입 후 “메일 확인 후 로그인하세요”가 나온다.

### 버킷 만들기

`0006_photos.sql`이 비공개 버킷 `listing-photos`를 SQL로 만들고 접근 정책을 건다. Supabase 문서는 storage 테이블을 API·대시보드로 다루도록 권하므로, 실행 결과에 `bucket insert skipped` 알림이 보이거나 Storage 화면에 버킷이 없으면 대시보드에서 만든다.

1. 대시보드 **Storage → New bucket**
2. 이름 `listing-photos`, **Public bucket 끔**(비공개)
3. 만든 뒤 `0006_photos.sql`을 한 번 더 실행해 정책을 확인한다(이미 있으면 그대로 둔다).

사진 경로 규칙은 `{auth_user_id}/{listing_id}/{파일이름}`이다. 첫 폴더가 본인 auth uid가 아니면 정책이 막는다.

### 운영자 지정

운영자(대시보드·평가 화면 접근)는 SQL 편집기에서 지정한다.

```sql
update public.profiles
   set role = 'admin'
 where auth_user_id = (select id from auth.users where email = 'admin@example.com');
```

되돌리기는 `set role = 'user'`. 바뀐 역할은 다음 로그인(또는 /me 조회)부터 화면에 반영된다.

## 3. 설정 파일

| 파일 | 위치 | 내용 |
| --- | --- | --- |
| `backend/.env` | `backend/.env.example` 복사 | Supabase URL·키, `REDIS_URL`, `GEMINI_API_KEY` |
| `.streamlit/secrets.toml` | **저장소 루트**의 `.streamlit/` (`secrets.toml.example` 복사) | `API_BASE_URL = "http://localhost:8000"` |

둘 다 git에 올리지 않는다(`.gitignore`). Streamlit은 실행 위치(저장소 루트)의 `.streamlit/`을 읽는다.

## 4. 로컬 실행

저장소 루트에서 차례로(각각 다른 터미널):

```bash
docker compose up -d                       # Redis 호환 저장소 (compose.yaml은 P8이 만든다)
cd backend && uvicorn app.main:app --reload --port 8000
streamlit run frontend/app.py              # 저장소 루트에서
```

- 서버 확인: `curl localhost:8000/health` → `{"status":"ok"}`, `curl localhost:8000/ready` → `{"db":true,"redis":true}`
- Redis가 없으면 `/ready`는 `redis:false`(200)이고 초안·캐시·실시간 로그만 멈춘다. DB가 안 되면 503.
- 자세한 로컬·배포 절차는 `docs/DEPLOY.md`(P8)의 “로컬 실행” 절.

## 5. 테스트와 합치기

```bash
cd backend && pytest -q                    # 외부 서비스 없이 돈다
```

대화창 결과 합치기(저장소 루트에서):

```bash
python backend/scripts/check_merge.py merge P1_output.zip P2_output.zip ...   # 기존 파일은 덮어쓰지 않고 '충돌'로 표시
python backend/scripts/check_merge.py merge --overwrite I1_patch.zip           # 통합 수정 패치
python backend/scripts/check_merge.py check                                     # requirements 생성·등록 점검·pytest → merge_report.txt
```

## 6. 개인정보

화면 맨 위에 “실제 주소·연락처·실명을 적지 마세요”를 띄운다. Gemini 무료 등급은 입력 내용이 Google 제품 개선에 쓰일 수 있다.
서버 로그·요청 로그·오류 응답에는 메모 원문·비밀번호·토큰·키를 남기지 않는다.
