#!/usr/bin/env python3
"""
Backward-compatible entry point.

The original single-file script has been refactored into the `omatekk` package.
This shim keeps `python omatekk_daily.py` working; it simply runs the pipeline
once. See README.md for the full CLI (`python -m omatekk --help`).
"""

import sys

from omatekk.cli import main

if __name__ == "__main__":
    # Default to a single full run when invoked with no arguments.
    sys.exit(main(sys.argv[1:] or ["--once"]))
