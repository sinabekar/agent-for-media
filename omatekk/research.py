"""
Optional research enrichment.

Before writing, let Claude use the web_search server tool to gather current,
grounded context on the chosen topic — recent figures, named parties, timeline.
The notes it returns are fed into the writer so the article is accurate and
fresh rather than model-memory guesswork.

Disabled with ENABLE_RESEARCH=false (saves cost / avoids the tool).
"""

from __future__ import annotations

import logging

from .config import Config
from .llm import LLM, _text
from .models import Cluster

log = logging.getLogger(__name__)

# Dynamic-filtering web search (Opus 5 / Sonnet 5 / Opus 4.6+). Anthropic runs
# the search server-side; we just handle the pause_turn resume loop.
_WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 5}
_MAX_TURNS = 6


def enrich(llm: LLM, cfg: Config, cluster: Cluster, angle: str) -> str:
    if not cfg.enable_research:
        return ""

    head = cluster.headline
    prompt = f"""Research this news topic so an analyst can write about it accurately.

Topic: {head.title}
Context: {head.summary}
Planned angle: {angle}

Use web search to verify and gather the current facts: who is involved, key
figures and amounts, dates, and the latest developments as of today. Then write
a tight briefing (max ~250 words) of only the verified, load-bearing facts —
bullet points, each with the essential detail. Do not write the article; just
the facts and their sources."""

    messages = [{"role": "user", "content": prompt}]
    message = None
    try:
        for _ in range(_MAX_TURNS):
            message = llm.client.messages.create(
                model=cfg.writer_model,
                max_tokens=4000,
                tools=[_WEB_SEARCH_TOOL],
                output_config={"effort": "low"},
                messages=messages,
            )
            if message.stop_reason == "pause_turn":
                # Server tool hit its per-turn limit; resend to resume.
                messages.append({"role": "assistant", "content": message.content})
                continue
            break
    except Exception as exc:  # research is best-effort; never fail the run over it
        log.warning("research step failed (%s); continuing without notes", exc)
        return ""

    notes = _text(message).strip() if message else ""
    log.info("research produced %d chars of notes", len(notes))
    return notes
