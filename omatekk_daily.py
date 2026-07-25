#!/usr/bin/env python3
"""
Omatekk daily content generator.

Run it by hand whenever you want a fresh piece — no agents, no orchestrator:

    python omatekk_daily.py

What one run does:
  1. Reads news via RSS (Google News queries + any feeds you add)
  2. Keeps only the last N hours and asks Claude to pick the single best story
  3. Asks Claude to write a 1000-1500 word article + a LinkedIn post + an image prompt
  4. Saves all three into a timestamped folder under ./output

You then publish everything manually, wherever you like.
"""

import os
import re
import sys
import datetime
from urllib.parse import quote_plus

try:
    import feedparser
    from anthropic import Anthropic
except ImportError:
    sys.exit("Missing deps. Run:  pip install feedparser anthropic")


# ============================================================
# CONFIG  —  edit freely
# ============================================================

# Each query becomes a Google News RSS search.
QUERIES = [
    "Oman startup",
    "Oman venture capital",
    "Oman economy technology",
    "GCC startup funding",
    "MENA venture capital",
    "Oman Vision 2040 investment",
]

# Optional: paste any direct RSS feed URLs you trust here.
EXTRA_FEEDS = [
    "https://www.wamda.com/feed",
]

HOURS_BACK      = 48          # ignore anything older than this
OUTPUT_LANGUAGE = "English"   # change to "Persian" for Farsi output
MAX_HEADLINES   = 40          # how many headlines Claude sees when picking

WRITE_MODEL  = "claude-sonnet-5"
CURATE_MODEL = "claude-haiku-4-5-20251001"

OUT_DIR = "output"

# Who Omatekk is — shapes tone and angle. Edit to taste.
BRAND_BRIEF = """
Omatekk is an AI accelerator, consulting and investment firm based in Muscat,
Oman, operating across the GCC and European markets. Audience: founders,
operators, investors and enterprise leaders in the regional startup ecosystem.
Voice: sharp, informed, practical, never hypey. We connect the news to what it
means for builders and investors in Oman and the wider GCC.
""".strip()

# ============================================================


def gnews_url(query: str) -> str:
    return f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=OM&ceid=OM:en"


def fetch_items():
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=HOURS_BACK)
    urls = [gnews_url(q) for q in QUERIES] + EXTRA_FEEDS
    seen, items = set(), []
    for url in urls:
        feed = feedparser.parse(url)
        for e in feed.entries:
            title = (e.get("title") or "").strip()
            if not title:
                continue
            key = re.sub(r"\s+", " ", title.lower())
            if key in seen:
                continue
            pub = e.get("published_parsed") or e.get("updated_parsed")
            if pub:
                dt = datetime.datetime(*pub[:6], tzinfo=datetime.timezone.utc)
                if dt < cutoff:
                    continue
            seen.add(key)
            summary = re.sub("<[^<]+?>", "", e.get("summary", ""))[:300].strip()
            items.append({"title": title, "link": e.get("link", ""), "summary": summary})
    return items


def curate(client, items):
    listing = "\n".join(f"[{i}] {it['title']} — {it['summary']}" for i, it in enumerate(items))
    prompt = f"""You are choosing one news story for Omatekk's content.

{BRAND_BRIEF}

Today's headlines:
{listing}

Pick the SINGLE best story to write about for this audience — most relevant,
timely and substantive. Reply with exactly:
INDEX: <number>
REASON: <short reason>"""
    msg = client.messages.create(
        model=CURATE_MODEL, max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    text = msg.content[0].text
    m = re.search(r"INDEX:\s*(\d+)", text)
    idx = int(m.group(1)) if m else 0
    idx = idx if 0 <= idx < len(items) else 0
    r = re.search(r"REASON:\s*(.+)", text)
    return idx, (r.group(1).strip() if r else "")


def write_content(client, item):
    prompt = f"""{BRAND_BRIEF}

Write in {OUTPUT_LANGUAGE}.

Source story:
Title: {item['title']}
Summary: {item['summary']}
Link: {item['link']}

Produce THREE things, separated EXACTLY by the delimiter lines below.
Output nothing before the first delimiter or after the last section.

===ARTICLE===
A polished 1000-1500 word article for the Omatekk website, in Markdown.
Strong H1 headline, a compelling lede, clear subheads, and a closing takeaway
tying the story to what it means for founders and investors in Oman and the GCC.
Stay grounded in the source; where you extend it, frame that as analysis.

===LINKEDIN===
A LinkedIn version: 150-250 words, a scroll-stopping first line, short punchy
paragraphs, and 3-5 relevant hashtags at the end.

===IMAGE===
One detailed image-generation prompt for an AI image model — a strong header
image for this article. Describe subject, style, mood, composition and color in
a single paragraph. No quotes."""
    msg = client.messages.create(
        model=WRITE_MODEL, max_tokens=8000,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def split_sections(text):
    article, linkedin, image = "", "", ""
    m = re.search(r"===ARTICLE===\s*(.*?)\s*===LINKEDIN===", text, re.S)
    if m: article = m.group(1).strip()
    m = re.search(r"===LINKEDIN===\s*(.*?)\s*===IMAGE===", text, re.S)
    if m: linkedin = m.group(1).strip()
    m = re.search(r"===IMAGE===\s*(.*)", text, re.S)
    if m: image = m.group(1).strip()
    return article, linkedin, image


def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Set your key first:  export ANTHROPIC_API_KEY=sk-ant-...")

    client = Anthropic()

    print("Fetching news…")
    items = fetch_items()
    if not items:
        sys.exit("No fresh stories found. Widen HOURS_BACK or QUERIES.")
    print(f"  {len(items)} stories found.")
    items = items[:MAX_HEADLINES]

    print("Picking the best story…")
    idx, reason = curate(client, items)
    chosen = items[idx]
    print(f"  Chosen: {chosen['title']}")
    print(f"  Why:    {reason}")

    print("Writing article + LinkedIn + image prompt…")
    raw = write_content(client, chosen)
    article, linkedin, image = split_sections(raw)

    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
    folder = os.path.join(OUT_DIR, stamp)
    os.makedirs(folder, exist_ok=True)

    for name, content in [
        ("article.md", article or raw),
        ("linkedin.txt", linkedin),
        ("image_prompt.txt", image),
        ("source.txt", f"{chosen['title']}\n{chosen['link']}\n\nwhy: {reason}\n"),
    ]:
        with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
            f.write(content)

    print(f"\nDone. Files saved in: {folder}")
    print("  article.md        -> website")
    print("  linkedin.txt      -> LinkedIn")
    print("  image_prompt.txt  -> paste into your image AI")


if __name__ == "__main__":
    main()

