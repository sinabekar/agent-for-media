"""
Source adapters + collection.

Each adapter is a small function that returns a list[Item]. Adapters are
independent and fail soft: if one source is down or rate-limited, the run
continues with whatever the others returned.

Implemented (no credentials required):
  * google_news  — Google News RSS search per query
  * rss          — any direct RSS/Atom feeds you trust
  * reddit       — public subreddit "hot" JSON
  * hackernews   — Hacker News via the Algolia search API

Credentialed / pluggable:
  * twitter (X)  — official X API v2 recent search; active only when
                   X_BEARER_TOKEN is set.
  * linkedin     — LinkedIn has no public read API and scraping it breaks their
                   ToS, so this adapter reads LinkedIn *RSS bridges* you supply
                   (e.g. an rss.app feed for a company page) via LINKEDIN_FEEDS.
                   With no feeds configured it is a documented no-op.

To add a new source, write a function `foo(cfg) -> list[Item]` and register it
in `collect()`.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import time
from urllib.parse import quote_plus, urlparse

import requests

try:
    import feedparser
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Missing dependency. Run: pip install -r requirements.txt") from exc

from .config import Config
from .models import Item

log = logging.getLogger(__name__)

USER_AGENT = "OmatekkContentBot/1.0 (+https://omatekk.com)"
_HTML_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


# --------------------------------------------------------------------------- #
# HTTP + parsing helpers
# --------------------------------------------------------------------------- #
def _http_get(url: str, *, timeout: int, headers: dict | None = None, params: dict | None = None):
    """GET with a couple of retries and a friendly User-Agent."""
    hdrs = {"User-Agent": USER_AGENT}
    if headers:
        hdrs.update(headers)
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=hdrs, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            last_exc = exc
            time.sleep(2 ** attempt)
    log.warning("GET failed after retries: %s (%s)", url, last_exc)
    return None


def _clean(text: str, limit: int = 300) -> str:
    return _WS.sub(" ", _HTML_TAG.sub("", text or "")).strip()[:limit]


def _domain(link: str) -> str:
    try:
        return urlparse(link).netloc.lower().removeprefix("www.")
    except ValueError:
        return ""


def _parse_feed_time(entry) -> dt.datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return dt.datetime(*parsed[:6], tzinfo=dt.timezone.utc)


# --------------------------------------------------------------------------- #
# Adapters
# --------------------------------------------------------------------------- #
def google_news(cfg: Config) -> list[Item]:
    items: list[Item] = []
    for query in cfg.queries:
        url = (
            "https://news.google.com/rss/search?q="
            f"{quote_plus(query)}&hl={cfg.gnews_hl}&gl={cfg.gnews_gl}&ceid={cfg.gnews_gl}:en"
        )
        feed = feedparser.parse(url)
        for entry in feed.entries:
            link = entry.get("link", "")
            items.append(
                Item(
                    title=(entry.get("title") or "").strip(),
                    link=link,
                    summary=_clean(entry.get("summary", "")),
                    source="google_news",
                    domain=_domain(entry.get("source", {}).get("href", "")) or _domain(link),
                    published=_parse_feed_time(entry),
                )
            )
    return items


def rss(cfg: Config) -> list[Item]:
    return _read_feeds(cfg.extra_feeds, source="rss")


def linkedin(cfg: Config) -> list[Item]:
    if not cfg.linkedin_feeds:
        log.info("linkedin: no LINKEDIN_FEEDS configured — skipping (see README).")
        return []
    return _read_feeds(cfg.linkedin_feeds, source="linkedin")


def _read_feeds(urls: list[str], *, source: str) -> list[Item]:
    items: list[Item] = []
    for url in urls:
        feed = feedparser.parse(url)
        for entry in feed.entries:
            link = entry.get("link", "")
            items.append(
                Item(
                    title=(entry.get("title") or "").strip(),
                    link=link,
                    summary=_clean(entry.get("summary", "")),
                    source=source,
                    domain=_domain(link),
                    published=_parse_feed_time(entry),
                )
            )
    return items


def reddit(cfg: Config) -> list[Item]:
    items: list[Item] = []
    for sub in cfg.reddit_subreddits:
        resp = _http_get(
            f"https://www.reddit.com/r/{sub}/hot.json",
            timeout=cfg.http_timeout,
            params={"limit": 25},
        )
        if resp is None:
            continue
        try:
            children = resp.json()["data"]["children"]
        except (ValueError, KeyError):
            log.warning("reddit: unexpected response for r/%s", sub)
            continue
        for child in children:
            d = child.get("data", {})
            if d.get("stickied"):
                continue
            external = d.get("url_overridden_by_dest") or d.get("url", "")
            published = None
            if d.get("created_utc"):
                published = dt.datetime.fromtimestamp(d["created_utc"], tz=dt.timezone.utc)
            items.append(
                Item(
                    title=(d.get("title") or "").strip(),
                    link=f"https://www.reddit.com{d.get('permalink', '')}",
                    summary=_clean(d.get("selftext", "")),
                    source="reddit",
                    domain=_domain(external) or "reddit.com",
                    published=published,
                    score=float(d.get("ups", 0)),
                )
            )
    return items


def hackernews(cfg: Config) -> list[Item]:
    items: list[Item] = []
    for query in cfg.hn_queries:
        resp = _http_get(
            "https://hn.algolia.com/api/v1/search_by_date",
            timeout=cfg.http_timeout,
            params={"query": query, "tags": "story", "hitsPerPage": 20},
        )
        if resp is None:
            continue
        try:
            hits = resp.json().get("hits", [])
        except ValueError:
            continue
        for hit in hits:
            title = (hit.get("title") or hit.get("story_title") or "").strip()
            if not title:
                continue
            link = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
            published = None
            if hit.get("created_at"):
                try:
                    published = dt.datetime.fromisoformat(
                        hit["created_at"].replace("Z", "+00:00")
                    )
                except ValueError:
                    published = None
            items.append(
                Item(
                    title=title,
                    link=link,
                    summary="",
                    source="hackernews",
                    domain=_domain(link),
                    published=published,
                    score=float(hit.get("points") or 0),
                )
            )
    return items


def twitter(cfg: Config) -> list[Item]:
    """X / Twitter recent search via the official API v2. Needs a bearer token."""
    if not cfg.x_bearer_token:
        log.info("twitter: X_BEARER_TOKEN not set — skipping (see README).")
        return []
    items: list[Item] = []
    for query in cfg.queries:
        full_query = f"{query} -is:retweet lang:en"
        resp = _http_get(
            "https://api.twitter.com/2/tweets/search/recent",
            timeout=cfg.http_timeout,
            headers={"Authorization": f"Bearer {cfg.x_bearer_token}"},
            params={
                "query": full_query,
                "max_results": 10,
                "tweet.fields": "created_at,public_metrics",
            },
        )
        if resp is None:
            continue
        try:
            data = resp.json().get("data", [])
        except ValueError:
            continue
        for tweet in data:
            metrics = tweet.get("public_metrics", {})
            score = metrics.get("like_count", 0) + 2 * metrics.get("retweet_count", 0)
            published = None
            if tweet.get("created_at"):
                try:
                    published = dt.datetime.fromisoformat(
                        tweet["created_at"].replace("Z", "+00:00")
                    )
                except ValueError:
                    published = None
            text = _clean(tweet.get("text", ""), limit=200)
            items.append(
                Item(
                    title=text[:120],
                    link=f"https://twitter.com/i/web/status/{tweet.get('id')}",
                    summary=text,
                    source="twitter",
                    domain="twitter.com",
                    published=published,
                    score=float(score),
                )
            )
    return items


# --------------------------------------------------------------------------- #
# Collection + dedup
# --------------------------------------------------------------------------- #
_ADAPTERS: list[tuple[str, str, callable]] = [
    ("source_google_news", "google_news", google_news),
    ("source_rss", "rss", rss),
    ("source_reddit", "reddit", reddit),
    ("source_hackernews", "hackernews", hackernews),
    ("source_twitter", "twitter", twitter),
    ("source_linkedin", "linkedin", linkedin),
]


def _norm_title(title: str) -> str:
    return _WS.sub(" ", re.sub(r"[^\w\s]", "", title.lower())).strip()


def collect(cfg: Config) -> list[Item]:
    """Run every enabled adapter, then de-duplicate and filter by recency."""
    now = dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(hours=cfg.hours_back)

    raw: list[Item] = []
    for flag, name, adapter in _ADAPTERS:
        if not getattr(cfg, flag):
            continue
        try:
            got = adapter(cfg)
            log.info("source %-12s -> %d items", name, len(got))
            raw.extend(got)
        except Exception as exc:  # never let one source kill the run
            log.warning("source %s failed: %s", name, exc)

    seen_titles: set[str] = set()
    seen_links: set[str] = set()
    kept: list[Item] = []
    for item in raw:
        if not item.title:
            continue
        if item.published is not None and item.published < cutoff:
            continue
        key = _norm_title(item.title)
        if not key or key in seen_titles:
            continue
        if item.link and item.link in seen_links:
            continue
        seen_titles.add(key)
        if item.link:
            seen_links.add(item.link)
        kept.append(item)

    log.info("collected %d unique items within %dh", len(kept), cfg.hours_back)
    return kept
