"""
Thin wrapper around the Anthropic SDK.

Encapsulates the model-specific request shape so the rest of the pipeline never
has to think about it:

  * Opus/Sonnet-tier writer calls stream (thinking is on by default on Opus 5 and
    counts against max_tokens, so streaming avoids HTTP timeouts) and use the
    `effort` control instead of temperature/top_p (which 400 on Opus 5).
  * Structured calls use `output_config.format` with a JSON schema and are parsed
    into a dict — no brittle delimiter parsing.
"""

from __future__ import annotations

import json
import logging

try:
    import anthropic
except ImportError as exc:  # pragma: no cover - dependency guard
    raise SystemExit("Missing dependency. Run: pip install -r requirements.txt") from exc

log = logging.getLogger(__name__)


def _text(message) -> str:
    """Concatenate the text blocks of a message, skipping thinking/tool blocks."""
    return "".join(
        getattr(block, "text", "")
        for block in message.content
        if getattr(block, "type", None) == "text"
    )


class LLM:
    def __init__(self, client=None):
        self.client = client or anthropic.Anthropic()

    def write(
        self,
        *,
        model: str,
        prompt: str,
        system: str | None = None,
        max_tokens: int = 8000,
        effort: str | None = None,
    ) -> str:
        """Stream a long-form text completion and return the final text."""
        kwargs: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        if effort:
            # `effort` is unsupported on Haiku; callers only pass it for Opus/Sonnet.
            kwargs["output_config"] = {"effort": effort}

        with self.client.messages.stream(**kwargs) as stream:
            message = stream.get_final_message()

        if message.stop_reason == "refusal":
            raise RuntimeError("Model refused the request (safety). Adjust the prompt/topic.")
        return _text(message).strip()

    def structured(
        self,
        *,
        model: str,
        prompt: str,
        schema: dict,
        system: str | None = None,
        max_tokens: int = 2000,
    ) -> dict:
        """Return a dict guaranteed to match `schema` via structured outputs."""
        kwargs: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
            "output_config": {"format": {"type": "json_schema", "schema": schema}},
        }
        if system:
            kwargs["system"] = system

        message = self.client.messages.create(**kwargs)
        if message.stop_reason == "refusal":
            raise RuntimeError("Model refused the structured request.")
        return json.loads(_text(message))
