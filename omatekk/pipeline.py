"""
End-to-end orchestration: collect -> detect trends -> curate -> research ->
generate -> write files -> record history.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os

from .config import Config
from .curate import choose
from .generate import generate
from .llm import LLM
from .models import GeneratedContent
from .research import enrich
from .sources import collect
from .state import History
from .trends import top_trending

log = logging.getLogger(__name__)


class PipelineError(RuntimeError):
    pass


def _yaml_scalar(value) -> str:
    text = str(value)
    if text == "" or text.strip() != text or any(c in text for c in ':#"\'\n[]{}'):
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def _frontmatter(data: dict) -> str:
    lines = ["---"]
    for key, value in data.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            for entry in value:
                lines.append(f"  - {_yaml_scalar(entry)}")
        else:
            lines.append(f"{key}: {_yaml_scalar(value)}")
    lines.append("---")
    return "\n".join(lines)


def _write_outputs(cfg: Config, content: GeneratedContent) -> str:
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    folder = os.path.join(cfg.output_dir, stamp)
    os.makedirs(folder, exist_ok=True)

    seo = content.seo
    frontmatter = _frontmatter(
        {
            "title": seo.get("title", content.topic),
            "description": seo.get("meta_description", ""),
            "slug": seo.get("slug", ""),
            "date": dt.date.today().isoformat(),
            "primary_keyword": seo.get("primary_keyword", ""),
            "keywords": seo.get("keywords", []),
            "tags": seo.get("tags", []),
        }
    )
    article = f"{frontmatter}\n\n{content.article_markdown}\n"

    files = {
        "article.md": article,
        "linkedin.txt": content.linkedin + "\n",
        "image_prompt.txt": content.image_prompt + "\n",
        "seo.json": json.dumps(seo, indent=2, ensure_ascii=False),
        "meta.json": json.dumps(
            {
                "topic": content.topic,
                "angle": content.angle,
                "reason": content.reason,
                "sources": content.sources,
                "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            },
            indent=2,
            ensure_ascii=False,
        ),
    }
    if content.research_notes:
        files["research.md"] = content.research_notes + "\n"

    for name, body in files.items():
        with open(os.path.join(folder, name), "w", encoding="utf-8") as fh:
            fh.write(body)

    return folder


def run(cfg: Config | None = None, *, dry_run: bool = False) -> dict:
    """Run one full pipeline cycle. Returns a summary dict."""
    cfg = cfg or Config()
    log.info("config: %s", cfg.summary())
    llm = LLM()
    history = History(cfg.state_dir, cfg.history_days)

    # 1. collect
    items = collect(cfg)
    if not items:
        raise PipelineError("No items collected. Widen HOURS_BACK / queries, or check connectivity.")

    # 2. detect trends (cap the number of items clustered for cost/latency)
    clusters = top_trending(cfg, items[: cfg.max_headlines])
    clusters = history.filter_new(clusters)
    if not clusters:
        raise PipelineError("Every trending topic was already covered recently. Try again later.")
    clusters = clusters[: cfg.max_clusters]

    log.info("top topic: %s (score=%s)", clusters[0].headline.title, clusters[0].score)

    if dry_run:
        return {
            "dry_run": True,
            "items": len(items),
            "topics": [
                {"title": c.headline.title, "score": c.score, **c.reasons}
                for c in clusters
            ],
        }

    # 3. curate
    decision = choose(llm, cfg, clusters)
    chosen = clusters[decision["chosen_index"]]
    angle = decision.get("angle", "")
    reason = decision.get("reason", "")
    log.info("chosen: %s", chosen.headline.title)
    log.info("angle:  %s", angle)

    # 4. research (optional)
    notes = enrich(llm, cfg, chosen, angle)

    # 5. generate
    content = generate(llm, cfg, chosen, angle, reason, notes)

    # 6. write + 7. record
    folder = _write_outputs(cfg, content)
    history.record(chosen, content.topic)
    history.save()

    log.info("done -> %s", folder)
    return {
        "dry_run": False,
        "folder": folder,
        "topic": content.topic,
        "angle": angle,
        "reason": reason,
        "seo_title": content.seo.get("title", ""),
        "items": len(items),
        "sources": sorted(chosen.sources),
    }
