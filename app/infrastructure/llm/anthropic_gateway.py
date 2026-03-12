"""Infrastructure adapter — Anthropic Claude implementation of LLMGateway."""

from __future__ import annotations

import asyncio
import json
import re
from typing import TYPE_CHECKING, Any

import anthropic
import structlog

if TYPE_CHECKING:
    from pydantic import BaseModel

from app.domain.interfaces.llm_gateway import LLMGateway

logger = structlog.get_logger(__name__)

# Cost per 1M tokens (input, output) — updated Mar 2025
MODEL_COSTS: dict[str, tuple[float, float]] = {
    "claude-opus-4-6": (15.00, 75.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5-20251001": (0.80, 4.00),
}

# Max concurrent API calls to avoid 429 rate limits.
# Anthropic free/low-tier accounts typically allow 5 concurrent connections.
DEFAULT_MAX_CONCURRENT = 5


class AnthropicGateway(LLMGateway):
    def __init__(
        self,
        api_key: str,
        default_model: str = "claude-haiku-4-5-20251001",
        default_max_tokens: int = 4096,
        max_concurrent: int = DEFAULT_MAX_CONCURRENT,
    ) -> None:
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key,
            max_retries=3,  # SDK auto-retries 429/5xx with backoff
        )
        self._default_model = default_model
        self._default_max_tokens = default_max_tokens
        self._total_tokens_used = 0
        self._total_cost_usd = 0.0
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def chat(
        self,
        messages: list[dict],
        system: str = "",
        max_tokens: int = 2048,
        temperature: float = 0.3,
        model: str | None = None,
        json_mode: bool = False,
    ) -> dict:
        target_model = model or self._default_model

        # Build system prompt — append JSON instruction if json_mode
        effective_system = system or ""
        if json_mode and effective_system:
            effective_system += "\n\nIMPORTANT: Respond with valid JSON only. No markdown fences, no prose."
        elif json_mode:
            effective_system = "Respond with valid JSON only. No markdown fences, no prose."

        kwargs: dict = {
            "model": target_model,
            "max_tokens": max_tokens or self._default_max_tokens,
            "temperature": temperature,
            "messages": messages,
        }
        if effective_system:
            kwargs["system"] = effective_system

        async with self._semaphore:
            resp = await self._client.messages.create(**kwargs)

        content = resp.content[0].text if resp.content else ""
        prompt_tokens = resp.usage.input_tokens or 0
        completion_tokens = resp.usage.output_tokens or 0
        total_tokens = prompt_tokens + completion_tokens

        cost = self._estimate_cost(target_model, prompt_tokens, completion_tokens)
        self._total_tokens_used += total_tokens
        self._total_cost_usd += cost

        return {
            "content": content,
            "tokens_used": total_tokens,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "model": resp.model,
            "cost_usd": cost,
        }

    async def chat_structured(
        self,
        messages: list[dict],
        response_model: type,
        system: str = "",
        max_tokens: int = 2048,
        temperature: float = 0.3,
        model: str | None = None,
        max_retries: int = 2,
    ) -> tuple[Any, dict]:
        """Structured output — calls chat() then parses with Pydantic."""
        result = await self.chat(
            messages, system, max_tokens, temperature, model, json_mode=True,
        )
        content = result.get("content", "")

        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", content.strip())
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)

        data = json.loads(cleaned)
        parsed = response_model.model_validate(data)
        return parsed, result

    def count_tokens(self, text: str) -> int:
        return len(text) // 4

    @property
    def total_tokens_used(self) -> int:
        return self._total_tokens_used

    @property
    def total_cost_usd(self) -> float:
        return self._total_cost_usd

    def reset_counters(self) -> None:
        self._total_tokens_used = 0
        self._total_cost_usd = 0.0

    def _estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        costs = MODEL_COSTS.get(model, (0.80, 4.00))
        input_cost = (input_tokens / 1_000_000) * costs[0]
        output_cost = (output_tokens / 1_000_000) * costs[1]
        return round(input_cost + output_cost, 6)
