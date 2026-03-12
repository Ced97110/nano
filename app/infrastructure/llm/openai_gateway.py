"""Infrastructure adapter — Lightweight OpenAI gateway via aiohttp.

Zero heavy imports at module level. tiktoken/pydantic are deferred to first use.
Uses aiohttp (already installed via redis/chromadb) instead of openai SDK or httpx.
"""

from __future__ import annotations

import json
import os
import re
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from pydantic import BaseModel

from app.domain.interfaces.llm_gateway import LLMGateway

logger = structlog.get_logger(__name__)

DEFAULT_BASE_URL = "https://api.openai.com/v1"

# Cost per 1M tokens (input, output) — updated Mar 2025
MODEL_COSTS: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.00, 30.00),
    "gpt-4": (30.00, 60.00),
    "gpt-3.5-turbo": (0.50, 1.50),
    "o1": (15.00, 60.00),
    "o1-mini": (3.00, 12.00),
    "o3-mini": (1.10, 4.40),
    "glm-4.7:cloud": (0.0, 0.0),  # Ollama/local — no cost
}


class OpenAIGateway(LLMGateway):
    """Lightweight OpenAI gateway — zero heavy imports at load time."""

    def __init__(
        self,
        default_model: str = "gpt-4o",
        default_max_tokens: int = 4096,
        fallback_models: list[str] | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self._default_model = default_model
        self._default_max_tokens = default_max_tokens
        self._fallback_models = fallback_models or []
        self._total_tokens_used = 0
        self._total_cost_usd = 0.0
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._base_url = (base_url or os.environ.get("OPENAI_BASE_URL", "")).rstrip("/") or DEFAULT_BASE_URL
        self._chat_url = f"{self._base_url}/chat/completions"
        self._session = None  # aiohttp.ClientSession, lazy
        self._encoder = None  # tiktoken encoder, lazy

    def _get_encoder(self):
        if self._encoder is None:
            import tiktoken
            try:
                self._encoder = tiktoken.encoding_for_model(self._default_model)
            except KeyError:
                self._encoder = tiktoken.get_encoding("cl100k_base")
        return self._encoder

    async def _get_session(self):
        if self._session is None or self._session.closed:
            import aiohttp
            timeout = aiohttp.ClientTimeout(total=120, connect=10)
            self._session = aiohttp.ClientSession(
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                timeout=timeout,
            )
        return self._session

    async def _call_api(
        self, model: str, messages: list[dict], max_tokens: int, temperature: float,
        json_mode: bool = False,
    ) -> dict:
        session = await self._get_session()
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        async with session.post(self._chat_url, json=payload) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"OpenAI API error {resp.status}: {body[:500]}")
            return await resp.json()

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

        api_messages = []
        if system:
            api_messages.append({"role": "system", "content": system})
        api_messages.extend(messages)

        input_tokens = self._count_tokens(api_messages)

        try:
            data = await self._call_api(target_model, api_messages, max_tokens, temperature, json_mode=json_mode)
        except Exception as exc:
            if self._fallback_models:
                for fallback in self._fallback_models:
                    try:
                        logger.warning("openai.fallback", primary=target_model, fallback=fallback, error=str(exc))
                        data = await self._call_api(fallback, api_messages, max_tokens, temperature, json_mode=json_mode)
                        target_model = fallback
                        break
                    except Exception:
                        continue
                else:
                    raise exc
            else:
                raise exc

        content = data["choices"][0]["message"]["content"] or ""
        usage = data.get("usage", {})

        prompt_tokens = usage.get("prompt_tokens", input_tokens)
        completion_tokens = usage.get("completion_tokens", self._count_text_tokens(content))
        total_tokens = prompt_tokens + completion_tokens

        cost = self._estimate_cost(target_model, prompt_tokens, completion_tokens)
        self._total_tokens_used += total_tokens
        self._total_cost_usd += cost

        return {
            "content": content,
            "tokens_used": total_tokens,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "model": target_model,
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
        result = await self.chat(messages, system, max_tokens, temperature, model)
        content = result.get("content", "")

        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", content.strip())
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)

        data = json.loads(cleaned)
        parsed = response_model.model_validate(data)
        return parsed, result

    def count_tokens(self, text: str) -> int:
        return self._count_text_tokens(text)

    @property
    def total_tokens_used(self) -> int:
        return self._total_tokens_used

    @property
    def total_cost_usd(self) -> float:
        return self._total_cost_usd

    def reset_counters(self) -> None:
        self._total_tokens_used = 0
        self._total_cost_usd = 0.0

    def _count_tokens(self, messages: list[dict]) -> int:
        total = 0
        for msg in messages:
            total += 4
            total += self._count_text_tokens(msg.get("content", ""))
            total += self._count_text_tokens(msg.get("role", ""))
        total += 2
        return total

    def _count_text_tokens(self, text: str) -> int:
        try:
            enc = self._get_encoder()
            return len(enc.encode(text))
        except Exception:
            return len(text) // 4

    def _estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        costs = MODEL_COSTS.get(model, (2.50, 10.00))
        input_cost = (input_tokens / 1_000_000) * costs[0]
        output_cost = (output_tokens / 1_000_000) * costs[1]
        return round(input_cost + output_cost, 6)
