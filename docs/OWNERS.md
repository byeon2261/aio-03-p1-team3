# OWNERS — 폴더와 만드는 대화창

```text
house-tour-notes/
├─ backend/
│  ├─ app/
│  │  ├─ main.py                     R
│  │  ├─ core/                       R  (계약: 설정·오류·인증·DB·KV·저장소·브로커·로그·등록)
│  │  └─ features/
│  │     ├─ auth/                    R   F1
│  │     ├─ sessions/ listings/ drafts/   P1  F2·F3
│  │     ├─ analysis/                P2  F4·F5
│  │     ├─ comparison/ feedback/    P3  F6·F7
│  │     ├─ photos/ mypage/          P4  F10 (담당 건형)
│  │     ├─ budget/                  P5  F11 (담당 은지)
│  │     ├─ admin_logs/              P6  F8
│  │     └─ evals/                   P7  F9
│  ├─ tests/conftest.py, fakes.py    R
│  ├─ tests/<기능>/                  그 기능을 만든 대화창
│  ├─ requirements/base.txt          R
│  ├─ requirements/<단계>.txt        추가 의존성이 있는 P만 (예: p2.txt)
│  └─ scripts/                       R: check_merge.py · P7: load_eval_cases.py, run_eval.py · P8: smoke_test.py
├─ frontend/
│  ├─ app.py, core/                  R
│  ├─ features/<기능>/               백엔드와 같은 대화창 (pages.py, sections.py, 부품)
│  └─ requirements/                  backend와 같은 규칙
├─ .streamlit/                       R: secrets.toml.example · P8: config.toml
├─ supabase/migrations/              R
├─ eval/                             P7
├─ docs/                             R: CONTRACT.md, OWNERS.md · P6: METRICS.md · P8: DEPLOY.md, DEMO_CHECKLIST.md, EXTENSION.md, USABILITY_EVAL.md
├─ compose.yaml                      P8 (로컬용 Redis 호환 저장소 하나)
├─ render.yaml                       P8
├─ .gitignore                        R
└─ README.md                         R
```

프론트 기능 폴더 이름: auth(R), sessions(P1), analysis(P2), comparison(P3), photos·mypage(P4), budget(P5), admin_logs(P6), evals(P7).

| 대화창 | 기능 | 백엔드 | 프론트 |
| --- | --- | --- | --- |
| R | 뼈대, F1 인증 | main.py, core/, features/auth | app.py, core/, features/auth |
| P1 | F2 세션·매물, F3 초안 | features/sessions, listings, drafts | features/sessions |
| P2 | F4 분석, F5 재분석 | features/analysis | features/analysis |
| P3 | F6 비교표, F7 수정·피드백 | features/comparison, feedback | features/comparison |
| P4 | F10 사진·마이페이지 | features/photos, mypage | features/photos, mypage |
| P5 | F11 예산 | features/budget | features/budget |
| P6 | F8 운영 로그 대시보드 | features/admin_logs | features/admin_logs |
| P7 | F9 평가(개선 전후 비교) | features/evals | features/evals |
| P8 | 배포·문서 | scripts/smoke_test.py | .streamlit/config.toml, compose.yaml, render.yaml |

F10은 건형, F11은 은지가 이후 다듬는다.

예약 번호: 마이그레이션 0004·0005는 비워 둠, 0120~ F12 · 0130~ F13 · 0140~ F14 (이번 범위 밖).
