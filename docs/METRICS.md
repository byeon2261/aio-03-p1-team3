# METRICS — 운영 대시보드 지표 정의 (F8, P6)

운영자·발표용. 화면(운영 대시보드)과 `GET /admin/metrics`가 이 정의대로 계산한다.
계산 코드: `backend/app/features/admin_logs/metrics.py`.

## 공통

- **기간**: `from` ≤ `created_at` ≤ `to` (UTC 저장, 화면은 서울 시각). 기본은 끝 = 지금, 시작 = 24시간 전.
- **계산 방식**: 기간 조건으로 행을 가져와 서버 Python에서 계산한다(DB 집계 함수 없음). 한 번에 최대 50,000행. 넘으면 `extra.truncated = true`이고 화면이 "기간을 줄이라"고 안내한다.
- **집계 대상은 업무 요청이다.**
  - `/health`·`/ready`·`/admin/logs/stream`은 R 미들웨어가 처음부터 기록하지 않는다.
  - 나머지 `/admin/*` 요청(운영 대시보드가 부른 요청)은 기본으로 뺀다. `include_admin=true`(화면의 "운영자 요청 포함")면 넣는다.
- **분석 요청**: `POST /listings/{listing_id}/analyses` (request_logs.endpoint에는 경로 틀이 저장된다).
- **프롬프트 버전 조건**(`prompt_version`): 요청 로그는 그 버전이 기록된 요청만, 분석·평가는 그 버전으로 만든 분석만 본다. 버전은 분석 요청에만 기록되므로 버전을 고르면 요청 수가 분석 요청 수로 줄어든다.
- 분모가 0이면 값은 `null`이고 화면은 "데이터 없음"으로 보여 준다(0%로 보이지 않게).

## 지표

| 지표 | 정의 | 분자 | 분모 | 빼는 것 | 한계 |
| --- | --- | --- | --- | --- | --- |
| 요청 수 | 기간 안 업무 요청 개수. 차트는 구간별 개수 | 요청 행 수 | - | 공통 제외 | 구간: 기간 48시간 이하는 1시간, 넘으면 서울 날짜 1일. 빈 구간은 0 |
| 처리 시간 중앙값 | `latency_ms` 중앙값 | - | - | 공통 제외 | 서버 안 처리 시간(미들웨어 기준). 네트워크·Render 깨우기 시간은 없음 |
| 처리 시간 상위 5% | `latency_ms` 95% 위치 값 | - | - | 공통 제외 | nearest-rank: 오름차순 정렬 후 ⌈0.95·n⌉번째 값. 표본이 적으면(n < 20) 사실상 최댓값 |
| AI 시간(AI 비중) | `ai_latency_ms`가 있는 요청의 중앙값(상위 5%도 함께) | - | - | `ai_latency_ms` 없는 요청(캐시 적중 포함) | 분석 기능(P2)이 `set_log_fields`로 넘긴 값만 반영 |
| 실패율 | 상태 코드 400 이상 비율 | `status_code ≥ 400` 요청 수 | 전체 요청 수 | 공통 제외 | 4xx(사용자 입력·권한)와 5xx(서버·AI)를 함께 센다. 실패 유형 분포로 나눠 본다 |
| 실패 유형 분포 | 실패 요청의 `error_code`별 개수 | - | - | 성공 요청 | `error_code`가 없는 실패는 `UNKNOWN` |
| AI 형식 실패 비율 | 분석 요청 중 AI 응답 형식 실패 | `error_code`가 `FMT` 또는 `AI_FORMAT_ERROR`인 분석 요청 | 분석 요청 수 | 분석 요청이 아닌 요청 | `MetricsOut.format_error_rate`. P2가 형식 실패를 이 코드로 남겨야 잡힌다 |
| 필드 수정 비율 | 사용자가 AI 값을 고친 상태로 남긴 빈도(최종 상태 기준, I2) | 기간 내 성공 분석들의 (analysis_id, field_name)별 feedback 행을 `created_at` 순으로 놓았을 때 **마지막 행이 수정**(`action = 'set'`, '메모에 없음' = set + null 포함)인 고유 쌍 수. 규칙은 `core.repo.overrides_from_rows`(= `field_overrides`)와 같다 | 기간 내 성공 분석 수 × `len(EDITABLE_FIELDS)`(=9) | 실패 분석, `EDITABLE_FIELDS` 밖의 field_name, 전체 평가 행(field_name 없음), **마지막 행이 수정 취소**(`action = 'revert'`, 0008 이전 행은 corrected_value null)인 필드 | **정답과 비교한 값이 아니다**(정답 기반 비교는 F9 평가). 사용자가 고치지 않은 틀린 값은 잡히지 않는다. 고쳤다가 되돌린 필드는 세지 않는다. 분석 시각 기준이며 피드백 시각은 보지 않는다. 분모는 지금의 `EDITABLE_FIELDS` 개수라, 필드를 더하거나 빼면 옛 분석의 분모도 함께 바뀐다 |
| 👎 비율 | 전체 평가 중 👎 비율 | 분석별 최신 평가가 down인 수 | 분석별 최신 평가 수(up+down) | 필드 수정 행, rating 없는 행, 최신이 아닌 평가 | feedback은 새 행 추가 방식이라 분석마다 기간 안의 마지막 평가 행만 센다. 평가 시각 기준 |
| 👎 사유별 개수 | 위 👎 평가의 `reason` 6종별 개수(+ 사유 안 고름 `none`) | - | - | up 평가 | 계약상 `/admin/feedback` 응답은 목록이라 `extra.feedback_reason_counts`로 준다 |
| 캐시 적중률 | 분석 요청 중 캐시를 쓴 비율 | `cache_hit = true`인 분석 요청 수 | 분석 요청 수 | 분석 요청이 아닌 요청 | 실패한 분석 요청도 분모에 들어간다 |
| 프롬프트 버전별 비교 | 위 지표를 `prompt_version`별로 | - | - | 버전이 기록되지 않은 요청(조회·저장 등) | 요청 지표는 요청 로그의 버전, 필드 수정·👎은 분석 행의 버전으로 나눈다 |

