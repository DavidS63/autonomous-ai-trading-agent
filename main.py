#!/usr/bin/env python3
"""
Self-Improving Autonomous AI Trading Agent
Alpaca Paper Trading only.
"""

from __future__ import annotations

import argparse
import time
import yaml
from pathlib import Path
from datetime import datetime
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agent.broker import PaperBroker
from agent.research import ResearchEngine
from agent.decision import DecisionEngine
from agent.journal import TradeJournal
from agent.improvement import SelfImprovement

console = Console(force_terminal=False, emoji=False, legacy_windows=True)


def load_config() -> dict:
    cfg_path = Path("config/settings.yaml")
    with open(cfg_path) as f:
        return yaml.safe_load(f)


def print_account(account: dict, positions: list):
    table = Table(title="Paper Account Snapshot")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Equity", f"${account.get('equity', 0):,.2f}")
    table.add_row("Cash", f"${account.get('cash', 0):,.2f}")
    table.add_row("Buying Power", f"${account.get('buying_power', 0):,.2f}")
    table.add_row("Open Positions", str(len(positions)))
    console.print(table)

    if positions:
        pos_table = Table(title="Open Positions")
        pos_table.add_column("Symbol")
        pos_table.add_column("Qty")
        pos_table.add_column("Avg Entry")
        pos_table.add_column("Current")
        pos_table.add_column("Unrealized P/L")
        for p in positions:
            pl_style = "green" if p["unrealized_pl"] >= 0 else "red"
            pos_table.add_row(
                p["symbol"],
                f"{p['qty']:.2f}",
                f"{p['avg_entry_price']:.2f}",
                f"{p['current_price']:.2f}",
                f"[{pl_style}]{p['unrealized_pl']:+.2f} ({p['unrealized_plpc']*100:+.1f}%)[/]",
            )
        console.print(pos_table)


def run_cycle(broker, research, decision, journal, config, dry_run: bool = False):
    console.print(Panel.fit("[bold]Autonomous AI Trading Agent - Cycle Start[/]", style="blue"))

    research_data = research.run_full_scan()
    account = research_data["account"]
    positions = research_data["open_positions"]
    print_account(account, positions)

    console.print(f"\n[dim]Self-reflection:[/] {research_data['self_reflection']}\n")

    ideas = decision.generate_ideas(research_data)
    approved = decision.apply_risk_limits(
        ideas, account["equity"], positions, broker
    )

    for idea in approved:
        idea_dict = {
            "symbol": idea.symbol,
            "side": idea.side,
            "qty": idea.qty,
            "entry": idea.entry,
            "stop": idea.stop,
            "target": idea.target,
            "confidence": idea.confidence,
            "thesis": idea.thesis,
        }

        if idea.side.lower() == "sell" and not dry_run:
            console.print(
                f"\n[bold yellow]PERMISSION NEEDED[/] - short/sell idea:\n"
                f"  {idea.side.upper()} {idea.qty} {idea.symbol} @ ~{idea.entry:.2f}\n"
                f"  Stop {idea.stop:.2f} | Conf {idea.confidence:.2f}\n"
                f"  Thesis: {idea.thesis}"
            )
            try:
                answer = input("Allow this short/sell? Type YES to approve, anything else to skip: ").strip()
            except EOFError:
                answer = ""
            if answer.upper() != "YES":
                console.print(f"[dim]Skipped short {idea.symbol} (no permission).[/]")
                journal.log_decision(
                    {**idea_dict, "status": "skipped_no_permission"},
                    None,
                    research_data,
                )
                continue

        if dry_run:
            console.print(f"[yellow]DRY-RUN[/] would {idea.side.upper()} {idea.qty} {idea.symbol}")
            journal.log_decision(idea_dict, None, research_data)
        else:
            try:
                order = broker.submit_market_order(
                    symbol=idea.symbol,
                    qty=idea.qty,
                    side=idea.side,
                )
                journal.log_decision(idea_dict, order, research_data)
            except Exception as e:
                console.print(f"[red]Execution error:[/] {e}")
                journal.log_decision(idea_dict, {"error": str(e)}, research_data)

    if not approved:
        console.print("[yellow]No high-confidence edge found - sitting out (good discipline).[/]")

    console.print(Panel.fit("[bold green]Cycle complete[/]", style="green"))
    return research_data


def main():
    parser = argparse.ArgumentParser(description="Self-Improving Alpaca Paper Trading Agent")
    parser.add_argument("--loop", action="store_true", help="Run continuously")
    parser.add_argument("--review", action="store_true", help="Force end-of-day review")
    parser.add_argument("--dry-run", action="store_true", help="Research + decide but do not place orders")
    parser.add_argument("--interval", type=int, default=30, help="Minutes between cycles in loop mode")
    args = parser.parse_args()

    config = load_config()
    console.print(f"[bold]Loading agent:[/] {config['agent']['name']}")

    try:
        broker = PaperBroker()
        account = broker.get_account()
        console.print(f"[green]OK Connected to Alpaca Paper[/] - Equity ${account['equity']:,.2f}")
    except Exception as e:
        console.print(f"[red]Failed to connect:[/] {e}")
        console.print("Make sure .env contains valid paper keys from https://app.alpaca.markets")
        return

    research = ResearchEngine(broker, config)
    decision = DecisionEngine(config)
    journal = TradeJournal(config.get("logging", {}).get("journal_path", "data/trade_journal.jsonl"))
    improver = SelfImprovement(journal, decision)

    if args.review:
        positions = broker.get_positions()
        improver.end_of_day_review(account, positions)
        return

    if args.loop:
        console.print(f"[cyan]Entering continuous loop (every {args.interval} min). Ctrl+C to stop.[/]")
        while True:
            try:
                run_cycle(broker, research, decision, journal, config, dry_run=args.dry_run)
                now = datetime.now()
                if now.hour == 15 and now.minute >= 50:
                    positions = broker.get_positions()
                    improver.end_of_day_review(broker.get_account(), positions)
                time.sleep(args.interval * 60)
            except KeyboardInterrupt:
                console.print("\n[yellow]Stopped by user.[/]")
                break
            except Exception as e:
                console.print(f"[red]Cycle error:[/] {e}")
                time.sleep(60)
    else:
        run_cycle(broker, research, decision, journal, config, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
