-- 0010_listing_name_update.sql — 매물 이름 수정 권한. 0009_listing_name.sql 뒤에 실행한다.
-- Supabase SQL 편집기에 그대로 붙여 실행한다. 여러 번 실행해도 안전하게 썼다(grant는 다시 실행해도 같다).
--
-- 세션 상세 매물 카드의 연필 버튼 → '매물 수정' 모달에서 이름(listings.name)과 메모를 함께 고친다.
-- 0003은 사용자에게 memo_text 수정 권한만 주었으므로 name 수정 권한을 더한다.
-- 길이 검사(1~30자)는 0009의 CHECK listings_name_len이 그대로 막는다.

grant update (name) on public.listings to authenticated;
