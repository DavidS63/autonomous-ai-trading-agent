#!/usr/bin/env python3
"""
Companion Briefing Agent
Reads the trading agent's journal and performance files and prints a
plain-English summary a 12-year-old could understand.
"""

from __future__ import annotations

import json
from pathlib import Path
from collections import Counter
from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

JOURNAL = Path("data/trade_journal.jsonl")
PERF = Path("data/performance.json")


def load_journal(limit: int = 40) -> list:
    if not JOURNAL.exists():
        return []
    lines = JOURNAL.read_text().strip().splitlines()[-limit:]
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


def main():
    console.print(Panel.fit("[bold]Companion Briefing Agent[/]\nPlain-English summary of the trading robot", style="cyan"))

    entries = load_journal()
    if not entries:
        console.print("[yellow]No journal yet. Run the trading agent at least once first.[/]")
        return

    decisions = [e for e in entries if e.get("type") == "decision"]
    reviews = [e for e in entries if e.get("type") == "end_of_day_review"]

    console.print(f"\nI found [bold]{len(decisions)}[/] trade decisions and [bold]{len(reviews)}[/] reviews in the notebook.\n")

    sides = Counter()
    symbols = Counter()
    for d in decisions:
        idea = d.get("idea") or {}
        side = (idea.get("side") or "?").upper()
        sym = idea.get("symbol") or "?"
        sides[side] += 1
        symbols[sym] += 1

    table = Table(title="What the robot wanted to do")
    table.add_column("Action")
    table.add_column("Count")
    for side, count in sides.most_common():
        table.add_row(side, str(count))
    console.print(table)

    table2 = Table(title="Most mentioned symbols")
    table2.add_column("Symbol")
    table2.add_column("Times")
    for sym, count in symbols.most_common(8):
        table2.add_row(sym, str(count))
    console.print(table2)

    if reviews:
        latest = reviews[-1].get("summary") or {}
        console.print("\n[bold]Latest self-review lessons:[/]")
        for lesson in latest.get("lessons") or ["(none written yet)"]:
            console.print(f"  • {lesson}")
        console.print(f"\nOpen positions at last review: {latest.get('open_positions', '?')}")
        console.print(f"Ideas that day: {latest.get('ideas_generated_today', '?')}")
    else:
        console.print("\n[dim]No formal end-of-day review has been run yet. Try: python main.py --review[/]")

    console.print("\n[bold cyan]Companion advice:[/]")
    if not decisions:
        console.print("  The robot has not made any decisions yet. Run a dry-run first.")
    elif sides.get("BUY", 0) > sides.get("SELL", 0) * 2:
        console.print("  It has been mostly looking for buys. That can be fine in a rising market; watch risk.")
    elif sides.get("SELL", 0) > sides.get("BUY", 0) * 2:
        console.print("  It has been mostly looking for sells/shorts. Make sure you are comfortable with short ideas.")
    else:
        console.print("  Mix of buys and sells — balanced so far.")

    console.print("\n[green]Briefing complete.[/] Run this any time after the main agent finishes a cycle.")


if __name__ == "__main__":
    main()
