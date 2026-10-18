"""F13 지도 탐색 화면의 값 계산(Streamlit을 쓰지 않는다)."""

from __future__ import annotations

import os
from pathlib import Path

# 로컬 실행용 키 파일(git에 올리지 않는다. .gitignore의 .env 규칙)
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
DEMO_ORIGIN = {"label": "서울역 데모 기준점", "latitude": 37.5547, "longitude": 126.9706}
RADIUS_OPTIONS = [300, 500, 1000]
KEY_NAME = "KAKAO_JAVASCRIPT_KEY"

# st.session_state 키(다른 기능과 겹치지 않게 map_ 으로 시작한다)
COMMAND = "map_command"
ORIGIN = "map_search_origin"
SELECTED = "map_selected_listing_id"
RADIUS = "map_radius_m"
KEY_INPUT = "map_kakao_javascript_key"


def read_env_file(path: Path, name: str) -> str:
    """KEY=VALUE 형식의 .env 파일에서 값 하나를 읽는다(python-dotenv 없이). 없으면 빈 문자열."""
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return ""
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip().removeprefix("export ").strip() == name:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            return value.strip()
    return ""


def configured_api_key(secrets: object | None = None, env_file: Path = ENV_FILE) -> str:
    """카카오 JavaScript 키: Streamlit secrets → 환경변수 → frontend/.env 순서로 읽는다. 없으면 빈 문자열."""
    value = ""
    if secrets is not None:
        try:
            value = str(secrets.get(KEY_NAME, "") or "")  # type: ignore[attr-defined]
        except Exception:  # secrets.toml이 없으면 예외
            value = ""
    return (value or os.environ.get(KEY_NAME, "") or read_env_file(env_file, KEY_NAME)).strip()


def radius_label(radius_m: int) -> str:
    return "1km" if radius_m == 1000 else f"{radius_m}m"


def price_text(listing: dict) -> str:
    if listing["lease_type"] == "월세":
        return f"보증금 {listing['deposit_manwon']:,} / 월 {listing['monthly_rent_manwon']:,}만원"
    return f"전세 {listing['deposit_manwon']:,}만원"


def data_note(listing: dict) -> str:
    if listing.get("road_address"):
        return "주소는 실제 위치이며, 표시된 매물 조건은 테스트용입니다."
    return "위치·가격·면적·층수 모두 테스트용 가상 값입니다."


def coordinate_text(point: dict | None) -> str:
    if not point:
        return "—"
    return f"{point['latitude']:.6f}, {point['longitude']:.6f}"


def next_command(current: dict | None, type_: str, **fields: object) -> dict:
    """지도에 보낼 명령. id가 바뀌어야 지도 쪽이 새 명령으로 알아본다."""
    return {"id": int((current or {}).get("id", 0)) + 1, "type": type_, **fields}


def search_params(origin: dict, radius_m: int) -> dict:
    return {"latitude": origin["latitude"], "longitude": origin["longitude"], "radius_m": radius_m}


def map_payload(origin: dict | None, radius_m: int, listings: list[dict]) -> dict:
    """지도 컴포넌트에 넘길 검색 결과(가격 문구를 붙인다)."""
    return {
        "origin": origin,
        "radiusM": radius_m,
        "listings": [{**listing, "price": price_text(listing)} for listing in listings],
    }


# ------------------------------------------------------------------ 내 매물 위치
def address_text(location: dict | None) -> str:
    """저장한 위치를 한 줄로. 도로명 → 지번 순, 건물명은 괄호로."""
    if not location:
        return ""
    text = location.get("road_address") or location.get("parcel_address") or ""
    if location.get("building_name"):
        text += f" ({location['building_name']})"
    return text


def session_pins(pins: list[dict]) -> list[dict]:
    """GET /sessions/{id}/locations 결과 → 핀 지도 데이터."""
    return [{"id": p["listing_id"], "label": p["label"], "detail": address_text(p["location"]),
             "latitude": p["location"]["latitude"], "longitude": p["location"]["longitude"], "clickable": True}
            for p in pins]


def location_body(geocoded: dict) -> dict:
    """핀 지도의 좌표 변환 결과 → PUT /listings/{id}/location 본문."""
    return {
        "road_address": geocoded.get("roadAddress") or None,
        "parcel_address": geocoded.get("parcelAddress") or None,
        "postal_code": geocoded.get("zonecode") or None,
        "building_name": geocoded.get("buildingName") or None,
        "latitude": geocoded["latitude"],
        "longitude": geocoded["longitude"],
    }
