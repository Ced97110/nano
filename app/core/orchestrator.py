"""Orchestrator — routes requests to the correct persona system.

Receives infrastructure dependencies via constructor (DI).
No global state, no module-level singletons.
"""

import importlib
import structlog

from app.domain.interfaces import AuditStore, CacheRepository, EventPublisher, LLMGateway
from app.domain.interfaces.web_search import WebSearchGateway

logger = structlog.get_logger(__name__)

PERSONA_SYSTEM_MAP: dict[str, str] = {
    "finagent": "app.persona_systems.finagent.system.FinAgentPro",
}


class Orchestrator:
    def __init__(
        self,
        llm: LLMGateway,
        cache: CacheRepository,
        events: EventPublisher,
        data_repos: dict | None = None,
        audit_store: AuditStore | None = None,
        web_search: WebSearchGateway | None = None,
    ) -> None:
        self._llm = llm
        self._cache = cache
        self._events = events
        self._data = data_repos or {}
        self._audit_store = audit_store
        self._web_search = web_search
        self._instances: dict = {}

    def get_system(self, system_id: str):
        if system_id not in PERSONA_SYSTEM_MAP:
            raise ValueError(f"Unknown persona system: {system_id}")

        if system_id not in self._instances:
            dotted = PERSONA_SYSTEM_MAP[system_id]
            module_path, class_name = dotted.rsplit(".", 1)
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            self._instances[system_id] = cls(
                llm=self._llm,
                cache=self._cache,
                events=self._events,
                data_repos=self._data,
                audit_store=self._audit_store,
                web_search=self._web_search,
            )
            logger.info("orchestrator.loaded", system=system_id)

        return self._instances[system_id]
