-- 0120_scoring.sql — F12 항목 가중치화(매물 적합도 점수). 0001~0008 뒤에 실행한다.
-- Supabase SQL 편집기에 그대로 붙여 실행한다. 여러 번 실행해도 안전하게 썼다.
--
-- weight_profiles        계정(profiles) 단위 가중치 프로필(예: 여름 6개월·겨울 6개월). 여러 세션에서 다시 쓴다.
-- weight_items           프로필의 항목별 가중치(0~100 정수).
-- listing_satisfactions  매물의 항목별 만족도(0~100 정수, 높을수록 좋음). 행이 없으면 '미입력'.
-- session_scoring        세션별 설정: 가중치 기능 켜기/끄기, 고른 프로필(없으면 동일 가중치).
--
-- item_key에는 항목 목록 CHECK를 걸지 않는다. 항목 목록은 서버 코드(features/scoring/items.py의
-- SCORE_ITEMS)가 정하고, 목록을 바꿔도 마이그레이션 없이 동작하게 하기 위해서다.
-- 점수 계산은 서버가 하고 DB에 저장하지 않는다(만족도·가중치가 바뀌면 바로 다시 계산되도록).

-- ---------------------------------------------------------------
-- weight_profiles
-- ---------------------------------------------------------------
create table if not exists public.weight_profiles (
    id          uuid primary key default gen_random_uuid(),
    profile_id  uuid not null references public.profiles (id) on delete cascade,
    name        text not null check (char_length(btrim(name)) between 1 and 30),
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);
create index if not exists weight_profiles_profile_id_idx on public.weight_profiles (profile_id, created_at);

comment on table public.weight_profiles is 'F12 가중치 프로필. 계정 단위로 만들고 세션마다 하나를 고른다';
comment on column public.weight_profiles.id is '프로필 ID';
comment on column public.weight_profiles.profile_id is '소유 사용자(profiles.id). 사용자 삭제 시 함께 삭제';
comment on column public.weight_profiles.name is '프로필 이름(1~30자), 예: 여름 6개월';
comment on column public.weight_profiles.created_at is '만든 시각(UTC)';
comment on column public.weight_profiles.updated_at is '마지막으로 이름·가중치를 고친 시각(UTC)';

-- ---------------------------------------------------------------
-- weight_items
-- ---------------------------------------------------------------
create table if not exists public.weight_items (
    weight_profile_id  uuid not null references public.weight_profiles (id) on delete cascade,
    item_key           text not null check (char_length(item_key) between 1 and 30),
    weight             smallint not null check (weight between 0 and 100),
    primary key (weight_profile_id, item_key)
);

comment on table public.weight_items is 'F12 프로필의 항목별 가중치. 행이 없는 항목은 가중치 0';
comment on column public.weight_items.weight_profile_id is '가중치 프로필(weight_profiles.id). 프로필 삭제 시 함께 삭제';
comment on column public.weight_items.item_key is '평가 항목 이름(서버 SCORE_ITEMS 중 하나, 예: 채광)';
comment on column public.weight_items.weight is '중요도 0~100 정수. 합이 100이 아니어도 계산에서 비율로 맞춘다';

-- ---------------------------------------------------------------
-- listing_satisfactions
-- ---------------------------------------------------------------
create table if not exists public.listing_satisfactions (
    listing_id    uuid not null references public.listings (id) on delete cascade,
    item_key      text not null check (char_length(item_key) between 1 and 30),
    satisfaction  smallint not null check (satisfaction between 0 and 100),
    updated_at    timestamptz not null default now(),
    primary key (listing_id, item_key)
);

comment on table public.listing_satisfactions is 'F12 매물의 항목별 주관 만족도. 행이 없는 항목은 미입력(계산에서 뺀다)';
comment on column public.listing_satisfactions.listing_id is '매물(listings.id). 매물 삭제 시 함께 삭제';
comment on column public.listing_satisfactions.item_key is '평가 항목 이름(서버 SCORE_ITEMS 중 하나)';
comment on column public.listing_satisfactions.satisfaction is '만족도 0~100 정수, 높을수록 좋음(측정값 아님)';
comment on column public.listing_satisfactions.updated_at is '저장한 시각(UTC)';

