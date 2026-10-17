"""F14 주소 정리 규칙과 연락처 검사."""

from __future__ import annotations

from app.features.community.address import address_key, address_matches, normalize_address
from app.features.community.privacy import contact_reason


def test_community_address_rules():
    assert normalize_address("  가상시   예시구  샘플동 12-3 ") == "가상시 예시구 샘플동 12-3"
    assert address_key("샘플동 12번지 3") == address_key("샘플동 12-3") == "샘플동12-3"
    assert address_key("샘플동 12 번지") == "샘플동12"
    assert address_matches("샘플동 12-3", address_key("가상시 예시구 샘플동 12-3"))
    assert not address_matches("   ", address_key("가상시 예시구 샘플동 12-3"))
    assert not address_matches("견본동", address_key("가상시 예시구 샘플동 12-3"))


def test_community_contact_detection():
    for text in ("010-1234-5678", "01012345678", "010 1234 5678", "02-123-4567", "+82 10-1234-5678"):
        assert contact_reason(text) == "phone", text
    assert contact_reason("메일 someone@example.com") == "email"
    for text in ("3층, 2026-10-17 방문", "관리비 70000원", "123-45번지", "면적 33.05㎡", "보증금 1000/50"):
        assert contact_reason(text) is None, text
