"""Self-improvement cycle – review trades, extract lessons, update strategy."""

from __future__ import annotations

from typing import Dict, Any, List
from rich.console import Console
from agent.journal import TradeJournal

console = Console()


class SelfImprovement:
    def __init__(self, journal: TradeJournal, decision_engine):
        self.journal = journal
        self.decision = decision_engine

    def end_of_day_review(self, account: Dict, positions: List[Dict]) -> Dict[str, Any]:
        console.print("[bold magenta]▶ End-of-day self-improvement review[/]")

        recent = self.journal.load_recent_decisions(100)
        decisions = [r for r in recent if r.get("type") == "decision"]

        # Very simple stats (in production you would mark outcomes after 1–5 days)
        closed_or_open = len(positions)
        total_ideas = len(decisions)

        summary = {
            "account_equity": account.get("equity"),
            "open_positions": closed_or_open,
            "ideas_generated_today": total_ideas,
            "win_rate_estimate": 0.5,  # placeholder – wire real outcome tracking later
            "lessons": self._extract_lessons(decisions, positions),
            "next_actions": [
                "Continue monitoring open positions with updated stops if needed",
                "Re-run full research at next market open",
                "Review any high-confidence missed setups",
            ],
        }

        self.journal.log_review(summary)
        self.decision.update_weights(summary)

        console.print("[green]✓ Review complete and weights updated[/]")
        return summary

    def _extract_lessons(self, decisions: List[Dict], positions: List[Dict]) -> List[str]:
        lessons = []
        if not decisions:
            lessons.append("No trades taken – edge was insufficient or conditions unclear. Good discipline.")
        else:
            high_conf = [d for d in decisions if d.get("idea", {}).get("confidence", 0) > 0.75]
            if high_conf:
                lessons.append(f"{len(high_conf)} high-confidence ideas generated. Review their subsequent performance.")
            lessons.append("Persist all thesis + outcome pairs for future statistical weighting.")

        if positions:
            losers = [p for p in positions if p.get("unrealized_pl", 0) < 0]
            if losers:
                lessons.append(f"{len(losers)} positions currently underwater – check if original thesis still valid.")

        return lessons
