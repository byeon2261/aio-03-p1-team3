-- 0003_rls.sql — 권한(GRANT)과 행 수준 보안(RLS)
-- 원칙
--   * 사용자 토큰(authenticated)은 자기 소유 사슬 profiles → tour_sessions → listings → analyses → feedback 안에서만 읽고 쓴다.
--   * profiles는 SELECT만 준다. 생성·닉네임 변경은 서버가 secret key로 한다.
--   * request_logs, eval_*는 RLS를 켜고 anon·authenticated 정책을 두지 않는다(secret key 전용).
--   * Supabase 기본 권한에 기대지 않도록 먼저 모두 회수(REVOKE)한 뒤 필요한 것만 준다.
-- photos(0006), session_budgets(0007)의 권한·정책은 각 파일에 있다(테이블이 그 파일에서 생기므로).

-- ---------------------------------------------------------------
-- 현재 로그인 사용자의 profile id
-- ---------------------------------------------------------------
create or replace function public.current_profile_id()
returns uuid
language sql
stable
security definer
set search_path = ''
as $$
    select p.id from public.profiles p where p.auth_user_id = (select auth.uid())
$$;

revoke all on function public.current_profile_id() from public;
grant execute on function public.current_profile_id() to authenticated, service_role;

-- 트리거 함수는 사용자가 직접 부를 일이 없다.
revoke all on function public.handle_new_auth_user() from public, anon, authenticated;
revoke all on function public.assign_listing_no() from public, anon, authenticated;

-- ---------------------------------------------------------------
-- 권한 회수 후 재부여
-- ---------------------------------------------------------------
revoke all on public.profiles, public.tour_sessions, public.listings, public.analyses, public.feedback
    from anon, authenticated;
revoke all on public.request_logs, public.eval_cases, public.eval_runs, public.eval_results
    from anon, authenticated;

grant select on public.profiles to authenticated;

grant select, insert, delete on public.tour_sessions to authenticated;
grant update (title, visit_date) on public.tour_sessions to authenticated;   -- last_listing_no는 트리거만

grant select, insert, delete on public.listings to authenticated;
grant update (memo_text) on public.listings to authenticated;               -- memo_updated_at은 트리거가 바꾼다

grant select, insert, delete on public.analyses to authenticated;
grant select, insert, delete on public.feedback to authenticated;

-- 서버(secret key = service_role)는 모두 가능
grant all on public.profiles, public.tour_sessions, public.listings, public.analyses, public.feedback,
             public.request_logs, public.eval_cases, public.eval_runs, public.eval_results
    to service_role;
grant usage, select on all sequences in schema public to service_role;

-- ---------------------------------------------------------------
-- RLS 켜기
-- ---------------------------------------------------------------
alter table public.profiles      enable row level security;
alter table public.tour_sessions enable row level security;
alter table public.listings      enable row level security;
alter table public.analyses      enable row level security;
alter table public.feedback      enable row level security;
alter table public.request_logs  enable row level security;
alter table public.eval_cases    enable row level security;
alter table public.eval_runs     enable row level security;
alter table public.eval_results  enable row level security;

-- ---------------------------------------------------------------
-- 정책
-- ---------------------------------------------------------------
drop policy if exists profiles_select_own on public.profiles;
create policy profiles_select_own on public.profiles
    for select to authenticated
    using (auth_user_id = (select auth.uid()));

drop policy if exists tour_sessions_own on public.tour_sessions;
create policy tour_sessions_own on public.tour_sessions
    for all to authenticated
    using (profile_id = (select public.current_profile_id()))
    with check (profile_id = (select public.current_profile_id()));

drop policy if exists listings_own on public.listings;
create policy listings_own on public.listings
    for all to authenticated
    using (exists (
        select 1 from public.tour_sessions s
         where s.id = listings.session_id
           and s.profile_id = (select public.current_profile_id())
    ))
    with check (exists (
        select 1 from public.tour_sessions s
         where s.id = listings.session_id
           and s.profile_id = (select public.current_profile_id())
    ));

drop policy if exists analyses_own on public.analyses;
create policy analyses_own on public.analyses
    for all to authenticated
    using (exists (
        select 1
          from public.listings l
          join public.tour_sessions s on s.id = l.session_id
         where l.id = analyses.listing_id
           and s.profile_id = (select public.current_profile_id())
    ))
    with check (exists (
        select 1
          from public.listings l
          join public.tour_sessions s on s.id = l.session_id
         where l.id = analyses.listing_id
           and s.profile_id = (select public.current_profile_id())
    ));

drop policy if exists feedback_own on public.feedback;
create policy feedback_own on public.feedback
    for all to authenticated
    using (
        profile_id = (select public.current_profile_id())
        and exists (
            select 1
              from public.analyses a
              join public.listings l on l.id = a.listing_id
              join public.tour_sessions s on s.id = l.session_id
             where a.id = feedback.analysis_id
               and s.profile_id = (select public.current_profile_id())
        )
    )
    with check (
        profile_id = (select public.current_profile_id())
        and exists (
            select 1
              from public.analyses a
              join public.listings l on l.id = a.listing_id
              join public.tour_sessions s on s.id = l.session_id
             where a.id = feedback.analysis_id
               and s.profile_id = (select public.current_profile_id())
        )
    );

-- request_logs, eval_*: 정책 없음 → anon·authenticated는 아무 행도 볼 수 없다.
