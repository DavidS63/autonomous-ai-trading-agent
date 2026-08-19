#!/usr/bin/env python3
"""
Daily email summary for the trading agent.
Sends a plain-English briefing to your inbox.

Setup (Gmail example):
  1. Turn on 2-Step Verification on your Google account
  2. Create an App Password: https://myaccount.google.com/apppasswords
  3. Put these in .env:
       EMAIL_TO=you@gmail.com
       EMAIL_FROM=you@gmail.com
       SMTP_HOST=smtp.gmail.com
       SMTP_PORT=587
       SMTP_USER=you@gmail.com
       SMTP_PASS=your_16_char_app_password
"""

from __future__ import annotations

import json
import os
import smtplib
from collections import Counter
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console

load_dotenv()
console = Console()

JOURNAL = Path("data/trade_journal.jsonl")
PERF = Path("data/performance.json")


def build_body() -> str:
    lines = []
    lines.append(f"Trading Agent Daily Briefing \u2014 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("=" * 50)
    lines.append("")

    if not JOURNAL.exists():
        lines.append("No journal yet. Run the agent at least once.")
        return "\n".join(lines)

    entries = []
    for line in JOURNAL.read_text().strip().splitlines()[-50:]:
        try:
            entries.append(json.loads(line))
        except Exception:
            pass

    decisions = [e for e in entries if e.get("type") == "decision"]
    reviews = [e for e in entries if e.get("type") == "end_of_day_review"]

    lines.append(f"Recent decisions logged: {len(decisions)}")
    lines.append(f"Reviews logged: {len(reviews)}")
    lines.append("")

    sides = Counter()
    symbols = Counter()
    skipped = 0
    for d in decisions:
        idea = d.get("idea") or {}
        if idea.get("status") == "skipped_no_permission":
            skipped += 1
        side = (idea.get("side") or "?").upper()
        sym = idea.get("symbol") or "?"
        sides[side] += 1
        symbols[sym] += 1

    lines.append("Actions:")
    for side, count in sides.most_common():
        lines.append(f"  {side}: {count}")
    if skipped:
        lines.append(f"  Skipped (no short permission): {skipped}")
    lines.append("")

    lines.append("Top symbols:")
    for sym, count in symbols.most_common(8):
        lines.append(f"  {sym}: {count}")
    lines.append("")

    if reviews:
        latest = reviews[-1].get("summary") or {}
        lines.append("Latest self-review lessons:")
        for lesson in latest.get("lessons") or ["(none)"]:
            lines.append(f"  \u2022 {lesson}")
        lines.append("")
        lines.append(f"Open positions at last review: {latest.get('open_positions', '?')}")
    else:
        lines.append("No formal review yet. Run: python main.py --review")

    lines.append("")
    lines.append("This is paper trading only. Never real money.")
    lines.append("\u2014 Your Autonomous AI Trading Agent")
    return "\n".join(lines)


def send_email(body: str) -> bool:
    to_addr = os.getenv("EMAIL_TO")
    from_addr = os.getenv("EMAIL_FROM") or to_addr
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASS")

    if not all([to_addr, from_addr, user, password]):
        console.print(
            "[yellow]Email not configured.[/]\n"
            "Add EMAIL_TO, EMAIL_FROM, SMTP_USER, SMTP_PASS to .env\n"
            "(Gmail: use an App Password, not your normal password.)"
        )
        console.print("\n[bold]Preview of what would be sent:[/]\n")
        console.print(body)
        return False

    msg = MIMEMultipart()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = f"Trading Agent Briefing \u2014 {datetime.now().strftime('%Y-%m-%d')}"
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(host, port, timeout=30) as server:
        server.starttls()
        server.login(user, password)
        server.send_message(msg)

    console.print(f"[green]\u2713 Email sent to {to_addr}[/]")
    return True


def main():
    body = build_body()
    send_email(body)


if __name__ == "__main__":
    main()
