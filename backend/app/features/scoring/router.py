"""F12 항목 가중치화 API.

GET·POST          /weight-profiles                    가중치 프로필 목록·만들기(계정 단위)
GET·PUT·DELETE    /weight-profiles/{profile_id}        프로필 하나 조회·통째로 고치기·삭제
GET·PUT           /listings/{listing_id}/satisfaction  매물 항목별 만족도 조회·통째로 바꾸기
GET·PUT           /sessions/{session_id}/scoring       세션 설정(켜기/끄기, 고른 프로필)
GET               /sessions/{session_id}/scores        적합도·순위(?filters=within_budget 처럼 필터 후 후보끼리)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.core.auth import CurrentUser, get_current_user
from app.core.db import Database, get_user_db
from app.core.ownership import get_owned_listing, get_owned_session
from app.core.schemas import OkOut
from app.features.scoring import service
from app.features.scoring.schemas import (
    SatisfactionIn, SatisfactionOut, ScoresOut, ScoringSettingIn, ScoringSettingOut, WeightProfileIn,
    WeightProfileOut,
)

router = APIRouter(tags=["scoring"])


# ------------------------------------------------------------------ 가중치 프로필
@router.get("/weight-profiles", response_model=list[WeightProfileOut])
def list_weight_profiles(user: CurrentUser = Depends(get_current_user),
                         db: Database = Depends(get_user_db)) -> list[WeightProfileOut]:
    """내 프로필을 만든 순서로."""
    return service.list_profiles(db, user)


@router.post("/weight-profiles", response_model=WeightProfileOut)
def create_weight_profile(body: WeightProfileIn, user: CurrentUser = Depends(get_current_user),
                          db: Database = Depends(get_user_db)) -> WeightProfileOut:
    return service.create_profile(db, user, body)


@router.get("/weight-profiles/{profile_id}", response_model=WeightProfileOut)
def read_weight_profile(profile_id: str, user: CurrentUser = Depends(get_current_user),
                        db: Database = Depends(get_user_db)) -> WeightProfileOut:
    row = service.get_owned_profile(db, user, profile_id)
    return service.to_profile_out(row, service.weights_of(db, row["id"]))


@router.put("/weight-profiles/{profile_id}", response_model=WeightProfileOut)
def update_weight_profile(profile_id: str, body: WeightProfileIn, user: CurrentUser = Depends(get_current_user),
                          db: Database = Depends(get_user_db)) -> WeightProfileOut:
    """이름과 가중치를 통째로 바꾼다(빠진 항목은 0)."""
    return service.update_profile(db, user, profile_id, body)


@router.delete("/weight-profiles/{profile_id}", response_model=OkOut)
def delete_weight_profile(profile_id: str, user: CurrentUser = Depends(get_current_user),
                          db: Database = Depends(get_user_db)) -> OkOut:
    """이 프로필을 고른 세션은 '프로필 없음(동일 가중치)'이 된다."""
    service.delete_profile(db, user, profile_id)
    return OkOut()


# ------------------------------------------------------------------ 매물 만족도
@router.get("/listings/{listing_id}/satisfaction", response_model=SatisfactionOut)
def read_satisfaction(listing_id: str, user: CurrentUser = Depends(get_current_user),
                      db: Database = Depends(get_user_db)) -> SatisfactionOut:
    listing = get_owned_listing(db, user, listing_id)
    values, updated_at = service.satisfactions_of(db, listing["id"])
    return service.to_satisfaction_out(listing["id"], values, updated_at)


@router.put("/listings/{listing_id}/satisfaction", response_model=SatisfactionOut)
def put_satisfaction(listing_id: str, body: SatisfactionIn, user: CurrentUser = Depends(get_current_user),
                     db: Database = Depends(get_user_db)) -> SatisfactionOut:
    """보낸 항목만 저장하고 나머지는 미입력. 0~100 밖이면 422."""
    listing = get_owned_listing(db, user, listing_id)
    return service.save_satisfactions(db, listing["id"], body)


# ------------------------------------------------------------------ 세션 설정·점수
@router.get("/sessions/{session_id}/scoring", response_model=ScoringSettingOut)
def read_scoring(session_id: str, user: CurrentUser = Depends(get_current_user),
                 db: Database = Depends(get_user_db)) -> ScoringSettingOut:
    """설정한 적이 없으면 켜짐·프로필 없음(동일 가중치)."""
    session = get_owned_session(db, user, session_id)
    return service.to_setting_out(db, session["id"], service.get_setting_row(db, session["id"]))


@router.put("/sessions/{session_id}/scoring", response_model=ScoringSettingOut)
def put_scoring(session_id: str, body: ScoringSettingIn, user: CurrentUser = Depends(get_current_user),
                db: Database = Depends(get_user_db)) -> ScoringSettingOut:
    """남의 프로필·없는 프로필은 404 WEIGHT_PROFILE_NOT_FOUND."""
    session = get_owned_session(db, user, session_id)
    return service.save_setting(db, user, session["id"], body)


@router.get("/sessions/{session_id}/scores", response_model=ScoresOut)
def read_scores(
    session_id: str,
    filters: str | None = Query(default=None, max_length=200, description="쉼표로 구분한 행 필터 이름(예: within_budget)"),
    user: CurrentUser = Depends(get_current_user),
    db: Database = Depends(get_user_db),
) -> ScoresOut:
    session = get_owned_session(db, user, session_id)
    return service.build_scores(db, user, session, service.parse_filters(filters))
