# CLAUDE.md — 이 저장소에서 작업하는 Claude가 따르는 팀 규칙

집 보기 메모 비교 서비스(Streamlit `frontend/` + FastAPI `backend/` + Supabase + Redis 호환 저장소)입니다.
팀원은 claude.ai/code에서 Claude에게 "수정"(기능 추가·수정·보수)을 맡기고, Claude는 브랜치와 PR로만 저장소를 바꿉니다.

## 1. 작업 시작 전에

- **`docs/PROJECT_CONTEXT.md`를 가장 먼저 읽습니다.** 과제 요구사항, 일정, 현재 상태, 남은 작업과 완료 기준이 들어 있습니다.
- 이어서 `docs/CONTRACT.md`(공통 함수·모델·엔드포인트·오류 코드)와 `docs/OWNERS.md`(폴더별 담당)를 읽습니다.
- 작업이 GitHub Issue 번호로 주어지면 그 Issue의 내용과 댓글을 읽고, 완료 기준을 그대로 따릅니다. PR 설명의 "관련 Issue"에 `Closes #번호`를 적습니다.
- 작업을 마쳐 남은 작업 표나 현재 상태가 바뀌면, 같은 PR에서 `docs/PROJECT_CONTEXT.md`의 해당 부분과 "마지막 갱신" 날짜도 고칩니다.
- 팀원이 역할분담(Issue 담당자) 변경을 요청하면 해당 Issue의 Assignees를 바꿉니다. 저장소 파일은 고치지 않습니다.
- 요청받은 범위 밖의 파일은 고치지 않습니다. 범위 밖 수정이 꼭 필요하면 고치기 전에 사용자에게 이유를 말하고 허락을 받습니다.
- 요청이 모호하거나, 사용자만 정할 수 있는 결정(화면 문구, 기능 범위, 데이터 구조 변경 등)이 있으면 추측하지 말고 먼저 질문합니다.

## 2. 브랜치·커밋·PR

- 항상 최신 `main`에서 새 브랜치를 만듭니다. 이름은 `feat/작업명`, `fix/작업명`, `docs/작업명` 중 하나로, 작업명은 영어 소문자와 하이픈으로 씁니다(예: `docs/api-design`).
- 작업 하나 = 브랜치 하나 = PR 하나. 서로 다른 작업을 한 PR에 섞지 않습니다.
- `main`에 직접 push하지 않습니다.
- 커밋 메시지는 한국어로, 앞에 `feat:`·`fix:`·`docs:`를 붙입니다(예: `docs: API 설계 문서 추가`).
- PR 설명은 `.github/pull_request_template.md` 양식을 모두 채웁니다(관련 Issue·병합 전에 할 일·변경 내용·실행 방법·확인 결과).
- **Claude는 PR을 병합하지 않습니다.** 다른 팀원 1명이 확인(승인)한 뒤 병합 담당자(변건형님)가 병합합니다.
- 작업을 마치면 사용자에게 PR 링크, 바꾼 파일 목록, 확인 결과를 짧게 알려 줍니다. PR에 새 마이그레이션이 있으면 3절의 "병합 전 SQL 실행" 안내를 **그보다 먼저, 맨 앞에** 보여 줍니다.

## 3. 담당 파일과 공통 파일

- 폴더별 담당은 `docs/OWNERS.md`를 따릅니다.
- 아래는 여러 기능이 함께 쓰는 공통 파일입니다. 고쳐야 하면 PR 설명의 "공통 파일 변경" 칸에 이유와 영향 받는 기능을 적고, 사용자에게 관련 담당자에게 리뷰를 요청하라고 안내합니다.
  - `backend/app/core/*`, `backend/app/main.py`, `backend/tests/conftest.py`, `backend/tests/fakes.py`
  - `frontend/app.py`, `frontend/core/*`
  - `supabase/migrations/*`(DB 스키마), `backend/app/core/schemas.py`(API 모델)
  - `backend/requirements/*`, `frontend/requirements/*`, `pyproject.toml`, `render.yaml`, `compose.yaml`, `.streamlit/config.toml`