## 응답 위치 (`GET /admin/metrics` → `MetricsOut`)

| 필드 | 지표 |
| --- | --- |
| `window_minutes` | 기간 길이(분) |
| `request_count`, `error_rate` | 요청 수, 실패율 |
| `p50_latency_ms`, `p95_latency_ms` | 처리 시간 중앙값, 상위 5% |
| `ai_p50_latency_ms`, `ai_p95_latency_ms` | AI 시간 중앙값, 상위 5% |
| `cache_hit_rate`, `format_error_rate` | 캐시 적중률, AI 형식 실패 비율 |
| `extra.series` | `{unit: "hour"/"day", points: [{start(UTC), count, error_count, error_rate, p50_latency_ms, p95_latency_ms}]}` |
| `extra.error_code_counts`, `extra.error_count` | 실패 유형 분포 |
| `extra.field_edit` | `{analysis_count, analyzed_fields, edited_fields, ratio, by_field}` |
| `extra.rating` | `{rating_count, down_count, down_rate}` |
| `extra.feedback_reason_counts` | `{amount, not_in_memo, missing_info, pros_cons, check_error, other, none}` |
| `extra.by_prompt_version` | `{버전: {요청 지표…, field_edit, rating}}` |
| `extra.ai_request_count`, `extra.analysis_request_count`, `extra.cache_hit_count`, `extra.format_error_count` | 분모·분자 확인용 개수 |
| `extra.from`, `extra.to`, `extra.prompt_version`, `extra.include_admin`, `extra.truncated` | 계산 조건 |

## 발표할 때 주의

- "필드 수정 비율"을 "오류율"이나 "정확도"로 부르지 않는다. 사용자가 고친 빈도일 뿐이다.
- 표본이 적으면(요청 수십 건) 상위 5%·비율이 크게 흔들린다. 숫자 옆에 건수를 함께 보인다(카드 도움말에 분자·분모가 나온다).
- Render 무료 서버가 잠들었다 깬 첫 요청은 처리 시간에 깨우는 시간이 들어가지 않는다(미들웨어는 앱이 깬 뒤부터 잰다). 사용자가 느끼는 대기와 다를 수 있다.
