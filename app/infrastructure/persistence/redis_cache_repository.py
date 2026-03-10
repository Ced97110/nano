"""Infrastructure adapter — Redis implementation of CacheRepository."""

import json

import redis.asyncio as aioredis
import structlog

from app.domain.interfaces.cache_repository import CacheRepository

logger = structlog.get_logger(__name__)


class RedisCacheRepository(CacheRepository):
    def __init__(self, redis: aioredis.Redis) -> None:
        self._redis = redis

    async def get_pipeline(self, system_id: str, entity: str) -> dict | None:
        key = f"pipeline:{system_id}:{entity}"
        raw = await self._redis.get(key)
        return json.loads(raw) if raw else None

    async def set_pipeline(self, system_id: str, entity: str, data: dict, ttl: int) -> None:
        key = f"pipeline:{system_id}:{entity}"
        await self._redis.set(key, json.dumps(data, default=str), ex=ttl)

    async def get_agent(self, agent_id: str, input_hash: str) -> dict | None:
        key = f"agent:{agent_id}:{input_hash}"
        raw = await self._redis.get(key)
        return json.loads(raw) if raw else None

    async def set_agent(self, agent_id: str, input_hash: str, data: dict, ttl: int) -> None:
        key = f"agent:{agent_id}:{input_hash}"
        await self._redis.set(key, json.dumps(data, default=str), ex=ttl)