- 새 마이그레이션은 기존 파일을 고치지 않고 다음 번호(`0009_…sql`부터)로 새 파일을 만듭니다. `0004`·`0005`와 `0120~`(F12)·`0130~`(F13)·`0140~`(F14)은 예약 번호라 다른 작업에 쓰지 않습니다(F12는 `0120_scoring.sql`부터 자기 번호대를 씁니다).
- **새 마이그레이션이 든 PR — 병합 전 SQL 실행**: Render 서버와 Streamlit 화면은 main에 병합되는 즉시 자동 배포됩니다(`render.yaml`의 `autoDeployTrigger: commit`). 그래서 마이그레이션은 **병합하기 전에** 배포 DB(Supabase SQL Editor)에서 실행해야 하고, 실행하는 사람은 PR을 연 사람입니다. `supabase/migrations/`에 파일을 추가하거나 바꾼 PR을 열 때 Claude는 다음을 지킵니다.
  1. PR 설명의 "병합 전에 할 일" 칸에 실행할 파일 이름(번호 순서), "Supabase SQL Editor에서 실행 → 실행 확인 → PR에 실행 완료 댓글 → 병합"을 적습니다.
  2. 사용자에게 작업 결과를 알릴 때 PR 링크보다 먼저, 맨 앞에 아래 안내를 그대로 보여 줍니다(`<파일>`만 바꿔서).

     > ⚠️ **병합하기 전에 SQL을 먼저 실행해 주세요.** 이 PR에는 새 마이그레이션 `<파일>`이 있습니다. main에 병합되면 서버가 바로 자동 배포되므로, 병합 전에 Supabase SQL Editor에서 이 파일 전체를 붙여 넣고 실행해 주세요(방법: `docs/DEPLOY.md` 2단계). 실행을 마치면 알려 주세요. PR에 '실행 완료' 댓글을 남겨 병합 담당자에게 알리겠습니다.

  3. 사용자가 실행을 마쳤다고 하면 PR에 `마이그레이션 실행 완료: <파일>` 댓글을 남깁니다. 병합 담당자는 이 댓글을 보고 병합합니다.
  4. 다른 작업 중에 새 마이그레이션이 든 PR이 실행 완료 댓글 없이 이미 병합된 것을 알게 되면, 하던 일을 멈추고 바로 사용자에게 "지금 SQL을 실행해야 한다"고 알립니다.
- API·DB·화면을 바꾸면 관련 문서(`docs/CONTRACT.md`, 설계 문서들)도 같은 PR에서 함께 고칩니다.

## 4. 의존성

- 패키지를 추가할 때는 `backend/requirements/<단계>.txt` 또는 `frontend/requirements/<단계>.txt`에 `==`로 버전을 고정해 적습니다.
- `backend/requirements.txt`와 `frontend/requirements.txt`는 직접 고치지 않습니다. `python backend/scripts/check_merge.py check`를 실행하면 다시 만들어지고, 그 결과를 함께 커밋합니다.

## 5. 실행과 확인 (PR 전에 반드시)

Python 3.12 기준, 저장소 루트에서:

```bash
pip install -r backend/requirements.txt -r frontend/requirements.txt
python backend/scripts/check_merge.py check
```

- `check`는 requirements 생성, 앱 import·등록 점검, `pytest -q`를 한 번에 돌립니다. 외부 서비스(Supabase·Redis·Gemini) 없이 통과해야 합니다.
- 통과하지 않으면 PR을 열지 않고 먼저 고칩니다. 고칠 수 없으면 사용자에게 오류 내용과 시도한 방법을 알립니다.
- 결과(통과한 테스트 수 등)를 PR 설명의 "확인 결과"에 적습니다. `merge_report.txt`는 커밋하지 않습니다.
- PR에서는 GitHub Actions(`.github/workflows/tests.yml`)가 같은 점검을 다시 돌립니다. 실패하면 로그를 보고 같은 브랜치에서 고칩니다.
- 새 기능에는 `backend/tests/<기능>/`에 테스트를 함께 추가합니다.

## 6. 비밀값과 개인정보

- `.env`, `.streamlit/secrets.toml`, 실제 API 키·토큰·비밀번호는 절대 커밋하지 않습니다. 새 환경변수는 `backend/.env.example`(또는 `secrets.toml.example`)에 이름과 설명만 적습니다.
- 코드·테스트·문서·예시 데이터에 실제 주소·연락처·실명·이메일을 넣지 않습니다.
- 로그와 오류 응답에 메모 원문·비밀번호·토큰·키를 남기지 않습니다.

## 7. 문서 작업

- 설계 문서는 실제 코드와 마이그레이션을 읽고 그 내용대로 씁니다. 코드에 없는 기능을 문서에 만들어 넣지 않습니다.
- 문서와 코드가 다르면 코드를 기준으로 쓰고, 차이를 PR 설명에 적어 사용자에게 알립니다.
- 그림(ERD·화면 흐름)은 GitHub에서 바로 보이는 Mermaid로 그립니다.
