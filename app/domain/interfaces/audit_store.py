"""Port — audit store interface.

Abstracts immutable audit trail persistence. Domain logs events without
knowing the storage backend (PostgreSQL, BigQuery, S3, etc.).

Every agent action is logged with timestamp, agent ID, action type,
input params, output summary, and data sources. Minimum 7-year retention.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class AuditEvent:
    workflow_id: str
    event_type: str  # agent_started, agent_completed, agent_error, hitl_pause, hitl_feedback, run_started, run_finished
    agent_id: str | None = None
    payload: dict = field(default_factory=dict)  # input params summary, output summary, data sources, cost, etc.
    created_at: datetime | None = None


class AuditStore(ABC):
    @abstractmethod
    async def log_event(self, event: AuditEvent) -> None:
        """Append an immutable audit event. Never updates or deletes."""
        ...

    @abstractmethod
    async def get_trail(self, workflow_id: str) -> list[AuditEvent]:
        """Retrieve the full ordered audit trail for a workflow."""
        ...

    @abstractmethod
    async def generate_compliance_report(self, workflow_id: str) -> dict:
        """Assemble a compliance report summarizing all events for a workflow.

        Returns a dict with: agents executed, HITL decisions, overrides applied,
        data sources, total cost, total tokens, timeline, etc.
        """
        ...
