"""Core data structures shared across the pipeline."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Item:
    """A single piece of content collected from a source."""

    title: str
    link: str = ""
    summary: str = ""
    source: str = ""            # logical source name, e.g. "google_news", "reddit"
    domain: str = ""            # publisher domain, e.g. "wamda.com"
    published: Optional[dt.datetime] = None  # timezone-aware UTC when known
    score: float = 0.0          # raw popularity signal from the source (upvotes, likes…)

    def age_hours(self, now: dt.datetime) -> float:
        if self.published is None:
            return float("nan")
        return max(0.0, (now - self.published).total_seconds() / 3600.0)


@dataclass
class Cluster:
    """A group of Items that all cover the same underlying topic."""

    items: list[Item] = field(default_factory=list)
    tokens: set[str] = field(default_factory=set)
    score: float = 0.0
    reasons: dict = field(default_factory=dict)  # score breakdown, for transparency

    @property
    def headline(self) -> Item:
        """The most representative item (most popular, then most recent)."""
        return max(
            self.items,
            key=lambda it: (it.score, it.published or dt.datetime.min.replace(tzinfo=dt.timezone.utc)),
        )

    @property
    def domains(self) -> set[str]:
        return {it.domain for it in self.items if it.domain}

    @property
    def sources(self) -> set[str]:
        return {it.source for it in self.items if it.source}

    @property
    def links(self) -> list[str]:
        return [it.link for it in self.items if it.link]


@dataclass
class GeneratedContent:
    """The final publish-ready outputs for one run."""

    topic: str
    angle: str
    reason: str
    article_markdown: str
    seo: dict
    linkedin: str
    image_prompt: str
    sources: list[str] = field(default_factory=list)
    research_notes: str = ""
