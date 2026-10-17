"""F14 발품 후기 API: 기획안 검증 상황(10절)과 인수 조건(C1~C7, C9)."""

from __future__ import annotations

from tests.fakes import MemoryStorage

ADDR = "가상시 예시구 샘플동 123-45"     # 테스트용 가짜 주소
OTHER_ADDR = "가상시 예시구 견본동 77"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100
JPG = b"\xff\xd8\xff" + b"0" * 100
WEBP = b"RIFF0000WEBP" + b"0" * 100


def post_body(**kw) -> dict:
    body = {"address": ADDR, "topic": "구조·설비", "title": "보일러가 욕실 안쪽에 있어요",
            "body": "보일러실이 욕실 안에 있어 점검할 때 불편합니다."}
    body.update(kw)
    return body


def create(client, **kw) -> dict:
    r = client.post("/community/posts", json=post_body(**kw))
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ C1 인증
def test_community_requires_login(client_as):
    c = client_as(None)
    assert c.get("/community/posts").status_code == 401
    assert c.post("/community/posts", json=post_body()).status_code == 401


# ------------------------------------------------------------------ C2 작성·재조회
def test_community_create_without_optional_fields(client_as, make_user):
    """사진·층수·방문일 없이도 등록되고, 다시 조회된다."""
    alice = make_user(nickname="집보는사람")
    c = client_as(alice)
    post = create(c)
    assert post["floor"] is None and post["visit_date"] is None and post["photo"] is None
    assert post["nickname"] == "집보는사람" and post["is_mine"] is True
    again = client_as(alice).get(f"/community/posts/{post['id']}").json()
    assert again["title"] == "보일러가 욕실 안쪽에 있어요" and again["address"] == ADDR


def test_community_create_with_floor_and_visit_date(client_as, make_user):
    post = create(client_as(make_user()), floor=3, visit_date="2026-10-17")
    assert post["floor"] == 3 and post["visit_date"] == "2026-10-17"


def test_community_required_fields(client_as, make_user):
    c = client_as(make_user())
    for missing in ("address", "topic", "title", "body"):
        body = post_body()
        body.pop(missing)
        assert c.post("/community/posts", json=body).status_code == 422, missing
    assert c.post("/community/posts", json=post_body(address="   ")).status_code == 422
    assert c.post("/community/posts", json=post_body(topic="맛집")).status_code == 422
    assert c.post("/community/posts", json=post_body(floor=0)).status_code == 422


def test_community_rejects_contact_info(client_as, make_user):
    c = client_as(make_user())
    r = c.post("/community/posts", json=post_body(body="궁금하면 010-1234-5678로 연락 주세요"))
    assert r.status_code == 422 and r.json()["error"]["detail"]["reason"] == "contact_info"
    r = c.post("/community/posts", json=post_body(title="문의 tester@example.com"))
    assert r.status_code == 422 and r.json()["error"]["detail"]["field"] == "title"


# ------------------------------------------------------------------ C3 검색
def test_community_list_all_newest_first_then_filter(client_as, make_user):
    alice, bob = make_user(), make_user()
    create(client_as(alice), title="첫 글", floor=3, topic="소음")
    create(client_as(bob), title="두 번째", address=OTHER_ADDR, floor=2)
    create(client_as(bob), title="세 번째", topic="채광")            # 층수 없음
    c = client_as(alice)

    assert [p["title"] for p in c.get("/community/posts").json()] == ["세 번째", "두 번째", "첫 글"]
    # 주소 부분 일치: 띄어쓰기·"번지" 표기가 달라도 찾는다
    assert {p["title"] for p in c.get("/community/posts", params={"address": "샘플동 123번지 45"}).json()} \
        == {"첫 글", "세 번째"}
    assert [p["title"] for p in c.get("/community/posts", params={"address": "견본동"}).json()] == ["두 번째"]
    # 층수: 같은 층만, 층수를 비운 글은 빠진다
    assert [p["title"] for p in c.get("/community/posts", params={"floor": 3}).json()] == ["첫 글"]
    assert [p["title"] for p in c.get("/community/posts", params={"topic": "채광"}).json()] == ["세 번째"]
    assert c.get("/community/posts", params={"address": "없는동"}).json() == []
    assert c.get("/community/posts", params={"topic": "맛집"}).status_code == 422


def test_community_list_mine_only(client_as, make_user):
    alice, bob = make_user(), make_user()
    create(client_as(alice), title="내 글")
    create(client_as(bob), title="남의 글")
    mine = client_as(alice).get("/community/posts", params={"mine": "true"}).json()
    assert [(p["title"], p["is_mine"]) for p in mine] == [("내 글", True)]


# ------------------------------------------------------------------ C4·C5 상세·사진
def test_community_photo_upload_and_detail(client_as, make_user, memory_storage):
    alice, bob = make_user(), make_user()
    post = create(client_as(alice))
    r = client_as(alice).post(f"/community/posts/{post['id']}/photo", files={"file": ("a.png", PNG, "image/png")})
    assert r.status_code == 200, r.text
    photo = r.json()["photo"]
    assert photo["content_type"] == "image/png" and photo["url"]
    path = next(iter(memory_storage.objects))
    assert path == f"{alice.auth_user_id}/community/{post['id']}/{photo['id']}.png"
    # 다른 사용자도 사진과 본문을 함께 본다
    seen = client_as(bob).get(f"/community/posts/{post['id']}").json()
    assert seen["photo"]["url"] and seen["is_mine"] is False
    assert client_as(bob).get("/community/posts").json()[0]["has_photo"] is True


