-- 0140_community.sql — F14 발품 후기(상세주소별 커뮤니티 후기). 0001~0120 뒤에 실행한다.
-- Supabase SQL 편집기에 그대로 붙여 실행한다. 여러 번 실행해도 안전하게 썼다.
--
-- community_posts        후기 글. 지번 주소(필수)·층수(선택)·주제·방문일(선택)·제목·본문.
--                        로그인한 사용자는 모두 읽고, 쓰기·고치기·지우기는 작성자만 한다.
-- community_post_photos  후기 사진(글당 1장). 파일은 기존 비공개 버킷 listing-photos의
--                        "{작성자 auth.uid()}/community/{글 id}/{사진 id}.{확장자}" 경로에 둔다.
--
-- 개인 매물·메모(listings 등)와는 연결하지 않는다. photos.visibility(F10)도 쓰지 않는다.
-- 작성자 닉네임은 서버가 secret key로 profiles에서 읽는다(profiles는 본인 행만 읽을 수 있으므로).
-- 운영자 숨김·처리 기록은 이번 범위에서 빼고 향후 확장으로 둔다(docs/EXTENSION.md).

-- ---------------------------------------------------------------
-- community_posts
-- ---------------------------------------------------------------
create table if not exists public.community_posts (
    id           uuid primary key default gen_random_uuid(),
    profile_id   uuid not null references public.profiles (id) on delete cascade,
    address      text not null check (char_length(btrim(address)) between 1 and 200),
    address_key  text not null check (char_length(address_key) between 1 and 200),
    floor        smallint check (floor between -10 and 200 and floor <> 0),
    topic        text not null check (topic in ('구조·설비', '소음', '채광', '주변 환경', '기타')),
    visit_date   date,
    title        text not null check (char_length(btrim(title)) between 1 and 100),
    body         text not null check (char_length(btrim(body)) between 1 and 3000),
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now()
);
create index if not exists community_posts_created_at_idx on public.community_posts (created_at desc);
create index if not exists community_posts_profile_id_idx on public.community_posts (profile_id, created_at desc);
create index if not exists community_posts_address_key_idx on public.community_posts (address_key);

comment on table public.community_posts is 'F14 발품 후기. 특정 건물·층에서 직접 확인한 정보를 공유하는 글. 로그인 사용자 모두 읽기, 작성자만 쓰기';
comment on column public.community_posts.id is '후기 ID';
comment on column public.community_posts.profile_id is '작성자(profiles.id). 응답에는 내보내지 않고 닉네임만 보여 준다. 사용자 삭제 시 함께 삭제';
comment on column public.community_posts.address is '지번 주소(카카오 주소 검색으로 고른 값, 1~200자). 호수는 받지 않는다';
comment on column public.community_posts.address_key is '검색용 주소 키: 공백·"번지"를 지운 소문자(서버가 address로 만든다)';
comment on column public.community_posts.floor is '층수(선택). 지상은 1 이상, 지하는 -1부터 음수. 0은 쓰지 않는다';
comment on column public.community_posts.topic is '주제: 구조·설비, 소음, 채광, 주변 환경, 기타';
comment on column public.community_posts.visit_date is '방문일(선택)';
comment on column public.community_posts.title is '제목(1~100자). 전화번호·이메일 모양은 서버가 거절';
comment on column public.community_posts.body is '본문(1~3000자). 전화번호·이메일 모양은 서버가 거절';
comment on column public.community_posts.created_at is '작성 시각(UTC, 서버 기록)';
comment on column public.community_posts.updated_at is '마지막 수정 시각(UTC)';

-- ---------------------------------------------------------------
-- community_post_photos
-- ---------------------------------------------------------------
create table if not exists public.community_post_photos (
    id            uuid primary key default gen_random_uuid(),
    post_id       uuid not null unique references public.community_posts (id) on delete cascade,
    profile_id    uuid not null references public.profiles (id) on delete cascade,
    storage_path  text not null unique,
    content_type  text not null check (content_type in ('image/jpeg', 'image/png')),
    size_bytes    integer not null check (size_bytes between 1 and 5242880),
    created_at    timestamptz not null default now()
);
create index if not exists community_post_photos_profile_id_idx on public.community_post_photos (profile_id);

