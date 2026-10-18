-- 0131_listing_locations.sql — F13 내 매물 위치(주소·좌표). 0001~0120 뒤에 실행한다.
-- Supabase SQL 편집기에 그대로 붙여 실행한다. 여러 번 실행해도 안전하게 썼다.
--
-- listing_locations  매물(listings) 하나당 위치 하나. 사용자가 매물 상세의 '위치'에서 카카오 주소 검색으로
--                    주소를 고르면, 화면의 카카오 지도 SDK가 좌표로 바꾸고 서버가 저장한다.
--                    메모(memo_text)와 따로 저장하고 AI 분석에는 보내지 않는다. 본인만 읽고 쓴다(소유 사슬 RLS).
--                    세션 상세의 매물 목록 옆 지도가 이 좌표로 핀을 찍는다.

-- ---------------------------------------------------------------
-- listing_locations
-- ---------------------------------------------------------------
create table if not exists public.listing_locations (
    listing_id      uuid primary key references public.listings (id) on delete cascade,
    road_address    text check (char_length(btrim(road_address)) between 1 and 200),
    parcel_address  text check (char_length(btrim(parcel_address)) between 1 and 200),
    postal_code     text check (postal_code ~ '^[0-9]{5}$'),
    building_name   text check (char_length(btrim(building_name)) between 1 and 100),
    latitude        double precision not null check (latitude between 33 and 39),
    longitude       double precision not null check (longitude between 124 and 132),
    updated_at      timestamptz not null default now(),
    -- 도로명·지번 중 하나는 있어야 한다
    constraint listing_locations_has_address check (road_address is not null or parcel_address is not null)
);

comment on table public.listing_locations is 'F13 내 매물 위치. 매물당 하나, 본인만 읽고 쓴다. 메모와 따로 저장하고 AI에 보내지 않는다';
comment on column public.listing_locations.listing_id is '매물(listings.id). 매물 삭제 시 함께 삭제';
comment on column public.listing_locations.road_address is '도로명주소(카카오 주소 검색 결과)';
comment on column public.listing_locations.parcel_address is '지번주소(카카오 주소 검색 결과)';
comment on column public.listing_locations.postal_code is '우편번호 5자리(있을 때만)';
comment on column public.listing_locations.building_name is '건물명(있을 때만)';
comment on column public.listing_locations.latitude is '위도(WGS84, 카카오 좌표 변환 결과)';
comment on column public.listing_locations.longitude is '경도(WGS84, 카카오 좌표 변환 결과)';
comment on column public.listing_locations.updated_at is '저장한 시각(UTC)';

-- ---------------------------------------------------------------
-- 권한·RLS: 소유 사슬(profile → session → listing)
-- ---------------------------------------------------------------
revoke all on public.listing_locations from anon, authenticated;
grant select, insert, update, delete on public.listing_locations to authenticated;
grant all on public.listing_locations to service_role;

alter table public.listing_locations enable row level security;

drop policy if exists listing_locations_own on public.listing_locations;
create policy listing_locations_own on public.listing_locations
    for all to authenticated
    using (exists (
        select 1 from public.listings l
          join public.tour_sessions s on s.id = l.session_id
         where l.id = listing_locations.listing_id
           and s.profile_id = (select public.current_profile_id())
    ))
    with check (exists (
        select 1 from public.listings l
          join public.tour_sessions s on s.id = l.session_id
         where l.id = listing_locations.listing_id
           and s.profile_id = (select public.current_profile_id())
    ));
