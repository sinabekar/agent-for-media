"""
Trend detection.

"Trending" is not "a recent headline" — it is *the same topic surfacing across
multiple independent sources within a short window*. This module turns a flat
list of items into scored topic clusters so that signal is explicit and
inspectable (every cluster carries a `reasons` breakdown).

Approach (deliberately lightweight, no ML dependency):
  1. Reduce each title to a bag of meaningful tokens.
  2. Greedily group items whose token sets overlap (Jaccard >= threshold).
  3. Score each cluster by cross-source diversity + recency + popularity.
"""

from __future__ import annotations

import datetime as dt
import math
import re

from .config import Config
from .models import Cluster, Item

# Small English stopword list — enough to keep clustering focused on nouns.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for", "with",
    "at", "by", "from", "as", "is", "are", "was", "were", "be", "been", "being",
    "this", "that", "these", "those", "it", "its", "into", "over", "after",
    "new", "says", "will", "amid", "how", "why", "what", "who", "when", "up",
    "out", "get", "gets", "more", "than", "has", "have", "had", "not", "no",
    "you", "your", "we", "our", "they", "their", "he", "she", "his", "her",
}

# Higher = more editorially trustworthy / on-brand signal.
_SOURCE_WEIGHTS = {
    "google_news": 1.0,
    "rss": 1.1,
    "linkedin": 1.0,
    "twitter": 0.8,
    "reddit": 0.6,
    "hackernews": 0.7,
}

_RECENCY_HALFLIFE_HOURS = 18.0
_DIVERSITY_WEIGHT = 1.5      # bonus per extra distinct domain
_POPULARITY_WEIGHT = 0.4     # weight on log(popularity)
_WORD = re.compile(r"[a-z0-9]+")


def _tokens(title: str) -> set[str]:
    return {
        tok
        for tok in _WORD.findall(title.lower())
        if len(tok) > 2 and tok not in _STOPWORDS
    }


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def build_clusters(items: list[Item], threshold: float) -> list[Cluster]:
    """Greedy single-pass clustering by title-token overlap."""
    clusters: list[Cluster] = []
    for item in items:
        toks = _tokens(item.title)
        if not toks:
            continue
        best: Cluster | None = None
        best_sim = threshold
        for cluster in clusters:
            sim = _jaccard(toks, cluster.tokens)
            if sim >= best_sim:
                best, best_sim = cluster, sim
        if best is None:
            clusters.append(Cluster(items=[item], tokens=set(toks)))
        else:
            best.items.append(item)
            best.tokens |= toks
    return clusters


def _recency_factor(item: Item, now: dt.datetime) -> float:
    age = item.age_hours(now)
    if math.isnan(age):
        age = 24.0  # unknown timestamp: treat as middle-aged
    return 0.5 ** (age / _RECENCY_HALFLIFE_HOURS)


def score_clusters(clusters: list[Cluster], now: dt.datetime | None = None) -> list[Cluster]:
    """Assign each cluster a score and return them sorted, highest first."""
    now = now or dt.datetime.now(dt.timezone.utc)
    for cluster in clusters:
        base = sum(
            _SOURCE_WEIGHTS.get(it.source, 0.5) * _recency_factor(it, now)
            for it in cluster.items
        )
        diversity = (len(cluster.domains) - 1) * _DIVERSITY_WEIGHT
        top_pop = max((it.score for it in cluster.items), default=0.0)
        popularity = math.log1p(top_pop) * _POPULARITY_WEIGHT
        cluster.score = round(base + diversity + popularity, 3)
        cluster.reasons = {
            "items": len(cluster.items),
            "distinct_domains": len(cluster.domains),
            "distinct_sources": len(cluster.sources),
            "base_recency_weighted": round(base, 3),
            "diversity_bonus": round(diversity, 3),
            "popularity_bonus": round(popularity, 3),
        }
    return sorted(clusters, key=lambda c: c.score, reverse=True)


def top_trending(cfg: Config, items: list[Item]) -> list[Cluster]:
    """Full trend pass: cluster -> score -> take the strongest N."""
    clusters = build_clusters(items, cfg.cluster_threshold)
    ranked = score_clusters(clusters)
    return ranked[: cfg.max_clusters]
