# 확장 계획 (F12~F14)

F12·F14는 구현했고(아래 F12·F14 절), F13은 내 매물 위치·세션 매물 지도·전체 매물 지도를 구현했다(찜은 아직). 기능마다 “지금 있는 자리”(이미 마련된 연결 지점)와 “나중 계획”을 적는다.
각 항목 끝의 표시는 출처다: [요청] 단계 파일에 적힌 내용(F12 절은 담당자가 #14에서, F14 절은 담당자가 #21에서 정한 내용) · [기존 계획] 이 문서의 처음 계획 · [Claude 제안] 문서·구현 때 덧붙인 제안(F13은 착수 때 팀이 정한다).

## 공통: 새 기능을 붙이는 방법

- 백엔드: `backend/app/features/<이름>/`에 `router.py`(변수 `router`)와 필요하면 `hooks.py`를 두면 자동 등록된다. `hooks.py`의 등록 코드는 여러 번 실행돼도 안전해야 한다. [요청]
- 프론트: `frontend/features/<이름>/`에 `pages.py`(`PAGES`)·`sections.py`(`SECTIONS`). import 때 Streamlit 함수를 부르지 않는다. [요청]
- 마이그레이션 번호대: F12 `0120~`(사용 중: `0120_scoring.sql`), F13 `0130~`(사용 중: `0131_listing_locations.sql`, `0132_drop_map_listings.sql`. `0130`은 지운 더미 매물이 썼던 번호라 다시 쓰지 않음), F14 `0140~`(사용 중: `0140_community.sql`, `0141_community_likes.sql`). [요청]
- 추가 패키지는 `backend/requirements/<기능>.txt`·`frontend/requirements/<기능>.txt`에 `==`로 고정한다. [Claude 제안]
- 새 테이블은 기존처럼 소유 사슬(profile → session → listing)로 RLS를 걸고, 소유 확인은 `core/ownership.py` 방식(타인 리소스는 404)을 따른다. [Claude 제안]

---

## F12 항목 가중치화 — 매물 적합도 점수 (담당 민성) · 구현됨 (#14)

처음 계획(AI가 속성을 좋음/나쁨/모름으로 추출, 기간으로 프로필 자동 적용)에서 아래처럼 바꿔 구현했다. [요청]

### 구현한 것

- 사용자가 매물마다 항목별 **만족도(0~100 정수, 높을수록 좋음)**를 직접 입력한다. 측정값(dB·%)은 쓰지 않는다. [요청]
- 항목별 **가중치(0~100 정수)**를 묶은 **가중치 프로필**을 계정 단위로 만들고(예: 여름 6개월·겨울 6개월), 세션마다 하나를 직접 고른다. 기간 자동 적용은 하지 않는다. [요청]
- 적합도 = Σ(가중치 × 만족도) ÷ Σ가중치, 0.5는 올리는 반올림으로 0~100 정수. 점수는 저장하지 않고 요청 때마다 서버가 계산한다. [요청]
  - 만족도를 입력하지 않은 항목은 빼고 남은 항목으로 비율을 맞춘다(처음 계획의 "모름 처리 규칙"을 이렇게 정함). [요청]
  - 쓰는 항목의 가중치가 전부 0이거나 프로필을 고르지 않으면 동일 가중치. 입력한 항목이 없으면 점수 없음(미입력). [요청]
- 세션마다 가중치 기능을 켜고 끈다. 끄면 비교표 열은 "꺼짐", 적합도 순위는 숨긴다(입력값은 남음). [요청]
- 순위는 필터(예산)를 통과한 후보끼리 매긴다. 같은 점수는 같은 순위(1, 2, 2, 4). [요청]
- 평가 항목은 `backend/app/features/scoring/items.py`의 `SCORE_ITEMS`(기본 = `CHECKLIST` 9개). F12 안에 따로 두어 바꿔도 AI 분석·평가에 영향이 없다. 추가된 항목은 기존 프로필에서 가중치 0, 빠진 항목의 DB 행은 무시한다. [요청]

### 연결 지점

- API: `GET /score-items`, `GET·POST /weight-profiles`, `GET·PUT·DELETE /weight-profiles/{profile_id}`, `GET·PUT /listings/{listing_id}/satisfaction`, `GET·PUT /sessions/{session_id}/scoring`, `GET /sessions/{session_id}/scores?filters=`. 모델은 `features/scoring/schemas.py`. [Claude 제안]
- 비교표 열 key `score`(제목 "적합도", order 20). 열은 필터 전 전체 매물로 계산하므로 순위는 넣지 않는다. [기존 계획 + Claude 제안]
- 화면 슬롯: `session_detail` 45 가중치 설정·프로필 관리(예산 40 아래), 35 적합도 순위 / `listing_detail` 45 항목 만족도. [Claude 제안]
- 마이페이지 '가중치 프로필' 탭: 세션과 상관없이 프로필 목록을 보고 만들기·고치기·삭제(`render_profile_manager()`, 마이페이지 P4 파일에서 부름). [요청]
- 테이블(`0120_scoring.sql`, 소유 사슬 RLS) [기존 계획을 바꿈]

  | 테이블 | 열 |
  | --- | --- |
  | `weight_profiles` | id, profile_id, name, created_at, updated_at |
  | `weight_items` | weight_profile_id, item_key, weight (PK 앞 두 열) |
  | `listing_satisfactions` | listing_id, item_key, satisfaction, updated_at (PK 앞 두 열) |
  | `session_scoring` | session_id(PK), enabled, weight_profile_id(프로필 삭제 시 null), updated_at |

- 오류: 없거나 남의 프로필은 404 `WEIGHT_PROFILE_NOT_FOUND`.

### 남은 한계

- 만족도는 사용자 주관이라 같은 집도 사람마다 점수가 다르다(비교 도구이지 객관 평가가 아님).
- 순위는 비교표 안이 아니라 비교표 아래 별도 섹션에 보인다(비교표 파일을 고치지 않기 위해).

---

## F13 찜·지도 (담당 건형)

### 구현한 것 — demo_st 지도 이전

- `demo_st/main.py`의 카카오 지도·주소 검색 JavaScript(SDK 로딩·주소 검색 창)를 `frontend/features/map/components.py`로 옮겨 아래 화면들이 쓴다. `demo_st` 폴더는 남겨 둔다. [요청]
- 처음에는 서울역 주변 더미 매물 30개(`map_listings`, `GET /map/listings`, `0130`)와 반경 검색 화면을 옮겼으나, 화면을 '전체 매물'로 바꾸며 쓰지 않게 되어 지웠다. 이미 0130을 실행한 DB는 `0132_drop_map_listings.sql`로 테이블을 지운다. [요청]
- 카카오 JavaScript 키는 화면(브라우저)에서 지도 SDK를 불러올 때 쓴다: `st.secrets` → 환경변수 → `frontend/.env`의 `KAKAO_JAVASCRIPT_KEY`, 없으면 화면에서 입력. 주소 → 좌표 변환도 지금은 화면의 카카오 SDK가 한다(아래 나중 계획의 서버 변환과 다름). [요청]
- 코드: `backend/app/features/map/`(router·locations·schemas), `frontend/features/map/`(pages·sections·listing_map·components·logic), 테스트 `backend/tests/map/`. [Claude 제안]

### 구현한 것 — 내 매물 위치와 세션 매물 지도

- 사이드바 '전체 매물'(key `map`, 옛 '동네 지도 탐색'을 바꿈): 내 모든 세션에서 위치를 넣은 매물을 사이드바를 뺀 화면 전체 지도에 핀으로 찍는다. 핀 위 이름표는 두 줄(위 세션 이름, 아래 N번 집, 긴 세션 이름은 말줄임)이다. 핀 카드는 세션 상세 지도와 같고, 주소 줄 앞에 세션 이름을 붙인다. 카드 글이 길면 카드 폭 안에서 줄을 바꾼다. 왼쪽 위 패널에 위치 있는/없는 매물 수와 매물 목록(세션 상세 매물 카드처럼 대표 사진·N번 집·분석 상태·메모, 여기에 세션 이름·보증금·월세)을 두고, 항목을 누르면 지도가 그 매물로 옮겨 가며 정보 카드가 열린다. 핀을 누르면 목록의 같은 항목이 강조된다. 패널은 [접기]로 접는다. API `GET /me/locations`(메모·분석 상태 포함), 사진은 `GET /me/photos`. [요청]
- 세션 상세의 '매물' 목록 오른쪽에 지도를 두고, 위치를 넣은 이 세션의 내 매물을 "N번 집" 핀으로 찍는다. 핀(또는 이름표)을 누르면 정보 카드(N번 집·주소·보증금·월세·관리비·[매물 상세 보기])가 열리고, [매물 상세 보기]는 그 매물 상세로 이동한다. 금액은 비교표와 같은 값(최신 성공 분석 + 사용자 수정값), 분석 전이면 안내만 보인다. 위치가 없는 매물 수도 알려 준다. [요청]
- 매물 상세 슬롯 `listing_detail` 50 '위치': 카카오 주소 검색으로 주소를 고르면 지도(카카오 JS SDK)가 좌표로 바꿔 임시 핀을 보여 주고, [이 위치로 저장]을 눌러야 저장한다. 주소 바꾸기·위치 지우기 가능. [요청 + Claude 제안]
- 주소 입력란은 메모와 분리했고(아래 나중 계획), 위치는 본인만 보며 AI 분석에 보내지 않는다는 안내를 섹션에 둔다. 공통 안내 문구(`core/ui.py`의 "실제 주소를 적지 마세요")는 메모에 대한 것이라 그대로 둔다. [Claude 제안]
- API `GET·PUT·DELETE /listings/{listing_id}/location`, `GET /sessions/{session_id}/locations`, 테이블 `listing_locations`(`0131_listing_locations.sql`, 매물당 하나, 소유 사슬 RLS, 매물 삭제 시 CASCADE). [Claude 제안]
- P1 파일 `frontend/features/sessions/sections.py`의 매물 목록만 두 칸(카드 3 : 지도 2)으로 나눴다(담당자 요청). [요청]

### 지금 있는 자리

- 매물 상세 슬롯 `listing_detail` — 찜 버튼·지도 섹션을 붙이는 자리(지금 쓰는 순서: 10·20·30·40). [요청]
- 비교표 열 제공자 — 찜 여부 열을 붙이는 자리. [요청]

### 나중 계획

- 찜 테이블(profile_id, listing_id). [요청]
- 매물에 주소·좌표를 저장한다. [요청]
- 주소 → 좌표 변환은 **서버에서** 카카오 로컬 API로 하고, 키는 서버 환경변수에 둔다(화면에서 직접 부르지 않음). [요청]
- 지도에서 핀을 고르면 그 매물 정보를 보여 주고, 주소 없음·검색 실패는 안내 문구로 알린다. [요청]
- 지금은 메모에 실제 주소를 적지 말라고 안내하므로, 주소 입력란은 메모와 분리해 사용자가 명시적으로 넣게 하고 개인정보 안내를 고친다. [Claude 제안]
- 환경변수 이름 예: `KAKAO_REST_API_KEY`, 섹션 순서 예: `listing_detail` 50. [Claude 제안]

---

## F14 발품 후기 — 주소별 후기 커뮤니티 (담당 영은) · 구현됨 (#21)

처음 계획(내 매물 사진을 골라 공개)과 달리, 집을 직접 보고 확인한 정보를 **지번 주소 단위로 글로 남기고 다른 사용자가 보는** 커뮤니티로 바꿔 구현했다. 개인 매물·메모와는 연결하지 않는다. [요청]

### 구현한 것

- 페이지 3개: **발품 후기**(목록, 사이드바에 보임), **발품 후기 쓰기**(사이드바에 안 보임, 목록의 [발품 후기 쓰기] 버튼으로 열고 '← 발품 후기'로 돌아감, 등록하면 목록으로 이동), **발품 후기 상세**(사이드바에 안 보임, 목록·마이페이지 '내 발품 후기' 탭의 [자세히 보기]로 열고 '← 목록으로'·브라우저 뒤로가기로 연 곳의 목록에 돌아감. 마이페이지에서 열면 마이페이지 제목·탭 아래 '내 발품 후기' 탭에 보임). 사이드바 '발품 후기'와 '내 발품 후기' 탭은 늘 목록을 보여 준다. [요청]
- 쓰기: 필수 지번 주소(카카오 주소 검색으로 고름)·주제·제목·내용, 선택 층수·방문일·사진 1장(JPG·PNG, 5MB). 등록 전에 개인정보 확인 체크. [요청]
- 주제: 구조·설비 / 소음 / 채광 / 주변 환경 / 기타. [요청]
- 안내 문구: 연락처·실명 금지, 단독·다가구는 주소만으로 사는 사람이 특정될 수 있다는 주의. 제목·내용에 전화번호·이메일 모양이 있으면 서버가 거절한다. [요청]
- 목록: 처음에는 전체 후기 최신순. 지번 주소 일부로 검색([조회]·[초기화]), 층·주제로 거르기. 자세히 보기에서 내 글은 수정·삭제, 남의 글은 보기만. 내 글에는 "내 글" 표시. [요청]
- 마이페이지 '내 발품 후기' 탭: 내가 쓴 후기만 모아 보고 고치기·지우기(`render_my_posts()`, 마이페이지 P4 파일에서 부름). [요청]
- 후기를 지우면 사진 파일도 지운다(파일 삭제 실패 시 503 `CLEANUP_FAILED`, 글은 남음). [요청]

### 연결 지점

- API: `GET /community/topics`, `GET·POST /community/posts`, `GET·PATCH·DELETE /community/posts/{post_id}`, `POST·DELETE /community/posts/{post_id}/photo`. 모델은 `features/community/schemas.py`. [Claude 제안]
- 페이지 key·order: `balpum_write` 60, `balpum_list` 65, `balpum_post` 66(상세). [Claude 제안]
- 주소 정리 규칙 `backend/app/features/community/address.py`(공백 정리, 검색 키는 "번지" 표기·공백을 지운 소문자). F13(지도)에서 주소를 다룰 때 같은 규칙을 쓰면 두 기능의 주소가 맞는다. [요청]
- 테이블(`0140_community.sql`) [기존 계획을 바꿈]

  | 테이블 | 열 |
  | --- | --- |
  | `community_posts` | id, profile_id, address, address_key, floor, topic, visit_date, title, body, created_at, updated_at |
  | `community_post_photos` | id, post_id(UNIQUE), profile_id, storage_path, content_type, size_bytes, created_at |

- RLS: 읽기는 로그인한 사용자 모두, 쓰기·고치기·지우기는 작성자만(남의 글 → 403 `FORBIDDEN`, 없는 글 → 404 `POST_NOT_FOUND`).
- 사진은 기존 비공개 버킷 `listing-photos`의 `{auth.uid()}/community/{post_id}/…`에 두고, 두 번째 폴더가 `community`인 파일만 로그인 사용자가 읽게 하는 Storage 정책을 더했다. 매물 사진은 계속 본인만 읽는다. 응답에는 서명 URL만 준다. [요청]
- `photos.visibility` 열(F10)은 쓰지 않는다(항상 `private`). [요청]

### 남은 한계와 향후 확장

- **운영자 숨김·처리 기록**: 신고된 글을 운영자가 숨기고 처리 내역을 남기는 기능은 이번 범위에서 뺐다. 향후 확장으로 둔다. [요청]
- 주소 검색은 부분 일치라 서버가 최근 글 1000개 안에서 거른다. 글이 아주 많아지면 DB 검색(예: trigram 색인)으로 바꿔야 한다. [Claude 제안]
- 사진 속 개인정보(문패·우편물 등)는 자동으로 가리지 않는다. 등록 전 확인 체크와 안내 문구로만 막는다. [Claude 제안]

---

## 향후 확장 (기능 번호 없음)

- 입주 점검·거주 중 기록: 지금 서비스는 집을 구하는 기간에 집중하므로 계획만 둔다. [요청]
