"""Infrastructure adapter — Anthropic Claude implementation of LLMGateway."""

import anthropic
import structlog

from app.domain.interfaces.llm_gateway import LLMGateway

logger = structlog.get_logger(__name__)


class AnthropicGateway(LLMGateway):
    def __init__(self, api_key: str, default_model: str, default_max_tokens: int) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._default_model = default_model
        self._default_max_tokens = default_max_tokens

    async def chat(
        self,
        messages: list[dict],
        system: str = "",
        max_tokens: int = 2048,
        temperature: float = 0.3,
    ) -> dict:
        kwargs: dict = {
            "model": self._default_model,
            "max_tokens": max_tokens or self._default_max_tokens,
            "temperature": temperature,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system

        resp = await self._client.messages.create(**kwargs)

        content = resp.content[0].text if resp.content else ""
        tokens_used = (resp.usage.input_tokens or 0) + (resp.usage.output_tokens or 0)

        return {
            "content": content,
            "tokens_used": tokens_used,
            "model": resp.model,
        }
