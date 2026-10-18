"""F13 지도 화면의 값 계산(Streamlit을 쓰지 않는다)."""

from __future__ import annotations

import os
from pathlib import Path

# 로컬 실행용 키 파일(git에 올리지 않는다. .gitignore의 .env 규칙)
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
KEY_NAME = "KAKAO_JAVASCRIPT_KEY"
# 화면에서 입력한 키(st.session_state). 다른 기능과 겹치지 않게 map_ 으로 시작한다
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


# ------------------------------------------------------------------ 내 매물 위치
def address_text(location: dict | None) -> str:
    """저장한 위치를 한 줄로. 도로명 → 지번 순, 건물명은 괄호로."""
    if not location:
        return ""
    text = location.get("road_address") or location.get("parcel_address") or ""
    if location.get("building_name"):
        text += f" ({location['building_name']})"
    return text


def manwon_text(value: int | None) -> str:
    """만원 단위 금액 → '1,000만원', '1억 2,000만원', '2억'. None은 '미기재'."""
    if value is None:
        return "미기재"
    value = int(value)
    if value >= 10000:
        eok, rest = divmod(value, 10000)
        return f"{eok}억" + (f" {rest:,}만원" if rest else "")
    return f"{value:,}만원"


def pin_rows(pin: dict) -> list[dict]:
    """정보 카드의 금액 줄. 보증금·월세는 늘 보이고, 관리비는 적혀 있을 때만."""
    if not pin.get("analyzed"):
        return []
    rows = [{"label": "보증금", "value": manwon_text(pin.get("deposit_manwon"))},
            {"label": "월세", "value": manwon_text(pin.get("monthly_rent_manwon"))}]
    if pin.get("maintenance_fee_manwon") is not None:
        rows.append({"label": "관리비", "value": manwon_text(pin["maintenance_fee_manwon"])})
    for row in rows:
        row["muted"] = row["value"] == "미기재"
    return rows


def session_pins(pins: list[dict]) -> list[dict]:
    """GET /sessions/{id}/locations 결과 → 핀 지도 데이터(정보 카드: 이름·주소·금액·매물 상세 보기)."""
    return [{"id": p["listing_id"], "label": p["label"], "detail": address_text(p["location"]),
             "latitude": p["location"]["latitude"], "longitude": p["location"]["longitude"],
             "rows": pin_rows(p), "note": None if p.get("analyzed") else "AI 정리 전이라 금액이 아직 없습니다.",
             "link": True}
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


def my_pins(pins: list[dict]) -> list[dict]:
    """GET /me/locations의 pins → 핀 지도 데이터. 카드 주소 줄 앞에 세션 이름을 붙인다."""
    out = session_pins(pins)
    for pin, src in zip(out, pins):
        title = (src.get("session_title") or "").strip()
        if title:
            pin["detail"] = f"{title} · {pin['detail']}" if pin["detail"] else title
    return out


def panel_text(pin_count: int, listing_count: int) -> dict:
    """전체 매물 지도 왼쪽 위 요약."""
    missing = max(listing_count - pin_count, 0)
    subtitle = f"위치를 넣은 매물 {pin_count}곳"
    if missing:
        subtitle += f" · 위치 없는 매물 {missing}곳"
    return {"title": "전체 매물", "subtitle": subtitle}
