"""
Run history, so the pipeline never covers the same topic two days running.

State is a small JSON file under STATE_DIR. Each covered topic records the
token fingerprint of what we wrote about plus its date; on the next run we skip
clusters that overlap too heavily with anything covered inside HISTORY_DAYS.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os

from .models import Cluster
from .trends import _jaccard, _tokens

log = logging.getLogger(__name__)

_OVERLAP_SKIP = 0.5  # a new cluster this similar to a recent one is a repeat


class History:
    def __init__(self, state_dir: str, history_days: int):
        self.path = os.path.join(state_dir, "history.json")
        self.history_days = history_days
        self.entries: list[dict] = []
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as fh:
                self.entries = json.load(fh).get("covered", [])
        except (ValueError, OSError) as exc:
            log.warning("could not read history (%s); starting fresh", exc)
            self.entries = []

    def _recent_fingerprints(self) -> list[set[str]]:
        cutoff = dt.date.today() - dt.timedelta(days=self.history_days)
        fps: list[set[str]] = []
        for entry in self.entries:
            try:
                covered = dt.date.fromisoformat(entry["date"])
            except (KeyError, ValueError):
                continue
            if covered >= cutoff:
                fps.append(set(entry.get("tokens", [])))
        return fps

    def is_recent(self, cluster: Cluster) -> bool:
        """True if this cluster substantially repeats something covered recently."""
        toks = set(cluster.tokens) or _tokens(cluster.headline.title)
        return any(_jaccard(toks, fp) >= _OVERLAP_SKIP for fp in self._recent_fingerprints())

    def filter_new(self, clusters: list[Cluster]) -> list[Cluster]:
        fresh = [c for c in clusters if not self.is_recent(c)]
        skipped = len(clusters) - len(fresh)
        if skipped:
            log.info("skipped %d cluster(s) already covered in the last %dd", skipped, self.history_days)
        return fresh

    def record(self, cluster: Cluster, topic: str) -> None:
        self.entries.append(
            {
                "date": dt.date.today().isoformat(),
                "topic": topic,
                "tokens": sorted(set(cluster.tokens) or _tokens(topic)),
                "links": cluster.links[:5],
            }
        )

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        # Prune anything older than the window so the file stays small.
        cutoff = dt.date.today() - dt.timedelta(days=self.history_days)
        kept = []
        for entry in self.entries:
            try:
                if dt.date.fromisoformat(entry["date"]) >= cutoff:
                    kept.append(entry)
            except (KeyError, ValueError):
                continue
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"covered": kept, "updated": dt.datetime.now(dt.timezone.utc).isoformat()}, fh, indent=2)
