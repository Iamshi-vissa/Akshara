"""Language-model provider abstraction (ARCHITECTURE.md §4, adapters.llm).

The application depends only on :class:`LLMProvider`. Swapping models or vendors means adding
an adapter, not rewriting features. There is deliberately no "fake" production provider: when
nothing is configured, AI features report themselves unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class LLMUnavailable(Exception):
    """No provider is configured, or the provider declined/failed; message is user-safe."""


@dataclass
class LLMResult:
    data: dict[str, Any]
    model: str
    input_tokens: int
    output_tokens: int


class LLMProvider(Protocol):
    name: str

    async def complete_json(
        self, *, system: str, prompt: str, schema: dict[str, Any], max_tokens: int = 4000
    ) -> LLMResult:
        """Return a JSON object that validates against ``schema``."""
        ...


def get_provider(provider: str, model: str) -> LLMProvider | None:
    if provider == "anthropic":
        from app.adapters.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider(model)
    return None
