"""
Content generation.

Each deliverable is its own call (no fragile one-shot-split-by-delimiter):
  * article   — a ~1,500-word Markdown blog post (streamed, flagship model)
  * seo       — structured SEO metadata derived from the finished article
  * linkedin  — a short, punchy LinkedIn adaptation of the same topic
  * image     — one image-generation prompt for a header image

The article is saved with YAML frontmatter (title/description/slug/keywords/tags)
so it drops straight into a static-site / CMS pipeline.
"""

from __future__ import annotations

import logging

from .config import Config
from .llm import LLM
from .models import Cluster, GeneratedContent

log = logging.getLogger(__name__)

_SEO_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "slug": {"type": "string"},
        "meta_description": {"type": "string"},
        "primary_keyword": {"type": "string"},
        "keywords": {"type": "array", "items": {"type": "string"}},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "slug", "meta_description", "primary_keyword", "keywords", "tags"],
    "additionalProperties": False,
}


def _source_block(cluster: Cluster) -> str:
    lines = []
    for it in cluster.items[:6]:
        lines.append(f"- {it.title} ({it.domain or it.source}) {it.link}".rstrip())
    return "\n".join(lines)


def write_article(llm: LLM, cfg: Config, cluster: Cluster, angle: str, notes: str) -> str:
    head = cluster.headline
    research = f"\n\nVerified research notes to ground the piece:\n{notes}\n" if notes else ""
    prompt = f"""{cfg.brand_brief}

Write in {cfg.output_language}.

Write a polished, SEO-friendly blog article of about 1,500 words for the Omatekk
website, in Markdown.

Topic: {head.title}
Angle to take: {angle}

Source coverage (for grounding — do not just summarise these, analyse them):
{_source_block(cluster)}{research}

Requirements:
- Open with a single H1 headline (a strong, specific, search-friendly title).
- A compelling lede that states why this matters now.
- Clear H2/H3 subheads structuring the argument; short, readable paragraphs.
- Weave the topic into what it means for founders and investors in Oman and the
  wider GCC — this is the payoff, not an afterthought.
- Stay grounded in the sources and research; where you extend beyond them, frame
  it explicitly as Omatekk's analysis.
- End with a clear takeaway.
- Output ONLY the article Markdown. No preamble, no frontmatter — just the piece."""

    return llm.write(
        model=cfg.writer_model,
        prompt=prompt,
        max_tokens=8000,
        effort=cfg.writer_effort,
    )


def write_seo(llm: LLM, cfg: Config, article_markdown: str) -> dict:
    prompt = f"""Produce SEO metadata for the article below.

Article:
{article_markdown[:6000]}

Return:
- title: <= 60 characters, compelling and keyword-led
- slug: lowercase, hyphenated, no stop words
- meta_description: 140-160 characters, action-oriented
- primary_keyword: the single main search term
- keywords: 5-8 relevant search terms
- tags: 3-5 short topical tags"""

    return llm.structured(
        model=cfg.analysis_model,
        prompt=prompt,
        schema=_SEO_SCHEMA,
        max_tokens=600,
    )


def write_linkedin(llm: LLM, cfg: Config, cluster: Cluster, angle: str, notes: str) -> str:
    head = cluster.headline
    research = f"\n\nVerified facts:\n{notes}\n" if notes else ""
    prompt = f"""{cfg.brand_brief}

Write in {cfg.output_language}.

Write a LinkedIn post (150-250 words) on this topic, adapted for a professional
social feed — not a copy of the blog.

Topic: {head.title}
Angle: {angle}{research}

Requirements:
- A scroll-stopping first line (the hook).
- Short, punchy paragraphs with line breaks; conversational but credible.
- One concrete insight or takeaway for founders/investors in the GCC.
- End with 3-5 relevant hashtags.
- Output ONLY the post text."""

    return llm.write(
        model=cfg.writer_model,
        prompt=prompt,
        max_tokens=1500,
        effort="medium",
    )


def write_image_prompt(llm: LLM, cfg: Config, title: str, angle: str) -> str:
    prompt = f"""Write ONE detailed image-generation prompt for a strong, editorial
header image for this article. Describe subject, style, mood, composition and
colour in a single paragraph. Professional and modern; no text in the image; no
quotes around the output.

Article title: {title}
Angle: {angle}"""

    return llm.write(
        model=cfg.analysis_model,
        prompt=prompt,
        max_tokens=500,
    )


def generate(llm: LLM, cfg: Config, cluster: Cluster, angle: str, reason: str, notes: str) -> GeneratedContent:
    log.info("writing article…")
    article = write_article(llm, cfg, cluster, angle, notes)

    log.info("deriving SEO metadata…")
    seo = write_seo(llm, cfg, article)

    log.info("writing LinkedIn post…")
    linkedin = write_linkedin(llm, cfg, cluster, angle, notes)

    log.info("writing image prompt…")
    image_prompt = write_image_prompt(llm, cfg, seo.get("title", cluster.headline.title), angle)

    return GeneratedContent(
        topic=cluster.headline.title,
        angle=angle,
        reason=reason,
        article_markdown=article,
        seo=seo,
        linkedin=linkedin,
        image_prompt=image_prompt,
        sources=cluster.links[:8],
        research_notes=notes,
    )
