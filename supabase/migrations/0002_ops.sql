-- 0002_ops.sql — 운영 테이블 (요청 로그, 평가)
-- secret key(service_role)로만 접근한다. RLS 설정은 0003에 있다.

-- ---------------------------------------------------------------
-- request_logs: 요청마다 한 행. 메모 원문·토큰은 남기지 않는다.
-- profile이 지워져도 로그는 남긴다(profile_id만 null).
-- ---------------------------------------------------------------
create table if not exists public.request_logs (
    id              bigint generated always as identity primary key,
    request_id      uuid not null,
    profile_id      uuid references public.profiles (id) on delete set null,
    endpoint        text not null,
    method          text not null,
    status_code     integer not null,
    latency_ms      integer not null,
    ai_latency_ms   integer,
    error_code      text,
    prompt_version  text,
    cache_hit       boolean,
    created_at      timestamptz not null default now()
);
create index if not exists request_logs_created_at_idx on public.request_logs (created_at);

-- ---------------------------------------------------------------
-- 평가: 케이스 → 실행 → 케이스별 결과
-- ---------------------------------------------------------------
create table if not exists public.eval_cases (
    id             uuid primary key default gen_random_uuid(),
    case_key       text not null unique,
    memo_text      text not null,
    expected_json  jsonb not null,
    tags           text[] not null default '{}'
);

create table if not exists public.eval_runs (
    id                      uuid primary key default gen_random_uuid(),
    prompt_version          text not null,
    model                   text not null,
    thinking_level          text,
    schema_version          text not null,
    status                  text not null default 'running' check (status in ('running', 'done', 'failed')),
    case_count              integer not null default 0,
    field_accuracy          double precision,
    hallucination_rate      double precision,
    missing_check_accuracy  double precision,
    format_error_rate       double precision,
    error_message           text,
    created_at              timestamptz not null default now(),
    finished_at             timestamptz
);

create table if not exists public.eval_results (
    id             uuid primary key default gen_random_uuid(),
    run_id         uuid not null references public.eval_runs (id) on delete cascade,
    case_id        uuid not null references public.eval_cases (id) on delete cascade,
    output_json    jsonb,
    status         text not null,
    field_matches  jsonb,
    failure_codes  text[] not null default '{}',
    created_at     timestamptz not null default now()
);
create index if not exists eval_results_run_id_idx on public.eval_results (run_id);
create index if not exists eval_results_case_id_idx on public.eval_results (case_id);
