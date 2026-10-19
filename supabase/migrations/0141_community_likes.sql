-- 0141_community_likes.sql — F14 발품 후기 좋아요. 0140_community.sql 뒤에 실행한다.
-- Supabase SQL 편집기에 그대로 붙여 실행한다. 여러 번 실행해도 안전하게 썼다.
--
-- community_post_likes  후기 좋아요. 한 사람은 한 글에 한 번만 누른다(post_id, profile_id UNIQUE).
--                       로그인한 사용자는 모두 읽고(좋아요 수 계산), 누르기·취소는 본인 것만 한다.
--                       내 글에는 누를 수 없다(서버가 403으로 막고, RLS도 한 번 더 막는다).
-- 기존 테이블(community_posts 등)과 데이터는 바꾸지 않는다.

create table if not exists public.community_post_likes (
    id          uuid primary key default gen_random_uuid(),
    post_id     uuid not null references public.community_posts (id) on delete cascade,
    profile_id  uuid not null references public.profiles (id) on delete cascade,
    created_at  timestamptz not null default now(),
    unique (post_id, profile_id)
);
create index if not exists community_post_likes_profile_id_idx on public.community_post_likes (profile_id);

comment on table public.community_post_likes is 'F14 발품 후기 좋아요. 한 사람이 한 글에 1번(post_id, profile_id UNIQUE). 내 글에는 못 누름';
comment on column public.community_post_likes.id is '좋아요 ID';
comment on column public.community_post_likes.post_id is '후기(community_posts.id). 후기 삭제 시 함께 삭제';
comment on column public.community_post_likes.profile_id is '누른 사용자(profiles.id). 응답에는 내보내지 않고 수와 내가 눌렀는지만 준다';
comment on column public.community_post_likes.created_at is '누른 시각(UTC)';

revoke all on public.community_post_likes from anon, authenticated;
grant select, insert, delete on public.community_post_likes to authenticated;
grant all on public.community_post_likes to service_role;

alter table public.community_post_likes enable row level security;

-- 읽기: 로그인한 사용자 모두(좋아요 수)
drop policy if exists community_post_likes_read on public.community_post_likes;
create policy community_post_likes_read on public.community_post_likes
    for select to authenticated
    using (true);

-- 누르기: 본인 이름으로만, 남의 글에만
drop policy if exists community_post_likes_insert_own on public.community_post_likes;
create policy community_post_likes_insert_own on public.community_post_likes
    for insert to authenticated
    with check (
        profile_id = (select public.current_profile_id())
        and exists (
            select 1 from public.community_posts p
             where p.id = community_post_likes.post_id
               and p.profile_id <> (select public.current_profile_id())
        )
    );

-- 취소: 본인 것만
drop policy if exists community_post_likes_delete_own on public.community_post_likes;
create policy community_post_likes_delete_own on public.community_post_likes
    for delete to authenticated
    using (profile_id = (select public.current_profile_id()));
