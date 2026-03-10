"""Port — event publisher interface.

Abstracts AG-UI event streaming. Domain publishes events without knowing
the transport (Redis pub/sub, WebSocket, Kafka, etc.).

Also supports Human-in-the-Loop (HITL) synchronization:
  - wait_for_input: blocks until human provides feedback (or timeout)
  - send_input: delivers human feedback to a waiting pipeline
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


class EventPublisher(ABC):
    @abstractmethod
    async def publish(self, channel_id: str, event: dict) -> None: ...

    @abstractmethod
    def subscribe(self, channel_id: str) -> AsyncIterator[dict]: ...

    async def wait_for_input(self, channel_id: str, timeout: float = 300) -> dict | None:
        """Block until human input arrives on HITL channel, or timeout.

        Returns the feedback dict, or None if timeout elapsed.
        """
        raise NotImplementedError("HITL not supported by this publisher")

    async def send_input(self, channel_id: str, data: dict) -> None:
        """Deliver human feedback to a waiting HITL channel."""
        raise NotImplementedError("HITL not supported by this publisher")
