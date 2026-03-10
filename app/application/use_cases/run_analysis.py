"""Use case — run a persona system pipeline synchronously."""

import uuid

from app.application.dto.analysis_dto import AnalysisRequestDTO, AnalysisResultDTO
from app.core.orchestrator import Orchestrator
from app.domain.entities.analysis import AnalysisRequest


class RunAnalysisUseCase:
    def __init__(self, orchestrator: Orchestrator) -> None:
        self._orchestrator = orchestrator

    async def execute(self, dto: AnalysisRequestDTO) -> AnalysisResultDTO:
        request_id = str(uuid.uuid4())

        analysis = AnalysisRequest(
            request_id=request_id,
            persona_system=dto.persona_system,
            ticker=dto.ticker,
            query=dto.query,
            country=dto.country,
            analysis_type=dto.analysis_type,
        )

        system = self._orchestrator.get_system(analysis.persona_system)

        result = await system.run_pipeline(
            request={
                "id": request_id,
                "ticker": analysis.ticker,
                "analysis_type": analysis.analysis_type,
            },
            intent=analysis.intent,
        )

        return AnalysisResultDTO(
            request_id=request_id,
            system_id=analysis.persona_system,
            result=result,
            cached=result.get("_cache", {}).get("hit", False),
        )
