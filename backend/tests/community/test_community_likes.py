"""F14 발품 후기 좋아요(0141): 누르기·취소, 내 글 막기, 좋아요 수·내가 눌렀는지, 좋아요 많은순 정렬."""

from __future__ import annotations

from tests.community.test_community_api import create


def _like(client, pid):
    return client.put(f"/community/posts/{pid}/like")


def _unlike(client, pid):
    return client.delete(f"/community/posts/{pid}/like")


def test_like_and_unlike_counts_once(client_as, make_user):
    alice, bob, carol = make_user(), make_user(), make_user()
    post = create(client_as(alice))
    assert post["like_count"] == 0 and post["liked_by_me"] is False

    r = _like(client_as(bob), post["id"])
    assert r.status_code == 200, r.text
    assert r.json() == {"post_id": post["id"], "like_count": 1, "liked_by_me": True}
    # 여러 번 눌러도 1번
    assert _like(client_as(bob), post["id"]).json()["like_count"] == 1
    assert _like(client_as(carol), post["id"]).json()["like_count"] == 2

    detail = client_as(bob).get(f"/community/posts/{post['id']}").json()
    assert detail["like_count"] == 2 and detail["liked_by_me"] is True
    mine = client_as(alice).get(f"/community/posts/{post['id']}").json()
    assert mine["like_count"] == 2 and mine["liked_by_me"] is False

    r = _unlike(client_as(bob), post["id"])
    assert r.status_code == 200 and r.json() == {"post_id": post["id"], "like_count": 1, "liked_by_me": False}
    # 누른 적 없어도 취소는 오류 없이 현재 상태
    assert _unlike(client_as(bob), post["id"]).json()["like_count"] == 1


def test_cannot_like_own_post(client_as, make_user):
    alice = make_user()
    post = create(client_as(alice))
    r = _like(client_as(alice), post["id"])
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN"
    assert client_as(alice).get(f"/community/posts/{post['id']}").json()["like_count"] == 0


def test_like_requires_login_and_existing_post(client_as, make_user):
    alice = make_user()
    post = create(client_as(alice))
    assert _like(client_as(None), post["id"]).status_code == 401
    assert _like(client_as(make_user()), "not-a-uuid").status_code == 404
    assert _like(client_as(make_user()), "00000000-0000-0000-0000-000000000000").status_code == 404


def test_list_shows_likes_and_sorts_by_likes(client_as, make_user):
    alice, bob, carol = make_user(), make_user(), make_user()
    old = create(client_as(alice), title="먼저 쓴 글")
    mid = create(client_as(alice), title="가운데 글")
    new = create(client_as(alice), title="나중에 쓴 글")
    for u in (bob, carol):
        _like(client_as(u), mid["id"])
    _like(client_as(bob), old["id"])

    latest = client_as(bob).get("/community/posts").json()
    assert [p["id"] for p in latest] == [new["id"], mid["id"], old["id"]]
    by_id = {p["id"]: p for p in latest}
    assert by_id[mid["id"]]["like_count"] == 2 and by_id[mid["id"]]["liked_by_me"] is True
    assert by_id[new["id"]]["like_count"] == 0 and by_id[new["id"]]["liked_by_me"] is False

    liked = client_as(carol).get("/community/posts", params={"sort": "likes"}).json()
    assert [p["id"] for p in liked] == [mid["id"], old["id"], new["id"]]
    # 같은 좋아요 수면 최신순
    tie = client_as(carol).get("/community/posts", params={"sort": "likes", "limit": 3}).json()
    assert [p["like_count"] for p in tie] == [2, 1, 0]
    assert client_as(carol).get("/community/posts", params={"sort": "popular"}).status_code == 422
