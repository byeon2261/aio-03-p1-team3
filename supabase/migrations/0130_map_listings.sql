-- 0130_map_listings.sql — F13 지도 탐색용 더미 매물. 0001~0120 뒤에 실행한다(다른 테이블을 참조하지 않는다).
-- Supabase SQL 편집기에 그대로 붙여 실행한다. 여러 번 실행해도 안전하게 썼다(같은 id는 값을 덮어쓴다).
--
-- map_listings  서울역 데모 기준점(37.5547, 126.9706) 반경 1km 안의 더미 매물 30개.
--               300m 안 8개, 500m 안 18개, 1km 안 30개.
--               - 실제 주소 샘플 9개: 도로명·지번·우편번호·건물 대표 좌표는 공개 주소자료에서 확인(출처·확인일 열).
--               - 가상 매물 21개: 좌표도 가상이고 주소는 동 단위(area_name)까지만 둔다.
--               가격·면적·층수·임대 조건은 30개 모두 가상이다. 개인 매물(listings)과 연결하지 않는다.
--               로그인한 사용자는 모두 읽고, 쓰기는 service_role(관리자)만 한다.
--
-- 값은 backend/app/features/map/seed.py와 같다(backend/tests/map 테스트가 확인한다).

-- ---------------------------------------------------------------
-- map_listings
-- ---------------------------------------------------------------
create table if not exists public.map_listings (
    id                   text primary key check (id ~ '^[a-z0-9-]{1,40}$'),
    title                text not null check (char_length(btrim(title)) between 1 and 100),
    area_name            text not null check (char_length(btrim(area_name)) between 1 and 100),
    property_type        text not null check (property_type in ('원룸', '투룸', '오피스텔', '빌라', '아파트')),
    lease_type           text not null check (lease_type in ('월세', '전세')),
    deposit_manwon       integer not null check (deposit_manwon between 0 and 1000000),
    monthly_rent_manwon  integer check (monthly_rent_manwon between 0 and 10000),
    area_m2              numeric(6, 1) not null check (area_m2 > 0 and area_m2 < 1000),
    floor                smallint not null check (floor between -10 and 200 and floor <> 0),
    latitude             double precision not null check (latitude between 33 and 39),
    longitude            double precision not null check (longitude between 124 and 132),
    road_address         text check (char_length(btrim(road_address)) between 1 and 200),
    parcel_address       text check (char_length(btrim(parcel_address)) between 1 and 200),
    postal_code          text check (postal_code ~ '^[0-9]{5}$'),
    building_name        text check (char_length(btrim(building_name)) between 1 and 100),
    address_source_url   text check (address_source_url ~ '^https://'),
    address_verified_on  date,
    created_at           timestamptz not null default now(),
    -- 월세는 월세 금액이 있고, 전세는 없다
    constraint map_listings_rent_by_lease check (
        (lease_type = '월세' and monthly_rent_manwon is not null)
        or (lease_type = '전세' and monthly_rent_manwon is null)
    ),
    -- 실제 주소를 넣으면 도로명·지번·우편번호·출처·확인일을 모두 넣는다(가상 매물은 모두 null)
    constraint map_listings_address_complete check (
        (road_address is null and parcel_address is null and postal_code is null
         and address_source_url is null and address_verified_on is null)
        or (road_address is not null and parcel_address is not null and postal_code is not null
            and address_source_url is not null and address_verified_on is not null)
    )
);
create index if not exists map_listings_lat_lng_idx on public.map_listings (latitude, longitude);

