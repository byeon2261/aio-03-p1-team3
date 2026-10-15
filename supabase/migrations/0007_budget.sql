-- 0007_budget.sql — 세션 예산(F11). 금액은 만원 단위 정수, null은 "제한 없음(미설정)".

create table if not exists public.session_budgets (
    session_id          uuid primary key references public.tour_sessions (id) on delete cascade,
    deposit_max_manwon  integer check (deposit_max_manwon is null or deposit_max_manwon >= 0),
    monthly_max_manwon  integer check (monthly_max_manwon is null or monthly_max_manwon >= 0),
    updated_at          timestamptz not null default now()
);

revoke all on public.session_budgets from anon, authenticated;
grant select, insert, update, delete on public.session_budgets to authenticated;
grant all on public.session_budgets to service_role;

alter table public.session_budgets enable row level security;

drop policy if exists session_budgets_own on public.session_budgets;
create policy session_budgets_own on public.session_budgets
    for all to authenticated
    using (exists (
        select 1 from public.tour_sessions s
         where s.id = session_budgets.session_id
           and s.profile_id = (select public.current_profile_id())
    ))
    with check (exists (
        select 1 from public.tour_sessions s
         where s.id = session_budgets.session_id
           and s.profile_id = (select public.current_profile_id())
    ));
