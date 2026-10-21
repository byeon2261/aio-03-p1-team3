-- 0011_comments.sql — 컬럼·테이블 코멘트(Issue #6). 0001~0010 뒤에 실행한다.
-- Supabase SQL 편집기에 그대로 붙여 실행한다. COMMENT ON은 덮어쓰기라 여러 번 실행해도 안전하다.
--
-- 0001·0002·0006·0007에서 만든 테이블에는 DB 코멘트가 없었다. docs/DB_DESIGN.md 5절의 코멘트를 그대로 넣는다.
-- 데이터·구조·권한은 바꾸지 않는다. 이미 코멘트가 있는 listings.name(0009)·feedback.action(0008)은 건드리지 않는다.
-- (Issue #6은 처음에 0009_comments.sql로 계획했지만 0009·0010을 매물 이름이 먼저 써서 0011을 쓴다.)

-- profiles
comment on table public.profiles is '사용자';
comment on column public.profiles.id is '사용자 ID. 다른 테이블이 소유자로 가리키는 값';
comment on column public.profiles.auth_user_id is 'Supabase 인증 계정 ID. 계정당 프로필 하나';
comment on column public.profiles.nickname is '화면에 보이는 이름. 가입 때 이메일 앞부분';
comment on column public.profiles.role is '권한. admin만 운영 화면·로그 API 사용';
comment on column public.profiles.created_at is '가입 시각(UTC)';

-- tour_sessions
comment on table public.tour_sessions is '집 보기 세션';
comment on column public.tour_sessions.id is '세션 ID';
comment on column public.tour_sessions.profile_id is '세션을 만든 사용자';
comment on column public.tour_sessions.title is '세션 제목(예: 10월 셋째 주 토요일)';
comment on column public.tour_sessions.visit_date is '방문일(선택)';
comment on column public.tour_sessions.last_listing_no is '마지막으로 준 매물 번호. 번호 트리거만 올린다(지운 번호를 다시 쓰지 않으려고)';
comment on column public.tour_sessions.created_at is '만든 시각(UTC)';

-- listings
comment on table public.listings is '매물 메모';
comment on column public.listings.id is '매물 ID';
comment on column public.listings.session_id is '소속 세션';
comment on column public.listings.listing_no is '세션 안 번호. 화면 이름 "N번 집"';
comment on column public.listings.memo_text is '사용자가 쓴 메모 원문';
comment on column public.listings.memo_updated_at is '메모가 바뀐 시각. 재분석 필요 판단에 쓴다';
comment on column public.listings.created_at is '만든 시각(UTC)';

-- analyses
comment on table public.analyses is 'AI 분석 결과';
comment on column public.analyses.id is '분석 ID';
comment on column public.analyses.listing_id is '분석한 매물';
comment on column public.analyses.result_json is '정리 결과(보증금·월세·관리비·장단점·체크리스트 9항목 등). 실패 시 null';
comment on column public.analyses.schema_version is 'result_json 형식 버전';
comment on column public.analyses.prompt_version is '사용한 프롬프트 버전(개선 전후 비교)';
comment on column public.analyses.model is '사용한 AI 모델 이름';
comment on column public.analyses.thinking_level is '모델 추론 수준 설정';
comment on column public.analyses.memo_hash is '분석할 때 메모의 해시. 지금 메모와 다르면 재분석 필요';
comment on column public.analyses.latency_ms is '서버 전체 처리 시간(ms)';
comment on column public.analyses.ai_latency_ms is 'AI 응답 시간(ms). 캐시 사용 시 null';
comment on column public.analyses.status is '분석 성공 여부';
comment on column public.analyses.error_code is '실패 시 오류 코드';
comment on column public.analyses.raw_output is '형식 실패 때 AI 원문(원인 확인용)';
comment on column public.analyses.created_at is '분석 시각(UTC). 최신 분석을 고를 때 쓴다';

-- feedback
comment on table public.feedback is '수정값·평가';
comment on column public.feedback.id is '피드백 ID';
comment on column public.feedback.analysis_id is '대상 분석';
comment on column public.feedback.profile_id is '남긴 사용자';
comment on column public.feedback.field_name is '수정한 필드 이름. null이면 전체 평가 행';
comment on column public.feedback.corrected_value is '수정값. set인데 null이면 "메모에 없음"';
comment on column public.feedback.rating is '전체 평가(좋아요·싫어요)';
comment on column public.feedback.reason is '싫어요 이유(금액·메모에 없음·빠진 정보·장단점·체크 오류·기타)';
comment on column public.feedback.comment is '자유 의견';
comment on column public.feedback.created_at is '남긴 시각(UTC). 최신 행 판단 기준';

-- photos
comment on table public.photos is '매물 사진';
comment on column public.photos.id is '사진 ID';
comment on column public.photos.listing_id is '사진을 붙인 매물';
comment on column public.photos.profile_id is '올린 사용자 = 매물 소유자(RLS가 확인)';
comment on column public.photos.storage_path is 'Storage 버킷 listing-photos 안 경로';
comment on column public.photos.content_type is '파일 형식(MIME)';
comment on column public.photos.size_bytes is '파일 크기(바이트)';
comment on column public.photos.visibility is '공개 범위. 지금은 private만 쓴다';
comment on column public.photos.created_at is '올린 시각(UTC)';

-- session_budgets
comment on table public.session_budgets is '세션 예산';
comment on column public.session_budgets.session_id is '예산을 정한 세션(세션당 하나)';
comment on column public.session_budgets.deposit_max_manwon is '보증금 상한(만원). null이면 제한 없음';
comment on column public.session_budgets.monthly_max_manwon is '월 비용(월세+관리비) 상한(만원). null이면 제한 없음';
comment on column public.session_budgets.updated_at is '마지막으로 고친 시각(UTC)';

-- request_logs
comment on table public.request_logs is '요청 로그';
comment on column public.request_logs.id is '로그 번호(쌓인 순서)';
comment on column public.request_logs.request_id is '요청 ID(응답 헤더 X-Request-ID와 같은 값)';
comment on column public.request_logs.profile_id is '요청한 사용자. 로그인 전 요청이나 사용자 삭제 후에는 null';
comment on column public.request_logs.endpoint is '요청 경로(예: /listings/{listing_id}/analyses)';
comment on column public.request_logs.method is 'HTTP 메서드';
comment on column public.request_logs.status_code is '응답 상태 코드';
comment on column public.request_logs.latency_ms is '서버 처리 시간(ms)';
comment on column public.request_logs.ai_latency_ms is 'AI 호출 시간(ms). AI를 부르지 않은 요청은 null';
comment on column public.request_logs.error_code is '오류 코드(예: AI_TIMEOUT). 성공은 null';
comment on column public.request_logs.prompt_version is '분석 요청의 프롬프트 버전';
comment on column public.request_logs.cache_hit is '분석 캐시 사용 여부. 분석 요청이 아니면 null';
comment on column public.request_logs.created_at is '요청 시각(UTC). 기간 조회·최신순 정렬';

-- eval_cases
comment on table public.eval_cases is '평가 케이스';
comment on column public.eval_cases.id is '케이스 ID';
comment on column public.eval_cases.case_key is '사람이 읽는 케이스 키(eval/eval_cases.json의 case_key). 다시 불러올 때 이 값으로 넣거나 갱신한다';
comment on column public.eval_cases.memo_text is '평가에 넣는 메모(예시 데이터, 실제 개인정보 없음)';
comment on column public.eval_cases.expected_json is '정답 결과. _criteria 키에 채점 기준 글';
comment on column public.eval_cases.tags is '분류 태그(예: money_idiom 금액 관용 표현, negation 부정 표현)';

-- eval_runs
comment on table public.eval_runs is '평가 실행';
comment on column public.eval_runs.id is '실행 ID';
comment on column public.eval_runs.prompt_version is '평가한 프롬프트 버전';
comment on column public.eval_runs.model is '사용한 AI 모델';
comment on column public.eval_runs.thinking_level is '추론 수준';
comment on column public.eval_runs.schema_version is '결과 형식 버전';
comment on column public.eval_runs.status is '실행 상태';
comment on column public.eval_runs.case_count is '채점한 케이스 수';
comment on column public.eval_runs.field_accuracy is '필드 정확도(끝나면 채움)';
comment on column public.eval_runs.hallucination_rate is '메모에 없는 값을 만든 비율';
comment on column public.eval_runs.missing_check_accuracy is '빠진 확인 항목 판단 정확도';
comment on column public.eval_runs.format_error_rate is '형식 오류 비율';
comment on column public.eval_runs.error_message is '실행 실패 사유';
comment on column public.eval_runs.created_at is '시작 시각(UTC)';
comment on column public.eval_runs.finished_at is '끝난 시각(UTC). 실행 중이면 null';

-- eval_results
comment on table public.eval_results is '케이스별 평가 결과';
comment on column public.eval_results.id is '결과 ID';
comment on column public.eval_results.run_id is '평가 실행';
comment on column public.eval_results.case_id is '평가 케이스';
comment on column public.eval_results.output_json is 'AI 출력. 실패 시 null';
comment on column public.eval_results.status is '케이스 결과 상태';
comment on column public.eval_results.field_matches is '필드별 정답 일치 여부';
comment on column public.eval_results.failure_codes is '실패 유형 코드 목록';
comment on column public.eval_results.created_at is '채점 시각(UTC)';