comment on table public.map_listings is 'F13 지도 탐색용 더미 매물(서울역 주변). 실제 주소 샘플 9개 + 가상 21개. 로그인 사용자 모두 읽기 전용. 개인 매물(listings)과 무관';
comment on column public.map_listings.id is '더미 매물 ID(예: map-01, 기준점에서 가까운 순)';
comment on column public.map_listings.title is '화면에 보이는 이름';
comment on column public.map_listings.area_name is '동 단위 지역(예: 서울특별시 중구 회현동)';
comment on column public.map_listings.property_type is '주택 유형: 원룸, 투룸, 오피스텔, 빌라, 아파트';
comment on column public.map_listings.lease_type is '임대 조건(가상): 월세, 전세';
comment on column public.map_listings.deposit_manwon is '보증금 또는 전세금(만원, 가상)';
comment on column public.map_listings.monthly_rent_manwon is '월세(만원, 가상). 전세면 null';
comment on column public.map_listings.area_m2 is '전용면적(㎡, 가상)';
comment on column public.map_listings.floor is '층수(가상). 지상 1 이상, 지하는 음수, 0은 쓰지 않는다';
comment on column public.map_listings.latitude is '위도(WGS84). 실제 주소 샘플은 건물 대표 좌표, 가상 매물은 가상 좌표';
comment on column public.map_listings.longitude is '경도(WGS84). 실제 주소 샘플은 건물 대표 좌표, 가상 매물은 가상 좌표';
comment on column public.map_listings.road_address is '도로명주소(실제 주소 샘플만). 가상 매물은 null';
comment on column public.map_listings.parcel_address is '지번주소(실제 주소 샘플만)';
comment on column public.map_listings.postal_code is '우편번호 5자리(실제 주소 샘플만)';
comment on column public.map_listings.building_name is '건물명(있을 때만)';
comment on column public.map_listings.address_source_url is '주소·좌표를 확인한 공개 주소자료 URL(실제 주소 샘플만)';
comment on column public.map_listings.address_verified_on is '주소를 확인한 날짜(실제 주소 샘플만)';
comment on column public.map_listings.created_at is '등록 시각(UTC)';

-- ---------------------------------------------------------------
-- 권한·RLS: 로그인 사용자는 읽기만
-- ---------------------------------------------------------------
revoke all on public.map_listings from anon, authenticated;
grant select on public.map_listings to authenticated;
grant all on public.map_listings to service_role;

alter table public.map_listings enable row level security;

drop policy if exists map_listings_read on public.map_listings;
create policy map_listings_read on public.map_listings
    for select to authenticated
    using (true);

-- ---------------------------------------------------------------
-- 더미 데이터 30개
-- ---------------------------------------------------------------
insert into public.map_listings
    (id, title, area_name, property_type, lease_type, deposit_manwon, monthly_rent_manwon, area_m2, floor, latitude, longitude, road_address, parcel_address, postal_code, building_name, address_source_url, address_verified_on)
