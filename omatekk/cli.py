"""
Command-line entry point.

Usage:
    python -m omatekk --once        # run the full pipeline once
    python -m omatekk --dry-run     # collect + rank topics, print them, generate nothing
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from .config import Config
from .pipeline import PipelineError, run


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="omatekk", description="Omatekk daily content pipeline")
    parser.add_argument("--once", action="store_true", help="run one full cycle (default)")
    parser.add_argument("--dry-run", action="store_true", help="rank topics and print them; generate nothing")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    args = parser.parse_args(argv)

    _configure_logging(args.verbose)

    if not os.environ.get("ANTHROPIC_API_KEY") and not args.dry_run:
        # The SDK can also resolve credentials from an `ant auth login` profile;
        # only warn rather than hard-fail, so profile-based auth still works.
        logging.getLogger(__name__).warning(
            "ANTHROPIC_API_KEY is not set; relying on an ambient credential/profile."
        )

    try:
        summary = run(Config(), dry_run=args.dry_run)
    except PipelineError as exc:
        print(f"Pipeline stopped: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - surface a clean message, log the trace
        logging.getLogger(__name__).exception("unexpected failure")
        print(f"Failed: {exc}", file=sys.stderr)
        return 2

    if summary.get("dry_run"):
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print("\nDone.")
        print(f"  topic:  {summary['topic']}")
        print(f"  angle:  {summary['angle']}")
        print(f"  output: {summary['folder']}")
        print("    article.md        -> website (has SEO frontmatter)")
        print("    linkedin.txt      -> LinkedIn")
        print("    image_prompt.txt  -> your image model")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
