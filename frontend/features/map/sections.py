"""F13 매물 상세 슬롯: listing_detail order 50 '위치'(주소 검색 → 좌표 확인 → 저장)."""

from __future__ import annotations

from features.map.listing_map import render_listing_location

SECTIONS = [
    {"slot": "listing_detail", "order": 50, "area": "media", "render": render_listing_location},   # '사진·위치' 탭
]
