"""현재 사용자의 프로필 생성·조회·수정 요청을 서비스에 전달한다."""

from fastapi import APIRouter

from app.schemas import ProfileInput, ProfileRecord

router = APIRouter(tags=["프로필"])
