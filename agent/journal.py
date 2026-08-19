"""Trade journal + performance tracking for self-improvement."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

from rich.console import Console

console = Console()


class TradeJournal:
    def __init__(self, path: str = "data/trade_journal.jsonl"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.perf_path = Path("data/performance.json")

    def log_decision(
        self,
        idea: Dict[str, Any],
        order_result: Optional[Dict[str, Any]] = None,
        research_snapshot: Optional[Dict] = None,
    ):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "decision",
            "idea": idea,
            "order": order_result,
            "research_context": {
                "self_reflection": research_snapshot.get("self_reflection") if research_snapshot else None,
            },
        }
        with open(self.path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")

    def log_review(self, summary: Dict[str, Any]):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "end_of_day_review",
            "summary": summary,
        }
        with open(self.path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")

        # Also update rolling performance file
        self._update_performance(summary)

    def _update_performance(self, summary: Dict[str, Any]):
        data = {}
        if self.perf_path.exists():
            try:
                data = json.loads(self.perf_path.read_text())
            except Exception:
                pass

        data["last_review"] = summary
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.perf_path.write_text(json.dumps(data, indent=2, default=str))

    def load_recent_decisions(self, limit: int = 50) -> List[Dict]:
        if not self.path.exists():
            return []
        lines = self.path.read_text().strip().splitlines()[-limit:]
        return [json.loads(l) for l in lines if l.strip()]
