-- 0009_listing_name.sql — 매물 이름(예: "1번방"). 0001~0141 뒤에 실행한다.
-- Supabase SQL 편집기에 그대로 붙여 실행한다. 여러 번 실행해도 안전하게 썼다.
--
-- listings.name  새 매물 메모를 저장할 때 사용자가 적는 이름. 화면의 매물 이름(label)으로 쓴다.
--                이 열이 생기기 전에 만든 매물은 null이고, 화면에는 지금처럼 "N번 집"으로 보인다.
--                INSERT 권한은 0003에서 표 전체에 주었으므로 따로 grant하지 않는다(수정 권한은 주지 않는다).

alter table public.listings add column if not exists name text;

alter table public.listings drop constraint if exists listings_name_len;
alter table public.listings
    add constraint listings_name_len check (name is null or char_length(btrim(name)) between 1 and 30);

comment on column public.listings.name is '매물 이름(사용자 입력, 1~30자). null이면 화면에 "N번 집"';
