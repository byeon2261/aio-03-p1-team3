# CONTRACT — P 대화창은 이 파일 먼저

> I1(통합 확인)에서 고침: 합친 결과에 맞춘 등록 규칙(1·7절), 형식 실패 표기, 기능 폴더 상속 모델(3절), 실제 응답 모델·기본값(4절), 추가 오류 코드·eval 저장 방식(5절), api.py 401 처리(6절).
> I2(계약 변경)에서 고침: feedback `action` 열(0008)로 '수정 취소(revert)'와 '메모에 없음(set + null)' 구분(2·3·5절, repo·FeedbackIn/Out·P3 본문·P6 필드 수정 비율 최종 상태 기준), 삭제 전 이벤트 payload에 `storage` 추가(2절 events).
> F12(#14)에서 더함: 항목 가중치화 — 3절 상속 모델, 4절 엔드포인트, 5절 오류 코드·테이블, 6절 슬롯·열 key.
> F14(#21)에서 더함: 발품 후기 — 3절 모델, 4절 엔드포인트, 5절 오류 코드·테이블, 6절 페이지·마이페이지 탭.
> F11(#23)에서 더함: 예산 판정 상세 — 3절 모델, 4절 엔드포인트와 요청·응답 예시(판정 규칙·DB는 그대로).
> F13에서 더함: 동네 지도 탐색(옛 demo_st 이전) — 3절 모델, 4절 엔드포인트, 5절 테이블, 6절 페이지.
> F13에서 더함: 지도(옛 demo_st 이전, 이후 '전체 매물' 페이지로 바꿈, 서울역 더미 매물은 0132로 삭제) — 3절 모델, 4절 엔드포인트, 5절 테이블, 6절 페이지.
> F13에서 더함: 내 매물 위치 — 3절 모델, 4절 엔드포인트, 5절 테이블, 6절 슬롯(listing_detail 50, 세션 상세 매물 목록 옆 지도).

R이 만든 파일(`backend/app/core/*`, `backend/app/main.py`, `backend/tests/conftest.py`·`fakes.py`, `frontend/app.py`, `frontend/core/*`, `supabase/migrations/*`)은 고치지 않는다. 바꿀 것이 있으면 REPORT "계약 변경 요청"에 적고 계약 안에서 우회한다.

## 1. 자동 등록
- 백엔드: `app/features/<이름>/router.py`의 `router`(APIRouter)를 이름순 등록. `hooks.py`는 import 시 등록 코드 실행(앱을 다시 만들면 다시 읽는다 → 등록 코드는 여러 번 돌아도 안전해야 함. R의 register_*·events.on은 같은 key·처리기를 바꿔 끼운다).
  - 기본 구현을 넣는 hooks는 이미 등록된 것이 있으면 덮지 않는다(P2 `analysis/hooks.py`: 파이프라인이 비어 있을 때만 Gemini 파이프라인 등록). 그래서 테스트에서 `register_pipeline(FakePipeline())`을 `client_as()` 앞에 불러도 유지된다.
- 프론트: `frontend/features/<이름>/pages.py`의 `PAGES`, `sections.py`의 `SECTIONS`. import 시 st 함수를 부르지 않는다.
  - PAGES 항목 `{"key","title","order","admin_only","render"}` (key는 `[a-z0-9_]`, URL 경로로 씀). 선택 `"hidden": True`면 사이드바 메뉴에 안 보이고 버튼(`nav`)으로만 간다
  - SECTIONS 항목 `{"slot","order","render(ctx)"}`
- 의존성: 추가 패키지는 `backend/requirements/<단계>.txt`·`frontend/requirements/<단계>.txt`(버전 고정 `==`). `requirements.txt`는 `check_merge.py check`가 만든다.
- 프론트 import 기준은 `frontend/`다: `from core.api import api_get`, `from features.sessions.x import y`.

## 2. 공통 함수 (backend/app/core)
| 모듈 | 이름 | 설명 |
|---|---|---|
| config | `settings`, `settings.require(*names)` | 4절 키. 값 없으면 503 CONFIG_MISSING |
| errors | `AppError(status, code, message, detail=None)` | 응답 `{"error":{"code","message","detail":{"request_id",…}}}`. 미처리 예외 500 INTERNAL_ERROR. detail에 원문·토큰 금지 |
| auth | `CurrentUser(auth_user_id, profile_id, role, access_token)`, `get_current_user`, `require_admin`, `ensure_profile(admin_db, auth_user_id, email)` | Depends로 사용 |
| auth_provider | `get_auth_provider()` → `sign_up/sign_in/sign_out/refresh/verify/update_password(access_token, new_password)` | 실패 시 AppError |
| db | `get_user_db`(RLS), `get_admin_db`(secret), `Database.select(table, filters=None, *, order_by=None, desc=False, limit=None)`, `insert(table, rows)`, `update(table, filters, values)`, `delete(table, filters)`, `UniqueViolation`, `is_valid_uuid` | 모두 `list[dict]`. filters: 값=eq, list=IN(빈 리스트→결과 없음), `("gte"/"lte"/"gt"/"lt", v)`, `("is", None)` 또는 None=IS NULL. date·datetime·UUID는 자동 ISO 문자열. 반환 시각은 ISO 문자열 |
| kv | `get_kv()`, `kv_available()`, `KV.get/set(key, value:str, ttl_sec)/delete(*keys)/exists` | 값은 문자열(json.dumps). Redis 장애 시 메서드가 503 KV_UNAVAILABLE. 캐시처럼 없어도 되는 기능은 `kv_available()` 먼저 |
| storage | `get_storage()`, `upload(path, data, content_type, access_token)`, `signed_url(path, ttl_sec, access_token) -> str`, `delete(paths, access_token)`, `StorageError` | 버킷 `listing-photos`. 경로 `{auth_user_id}/{listing_id}/{파일}` (첫 폴더=auth.uid() 필수) |
| broker | `publish_log(row)`, `subscribe_logs()`, `get_broker()` | async iterator. REDIS_URL 없으면 첫 반복에서 503 KV_UNAVAILABLE. 스트림을 열기 전 확인은 `get_broker() is None`이면 503(P6, 스트림이 시작된 뒤엔 상태 코드를 못 바꿈) |
| request_log | `set_log_fields(request, ai_latency_ms=, prompt_version=, cache_hit=, error_code=)` | AI 형식 실패는 error_code="FMT"(아래 '형식 실패 표기'). 안 넘기면 AppError code가 자동 기록 |
| ownership | `get_owned_session/listing/analysis/photo(db, user, id)` | 없거나 타인 → 404. listing은 `["session"]`, analysis·photo는 `["listing"]["session"]` 포함 |
| repo | `list_listings(db, sid)`, `latest_analysis(db, lid, status="success")`, `field_overrides(db, aid)`, `overrides_from_rows(rows)`, `is_revert(row)`, `latest_rating(db, aid)` | status=None→상태 무관 최신. overrides: 필드별 최신 행 기준 — `action="revert"`면 키 없음(AI 값), `action="set"`이면 `{필드: corrected_value}`(값 None = 메모에 없음, 키는 남음). action 없는 0008 이전 행은 corrected_value null을 revert로 본다. `overrides_from_rows`는 created_at 오름차순 행에 같은 규칙(P6 지표가 씀). rating: field_name null인 최신 행의 rating |
| values | `MONEY_FIELDS`, `effective_values(result_json, overrides)`, `monthly_cost(values)` | 덮어쓰기는 EDITABLE_FIELDS만(overrides 값 None이면 None으로 덮음 = 미기재). 월세+관리비, 하나라도 None이면 None |
| analysis_contract | `CHECKLIST`, `CHECK_STATUSES`, `SCHEMA_VERSION="1"`, `CheckItem`, `AnalysisAIOutput`, `AnalysisResult`, `build_result(ai)`, `classify_checks(checks)`, `SCHEMA_REGISTRY`, `EDITABLE_FIELDS`, `EVAL_FIELDS`, `memo_hash(text)`, `needs_reanalysis(listing, analysis)`, `AnalysisOutcome`, `AnalysisPipeline`, `register_pipeline`, `get_pipeline`, `reset_pipeline`(테스트용) | 아래 |
| registry | `ColumnValue(display, status=None, tone="default")`, `ColumnProvider(key, title, compute, order=100)`, `register_column_provider`, `get_column_providers`, `register_row_filter(name, fn)`, `get_row_filter(name)` | compute(*, db, user, session, rows) → {listing_id: ColumnValue}. 필터 fn(*, db, user, session, rows) → 남길 listing_id set. rows 항목: listing_id, listing_no, label, analysis_status, needs_reanalysis, values. 여기 `values`는 effective_values 전체 + `monthly_cost_manwon`·`followup_checks`(분석 없으면 {}). 응답 `ComparisonRow.values`는 비교표 11개 열 key만(P3) |
| events | `on(event, handler)`, `emit(event, **payload)` | `session.before_delete`(db, user, session, listing_ids, storage), `listing.before_delete`(db, user, listing, storage). storage는 삭제 엔드포인트(P1)가 `Depends(get_storage)`로 받아 넘긴 것(dependency_overrides를 따름, I2). 처리기는 키워드 인자로 받고 `**kw`도 받는다(인자가 늘어도 안전). 예외는 emit이 올리고 호출한 쪽은 삭제를 멈추고 그 오류를 응답 |

분석 계약
- `CHECKLIST=("채광","소음","수압","곰팡이","난방","층수","옵션","보안","교통")`, 상태 confirmed(분명함, "곰팡이 없음" 포함)·unchecked("확인 못함")·ambiguous.
- `AnalysisAIOutput`: label, deposit_manwon·monthly_rent_manwon·maintenance_fee_manwon(int|None), maintenance_includes, transit·floor·direction(str|None), pros, cons, checks(CheckItem: item, status, evidence), ambiguous, mixed_listings. Field description에 규칙(한국어).
- `AnalysisResult` = AI 출력 + confirmed_checks·unchecked·ambiguous_checks·missing_checks(서버 계산, `build_result`). 네 목록은 겹치지 않고 합치면 CHECKLIST(검증기). 한 항목에 상태가 여럿이면 ambiguous.
- `EDITABLE_FIELDS`: 금액 3, maintenance_includes, transit, floor, direction, pros, cons. `EVAL_FIELDS`: 금액 3, maintenance_includes, unchecked, missing_checks, floor, direction.
- `memo_hash` = sha256(strip(text)+SCHEMA_VERSION). `needs_reanalysis`: 분석이 있고 해시가 다르면 True(보통 `latest_analysis(status=None)`을 넘김).
- `AnalysisOutcome`: result, raw_output, ai_latency_ms, status(success/failed), error_code, cache_hit, prompt_version, model, thinking_level.
- `AnalysisPipeline.run(memo_text, prompt_version, *, use_cache=True, cache_scope=None)` (async). cache_scope=None이면 캐시 읽기·쓰기 안 함. 등록 없으면 `get_pipeline()` 503 CONFIG_MISSING. 실패는 예외가 아니라 `AnalysisOutcome(status="failed", error_code=…)`로 돌려준다. API 키가 없거나 Gemini가 401·403이면 503 CONFIG_MISSING 예외(P2).
- 형식 실패 표기: `AnalysisOutcome.error_code`는 `AI_FORMAT_ERROR`(`FMT`도 같은 뜻으로 받는다) → HTTP 응답 502 `AI_FORMAT_ERROR`, `analyses.error_code`·`request_logs.error_code`는 `FMT`, `eval_results.status`는 `AI_FORMAT_ERROR`·`failure_codes`는 `FMT`. 실패 여부는 코드가 아니라 `status`로 판단한다.

설정 키: SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, SUPABASE_SECRET_KEY, REDIS_URL, GEMINI_API_KEY, GEMINI_MODEL=gemini-3.5-flash-lite, GEMINI_THINKING_LEVEL=minimal, GEMINI_TIMEOUT_SEC=30, GEMINI_MIN_INTERVAL_SEC=4, ACTIVE_PROMPT_VERSION=v2, SIGNED_URL_TTL_SEC=600, MAX_PHOTO_MB=10, DRAFT_TTL_SEC=86400, CACHE_TTL_SEC=604800.

## 3. 모델 (backend/app/core/schemas.py)
교차 모델
- `SessionOut`: id, title, visit_date, created_at, listing_count
- `ListingOut`: id, session_id, listing_no, label("N번 집"), memo_text, memo_updated_at, created_at, latest_analysis_status(none/success/failed), needs_reanalysis
- `FieldValue`: ai_value, user_value, value, edited (edited이고 user_value null = 사용자가 '메모에 없음'으로 고침, value도 null)
- `AnalysisOut`: id, listing_id, status, error_code, prompt_version, model, thinking_level, schema_version, created_at, fields(dict[str, FieldValue]: EDITABLE_FIELDS+label), checks, confirmed_checks, unchecked, ambiguous_checks, missing_checks, ambiguous, mixed_listings, rating, needs_reanalysis, previous_overrides
- `ComparisonRow`: listing_id, listing_no, label, analysis_status, needs_reanalysis, values, columns(dict[str, ColumnValue])
- `ComparisonOut`: session_id, enough_listings, message, fields·providers(list[FieldTitle{key,title}]), rows, lowest({monthly_rent_manwon|maintenance_fee_manwon: [listing_id]}), hidden_count({filter: int})

그 밖: OkOut{ok}, SignupIn/LoginIn{email, password(6~72)}, RefreshIn, ProfileOut{id,nickname,role}, AuthTokensOut{access_token, refresh_token, expires_at(Unix 초), profile}, SignupOut{needs_email_confirm, +AuthTokensOut 필드(없으면 null)}, SessionCreateIn{title(1~100), visit_date}, SessionUpdateIn(둘 다 선택, `model_fields_set`로 구분), ListingCreateIn{name(필수 1~30, 예: "1번방"), memo_text(≤5000)}, ListingUpdateIn{memo_text, name(선택 1~30, 생략하면 그대로)}, DraftIn{memo_text}, DraftOut{memo_text, saved_at, expires_at}, AnalysisCreateIn{use_cache=True}, FeedbackIn{field_name, corrected_value, action(set|revert, field_name 있을 때만·생략 시 set), rating, reason, comment(≤500)}, FeedbackOut(+action: 필드 수정 행 set|revert, 전체 평가 행 null), PhotoOut{id, listing_id, content_type, size_bytes, visibility, created_at, url, url_expires_at}, MyPhotoOut(+session_id, session_title, listing_no, listing_label), MeUpdateIn{nickname(1~30)}, PasswordChangeIn{new_password}, MySummaryOut{session·listing·analysis·photo·feedback_count}, BudgetIn/BudgetOut{deposit_max_manwon, monthly_max_manwon(월세+관리비 기준), updated_at}, RequestLogOut, MetricsOut{window_minutes, request_count, error_rate, p50/p95_latency_ms, ai_p50/ai_p95_latency_ms, cache_hit_rate, format_error_rate, extra}, FeedbackAdminOut(+listing_id, prompt_version), EvalRunCreateIn{prompt_version, case_keys}, EvalRunOut, EvalResultOut, EvalResultsOut{run, compare_run, results}. 상수 MEMO_MAX_CHARS=5000.

기능 폴더의 상속 모델(계약 모델을 넓힌 것, 응답 최상위는 부모 모양을 유지)
- P3 `features/feedback/schemas.py`: `FeedbackCreateIn`(FeedbackIn + `corrections: [{field_name, action, corrected_value}]`. 한 필드 모양 `{field_name, action, corrected_value}`도 받아 corrections 하나로 본다. `action`은 `"set"`(기본)·`"revert"`. set은 corrected_value 키 필수이고 null = 메모에 없음(금액 3개·transit·floor·direction만, 목록은 `[]`). revert = 수정 취소(AI 값으로 되돌림), corrected_value는 생략 또는 null. field_name 없이 action만 보내면 422), `FeedbackSaveOut`(FeedbackOut 대표 행 + `items: list[FeedbackOut]` 이번에 저장한 모든 행)
- P6 `features/admin_logs/feedback_cases.py`: `FeedbackCaseOut`(FeedbackAdminOut + `memo_head`, `analysis_summary`)
- P7 `features/evals/schemas.py`: `EvalRunSummaryOut`(EvalRunOut + failure_counts, result_count, error_case_count), `EvalResultDetailOut`(EvalResultOut + case_id, memo_text, criteria, expected_json, mixed_listings_match, compare_output_json, compare_mixed_listings_match), `EvalCompareOut`(EvalResultsOut + condition_mismatches, run·compare_run은 EvalRunSummaryOut, results는 EvalResultDetailOut)
- F12 `features/scoring/schemas.py`(계약 모델을 상속하지 않는 새 모델): `WeightProfileIn{name(1~30, 앞뒤 공백 제거), weights: [WeightItemIn{item_key, weight(0~100)}]}`(빠진 항목은 0), `WeightProfileOut{id, name, weights: [WeightItemOut] (SCORE_ITEMS 전체·순서), created_at, updated_at}`, `SatisfactionIn{items: [SatisfactionItemIn{item_key, satisfaction(0~100)}]}`(빠진 항목 = 미입력, 통째로 바꿈), `SatisfactionOut{listing_id, items: [SatisfactionItemOut{item_key, satisfaction|null}], entered_count, updated_at}`, `ScoringSettingIn{enabled, weight_profile_id|null}`, `ScoringSettingOut{session_id, enabled(기본 true), weight_profile_id, weight_profile_name, updated_at, items}`, `ScoresOut{session_id, setting: ScoringSettingOut, items, rows: [ScoreRow{listing_id, listing_no, label, score|null, rank|null, entered_count, total_items}], hidden_count}`. item_key는 `features/scoring/items.py`의 `SCORE_ITEMS`(기본 = CHECKLIST) 중 하나, 아니거나 중복이면 422
- F14 `features/community/schemas.py`(새 모델): `PostIn{address(1~200), topic, title(1~100), body(1~3000), floor|null(-10~200, 0 제외), visit_date|null}`(글자는 앞뒤 공백 제거, 제목·본문에 전화번호·이메일 모양이 있으면 422 reason `contact_info`), `PostUpdateIn`(보낸 칸만 바꿈, 필수 칸은 null 불가), `PostSummaryOut{id, address, floor, topic, visit_date, title, nickname, is_mine, has_photo, like_count, liked_by_me, created_at, updated_at}`, `PostOut`(PostSummaryOut + body, photo: `PostPhotoOut{id, content_type, size_bytes, url, url_expires_at}`|null), `PostLikeOut{post_id, like_count, liked_by_me}`, `TopicsOut{topics}`. topic은 `구조·설비`·`소음`·`채광`·`주변 환경`·`기타`. 작성자 id·이메일은 응답에 넣지 않는다
- F11 `features/budget/schemas.py`(새 모델): `BudgetEvaluationsOut{session_id, budget_set, counts: BudgetCountsOut{within, over, unknown}, items: [BudgetEvaluationOut{listing_id, listing_no, label, status(within|over|unknown|null), status_label, reason, missing: list[str], next_action|null}]}`. status·reason은 `service.evaluate` 그대로(비교표 `budget` 열·`within_budget` 필터와 같은 판정), `missing`·`next_action`은 unknown일 때만 채우는 안내용
- F13 `features/map/schemas.py`(새 모델): 내 매물 위치: `LocationIn{road_address|null(≤200), parcel_address|null(≤200), postal_code|null(숫자 5자리), building_name|null(≤100), latitude(33~39), longitude(124~132)}`(앞뒤 공백 제거·빈 칸은 null, 도로명·지번 중 하나 필수, 아니면 422), `LocationOut`(LocationIn 칸 + updated_at), `ListingLocationOut{listing_id, location: LocationOut|null}`, `SessionPinOut{listing_id, listing_no, label, location: LocationOut, deposit_manwon|null, monthly_rent_manwon|null, maintenance_fee_manwon|null, analyzed}`(금액은 최신 성공 분석 + 사용자 수정값, 비교표와 같은 값)

## 4. 엔드포인트
| 담당 | 메서드 경로 | 요청 → 응답 |
|---|---|---|
| R | POST /auth/signup · /auth/login | SignupIn → SignupOut · LoginIn → AuthTokensOut |
| R | POST /auth/refresh · /auth/logout | RefreshIn → AuthTokensOut · (토큰 선택) → OkOut |
| R | GET /me · /health · /ready | ProfileOut · {"status"} · {"db","redis"}(db false면 503) |
| P1 | GET·POST /sessions | → list[SessionOut] · SessionCreateIn → SessionOut |
| P1 | GET·PATCH·DELETE /sessions/{session_id} | SessionOut · SessionUpdateIn → SessionOut · OkOut |
| P1 | GET·POST /sessions/{session_id}/listings | list[ListingOut] · ListingCreateIn → ListingOut |
| P1 | GET·PATCH·DELETE /listings/{listing_id} | ListingOut · ListingUpdateIn → ListingOut · OkOut |
| P1 | GET·PUT /listings/{listing_id}/draft | DraftOut · DraftIn → DraftOut |
| P1 | GET·PUT·DELETE /sessions/{session_id}/draft | DraftOut · DraftIn → DraftOut · OkOut |
| P2 | POST /listings/{listing_id}/analyses | AnalysisCreateIn(본문 생략 가능) → AnalysisOut |
| P2 | GET /listings/{listing_id}/analyses/latest | AnalysisOut (없으면 404 ANALYSIS_NOT_FOUND) |
| P3 | GET /sessions/{session_id}/comparison?filters=a,b | ComparisonOut |
| P3 | POST /analyses/{analysis_id}/feedback | FeedbackCreateIn → FeedbackSaveOut |
| P4 | GET·POST /listings/{listing_id}/photos | list[PhotoOut] · multipart `file` → PhotoOut |
| P4 | DELETE /photos/{photo_id} | OkOut |
| P4 | PATCH /me · POST /me/password | MeUpdateIn → ProfileOut · PasswordChangeIn → OkOut |
| P4 | GET /me/photos · /me/summary | list[MyPhotoOut] · MySummaryOut |
| P5 | GET·PUT /sessions/{session_id}/budget | BudgetOut(미설정이면 값 null) · BudgetIn → BudgetOut |
| P5 | GET /sessions/{session_id}/budget/evaluations | BudgetEvaluationsOut(매물별 판정·사유·다음 행동, listing_no 순. 예시는 4절 끝) |
| P6 | GET /admin/logs · /admin/logs/stream | list[RequestLogOut](기본 최신순 id 내림차순, `after_id`가 있으면 id 오름차순. `limit` 기본 100·최대 500. `include_admin` 기본 false면 `/admin` 요청 제외. 그 밖 `from`·`to`·`status`·`prompt_version`) · SSE(event `log`, id=로그 id, Last-Event-ID 뒤 DB 로그 먼저) |
| P6 | GET /admin/metrics · /admin/feedback | MetricsOut(기본 최근 24시간, 사유별 개수는 `extra.feedback_reason_counts`) · list[FeedbackCaseOut](`rating` 기본 down, `limit` 기본 20·최대 100, 분석별 최신 평가만) |
| P7 | GET·POST /admin/eval-runs | list[EvalRunSummaryOut] · EvalRunCreateIn → EvalRunSummaryOut('running', 실행은 백그라운드) |
| P7 | GET /admin/eval-runs/{run_id}/results?compare_to= | EvalCompareOut |
| F12 | GET /score-items | {items: list[str]}(SCORE_ITEMS 순서, 프로필이 없어도 입력칸을 그릴 때 씀) |
| F12 | GET·POST /weight-profiles | list[WeightProfileOut](만든 순서) · WeightProfileIn → WeightProfileOut |
| F12 | GET·PUT·DELETE /weight-profiles/{profile_id} | WeightProfileOut · WeightProfileIn → WeightProfileOut(통째로 바꿈) · OkOut(고른 세션은 프로필 없음으로) |
| F12 | GET·PUT /listings/{listing_id}/satisfaction | SatisfactionOut · SatisfactionIn → SatisfactionOut |
| F12 | GET·PUT /sessions/{session_id}/scoring | ScoringSettingOut(설정 없으면 켜짐·프로필 없음) · ScoringSettingIn → ScoringSettingOut |
| F12 | GET /sessions/{session_id}/scores?filters=a,b | ScoresOut(필터 통과 매물끼리 순위, 꺼져 있으면 rows 빈 목록) |
| F14 | GET /community/topics | TopicsOut |
| F14 | GET·POST /community/posts | list[PostSummaryOut](기본 최신순, `sort=likes`면 좋아요 많은순, `address` 부분 일치·`floor`·`topic`·`mine`, `limit` 기본 50·최대 200) · PostIn → PostOut |
| F14 | GET·PATCH·DELETE /community/posts/{post_id} | PostOut(로그인 사용자 모두) · PostUpdateIn → PostOut(작성자만) · OkOut(작성자만, 사진 파일 먼저 삭제) |
| F14 | PUT·DELETE /community/posts/{post_id}/like | PostLikeOut(좋아요 누르기·취소. 남의 후기에만, 내 후기 403 FORBIDDEN, 여러 번 눌러도 1번) |
| F14 | POST·DELETE /community/posts/{post_id}/photo | multipart `file`(JPG·PNG, 5MB, 글당 1장, 있으면 바꿈) → PostOut · PostOut(작성자만) |
| F13 | GET·PUT·DELETE /listings/{listing_id}/location | ListingLocationOut(없으면 location null) · LocationIn → ListingLocationOut(있으면 통째로 바꿈) · OkOut(없어도 성공). 남의 매물은 404 LISTING_NOT_FOUND |
| F13 | GET /me/locations | MyPinsOut{pins: [MyPinOut](SessionPinOut + session_id, session_title, memo_text, analysis_status, needs_reanalysis, 세션 최신순 → 매물 번호 순), listing_count(위치 없는 매물 포함)} |
| F13 | GET /sessions/{session_id}/locations | list[SessionPinOut](위치가 있는 매물만, listing_no 순). 남의 세션은 404 SESSION_NOT_FOUND |
/admin/*는 `require_admin`.

### P5 `GET /sessions/{session_id}/budget/evaluations` 예시

'예산 안만 보기'로 숨긴 매물의 사유와 다음 행동을 보여 줄 때 쓴다. 판정 결과·규칙은 바꾸지 않고, 미기재를 0원·추정값으로 채우지 않는다.

- 요청: 본문·쿼리 없음, `Authorization: Bearer <access_token>`. 본인 세션만.
- 응답 200 `BudgetEvaluationsOut` — 예산(보증금 상한 1000, 월 고정비 상한 55)에 매물 5개: 예산 안 1, 판단 불가 2(관리비 미기재·분석 전), 예산 초과 2.

```http
GET /sessions/6f1c2a3e-0000-4000-8000-000000000001/budget/evaluations
```

```json
{
  "session_id": "6f1c2a3e-0000-4000-8000-000000000001",
  "budget_set": true,
  "counts": {"within": 1, "over": 2, "unknown": 2},
  "items": [
    {"listing_id": "a1000000-0000-4000-8000-000000000001", "listing_no": 1, "label": "1번 집",
     "status": "within", "status_label": "예산 안", "reason": "예산 안", "missing": [], "next_action": null},
    {"listing_id": "a1000000-0000-4000-8000-000000000002", "listing_no": 2, "label": "2번 집",
     "status": "unknown", "status_label": "판단 불가", "reason": "관리비 미기재", "missing": ["관리비"],
     "next_action": "관리비 17만원 이하면 예산 안"},
    {"listing_id": "a1000000-0000-4000-8000-000000000003", "listing_no": 3, "label": "3번 집",
     "status": "unknown", "status_label": "판단 불가", "reason": "분석 결과 없음", "missing": [],
     "next_action": "AI 정리를 실행하세요"},
    {"listing_id": "a1000000-0000-4000-8000-000000000004", "listing_no": 4, "label": "4번 집",
     "status": "over", "status_label": "예산 초과", "reason": "보증금 초과", "missing": [], "next_action": null},
    {"listing_id": "a1000000-0000-4000-8000-000000000005", "listing_no": 5, "label": "5번 집",
     "status": "over", "status_label": "예산 초과", "reason": "월 고정비 초과", "missing": [], "next_action": null}
  ]
}
```

2번 집: 월세 38 + 관리비 미기재 → 관리비를 0원으로 더하지 않아 `unknown`. 다음 행동의 17 = 월 고정비 상한 55 − 월세 38.

`next_action` 규칙(unknown일 때만, 그 밖에는 null):

| 경우 | next_action |
|---|---|
| 분석 결과 없음 | `AI 정리를 실행하세요` |
| 관리비만 미기재, 월세 < 월 고정비 상한 | `관리비 n만원 이하면 예산 안` (n = 상한 − 월세) |
| 관리비만 미기재, 월세 = 상한 | `관리비가 없어야 예산 안` |
| 보증금 미기재(보증금 상한이 있을 때만) | `보증금을 확인하세요` |
| 월세 미기재(월 고정비 상한이 있을 때만) | `월세를 확인하세요`, 관리비도 미기재면 `월세·관리비를 확인하세요` |
| 여러 값 미기재 | ` · `로 이음. 관리비는 `관리비는 n만원 이하여야 합니다`(월세 = 상한이면 `관리비가 없어야 합니다`) — 예: `보증금을 확인하세요 · 관리비는 17만원 이하여야 합니다` |

- 예산 미설정: `budget_set` false, `counts` 모두 0, 각 item `status` null·`status_label` "-"·`reason` "예산 미설정".
- 오류: 다른 사람·없는 세션 404, 로그인 없음 401.

```json
{"error": {"code": "SESSION_NOT_FOUND", "message": "세션을 찾을 수 없습니다.", "detail": {"request_id": "…"}}}
```

## 5. 오류 코드·테이블
오류: AUTH_REQUIRED·INVALID_CREDENTIALS 401, EMAIL_NOT_CONFIRMED·FORBIDDEN 403, SESSION/LISTING/ANALYSIS/PHOTO/DRAFT_NOT_FOUND 404, DRAFT_EXPIRED 410, VALIDATION_ERROR 422(detail.fields: loc·type·msg만), AI_RATE_LIMITED 429, INTERNAL_ERROR 500, AI_FORMAT_ERROR 502, CONFIG_MISSING·KV_UNAVAILABLE·CLEANUP_FAILED 503, AI_TIMEOUT 504.
기능이 추가한 오류(I1 반영): AI_UPSTREAM_ERROR 502(그 밖의 Gemini 오류, P2), STORAGE_UNAVAILABLE 503(사진 업로드 실패, P4), EVAL_CASES_EMPTY·EVAL_RUN_IN_PROGRESS 409, EVAL_RUN_NOT_FOUND 404(P7). WEIGHT_PROFILE_NOT_FOUND 404(없거나 남의 가중치 프로필, F12). POST_NOT_FOUND 404(없는 발품 후기, F14), 남의 후기를 고치거나 지우면 FORBIDDEN 403(F14, 남의 글도 읽을 수는 있으므로 404가 아님). 화면 문구는 `frontend/core/ui.py`의 `ERROR_MESSAGES`.

| 테이블 | 쓰기 담당 | 메모 |
|---|---|---|
| profiles | R(트리거·get_current_user), P4 닉네임 — admin db | 사용자 토큰은 SELECT만 |
| tour_sessions | P1 | UPDATE는 title·visit_date만(last_listing_no는 트리거) |
| listings | P1 | listing_no는 트리거(보내지 않음). UPDATE는 memo_text만(memo_updated_at 자동) |
| analyses | P2 | UPDATE 권한 없음(새 행 추가) |
| feedback | P3 | UPDATE 권한 없음(새 행 추가, 최신 행이 유효). `action`(0008): 필드 수정 행은 `set`(null = 메모에 없음)·`revert`(수정 취소, 값 null), 전체 평가 행은 null(CHECK 제약) |
| photos | P4 | (0006) |
| session_budgets | P5 | PK session_id (0007) |
| request_logs | R 미들웨어 | admin db 전용 |
| eval_cases·eval_runs·eval_results | P7 | admin db 전용. 채점 기준 글은 `eval_cases.expected_json`의 `_criteria` 키(전용 열 없음, 채점·응답 expected에서는 빼고 `criteria`로 따로 준다). `eval_results.status`는 `success` 또는 파이프라인 오류 코드, `failure_codes`는 NUM·HAL·MIS·CHK·FMT. AI 원문(raw_output)은 저장하지 않는다 |
| weight_profiles·weight_items·listing_satisfactions·session_scoring | F12 | (0120) 항목 행은 대상별로 지우고 다시 넣어 통째로 바꾼다. session_scoring PK session_id, weight_profile_id는 프로필 삭제 시 SET NULL. item_key에 목록 CHECK 없음(SCORE_ITEMS가 정함) |
| community_post_likes | F14 | (0141) 읽기는 로그인 사용자 모두(좋아요 수), 누르기는 본인 이름으로 남의 후기에만, 취소는 본인 것만. (post_id, profile_id) UNIQUE |
| community_posts·community_post_photos | F14 | (0140) 읽기는 로그인 사용자 모두, 쓰기·고치기·지우기는 작성자(profile_id)만. 사진은 글당 1장(post_id UNIQUE), 파일은 `listing-photos`의 `{auth.uid()}/community/{post_id}/…` 경로이고 두 번째 폴더가 `community`인 파일만 로그인 사용자 읽기 Storage 정책을 더했다. 작성자 닉네임은 admin db로 읽는다 |
| listing_locations | F13 | (0131) PK listing_id(매물당 하나, 매물 삭제 시 CASCADE), 소유 사슬 RLS. 도로명·지번 중 하나 필수(CHECK). 좌표는 화면의 카카오 지도 SDK가 바꾼 값. 메모와 따로 두고 AI에 보내지 않는다 |
CASCADE는 소유 사슬(→photos·session_budgets·eval_results·F12 테이블 포함)과 profiles→F14 테이블, request_logs.profile_id만 SET NULL. 읽기는 누구나.

## 6. 화면 (frontend/core)
- `api.py`: `api_get/post/put/patch/delete(path, *, json=None, params=None, files=None)`, `api_stream(path, params=None)`(SSE, {"event","data","id"}), `ApiError(status, code, message, detail)`. 토큰 자동, 만료 임박·401이면 1회 갱신 후 재시도, 대기 90초. 갱신한 토큰으로도 401 `INVALID_CREDENTIALS`면(예: `/me/password` 현재 비밀번호 틀림) 로그인을 유지하고 오류만 낸다. 그 밖의 401은 로그인 상태를 지운다. 연결 실패 status 0 NETWORK_ERROR/TIMEOUT.
- `state.py`: `current_profile()`, `is_admin()`, `is_logged_in()`, `set_profile(p)`, `budget_filter_key(sid)`. 키 `auth`, `selected_session_id`, `selected_listing_id`, `budget_filter_on:{session_id}`(P5 씀, P3 읽음).
- `nav.py`: `go_sessions()`, `go_session_detail(sid)`, `go_listing_detail(lid)`, `go_page(key)`. on_click 콜백이 아닌 본문(`if st.button(...)`)에서 부른다.
- `slots.py`: `render_slot(slot, ctx)`. `ui.py`: `fmt_manwon(v)`("미기재"/"500만원"), `fmt_kst(t)`, `show_api_error(e)`(코드별 문구+다음 할 일), `privacy_notice()`.
- 슬롯: `session_detail`(ctx: session) → P1 매물 목록·새 메모 10(사진이 있는 매물 카드에 처음 올린 사진·+N, `GET /me/photos` 한 번으로 이 세션 것만 고름, 실패하면 사진 없이 표시. 매물 카드 오른쪽에 F13 `features.map.listing_map.render_session_map()` 매물 지도), P3 비교표 30, F12 항목 가중치 32, F12 적합도 순위 35, P5 예산 40(“예산 안만 보기” 토글은 on_change로 위 비교표·순위에 바로 반영). `listing_detail`(ctx: listing, session) → P1 메모 편집 10, P2 분석 20, P3 수정·피드백 30, P4 사진 40, F12 항목 만족도 45, F13 위치 50.
- 페이지 order·key(사이드바 이름): P1 세션 목록 10 `sessions`('세션'), R 세션 상세 20 `session_detail`(사이드바에 안 보임, '← 세션'), R 매물 상세 30 `listing_detail`(사이드바에 안 보임, '← 세션 제목'), F14 발품 후기 쓰기 60 `balpum_write`(사이드바에 안 보임, 목록의 [발품 후기 쓰기]로 열고 '← 발품 후기'로 돌아감, 등록하면 목록으로 이동), F14 발품 후기 목록 65 `balpum_list`('발품 후기', 늘 목록), F14 발품 후기 상세 66 `balpum_post`(사이드바에 안 보임, 목록·마이페이지 '내 발품 후기' 탭의 [자세히 보기]로 열고 '← 목록으로'·브라우저 뒤로가기로 연 곳의 목록에 돌아감. 마이페이지에서 열면 마이페이지 제목·탭째로 보임), F13 전체 매물 70 `map`(내 모든 세션의 위치 있는 매물을 사이드바 오른쪽 전체 지도에 핀으로, 왼쪽 위 매물 목록을 누르면 그 핀으로 이동, 핀 카드에서 매물 상세로 이동. 카카오 JavaScript 키: secrets·환경변수·`frontend/.env`의 `KAKAO_JAVASCRIPT_KEY`, 없으면 화면 입력), P4 마이페이지 80 `mypage`(탭 내 정보·내 사진·요약·가중치 프로필·내 발품 후기, 가중치 프로필 탭은 F12 `features.scoring.sections.render_profile_manager()`, 마지막 탭은 F14 `features.community.mypage_tab.render_my_posts()`), P6 운영 대시보드 90 `admin_logs`(admin_only), P7 개선 전후 비교 95 `evals`(admin_only).
- 이름 예약: 비교표 열 key `budget`, 행 필터 `within_budget`(P5 등록, P3 사용), 비교표 열 key `score`(F12, order 20). F12 순위 섹션은 `budget_filter_key(sid)`를 읽어 같은 필터로 `/scores`를 부른다.

## 7. 테스트
픽스처: `memory_db`, `memory_kv`, `memory_storage`, `memory_broker`, `fake_auth`, `make_user(role="user")`, `client_as(user | None)`. 등록부·이벤트·파이프라인은 테스트마다 자동 초기화.
- `client_as()`는 앱을 새로 만들고 그때 **모든 기능의 hooks가 다시 등록된다**(합친 뒤엔 P2 파이프라인, P5 `budget` 열·`within_budget` 필터, P4 삭제 처리기가 항상 있음). 그래서:
  - 실제 기능과 같은 key의 가짜(열·필터)는 `client_as()` **뒤에** 등록한다(같은 key는 교체).
  - '파이프라인 미등록' 상태가 필요하면 `client_as()` 뒤에 `reset_pipeline()`.
  - 등록 개수를 확인할 때는 자기 key·자기 모듈(`handler.__module__`)의 것만 센다.
- 테스트에서 파일을 쓰고 읽을 때는 `encoding="utf-8"`을 붙인다(Windows 기본 cp949). fakes: `MemoryDatabase(fail_all)`, `MemoryKV(advance, available)`, `MemoryStorage(fail_uploads/fail_deletes/fail_signed_urls)`, `MemoryBroker(published)`, `FakeAuthProvider`, `FakePipeline(outcome, raises=)`, `success_outcome()`, `failed_outcome(code)`, `sample_ai_output(**kw)`. 파일 `backend/tests/<기능>/test_<기능>_*.py`, 폴더마다 `__init__.py`.

```python
from app.core.analysis_contract import register_pipeline
from tests.fakes import FakePipeline

def test_sessions_list_only_mine(client_as, make_user, memory_db):
    alice, bob = make_user(), make_user()
    memory_db.insert("tour_sessions", {"profile_id": bob.profile_id, "title": "남의 것"})
    register_pipeline(FakePipeline())          # 분석이 필요하면
    r = client_as(alice).get("/sessions")
    assert r.status_code == 200 and r.json() == []
```
