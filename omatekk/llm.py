"""
LLM wrapper supporting two providers behind one interface:

  * "anthropic" — native Claude API. Writer calls stream (thinking is on by
    default on Opus 5 and counts against max_tokens) and use the `effort`
    control; structured calls use `output_config.format` with a JSON schema.
  * "openai" — any OpenAI-compatible endpoint (OpenAI, OpenRouter, avalai.ir…)
    via the `openai` SDK with a custom `base_url`. Writer calls use
    chat.completions; structured calls use JSON mode with the schema described
    in the prompt and a tolerant parser.

The rest of the pipeline only ever calls `write()` and `structured()` and never
needs to know which provider is active.
"""

from __future__ import annotations

import json
import logging
import re

log = logging.getLogger(__name__)


def _anthropic_text(message) -> str:
    """Concatenate the text blocks of an Anthropic message."""
    return "".join(
        getattr(block, "text", "")
        for block in message.content
        if getattr(block, "type", None) == "text"
    )


def _extract_json(text: str) -> dict:
    """Parse a JSON object from model output, tolerating fences/prose."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    match = re.search(r"\{.*\}", text, re.S)
    if match:
        return json.loads(match.group(0))
    raise ValueError("could not parse a JSON object from the model output")


class LLM:
    def __init__(self, cfg):
        self.cfg = cfg
        self.provider = cfg.llm_provider

        if self.provider == "anthropic":
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover
                raise SystemExit("Missing dependency. Run: pip install -r requirements.txt") from exc
            self.client = anthropic.Anthropic()

        elif self.provider == "openai":
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover
                raise SystemExit("Missing dependency. Run: pip install -r requirements.txt") from exc
            kwargs: dict = {}
            if cfg.openai_api_key:
                kwargs["api_key"] = cfg.openai_api_key
            if cfg.openai_base_url:
                kwargs["base_url"] = cfg.openai_base_url
            self.client = OpenAI(**kwargs)

        else:
            raise ValueError(f"Unknown LLM_PROVIDER: {self.provider!r} (use 'anthropic' or 'openai')")

    # ------------------------------------------------------------------ #
    # Public interface
    # ------------------------------------------------------------------ #
    def write(
        self,
        *,
        model: str,
        prompt: str,
        system: str | None = None,
        max_tokens: int = 8000,
        effort: str | None = None,
    ) -> str:
        if self.provider == "anthropic":
            return self._anthropic_write(model, prompt, system, max_tokens, effort)
        return self._openai_write(model, prompt, system, max_tokens)

    def structured(
        self,
        *,
        model: str,
        prompt: str,
        schema: dict,
        system: str | None = None,
        max_tokens: int = 2000,
    ) -> dict:
        if self.provider == "anthropic":
            return self._anthropic_structured(model, prompt, schema, system, max_tokens)
        return self._openai_structured(model, prompt, schema, system, max_tokens)

    # ------------------------------------------------------------------ #
    # Anthropic implementation
    # ------------------------------------------------------------------ #
    def _anthropic_write(self, model, prompt, system, max_tokens, effort) -> str:
        kwargs: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        if effort:
            kwargs["output_config"] = {"effort": effort}
        with self.client.messages.stream(**kwargs) as stream:
            message = stream.get_final_message()
        if message.stop_reason == "refusal":
            raise RuntimeError("Model refused the request (safety). Adjust the prompt/topic.")
        return _anthropic_text(message).strip()

    def _anthropic_structured(self, model, prompt, schema, system, max_tokens) -> dict:
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
        return json.loads(_anthropic_text(message))

    # ------------------------------------------------------------------ #
    # OpenAI-compatible implementation
    # ------------------------------------------------------------------ #
    def _openai_messages(self, prompt, system) -> list[dict]:
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _openai_write(self, model, prompt, system, max_tokens) -> str:
        resp = self.client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=self._openai_messages(prompt, system),
        )
        return (resp.choices[0].message.content or "").strip()

    def _openai_structured(self, model, prompt, schema, system, max_tokens) -> dict:
        json_prompt = (
            f"{prompt}\n\nReturn ONLY a single JSON object (no prose, no code fences) "
            f"that conforms to this JSON schema:\n{json.dumps(schema)}"
        )
        messages = self._openai_messages(json_prompt, system)
        try:
            resp = self.client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                messages=messages,
                response_format={"type": "json_object"},
            )
        except Exception as exc:  # some proxies reject response_format; retry plain
            log.debug("response_format rejected (%s); retrying without it", exc)
            resp = self.client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                messages=messages,
            )
        return _extract_json(resp.choices[0].message.content or "")
