-- 0006_photos.sql — 매물 사진(F10) 테이블과 Storage 비공개 버킷 listing-photos
-- Storage 경로 규칙: {auth_user_id}/{listing_id}/{파일이름}
--   첫 폴더가 업로드한 사용자의 auth.uid()여야 아래 정책을 통과한다.

create table if not exists public.photos (
    id            uuid primary key default gen_random_uuid(),
    listing_id    uuid not null references public.listings (id) on delete cascade,
    profile_id    uuid not null references public.profiles (id) on delete cascade,
    storage_path  text not null unique,
    content_type  text not null,
    size_bytes    integer not null check (size_bytes >= 0),
    visibility    text not null default 'private' check (visibility in ('private', 'public')),
    created_at    timestamptz not null default now()
);
create index if not exists photos_listing_id_idx on public.photos (listing_id);
create index if not exists photos_profile_id_idx on public.photos (profile_id);

revoke all on public.photos from anon, authenticated;
grant select, insert, delete on public.photos to authenticated;
grant all on public.photos to service_role;

alter table public.photos enable row level security;

drop policy if exists photos_own on public.photos;
create policy photos_own on public.photos
    for all to authenticated
    using (
        profile_id = (select public.current_profile_id())
        and exists (
            select 1
              from public.listings l
              join public.tour_sessions s on s.id = l.session_id
             where l.id = photos.listing_id
               and s.profile_id = (select public.current_profile_id())
        )
    )
    with check (
        profile_id = (select public.current_profile_id())
        and exists (
            select 1
              from public.listings l
              join public.tour_sessions s on s.id = l.session_id
             where l.id = photos.listing_id
               and s.profile_id = (select public.current_profile_id())
        )
    );

-- ---------------------------------------------------------------
-- 버킷 만들기
-- Supabase 문서는 storage 스키마 테이블을 API·대시보드로 다루라고 권한다.
-- 아래 INSERT가 실패해도 이 파일의 나머지(정책)는 계속 실행되도록 감쌌다.
-- "bucket insert skipped" 알림이 보이면 README의 "버킷 만들기(대시보드)" 절대로 만든다.
-- ---------------------------------------------------------------
do $$
begin
    insert into storage.buckets (id, name, public)
    values ('listing-photos', 'listing-photos', false)
    on conflict (id) do nothing;
exception when others then
    raise notice 'bucket insert skipped: %', sqlerrm;
end;
$$;

-- ---------------------------------------------------------------
-- storage.objects 정책: 첫 폴더가 auth.uid()인 객체만 본인이 읽기·쓰기·삭제
-- (서명 URL 생성에는 objects SELECT 권한이 필요하다)
-- ---------------------------------------------------------------
drop policy if exists listing_photos_select_own on storage.objects;
create policy listing_photos_select_own on storage.objects
    for select to authenticated
    using (
        bucket_id = 'listing-photos'
        and (storage.foldername(name))[1] = (select auth.uid())::text
    );

drop policy if exists listing_photos_insert_own on storage.objects;
create policy listing_photos_insert_own on storage.objects
    for insert to authenticated
    with check (
        bucket_id = 'listing-photos'
        and (storage.foldername(name))[1] = (select auth.uid())::text
    );

drop policy if exists listing_photos_update_own on storage.objects;
create policy listing_photos_update_own on storage.objects
    for update to authenticated
    using (
        bucket_id = 'listing-photos'
        and (storage.foldername(name))[1] = (select auth.uid())::text
    )
    with check (
        bucket_id = 'listing-photos'
        and (storage.foldername(name))[1] = (select auth.uid())::text
    );

drop policy if exists listing_photos_delete_own on storage.objects;
create policy listing_photos_delete_own on storage.objects
    for delete to authenticated
    using (
        bucket_id = 'listing-photos'
        and (storage.foldername(name))[1] = (select auth.uid())::text
    );