comment on table public.community_post_photos is 'F14 발품 후기 사진. 글당 1장(post_id UNIQUE)';
comment on column public.community_post_photos.id is '사진 ID';
comment on column public.community_post_photos.post_id is '후기(community_posts.id). 후기 삭제 시 함께 삭제';
comment on column public.community_post_photos.profile_id is '올린 사용자(profiles.id) = 후기 작성자';
comment on column public.community_post_photos.storage_path is 'Storage 경로 {auth.uid()}/community/{글 id}/{사진 id}.{jpg|png}. 응답에는 서명 URL만 준다';
comment on column public.community_post_photos.content_type is '실제 파일 형식(서버가 파일 앞부분으로 판단): image/jpeg, image/png';
comment on column public.community_post_photos.size_bytes is '파일 크기(1바이트~5MB)';
comment on column public.community_post_photos.created_at is '올린 시각(UTC)';

-- ---------------------------------------------------------------
-- 권한·RLS
-- ---------------------------------------------------------------
revoke all on public.community_posts, public.community_post_photos from anon, authenticated;
grant select, insert, update, delete on public.community_posts to authenticated;
grant select, insert, delete on public.community_post_photos to authenticated;
grant all on public.community_posts, public.community_post_photos to service_role;

alter table public.community_posts enable row level security;
alter table public.community_post_photos enable row level security;

-- 읽기: 로그인한 사용자 모두
drop policy if exists community_posts_read on public.community_posts;
create policy community_posts_read on public.community_posts
    for select to authenticated
    using (true);

-- 쓰기·고치기·지우기: 작성자만
drop policy if exists community_posts_insert_own on public.community_posts;
create policy community_posts_insert_own on public.community_posts
    for insert to authenticated
    with check (profile_id = (select public.current_profile_id()));

drop policy if exists community_posts_update_own on public.community_posts;
create policy community_posts_update_own on public.community_posts
    for update to authenticated
    using (profile_id = (select public.current_profile_id()))
    with check (profile_id = (select public.current_profile_id()));

drop policy if exists community_posts_delete_own on public.community_posts;
create policy community_posts_delete_own on public.community_posts
    for delete to authenticated
    using (profile_id = (select public.current_profile_id()));

drop policy if exists community_post_photos_read on public.community_post_photos;
create policy community_post_photos_read on public.community_post_photos
    for select to authenticated
    using (true);

drop policy if exists community_post_photos_insert_own on public.community_post_photos;
create policy community_post_photos_insert_own on public.community_post_photos
    for insert to authenticated
    with check (
        profile_id = (select public.current_profile_id())
        and exists (
            select 1 from public.community_posts p
             where p.id = community_post_photos.post_id
               and p.profile_id = (select public.current_profile_id())
        )
    );

drop policy if exists community_post_photos_delete_own on public.community_post_photos;
create policy community_post_photos_delete_own on public.community_post_photos
    for delete to authenticated
    using (profile_id = (select public.current_profile_id()));

-- ---------------------------------------------------------------
-- storage.objects: 발품 후기 사진 읽기
-- 기존 정책(0006)은 첫 폴더가 본인 auth.uid()인 파일만 읽게 한다. 발품 후기 사진은 다른 로그인
-- 사용자도 봐야 하므로, 두 번째 폴더가 'community'인 파일만 로그인 사용자 읽기를 추가로 허용한다.
-- 매물 사진 경로는 두 번째 폴더가 매물 id(uuid)라 이 정책에 걸리지 않고 계속 본인만 읽는다.
-- 올리기·지우기는 기존 0006 정책(첫 폴더 = 본인 auth.uid())을 그대로 따른다.
-- ---------------------------------------------------------------
drop policy if exists listing_photos_select_community on storage.objects;
create policy listing_photos_select_community on storage.objects
    for select to authenticated
    using (
        bucket_id = 'listing-photos'
        and (storage.foldername(name))[2] = 'community'
    );