def test_community_photo_rules(client_as, make_user, memory_storage):
    alice = make_user()
    c = client_as(alice)
    post = create(c)
    url = f"/community/posts/{post['id']}/photo"
    assert c.post(url, files={"file": ("a.webp", WEBP, "image/webp")}).json()["error"]["detail"]["reason"] \
        == "unsupported_type"
    big = b"\xff\xd8\xff" + b"0" * (5 * 1024 * 1024)
    assert c.post(url, files={"file": ("big.jpg", big, "image/jpeg")}).json()["error"]["detail"]["reason"] \
        == "too_large"
    assert c.post(url, files={"file": ("a.jpg", JPG, "image/jpeg")}).status_code == 200
    # 글당 1장: 다시 올리면 바꾼다
    assert c.post(url, files={"file": ("b.png", PNG, "image/png")}).status_code == 200
    assert len(memory_storage.objects) == 1 and next(iter(memory_storage.objects)).endswith(".png")
    assert c.delete(url).json()["photo"] is None
    assert memory_storage.objects == {}


def test_community_photo_storage_failure(client_as, make_user, memory_storage):
    alice = make_user()
    c = client_as(alice)
    post = create(c)
    memory_storage.fail_uploads = True
    r = c.post(f"/community/posts/{post['id']}/photo", files={"file": ("a.png", PNG, "image/png")})
    assert r.status_code == 503 and r.json()["error"]["code"] == "STORAGE_UNAVAILABLE"


# ------------------------------------------------------------------ C6 본인만 수정·삭제
def test_community_only_author_can_edit_or_delete(client_as, make_user, memory_storage):
    alice, bob = make_user(), make_user()
    post = create(client_as(alice))
    b = client_as(bob)
    assert b.patch(f"/community/posts/{post['id']}", json={"title": "바꿈"}).status_code == 403
    assert b.delete(f"/community/posts/{post['id']}").status_code == 403
    assert b.post(f"/community/posts/{post['id']}/photo",
                  files={"file": ("a.png", PNG, "image/png")}).status_code == 403
    assert client_as(alice).get(f"/community/posts/{post['id']}").json()["title"] == "보일러가 욕실 안쪽에 있어요"


def test_community_author_edit_and_delete(client_as, make_user, memory_db, memory_storage):
    alice = make_user()
    c = client_as(alice)
    post = create(c, floor=3)
    r = c.patch(f"/community/posts/{post['id']}", json={"title": "고친 제목", "floor": None,
                                                         "address": "샘플동  123번지 45"})
    assert r.status_code == 200
    out = r.json()
    assert out["title"] == "고친 제목" and out["floor"] is None and out["topic"] == "구조·설비"
    assert out["address"] == "샘플동 123번지 45"
    assert c.patch(f"/community/posts/{post['id']}", json={"title": None}).status_code == 422
    assert c.patch(f"/community/posts/{post['id']}", json={"body": "010 1234 5678"}).status_code == 422

    c.post(f"/community/posts/{post['id']}/photo", files={"file": ("a.png", PNG, "image/png")})
    assert c.delete(f"/community/posts/{post['id']}").json() == {"ok": True}
    assert memory_storage.objects == {}                  # 사진 파일도 지운다
    assert memory_db.select("community_post_photos") == []
    r = c.get(f"/community/posts/{post['id']}")
    assert r.status_code == 404 and r.json()["error"]["code"] == "POST_NOT_FOUND"


def test_community_delete_keeps_post_when_file_cleanup_fails(client_as, make_user, memory_storage):
    alice = make_user()
    c = client_as(alice)
    post = create(c)
    c.post(f"/community/posts/{post['id']}/photo", files={"file": ("a.png", PNG, "image/png")})
    memory_storage.fail_deletes = True
    r = c.delete(f"/community/posts/{post['id']}")
    assert r.status_code == 503 and r.json()["error"]["code"] == "CLEANUP_FAILED"
    assert c.get(f"/community/posts/{post['id']}").status_code == 200


def test_community_not_found_and_bad_id(client_as, make_user):
    c = client_as(make_user())
    assert c.get("/community/posts/not-a-uuid").status_code == 404
    assert c.get("/community/posts/00000000-0000-0000-0000-000000000000").status_code == 404


# ------------------------------------------------------------------ C7 개인정보
def test_community_response_hides_author_identity(client_as, make_user):
    alice = make_user(nickname="닉네임만", email="alice-secret@example.com")
    post = create(client_as(alice))
    for item in (post, client_as(make_user()).get("/community/posts").json()[0]):
        text = str(item)
        assert "alice-secret" not in text and alice.profile_id not in text and "profile_id" not in item


# ------------------------------------------------------------------ C9 요청 로그
def test_community_request_logged_without_address(client_as, make_user, memory_db):
    c = client_as(make_user())
    c.get("/community/posts", params={"address": "샘플동"})
    logs = [r for r in memory_db.select("request_logs") if r["endpoint"] == "/community/posts"]
    assert logs and logs[-1]["status_code"] == 200
    assert "샘플동" not in str(logs)


def test_community_topics(client_as, make_user):
    assert client_as(make_user()).get("/community/topics").json() == {
        "topics": ["구조·설비", "소음", "채광", "주변 환경", "기타"]}
