"""
Omatekk automated content pipeline.

A daily pipeline that:
  1. Collects fresh items from many sources (news, Reddit, Hacker News, X, …)
  2. Clusters them into topics and scores which are genuinely *trending*
  3. Picks the single best topic for the brand (with Claude)
  4. Optionally enriches it with live web research
  5. Writes a ~1,500-word SEO blog article + a LinkedIn post + an image prompt
  6. Persists what it covered so it never repeats itself day to day

See README.md for architecture and setup.
"""

__version__ = "1.0.0"
