"""분석 파이프라인 등록. create_app()마다 다시 읽힌다.

이미 등록된 파이프라인이 있으면(예: 다른 기능 테스트가 FakePipeline을 먼저 등록) 바꾸지 않는다.
등록부가 비어 있을 때만 실제 Gemini 파이프라인을 넣는다. 여러 번 돌아도 안전하다.
"""

from __future__ import annotations

from app.core.analysis_contract import get_pipeline, register_pipeline
from app.core.errors import AppError
from app.features.analysis.pipeline import GeminiAnalysisPipeline


def register() -> None:
    try:
        get_pipeline()
    except AppError:
        register_pipeline(GeminiAnalysisPipeline())


register()
