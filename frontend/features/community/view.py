"""발품 후기 표시 도우미(st를 부르지 않는 순수 함수). 화면과 테스트가 함께 쓴다."""

from __future__ import annotations

TOPICS = ["구조·설비", "소음", "채광", "주변 환경", "기타"]   # 서버 TOPICS와 같게 둔다(서버가 최종 검사)
ALL = "전체"
FLOOR_OPTIONS: list = [ALL] + list(range(-3, 0)) + list(range(1, 51))
MAX_PHOTO_MB = 5
PHOTO_EXTS = ["jpg", "jpeg", "png"]
TITLE_MAX = 100
BODY_MAX = 3000
ADDRESS_MAX = 200

PRIVACY_NOTICE = ("연락처·실명은 적지 마세요. 단독·다가구 주택은 주소만으로 사는 사람이 특정될 수 있으니 "
                  "사진과 내용을 한 번 더 확인해 주세요.")

# 목록 정렬: 화면 라벨 → GET /community/posts?sort=
SORTS: dict[str, str] = {"최신순": "latest", "좋아요 많은순": "likes"}
DEFAULT_SORT = "최신순"
OWN_POST_LIKE_NOTE = "내 글에는 누를 수 없어요"
LIKE_HELP = "도움이 됐다면 눌러 주세요"
UNLIKE_HELP = "다시 누르면 취소돼요"

# 422 detail.reason → 안내 문구
REASONS = {
    "contact_info": None,   # 서버 문구를 그대로 쓴다(제목/내용 중 어디인지 알려 준다)
    "too_large": f"사진이 너무 큽니다. {MAX_PHOTO_MB}MB 이하로 줄여서 다시 올리세요.",
    "unsupported_type": "JPG·PNG 사진만 올릴 수 있습니다.",
    "empty_file": "빈 파일입니다. 사진 파일을 다시 고르세요.",
}


def fmt_floor(floor: int | None) -> str:
    if floor is None:
        return "층수 미입력"
    return f"지하 {-int(floor)}층" if int(floor) < 0 else f"{int(floor)}층"


def fmt_floor_option(value) -> str:
    return ALL if value == ALL else fmt_floor(value)


def meta_line(post: dict) -> str:
    """'주소 · 3층 · 소음 · 닉네임 · 10/17 방문'"""
    visit = post.get("visit_date")
    visit_text = f"{visit} 방문" if visit else "방문일 미입력"
    return " · ".join([post.get("address", ""), fmt_floor(post.get("floor")), post.get("topic", ""),
                       post.get("nickname", ""), visit_text])


def like_mark(post: dict) -> str:
    """'♥ 8'(내가 누름) / '♡ 2'(안 누름)."""
    return f"{'♥' if post.get('liked_by_me') else '♡'} {int(post.get('like_count') or 0)}"


def like_button_label(post: dict) -> str:
    return f"{'♥' if post.get('liked_by_me') else '♡'} 좋아요 {int(post.get('like_count') or 0)}"


def list_params(filters: dict, sort_label: str = DEFAULT_SORT) -> dict:
    """화면 필터 → GET /community/posts 쿼리. '전체'와 빈 값, 기본 정렬(최신순)은 보내지 않는다."""
    params: dict = {}
    sort = SORTS.get(sort_label, "latest")
    if sort != "latest":
        params["sort"] = sort
    address = (filters.get("address") or "").strip()
    if address:
        params["address"] = address
    if filters.get("floor") not in (None, ALL):
        params["floor"] = int(filters["floor"])
    if filters.get("topic") not in (None, ALL, ""):
        params["topic"] = filters["topic"]
    return params


def form_problems(address: str, title: str, body: str, topic: str | None) -> list[str]:
    """필수 칸 확인(서버도 다시 확인한다)."""
    problems = []
    if not (address or "").strip():
        problems.append("지번 주소를 입력하세요.")
    if not topic:
        problems.append("주제를 고르세요.")
    if not (title or "").strip():
        problems.append("제목을 입력하세요.")
    if not (body or "").strip():
        problems.append("내용을 입력하세요.")
    return problems
