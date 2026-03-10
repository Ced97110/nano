"""Port — cache repository interface.

Abstracts pipeline-level and agent-level caching.
Domain never knows if it's Redis, Memcached, or in-memory.
"""

from abc import ABC, abstractmethod


class CacheRepository(ABC):
    @abstractmethod
    async def get_pipeline(self, system_id: str, entity: str) -> dict | None: ...

    @abstractmethod
    async def set_pipeline(self, system_id: str, entity: str, data: dict, ttl: int) -> None: ...

    @abstractmethod
    async def get_agent(self, agent_id: str, input_hash: str) -> dict | None: ...

    @abstractmethod
    async def set_agent(self, agent_id: str, input_hash: str, data: dict, ttl: int) -> None: ...
