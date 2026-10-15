-- 0001_core.sql — 사용자 데이터 테이블 (profiles → tour_sessions → listings → analyses → feedback)
-- Supabase SQL 편집기에 그대로 붙여 실행한다. 여러 번 실행해도 안전하게 썼다.
-- 시각은 모두 timestamptz(UTC 저장)다.

-- ---------------------------------------------------------------
-- profiles: auth.users 1:1. 사용자는 SELECT만 할 수 있다(0003).
-- ---------------------------------------------------------------
create table if not exists public.profiles (
    id            uuid primary key default gen_random_uuid(),
    auth_user_id  uuid not null unique references auth.users (id) on delete cascade,
    nickname      text not null default '사용자',
    role          text not null default 'user' check (role in ('user', 'admin')),
    created_at    timestamptz not null default now()
);

-- auth.users에 행이 생기면 profiles를 만든다. 닉네임 기본값은 이메일 앞부분.
create or replace function public.handle_new_auth_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    insert into public.profiles (auth_user_id, nickname)
    values (
        new.id,
        coalesce(nullif(split_part(coalesce(new.email, ''), '@', 1), ''), '사용자')
    )
    on conflict (auth_user_id) do nothing;
    return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
    after insert on auth.users
    for each row execute function public.handle_new_auth_user();

-- ---------------------------------------------------------------
-- tour_sessions: 집 보기 하루(세션). last_listing_no는 번호 트리거만 올린다.
-- ---------------------------------------------------------------
create table if not exists public.tour_sessions (
    id               uuid primary key default gen_random_uuid(),
    profile_id       uuid not null references public.profiles (id) on delete cascade,
    title            text not null,
    visit_date       date,
    last_listing_no  integer not null default 0,
    created_at       timestamptz not null default now()
);
create index if not exists tour_sessions_profile_id_idx on public.tour_sessions (profile_id);

-- ---------------------------------------------------------------
-- listings: 매물 메모. listing_no는 BEFORE INSERT 트리거가 넣는다.
-- ---------------------------------------------------------------
create table if not exists public.listings (
    id               uuid primary key default gen_random_uuid(),
    session_id       uuid not null references public.tour_sessions (id) on delete cascade,
    listing_no       integer not null,
    memo_text        text not null default '',
    memo_updated_at  timestamptz not null default now(),
    created_at       timestamptz not null default now(),
    constraint listings_session_listing_no_key unique (session_id, listing_no)
);
-- listings.session_id 인덱스는 unique(session_id, listing_no)가 겸한다.

-- 번호 부여: 세션의 last_listing_no를 1 올리고 그 값을 쓴다. 지운 번호는 다시 나오지 않는다.
-- security definer: 사용자에게 last_listing_no UPDATE 권한을 주지 않기 위해서다(0003).
create or replace function public.assign_listing_no()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    next_no integer;
begin
    update public.tour_sessions
       set last_listing_no = last_listing_no + 1
     where id = new.session_id
    returning last_listing_no into next_no;

    if next_no is null then
        raise exception 'tour_session % not found', new.session_id
            using errcode = '23503';
    end if;

    new.listing_no := next_no;
    return new;
end;
$$;

drop trigger if exists listings_assign_no on public.listings;
create trigger listings_assign_no
    before insert on public.listings
    for each row execute function public.assign_listing_no();

-- 메모가 바뀌면 memo_updated_at을 지금으로 바꾼다.
create or replace function public.touch_memo_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    if new.memo_text is distinct from old.memo_text then
        new.memo_updated_at := now();
    end if;
    return new;
end;
$$;

drop trigger if exists listings_touch_memo on public.listings;
create trigger listings_touch_memo
    before update on public.listings
    for each row execute function public.touch_memo_updated_at();

-- ---------------------------------------------------------------
-- analyses: AI 분석 결과. 형식 실패 때도 raw_output을 남긴다.
-- ---------------------------------------------------------------
create table if not exists public.analyses (
    id              uuid primary key default gen_random_uuid(),
    listing_id      uuid not null references public.listings (id) on delete cascade,
    result_json     jsonb,
    schema_version  text not null,
    prompt_version  text not null,
    model           text not null,
    thinking_level  text,
    memo_hash       text not null,
    latency_ms      integer,
    ai_latency_ms   integer,
    status          text not null check (status in ('success', 'failed')),
    error_code      text,
    raw_output      text,
    created_at      timestamptz not null default now()
);
create index if not exists analyses_listing_id_idx on public.analyses (listing_id);

-- ---------------------------------------------------------------
-- feedback: 필드 수정값(field_name 있음) 또는 전체 평가(field_name null)
-- ---------------------------------------------------------------
create table if not exists public.feedback (
    id               uuid primary key default gen_random_uuid(),
    analysis_id      uuid not null references public.analyses (id) on delete cascade,
    profile_id       uuid not null references public.profiles (id) on delete cascade,
    field_name       text,
    corrected_value  jsonb,
    rating           text check (rating in ('up', 'down')),
    reason           text check (reason in ('amount', 'not_in_memo', 'missing_info', 'pros_cons', 'check_error', 'other')),
    comment          text,
    created_at       timestamptz not null default now()
);
create index if not exists feedback_analysis_id_idx on public.feedback (analysis_id);
create index if not exists feedback_profile_id_idx on public.feedback (profile_id);