values
    ('map-01', '동자동 가상 원룸 01', '서울특별시 용산구 동자동', '원룸', '월세', 3000, 110, 22.7, 15, 37.553316, 126.970175, null, null, null, null, null, null),
    ('map-02', '청파동 가상 투룸 02', '서울특별시 용산구 청파동', '투룸', '전세', 18000, null, 38.2, 10, 37.553939, 126.968907, null, null, null, null, null, null),
    ('map-03', '서계동 실제 주소 샘플 A', '서울특별시 용산구 서계동', '원룸', '월세', 1000, 60, 19.0, 2, 37.5542693, 126.9685446, '서울특별시 용산구 청파로93길 5', '서울특별시 용산구 서계동 223-8', '04300', null, 'https://findby.co.kr/details/04300-111704106393-st-652c0a2df27008be2c4f8e9d', '2026-10-16'),
    ('map-04', '회현동 가상 투룸 04', '서울특별시 중구 회현동', '투룸', '월세', 1000, 80, 43.0, 14, 37.556753, 126.97112, null, null, null, null, null, null),
    ('map-05', '회현동 가상 오피스텔 05', '서울특별시 중구 회현동', '오피스텔', '월세', 1000, 55, 27.4, 4, 37.555925, 126.972853, null, null, null, null, null, null),
    ('map-06', '서계동 실제 주소 샘플 B', '서울특별시 용산구 서계동', '원룸', '월세', 2000, 70, 23.0, 3, 37.5541202, 126.9677956, '서울특별시 용산구 청파로93길 21', '서울특별시 용산구 서계동 224-4', '04300', null, 'https://findby.co.kr/details/04300-111704106393-st-652c0a2df27008be2c4f8ea7', '2026-10-16'),
    ('map-07', '동자동 가상 아파트 07', '서울특별시 용산구 동자동', '아파트', '월세', 10000, 180, 82.7, 9, 37.552475, 126.971406, null, null, null, null, null, null),
    ('map-08', '서계동 실제 주소 샘플 C', '서울특별시 용산구 서계동', '투룸', '전세', 22000, null, 38.0, 4, 37.554344418449, 126.96724502817, '서울특별시 용산구 청파로93길 18-14', '서울특별시 용산구 서계동 223-70', '04300', null, 'https://jusoga.com/b/1117010800102230070021065/서울특별시-용산구-청파로93길-18-14-서계동', '2026-10-16'),
    ('map-09', '서계동 가상 원룸 09', '서울특별시 용산구 서계동', '원룸', '전세', 37000, null, 21.9, 6, 37.554684, 126.966949, null, null, null, null, null, null),
    ('map-10', '동자동 가상 오피스텔 10', '서울특별시 용산구 동자동', '오피스텔', '전세', 19000, null, 27.0, 12, 37.551925, 126.971644, null, null, null, null, null, null),
    ('map-11', '후암동 가상 투룸 11', '서울특별시 용산구 후암동', '투룸', '월세', 2000, 105, 33.0, 7, 37.553513, 126.973995, null, null, null, null, null, null),
    ('map-12', '중림동 가상 오피스텔 12', '서울특별시 중구 중림동', '오피스텔', '월세', 1000, 70, 21.0, 11, 37.557471, 126.969146, null, null, null, null, null, null),
    ('map-13', '회현동 가상 아파트 13', '서울특별시 중구 회현동', '아파트', '전세', 23000, null, 68.9, 5, 37.557103, 126.973321, null, null, null, null, null, null),
    ('map-14', '후암동 가상 원룸 14', '서울특별시 용산구 후암동', '원룸', '월세', 3000, 80, 24.9, 12, 37.555157, 126.975193, null, null, null, null, null, null),
    ('map-15', '트윈시티남산 실제 주소 샘플', '서울특별시 용산구 동자동', '투룸', '전세', 28000, null, 42.0, 3, 37.5511247, 126.9729133, '서울특별시 용산구 한강대로 366', '서울특별시 용산구 동자동 56', '04323', '트윈시티남산', 'https://findby.co.kr/details/04323-111702005005-st-652c0a11f27008be2c4f3cf0', '2026-10-16'),
    ('map-16', '서울역한라비발디센트럴 실제 주소 샘플', '서울특별시 중구 만리동2가', '원룸', '월세', 1000, 65, 21.0, 2, 37.5547038, 126.9654931, '서울특별시 중구 만리재로 177', '서울특별시 중구 만리동2가 288', '04501', '서울역한라비발디센트럴', 'https://findby.co.kr/details/04501-111403101016-st-652c0c7cf27008be2c565256', '2026-10-16'),
    ('map-17', '회현동 가상 빌라 17', '서울특별시 중구 회현동', '빌라', '전세', 37000, null, 40.9, 4, 37.558684, 126.971602, null, null, null, null, null, null),
    ('map-18', '센트레빌아스테리움서울 실제 주소 샘플', '서울특별시 용산구 동자동', '오피스텔', '월세', 3000, 90, 28.0, 7, 37.5513775, 126.9736403, '서울특별시 용산구 한강대로 372', '서울특별시 용산구 동자동 45', '04323', '센트레빌아스테리움서울', 'https://findby.co.kr/details/04323-111702005005-st-652c0a11f27008be2c4f3d31', '2026-10-16'),
    ('map-19', '동자동 가상 투룸 19', '서울특별시 용산구 동자동', '투룸', '전세', 25000, null, 35.3, 9, 37.550985, 126.97422, null, null, null, null, null, null),
    ('map-20', '회현동 가상 아파트 20', '서울특별시 중구 회현동', '아파트', '월세', 10000, 160, 59.8, 5, 37.559917, 126.971895, null, null, null, null, null, null),
    ('map-21', '쌍용더플래티넘서울역 실제 주소 샘플', '서울특별시 중구 중림동', '오피스텔', '전세', 25000, null, 31.0, 9, 37.5600449, 126.9686125, '서울특별시 중구 청파로 454', '서울특별시 중구 중림동 363', '04510', '쌍용더플래티넘서울역', 'https://findby.co.kr/details/04510-111403101023-st-652c0cc3f27008be2c572a63', '2026-10-16'),
    ('map-22', '서울역센트럴자이 실제 주소 샘플', '서울특별시 중구 만리동2가', '투룸', '월세', 5000, 110, 46.0, 5, 37.5549829, 126.9631641, '서울특별시 중구 만리재로 175', '서울특별시 중구 만리동2가 273', '04500', '서울역센트럴자이', 'https://findby.co.kr/details/04500-111403101016-st-652c0c7cf27008be2c565257', '2026-10-16'),
    ('map-23', '청파동 가상 빌라 23', '서울특별시 용산구 청파동', '빌라', '월세', 1000, 65, 45.7, 2, 37.548906, 126.967727, null, null, null, null, null, null),
    ('map-24', '브라운스톤서울 실제 주소 샘플', '서울특별시 중구 중림동', '아파트', '전세', 48000, null, 59.0, 8, 37.5608188, 126.9682259, '서울특별시 중구 청파로 464', '서울특별시 중구 중림동 355', '04510', '브라운스톤서울', 'https://findby.co.kr/details/04510-111403101023-st-652c0cc3f27008be2c572a5e', '2026-10-16'),
    ('map-25', '서계동 가상 오피스텔 25', '서울특별시 용산구 서계동', '오피스텔', '전세', 32000, null, 25.5, 1, 37.558693, 126.96388, null, null, null, null, null, null),
    ('map-26', '회현동 가상 원룸 26', '서울특별시 중구 회현동', '원룸', '전세', 33000, null, 24.8, 7, 37.56021, 126.975408, null, null, null, null, null, null),
    ('map-27', '동자동 가상 오피스텔 27', '서울특별시 용산구 동자동', '오피스텔', '월세', 2000, 80, 29.4, 5, 37.547914, 126.971265, null, null, null, null, null, null),
    ('map-28', '후암동 가상 원룸 28', '서울특별시 용산구 후암동', '원룸', '월세', 500, 120, 21.2, 14, 37.551845, 126.97867, null, null, null, null, null, null),
    ('map-29', '청파동 가상 아파트 29', '서울특별시 용산구 청파동', '아파트', '전세', 26000, null, 78.3, 19, 37.549142, 126.965025, null, null, null, null, null, null),
    ('map-30', '후암동 가상 아파트 30', '서울특별시 용산구 후암동', '아파트', '월세', 5000, 160, 62.0, 10, 37.555709, 126.979767, null, null, null, null, null, null)
on conflict (id) do update set
    title = excluded.title,
    area_name = excluded.area_name,
    property_type = excluded.property_type,
    lease_type = excluded.lease_type,
    deposit_manwon = excluded.deposit_manwon,
    monthly_rent_manwon = excluded.monthly_rent_manwon,
    area_m2 = excluded.area_m2,
    floor = excluded.floor,
    latitude = excluded.latitude,
    longitude = excluded.longitude,
    road_address = excluded.road_address,
    parcel_address = excluded.parcel_address,
    postal_code = excluded.postal_code,
    building_name = excluded.building_name,
    address_source_url = excluded.address_source_url,
    address_verified_on = excluded.address_verified_on;
