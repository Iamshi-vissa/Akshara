"""Anthropic (Claude) provider using the official SDK and JSON-schema structured output."""

from __future__ import annotations

import json
from typing import Any

import anthropic

from app.adapters.llm import LLMResult, LLMUnavailable


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str) -> None:
        self.model = model
        # Credentials come from the environment (ANTHROPIC_API_KEY or an `ant auth login` profile).
        self.client = anthropic.AsyncAnthropic()

    async def complete_json(
        self, *, system: str, prompt: str, schema: dict[str, Any], max_tokens: int = 4000
    ) -> LLMResult:
        try:
            response = await self.client.beta.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_config={"format": {"type": "json_schema", "schema": schema}},
                # On a policy refusal the API retries on a suitable fallback model in the same call.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.AuthenticationError as exc:
            raise LLMUnavailable("The language-model provider rejected the credentials.") from exc
        except anthropic.RateLimitError as exc:
            raise LLMUnavailable("The language-model provider is rate limiting requests; try again shortly.") from exc
        except anthropic.APIStatusError as exc:
            raise LLMUnavailable(f"The language-model provider returned an error ({exc.status_code}).") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMUnavailable("The language-model provider could not be reached.") from exc
        if response.stop_reason == "refusal":
            raise LLMUnavailable("The model declined this request.")
        if response.stop_reason == "max_tokens":
            raise LLMUnavailable("The response was too long; try a shorter selection.")
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMUnavailable("The model returned an unreadable response.") from exc
        return LLMResult(
            data=data,
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
