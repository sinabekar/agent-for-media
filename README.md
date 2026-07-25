# Omatekk — Automated AI Content Pipeline

A daily pipeline that finds what's **trending** across many sources, picks the
single best topic for the brand, and produces **publish-ready** content:

- a **~1,500-word SEO blog article** (Markdown, with SEO frontmatter), and
- a **LinkedIn post** adapted for a professional feed,

plus an image-generation prompt for a header image. It runs itself every 24
hours and never repeats a topic it already covered.

---

## How it works

```
        ┌───────────────────────────────────────────────────────────────┐
        │  1. COLLECT   many independent sources, in parallel, fail-soft │
        │     google_news · rss · reddit · hackernews · x/twitter*       │
        └───────────────────────────────┬───────────────────────────────┘
                                         ▼
        ┌───────────────────────────────────────────────────────────────┐
        │  2. DETECT TRENDS   cluster items by topic; score by           │
        │     cross-source diversity + recency + popularity              │
        └───────────────────────────────┬───────────────────────────────┘
                                         ▼
        ┌───────────────────────────────────────────────────────────────┐
        │  3. DE-DUPE   drop anything covered in the last HISTORY_DAYS    │
        └───────────────────────────────┬───────────────────────────────┘
                                         ▼
        ┌───────────────────────────────────────────────────────────────┐
        │  4. CURATE    Claude picks the best topic + a sharp angle       │
        │               (structured output — validated, not regex)       │
        └───────────────────────────────┬───────────────────────────────┘
                                         ▼
        ┌───────────────────────────────────────────────────────────────┐
        │  5. RESEARCH  (optional) Claude web-searches for current facts  │
        └───────────────────────────────┬───────────────────────────────┘
                                         ▼
        ┌───────────────────────────────────────────────────────────────┐
        │  6. GENERATE  blog article · SEO metadata · LinkedIn · image    │
        │               (each is its own call — no fragile splitting)     │
        └───────────────────────────────┬───────────────────────────────┘
                                         ▼
        ┌───────────────────────────────────────────────────────────────┐
        │  7. SAVE + RECORD   timestamped folder; remember the topic      │
        └───────────────────────────────────────────────────────────────┘
```

Why clustering matters: *trending* isn't "a recent headline" — it's the same
story surfacing across **multiple independent sources** at once. Step 2 computes
that signal explicitly, and every topic carries a score breakdown you can
inspect (`--dry-run`).

---

## Quick start

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...

# See what's trending right now without spending on generation:
python -m omatekk --dry-run

# Produce a full set of content:
python -m omatekk --once
```

Output lands in `output/<timestamp>/`:

| File | Use |
|------|-----|
| `article.md` | Website blog post — Markdown **with SEO frontmatter** (title, meta description, slug, keywords, tags) |
| `linkedin.txt` | LinkedIn post |
| `image_prompt.txt` | Paste into your image model |
| `seo.json` | SEO metadata as JSON |
| `meta.json` | Topic, angle, chosen sources, timestamp |
| `research.md` | The grounded research notes (if research was enabled) |

The original `python omatekk_daily.py` still works — it's now a thin shim over
the package.

---

## Configuration

Everything is configured through environment variables (see
[`config.example.env`](config.example.env) for the full list). Copy it to `.env`
and export it, or set the variables in your shell / CI. Sensible defaults target
the Omatekk / GCC startup beat, so a bare run works with just an API key.

Highlights:

- `WRITER_MODEL` (default `claude-opus-5`) — the model that writes the
  deliverables. Switch to `claude-sonnet-5` to cut cost.
- `ANALYSIS_MODEL` (default `claude-haiku-4-5`) — cheap ranking / SEO work.
- `ENABLE_RESEARCH` (default `true`) — web-search grounding before writing.
- `SOURCE_*` toggles, `GN_QUERIES`, `EXTRA_FEEDS`, `REDDIT_SUBREDDITS`,
  `HN_QUERIES` — tune what gets collected.
- `HISTORY_DAYS` (default `14`) — how long before a topic can recur.

---

## Running every 24 hours

A GitHub Actions workflow is included: [`.github/workflows/daily-content.yml`](.github/workflows/daily-content.yml).
It runs daily at 06:00 UTC (and on demand), commits the new content back to the
repo, and also uploads it as a build artifact.

Set up:
1. Add `ANTHROPIC_API_KEY` (and optionally `X_BEARER_TOKEN`) under
   **Settings → Secrets and variables → Actions**.
2. That's it — the schedule is already defined. Trigger a test run from the
   **Actions** tab (**Run workflow**).

Prefer to run it on your own box instead? Any scheduler works:

```cron
# crontab -e  — 06:00 daily
0 6 * * * cd /path/to/agent-for-media && /path/to/venv/bin/python -m omatekk --once >> pipeline.log 2>&1
```

---

## Sources & the LinkedIn / X reality

The collection layer is a set of pluggable adapters. Some need no credentials;
the social platforms are more constrained than they look:

| Source | Status | Notes |
|--------|--------|-------|
| Google News | ✅ built-in | RSS search per query |
| Direct RSS/Atom | ✅ built-in | Any feeds you trust (`EXTRA_FEEDS`) |
| Reddit | ✅ built-in | Public subreddit JSON |
| Hacker News | ✅ built-in | Algolia search API |
| **X / Twitter** | 🔑 credentialed | Official **API v2** recent search. Activates only when `X_BEARER_TOKEN` is set. There is no legitimate free scrape. |
| **LinkedIn** | ⚠️ bridge only | LinkedIn has **no public read API**, and scraping it violates their Terms of Service. This adapter reads **LinkedIn RSS bridges you supply** (`LINKEDIN_FEEDS`, e.g. an rss.app feed for a company page). With no feeds configured it's a documented no-op. |

**Adding a source** is a few lines: write a function `my_source(cfg) -> list[Item]`
in `omatekk/sources.py` and register it in the `_ADAPTERS` list. It automatically
gets de-duplication, recency filtering, clustering, and scoring for free.

---

## Package layout

```
omatekk/
  config.py     # env-driven configuration
  models.py     # Item / Cluster / GeneratedContent
  llm.py        # Anthropic client wrapper (streaming + structured output)
  sources.py    # source adapters + collect()/dedup
  trends.py     # clustering + trend scoring
  state.py      # cross-day topic de-duplication
  curate.py     # topic selection (structured)
  research.py   # optional web_search grounding
  generate.py   # blog + SEO + LinkedIn + image
  pipeline.py   # orchestration + output writing
  cli.py        # command-line entry point
```

---

## Design notes / what changed from the original script

- **Multi-source, fail-soft collection** replaces the single Google-News feed.
- **Real trend detection** (cross-source clustering + scoring) replaces picking
  one headline from a flat list.
- **Separate, structured generation calls** replace the single delimiter-split
  call, so a model drift can't silently corrupt all three outputs.
- **SEO frontmatter** (title, meta description, slug, keywords, tags) makes the
  article genuinely publish-ready.
- **Cross-day de-duplication** stops the pipeline repeating itself.
- **Automation** via GitHub Actions (or cron) for the 24-hour cadence.
- **Retries, logging, fail-soft sources, env-based config** for reliability.
