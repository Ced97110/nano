"""Port — LLM gateway interface.

Domain defines WHAT it needs. Infrastructure decides HOW (LiteLLM, Anthropic, OpenAI, etc.).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, TypeVar

T = TypeVar("T")


class LLMGateway(ABC):
    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        system: str = "",
        max_tokens: int = 2048,
        temperature: float = 0.3,
        model: str | None = None,
    ) -> dict:
        """Send messages to an LLM.

        Returns: {"content": str, "tokens_used": int, "prompt_tokens": int,
                  "completion_tokens": int, "model": str, "cost_usd": float}
        """
        ...

    async def chat_structured(
        self,
        messages: list[dict],
        response_model: type[T],
        system: str = "",
        max_tokens: int = 2048,
        temperature: float = 0.3,
        model: str | None = None,
        max_retries: int = 2,
    ) -> tuple[T, dict]:
        """Send messages and return a validated Pydantic model.

        Returns: (parsed_model, metadata_dict)
        Default implementation falls back to chat() + manual parsing.
        """
        result = await self.chat(messages, system, max_tokens, temperature, model)
        import json, re
        content = result.get("content", "")
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", content.strip())
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)
        data = json.loads(cleaned)
        parsed = response_model.model_validate(data)
        return parsed, result

    def count_tokens(self, text: str) -> int:
        """Count tokens in text. Default implementation for backwards compat."""
        return len(text) // 4