-- ---------------------------------------------------------------
-- session_scoring
-- ---------------------------------------------------------------
create table if not exists public.session_scoring (
    session_id         uuid primary key references public.tour_sessions (id) on delete cascade,
    enabled            boolean not null default true,
    weight_profile_id  uuid references public.weight_profiles (id) on delete set null,
    updated_at         timestamptz not null default now()
);
create index if not exists session_scoring_weight_profile_id_idx on public.session_scoring (weight_profile_id);

comment on table public.session_scoring is 'F12 세션별 가중치 설정. 행이 없으면 켜짐·프로필 없음(동일 가중치)';
comment on column public.session_scoring.session_id is '세션(tour_sessions.id). 세션 삭제 시 함께 삭제';
comment on column public.session_scoring.enabled is '가중치 기능 켜기(true)/끄기(false)';
comment on column public.session_scoring.weight_profile_id is '고른 프로필. null이면 모든 항목 동일 가중치. 프로필 삭제 시 null';
comment on column public.session_scoring.updated_at is '마지막으로 설정을 바꾼 시각(UTC)';

-- ---------------------------------------------------------------
-- 권한·RLS: 소유 사슬(profile → session → listing, profile → weight_profile)
-- ---------------------------------------------------------------
revoke all on public.weight_profiles, public.weight_items, public.listing_satisfactions, public.session_scoring
    from anon, authenticated;
grant select, insert, update, delete on public.weight_profiles, public.weight_items, public.listing_satisfactions,
    public.session_scoring to authenticated;
grant all on public.weight_profiles, public.weight_items, public.listing_satisfactions, public.session_scoring
    to service_role;

alter table public.weight_profiles enable row level security;
alter table public.weight_items enable row level security;
alter table public.listing_satisfactions enable row level security;
alter table public.session_scoring enable row level security;

drop policy if exists weight_profiles_own on public.weight_profiles;
create policy weight_profiles_own on public.weight_profiles
    for all to authenticated
    using (profile_id = (select public.current_profile_id()))
    with check (profile_id = (select public.current_profile_id()));

drop policy if exists weight_items_own on public.weight_items;
create policy weight_items_own on public.weight_items
    for all to authenticated
    using (exists (
        select 1 from public.weight_profiles w
         where w.id = weight_items.weight_profile_id
           and w.profile_id = (select public.current_profile_id())
    ))
    with check (exists (
        select 1 from public.weight_profiles w
         where w.id = weight_items.weight_profile_id
           and w.profile_id = (select public.current_profile_id())
    ));

drop policy if exists listing_satisfactions_own on public.listing_satisfactions;
create policy listing_satisfactions_own on public.listing_satisfactions
    for all to authenticated
    using (exists (
        select 1 from public.listings l
          join public.tour_sessions s on s.id = l.session_id
         where l.id = listing_satisfactions.listing_id
           and s.profile_id = (select public.current_profile_id())
    ))
    with check (exists (
        select 1 from public.listings l
          join public.tour_sessions s on s.id = l.session_id
         where l.id = listing_satisfactions.listing_id
           and s.profile_id = (select public.current_profile_id())
    ));

-- 남의 프로필을 내 세션에 고르지 못하게 with check에서 프로필 소유도 확인한다.
drop policy if exists session_scoring_own on public.session_scoring;
create policy session_scoring_own on public.session_scoring
    for all to authenticated
    using (exists (
        select 1 from public.tour_sessions s
         where s.id = session_scoring.session_id
           and s.profile_id = (select public.current_profile_id())
    ))
    with check (
        exists (
            select 1 from public.tour_sessions s
             where s.id = session_scoring.session_id
               and s.profile_id = (select public.current_profile_id())
        )
        and (
            weight_profile_id is null
            or exists (
                select 1 from public.weight_profiles w
                 where w.id = session_scoring.weight_profile_id
                   and w.profile_id = (select public.current_profile_id())
            )
        )
    );
