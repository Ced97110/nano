"""Use case — run a persona system pipeline with AG-UI SSE streaming."""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator

from app.application.dto.analysis_dto import AnalysisRequestDTO
from app.core.orchestrator import Orchestrator
from app.domain.entities.analysis import AnalysisRequest
from app.domain.interfaces.event_publisher import EventPublisher

logger = logging.getLogger(__name__)


class StreamAnalysisUseCase:
    def __init__(self, orchestrator: Orchestrator, events: EventPublisher) -> None:
        self._orchestrator = orchestrator
        self._events = events

    async def execute(self, dto: AnalysisRequestDTO) -> tuple[str, AsyncIterator[str]]:
        """Returns (request_id, SSE event stream)."""
        request_id = str(uuid.uuid4())

        analysis = AnalysisRequest(
            request_id=request_id,
            persona_system=dto.persona_system,
            ticker=dto.ticker,
            query=dto.query,
            country=dto.country,
            mode=dto.mode,
            analysis_type=dto.analysis_type,
        )

        system = self._orchestrator.get_system(analysis.persona_system)

        async def event_stream() -> AsyncIterator[str]:
            # Subscribe FIRST — ensures Redis subscription is active before
            # the pipeline publishes any events (fixes pub/sub race condition).
            subscriber = await self._events.subscribe(request_id)
            event_iter = subscriber.__aiter__()

            pipeline_task = asyncio.create_task(
                system.run_pipeline(
                    request={
                        "id": request_id,
                        "ticker": analysis.ticker,
                        "mode": analysis.mode,
                        "analysis_type": analysis.analysis_type,
                    },
                    intent=analysis.intent,
                )
            )

            run_finished = False
            try:

                while True:
                    # Wrap __anext__ in a task so we can race it against
                    # pipeline_task completing (e.g. due to a crash).
                    next_event_coro = event_iter.__anext__()
                    next_event_task = asyncio.ensure_future(next_event_coro)

                    # Wait for whichever finishes first: the next SSE event
                    # or the pipeline task itself.
                    done, _ = await asyncio.wait(
                        {next_event_task, pipeline_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )

                    if next_event_task in done:
                        try:
                            event = next_event_task.result()
                        except StopAsyncIteration:
                            break
                        yield f"data: {json.dumps(event, default=str)}\n\n"
                        if event.get("type") == "RUN_FINISHED":
                            run_finished = True
                            break
                    elif pipeline_task in done:
                        # Pipeline finished without a RUN_FINISHED event.
                        next_event_task.cancel()
                        try:
                            await next_event_task
                        except (asyncio.CancelledError, StopAsyncIteration):
                            pass
                        # Check if the pipeline raised an exception.
                        exc = pipeline_task.exception()
                        if exc is not None:
                            logger.error(
                                "Pipeline crashed before RUN_FINISHED: %s",
                                exc,
                                exc_info=exc,
                            )
                            yield f"data: {json.dumps({'type': 'RUN_ERROR', 'error': str(exc)}, default=str)}\n\n"
                        break

            except asyncio.CancelledError:
                pipeline_task.cancel()
                raise

            # ── Collect the pipeline result and yield RESULT event ──
            try:
                if not pipeline_task.done():
                    # Pipeline published RUN_FINISHED but hasn't returned yet
                    # (still doing audit logging). Give it 30s max.
                    result = await asyncio.wait_for(pipeline_task, timeout=30)
                elif pipeline_task.exception() is None:
                    result = pipeline_task.result()
                else:
                    # Pipeline raised — error event already yielded above.
                    return
            except Exception as exc:
                logger.error(
                    "Failed to collect pipeline result: %s",
                    exc,
                    exc_info=exc,
                )
                yield f"data: {json.dumps({'type': 'RUN_ERROR', 'error': f'Pipeline result error: {exc}'}, default=str)}\n\n"
                return

            try:
                payload = json.dumps(
                    {"type": "RESULT", "data": result}, default=str
                )
            except Exception as exc:
                logger.error(
                    "Failed to serialize pipeline result: %s",
                    exc,
                    exc_info=exc,
                )
                yield f"data: {json.dumps({'type': 'RUN_ERROR', 'error': f'Serialization error: {exc}'}, default=str)}\n\n"
                return

            yield f"data: {payload}\n\n"

        return request_id, event_stream()
