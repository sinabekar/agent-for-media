"""
Central configuration, loaded from environment variables with sensible defaults.

Nothing secret lives in code. Copy config.example.env to .env (or export the
variables in your shell / CI) and edit to taste. Every value has a default so a
bare `python -m omatekk --once` works out of the box for the Omatekk use case.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _get(name: str, default: str) -> str:
    return os.environ.get(name, default).strip()


def _get_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip())
    except (TypeError, ValueError):
        return default


def _get_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "").strip())
    except (TypeError, ValueError):
        return default


def _get_list(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if raw is None:
        return list(default)
    items = [x.strip() for x in raw.split(",")]
    return [x for x in items if x]


DEFAULT_BRAND_BRIEF = """
Omatekk is an AI accelerator, consulting and investment firm based in Muscat,
Oman, operating across the GCC and European markets. Audience: founders,
operators, investors and enterprise leaders in the regional startup ecosystem.
Voice: sharp, informed, practical, never hypey. We connect the news to what it
means for builders and investors in Oman and the wider GCC.
""".strip()

DEFAULT_QUERIES = [
    "Oman startup",
    "Oman venture capital",
    "Oman economy technology",
    "GCC startup funding",
    "MENA venture capital",
    "Oman Vision 2040 investment",
]

DEFAULT_EXTRA_FEEDS = [
    "https://www.wamda.com/feed",
]

DEFAULT_REDDIT_SUBS = ["startups", "venturecapital", "artificial"]
DEFAULT_HN_QUERIES = ["startup funding", "venture capital", "AI"]


@dataclass
class Config:
    # --- Brand / language -------------------------------------------------
    brand_brief: str = field(default_factory=lambda: _get("BRAND_BRIEF", DEFAULT_BRAND_BRIEF))
    output_language: str = field(default_factory=lambda: _get("OUTPUT_LANGUAGE", "English"))

    # --- Collection -------------------------------------------------------
    queries: list[str] = field(default_factory=lambda: _get_list("GN_QUERIES", DEFAULT_QUERIES))
    extra_feeds: list[str] = field(default_factory=lambda: _get_list("EXTRA_FEEDS", DEFAULT_EXTRA_FEEDS))
    reddit_subreddits: list[str] = field(default_factory=lambda: _get_list("REDDIT_SUBREDDITS", DEFAULT_REDDIT_SUBS))
    hn_queries: list[str] = field(default_factory=lambda: _get_list("HN_QUERIES", DEFAULT_HN_QUERIES))
    linkedin_feeds: list[str] = field(default_factory=lambda: _get_list("LINKEDIN_FEEDS", []))

    gnews_hl: str = field(default_factory=lambda: _get("GNEWS_HL", "en-US"))
    gnews_gl: str = field(default_factory=lambda: _get("GNEWS_GL", "OM"))

    hours_back: int = field(default_factory=lambda: _get_int("HOURS_BACK", 48))
    max_headlines: int = field(default_factory=lambda: _get_int("MAX_HEADLINES", 60))
    max_clusters: int = field(default_factory=lambda: _get_int("MAX_CLUSTERS", 12))
    cluster_threshold: float = field(default_factory=lambda: _get_float("CLUSTER_THRESHOLD", 0.28))
    http_timeout: int = field(default_factory=lambda: _get_int("HTTP_TIMEOUT", 20))

    # --- Source toggles ---------------------------------------------------
    source_google_news: bool = field(default_factory=lambda: _get_bool("SOURCE_GOOGLE_NEWS", True))
    source_rss: bool = field(default_factory=lambda: _get_bool("SOURCE_RSS", True))
    source_reddit: bool = field(default_factory=lambda: _get_bool("SOURCE_REDDIT", True))
    source_hackernews: bool = field(default_factory=lambda: _get_bool("SOURCE_HACKERNEWS", True))
    source_twitter: bool = field(default_factory=lambda: _get_bool("SOURCE_TWITTER", True))
    source_linkedin: bool = field(default_factory=lambda: _get_bool("SOURCE_LINKEDIN", True))

    x_bearer_token: str = field(default_factory=lambda: _get("X_BEARER_TOKEN", ""))

    # --- Models -----------------------------------------------------------
    # The writer produces the actual deliverables; flagship quality matters here.
    writer_model: str = field(default_factory=lambda: _get("WRITER_MODEL", "claude-opus-5"))
    # The analysis model does cheap mechanical work (ranking, SEO metadata).
    analysis_model: str = field(default_factory=lambda: _get("ANALYSIS_MODEL", "claude-haiku-4-5"))
    writer_effort: str = field(default_factory=lambda: _get("WRITER_EFFORT", "high"))

    enable_research: bool = field(default_factory=lambda: _get_bool("ENABLE_RESEARCH", True))

    # --- Persistence ------------------------------------------------------
    output_dir: str = field(default_factory=lambda: _get("OUTPUT_DIR", "output"))
    state_dir: str = field(default_factory=lambda: _get("STATE_DIR", "state"))
    history_days: int = field(default_factory=lambda: _get_int("HISTORY_DAYS", 14))

    def summary(self) -> str:
        enabled = [
            name
            for name, on in [
                ("google_news", self.source_google_news),
                ("rss", self.source_rss),
                ("reddit", self.source_reddit),
                ("hackernews", self.source_hackernews),
                ("twitter", self.source_twitter and bool(self.x_bearer_token)),
                ("linkedin", self.source_linkedin and bool(self.linkedin_feeds)),
            ]
            if on
        ]
        return (
            f"sources={enabled} | writer={self.writer_model} (effort={self.writer_effort}) "
            f"| analysis={self.analysis_model} | research={self.enable_research} "
            f"| window={self.hours_back}h | lang={self.output_language}"
        )
