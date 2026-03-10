"""Infrastructure adapter — Redis pub/sub implementation of EventPublisher.

Uses pub/sub for AG-UI event streaming and Redis lists (BLPOP/RPUSH)
for Human-in-the-Loop synchronization.
"""

import json
from collections.abc import AsyncIterator

import redis.asyncio as aioredis
import structlog

from app.domain.interfaces.event_publisher import EventPublisher

logger = structlog.get_logger(__name__)


class RedisEventPublisher(EventPublisher):
    def __init__(self, redis: aioredis.Redis) -> None:
        self._redis = redis

    async def publish(self, channel_id: str, event: dict) -> None:
        channel = f"analysis:{channel_id}"
        await self._redis.publish(channel, json.dumps(event, default=str))

    async def subscribe(self, channel_id: str) -> AsyncIterator[dict]:
        pubsub = self._redis.pubsub()
        channel = f"analysis:{channel_id}"
        await pubsub.subscribe(channel)
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    yield json.loads(message["data"])
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    async def wait_for_input(self, channel_id: str, timeout: float = 300) -> dict | None:
        """Block until human feedback arrives via RPUSH, or timeout.

        Uses Redis BLPOP — reliable, no race conditions.
        """
        key = f"hitl:{channel_id}"
        try:
            result = await self._redis.blpop(key, timeout=int(timeout))
            if result:
                _, data = result
                return json.loads(data)
        except Exception as exc:
            logger.warning("hitl.wait_for_input.error", channel=channel_id, error=str(exc))
        return None

    async def send_input(self, channel_id: str, data: dict) -> None:
        """Deliver human feedback to a waiting BLPOP."""
        key = f"hitl:{channel_id}"
        await self._redis.rpush(key, json.dumps(data, default=str))
        await self._redis.expire(key, 600)  # cleanup after 10min
