"""
Curation: given the top trending clusters, let Claude pick the single best
topic for the brand and propose an angle. Uses structured output so the result
is a validated dict, not free text we have to regex.
"""

from __future__ import annotations

import logging

from .config import Config
from .llm import LLM
from .models import Cluster

log = logging.getLogger(__name__)

_SCHEMA = {
    "type": "object",
    "properties": {
        "chosen_index": {"type": "integer"},
        "reason": {"type": "string"},
        "angle": {"type": "string"},
        "ranked_indices": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["chosen_index", "reason", "angle", "ranked_indices"],
    "additionalProperties": False,
}


def _listing(clusters: list[Cluster]) -> str:
    lines = []
    for idx, cluster in enumerate(clusters):
        head = cluster.headline
        srcs = ", ".join(sorted(cluster.sources))
        lines.append(
            f"[{idx}] {head.title}\n"
            f"     trend_score={cluster.score} | {cluster.reasons['distinct_domains']} domains "
            f"across {cluster.reasons['distinct_sources']} sources ({srcs})\n"
            f"     {head.summary[:200]}"
        )
    return "\n".join(lines)


def choose(llm: LLM, cfg: Config, clusters: list[Cluster]) -> dict:
    """Return {chosen_index, reason, angle, ranked_indices}, clamped to valid range."""
    prompt = f"""You are the editor selecting one topic for Omatekk's content today.

{cfg.brand_brief}

Below are today's trending topic clusters, each already scored by how widely it
is surfacing across independent sources. Higher trend_score means more genuinely
"in the air" right now.

{_listing(clusters)}

Choose the SINGLE best topic to publish about for this audience — balance how
timely and trending it is against how relevant and substantive it is for
founders and investors in Oman and the GCC. Then propose a sharp, specific angle
Omatekk should take (not a generic summary — a point of view).

Return the chosen cluster index, a one-sentence reason, the angle, and your full
ranking of the indices best-first."""

    result = llm.structured(
        model=cfg.analysis_model,
        prompt=prompt,
        schema=_SCHEMA,
        max_tokens=800,
    )

    idx = result.get("chosen_index", 0)
    if not isinstance(idx, int) or not 0 <= idx < len(clusters):
        log.warning("curator returned out-of-range index %r; defaulting to 0", idx)
        result["chosen_index"] = 0
    return result
