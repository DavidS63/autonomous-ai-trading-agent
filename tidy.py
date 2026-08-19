#!/usr/bin/env python3
"""Entry point for the filetidy CLI: `python tidy.py sort ~/Downloads`."""

from __future__ import annotations

from filetidy.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
