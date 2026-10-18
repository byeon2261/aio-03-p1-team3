"""F13 지도 탐색용 더미 매물 30개(서울역 데모 기준점 반경 1km 안).

`supabase/migrations/0130_map_listings.sql`의 INSERT와 같은 값이다(테스트가 둘이 같은지 확인한다).
- 실제 주소 샘플 9개: 옛 demo_st의 데이터. 도로명·지번·우편번호·건물 대표 좌표는 공개 주소자료에서
  확인했다(address_source_url, address_verified_on). 가격·면적·층수·임대 조건은 가상이다.
- 가상 매물 21개: 좌표·가격·면적·층수 모두 가상이고 주소는 동 단위(area_name)까지만 둔다.
서울역 데모 기준점에서 300m 안 8개, 500m 안 18개, 1km 안 30개가 잡힌다.
"""

from __future__ import annotations

ADDRESS_FIELDS = ("road_address", "parcel_address", "postal_code", "building_name",
                  "address_source_url", "address_verified_on")


def _row(**kw) -> dict:
    return {**{field: None for field in ADDRESS_FIELDS}, **kw}


DUMMY_MAP_LISTINGS: list[dict] = [
    _row(id='map-01', title='동자동 가상 원룸 01', area_name='서울특별시 용산구 동자동', property_type='원룸', lease_type='월세', deposit_manwon=3000, monthly_rent_manwon=110, area_m2=22.7, floor=15, latitude=37.553316, longitude=126.970175),
    _row(id='map-02', title='청파동 가상 투룸 02', area_name='서울특별시 용산구 청파동', property_type='투룸', lease_type='전세', deposit_manwon=18000, monthly_rent_manwon=None, area_m2=38.2, floor=10, latitude=37.553939, longitude=126.968907),
    _row(id='map-03', title='서계동 실제 주소 샘플 A', area_name='서울특별시 용산구 서계동', property_type='원룸', lease_type='월세', deposit_manwon=1000, monthly_rent_manwon=60, area_m2=19.0, floor=2, latitude=37.5542693, longitude=126.9685446,
         road_address='서울특별시 용산구 청파로93길 5', parcel_address='서울특별시 용산구 서계동 223-8', postal_code='04300', building_name=None, address_source_url='https://findby.co.kr/details/04300-111704106393-st-652c0a2df27008be2c4f8e9d', address_verified_on='2026-10-16'),
    _row(id='map-04', title='회현동 가상 투룸 04', area_name='서울특별시 중구 회현동', property_type='투룸', lease_type='월세', deposit_manwon=1000, monthly_rent_manwon=80, area_m2=43.0, floor=14, latitude=37.556753, longitude=126.97112),
    _row(id='map-05', title='회현동 가상 오피스텔 05', area_name='서울특별시 중구 회현동', property_type='오피스텔', lease_type='월세', deposit_manwon=1000, monthly_rent_manwon=55, area_m2=27.4, floor=4, latitude=37.555925, longitude=126.972853),
    _row(id='map-06', title='서계동 실제 주소 샘플 B', area_name='서울특별시 용산구 서계동', property_type='원룸', lease_type='월세', deposit_manwon=2000, monthly_rent_manwon=70, area_m2=23.0, floor=3, latitude=37.5541202, longitude=126.9677956,
         road_address='서울특별시 용산구 청파로93길 21', parcel_address='서울특별시 용산구 서계동 224-4', postal_code='04300', building_name=None, address_source_url='https://findby.co.kr/details/04300-111704106393-st-652c0a2df27008be2c4f8ea7', address_verified_on='2026-10-16'),
    _row(id='map-07', title='동자동 가상 아파트 07', area_name='서울특별시 용산구 동자동', property_type='아파트', lease_type='월세', deposit_manwon=10000, monthly_rent_manwon=180, area_m2=82.7, floor=9, latitude=37.552475, longitude=126.971406),
    _row(id='map-08', title='서계동 실제 주소 샘플 C', area_name='서울특별시 용산구 서계동', property_type='투룸', lease_type='전세', deposit_manwon=22000, monthly_rent_manwon=None, area_m2=38.0, floor=4, latitude=37.554344418449, longitude=126.96724502817,
         road_address='서울특별시 용산구 청파로93길 18-14', parcel_address='서울특별시 용산구 서계동 223-70', postal_code='04300', building_name=None, address_source_url='https://jusoga.com/b/1117010800102230070021065/서울특별시-용산구-청파로93길-18-14-서계동', address_verified_on='2026-10-16'),
    _row(id='map-09', title='서계동 가상 원룸 09', area_name='서울특별시 용산구 서계동', property_type='원룸', lease_type='전세', deposit_manwon=37000, monthly_rent_manwon=None, area_m2=21.9, floor=6, latitude=37.554684, longitude=126.966949),
    _row(id='map-10', title='동자동 가상 오피스텔 10', area_name='서울특별시 용산구 동자동', property_type='오피스텔', lease_type='전세', deposit_manwon=19000, monthly_rent_manwon=None, area_m2=27.0, floor=12, latitude=37.551925, longitude=126.971644),
    _row(id='map-11', title='후암동 가상 투룸 11', area_name='서울특별시 용산구 후암동', property_type='투룸', lease_type='월세', deposit_manwon=2000, monthly_rent_manwon=105, area_m2=33.0, floor=7, latitude=37.553513, longitude=126.973995),
    _row(id='map-12', title='중림동 가상 오피스텔 12', area_name='서울특별시 중구 중림동', property_type='오피스텔', lease_type='월세', deposit_manwon=1000, monthly_rent_manwon=70, area_m2=21.0, floor=11, latitude=37.557471, longitude=126.969146),
    _row(id='map-13', title='회현동 가상 아파트 13', area_name='서울특별시 중구 회현동', property_type='아파트', lease_type='전세', deposit_manwon=23000, monthly_rent_manwon=None, area_m2=68.9, floor=5, latitude=37.557103, longitude=126.973321),
    _row(id='map-14', title='후암동 가상 원룸 14', area_name='서울특별시 용산구 후암동', property_type='원룸', lease_type='월세', deposit_manwon=3000, monthly_rent_manwon=80, area_m2=24.9, floor=12, latitude=37.555157, longitude=126.975193),
    _row(id='map-15', title='트윈시티남산 실제 주소 샘플', area_name='서울특별시 용산구 동자동', property_type='투룸', lease_type='전세', deposit_manwon=28000, monthly_rent_manwon=None, area_m2=42.0, floor=3, latitude=37.5511247, longitude=126.9729133,
         road_address='서울특별시 용산구 한강대로 366', parcel_address='서울특별시 용산구 동자동 56', postal_code='04323', building_name='트윈시티남산', address_source_url='https://findby.co.kr/details/04323-111702005005-st-652c0a11f27008be2c4f3cf0', address_verified_on='2026-10-16'),
    _row(id='map-16', title='서울역한라비발디센트럴 실제 주소 샘플', area_name='서울특별시 중구 만리동2가', property_type='원룸', lease_type='월세', deposit_manwon=1000, monthly_rent_manwon=65, area_m2=21.0, floor=2, latitude=37.5547038, longitude=126.9654931,
         road_address='서울특별시 중구 만리재로 177', parcel_address='서울특별시 중구 만리동2가 288', postal_code='04501', building_name='서울역한라비발디센트럴', address_source_url='https://findby.co.kr/details/04501-111403101016-st-652c0c7cf27008be2c565256', address_verified_on='2026-10-16'),
    _row(id='map-17', title='회현동 가상 빌라 17', area_name='서울특별시 중구 회현동', property_type='빌라', lease_type='전세', deposit_manwon=37000, monthly_rent_manwon=None, area_m2=40.9, floor=4, latitude=37.558684, longitude=126.971602),
    _row(id='map-18', title='센트레빌아스테리움서울 실제 주소 샘플', area_name='서울특별시 용산구 동자동', property_type='오피스텔', lease_type='월세', deposit_manwon=3000, monthly_rent_manwon=90, area_m2=28.0, floor=7, latitude=37.5513775, longitude=126.9736403,
         road_address='서울특별시 용산구 한강대로 372', parcel_address='서울특별시 용산구 동자동 45', postal_code='04323', building_name='센트레빌아스테리움서울', address_source_url='https://findby.co.kr/details/04323-111702005005-st-652c0a11f27008be2c4f3d31', address_verified_on='2026-10-16'),
    _row(id='map-19', title='동자동 가상 투룸 19', area_name='서울특별시 용산구 동자동', property_type='투룸', lease_type='전세', deposit_manwon=25000, monthly_rent_manwon=None, area_m2=35.3, floor=9, latitude=37.550985, longitude=126.97422),
    _row(id='map-20', title='회현동 가상 아파트 20', area_name='서울특별시 중구 회현동', property_type='아파트', lease_type='월세', deposit_manwon=10000, monthly_rent_manwon=160, area_m2=59.8, floor=5, latitude=37.559917, longitude=126.971895),
    _row(id='map-21', title='쌍용더플래티넘서울역 실제 주소 샘플', area_name='서울특별시 중구 중림동', property_type='오피스텔', lease_type='전세', deposit_manwon=25000, monthly_rent_manwon=None, area_m2=31.0, floor=9, latitude=37.5600449, longitude=126.9686125,
         road_address='서울특별시 중구 청파로 454', parcel_address='서울특별시 중구 중림동 363', postal_code='04510', building_name='쌍용더플래티넘서울역', address_source_url='https://findby.co.kr/details/04510-111403101023-st-652c0cc3f27008be2c572a63', address_verified_on='2026-10-16'),
    _row(id='map-22', title='서울역센트럴자이 실제 주소 샘플', area_name='서울특별시 중구 만리동2가', property_type='투룸', lease_type='월세', deposit_manwon=5000, monthly_rent_manwon=110, area_m2=46.0, floor=5, latitude=37.5549829, longitude=126.9631641,
         road_address='서울특별시 중구 만리재로 175', parcel_address='서울특별시 중구 만리동2가 273', postal_code='04500', building_name='서울역센트럴자이', address_source_url='https://findby.co.kr/details/04500-111403101016-st-652c0c7cf27008be2c565257', address_verified_on='2026-10-16'),
    _row(id='map-23', title='청파동 가상 빌라 23', area_name='서울특별시 용산구 청파동', property_type='빌라', lease_type='월세', deposit_manwon=1000, monthly_rent_manwon=65, area_m2=45.7, floor=2, latitude=37.548906, longitude=126.967727),
    _row(id='map-24', title='브라운스톤서울 실제 주소 샘플', area_name='서울특별시 중구 중림동', property_type='아파트', lease_type='전세', deposit_manwon=48000, monthly_rent_manwon=None, area_m2=59.0, floor=8, latitude=37.5608188, longitude=126.9682259,
         road_address='서울특별시 중구 청파로 464', parcel_address='서울특별시 중구 중림동 355', postal_code='04510', building_name='브라운스톤서울', address_source_url='https://findby.co.kr/details/04510-111403101023-st-652c0cc3f27008be2c572a5e', address_verified_on='2026-10-16'),
    _row(id='map-25', title='서계동 가상 오피스텔 25', area_name='서울특별시 용산구 서계동', property_type='오피스텔', lease_type='전세', deposit_manwon=32000, monthly_rent_manwon=None, area_m2=25.5, floor=1, latitude=37.558693, longitude=126.96388),
    _row(id='map-26', title='회현동 가상 원룸 26', area_name='서울특별시 중구 회현동', property_type='원룸', lease_type='전세', deposit_manwon=33000, monthly_rent_manwon=None, area_m2=24.8, floor=7, latitude=37.56021, longitude=126.975408),
    _row(id='map-27', title='동자동 가상 오피스텔 27', area_name='서울특별시 용산구 동자동', property_type='오피스텔', lease_type='월세', deposit_manwon=2000, monthly_rent_manwon=80, area_m2=29.4, floor=5, latitude=37.547914, longitude=126.971265),
    _row(id='map-28', title='후암동 가상 원룸 28', area_name='서울특별시 용산구 후암동', property_type='원룸', lease_type='월세', deposit_manwon=500, monthly_rent_manwon=120, area_m2=21.2, floor=14, latitude=37.551845, longitude=126.97867),
    _row(id='map-29', title='청파동 가상 아파트 29', area_name='서울특별시 용산구 청파동', property_type='아파트', lease_type='전세', deposit_manwon=26000, monthly_rent_manwon=None, area_m2=78.3, floor=19, latitude=37.549142, longitude=126.965025),
    _row(id='map-30', title='후암동 가상 아파트 30', area_name='서울특별시 용산구 후암동', property_type='아파트', lease_type='월세', deposit_manwon=5000, monthly_rent_manwon=160, area_m2=62.0, floor=10, latitude=37.555709, longitude=126.979767),
]
