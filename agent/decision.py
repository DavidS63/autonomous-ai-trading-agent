"""Trade idea generation + risk-checked decision layer + optional LLM refinement."""

from __future__ import annotations

from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from rich.console import Console

from agent.llm_head import LLMDecisionHead

console = Console()


@dataclass
class TradeIdea:
    symbol: str
    side: str                 # "buy" or "sell"
    confidence: float
    entry: float
    stop: float
    target: float
    thesis: str
    qty: float = 0.0


class DecisionEngine:
    def __init__(self, config: Dict[str, Any]):
        self.risk_pct = config.get("agent", {}).get("risk_per_trade_pct", 1.0)
        self.max_positions = config.get("agent", {}).get("max_open_positions", 8)
        self.max_heat = config.get("agent", {}).get("max_portfolio_heat_pct", 6.0)
        self.min_conf = config.get("agent", {}).get("min_confidence", 0.62)
        self.stop_pct = config.get("agent", {}).get("default_stop_pct", 1.5)
        self.rr = config.get("agent", {}).get("take_profit_rr", 2.0)

        # Simple learned weights (self-improvement can update these)
        self.weights = {
            "trend_strength": 0.35,
            "momentum": 0.30,
            "volume_confirmation": 0.20,
            "mean_reversion_penalty": 0.15,
        }

        self.llm = LLMDecisionHead()

    def generate_ideas(self, research: Dict[str, Any]) -> List[TradeIdea]:
        ideas: List[TradeIdea] = []
        positions = {p["symbol"]: p for p in research.get("open_positions", [])}
        equity = research.get("account", {}).get("equity", 100000)

        for report in research.get("symbol_reports", []):
            if "error" in report:
                continue
            sym = report["symbol"]
            if sym in positions:
                continue

            idea = self._score_report(report, equity)
            if idea and idea.confidence >= self.min_conf * 0.85:  # slightly lower gate before LLM
                ideas.append(idea)

        # Rank by confidence
        ideas.sort(key=lambda x: x.confidence, reverse=True)
        ideas = ideas[: self.max_positions + 2]

        # Optional LLM refinement
        ideas = self.llm.refine_ideas(ideas, research)

        # Final confidence filter after LLM
        ideas = [i for i in ideas if i.confidence >= self.min_conf]
        return ideas[: self.max_positions]

    def _score_report(self, report: Dict[str, Any], equity: float) -> Optional[TradeIdea]:
        trend = report.get("trend", "neutral")
        mom = report.get("momentum", 0)
        vol_ratio = report.get("volume_ratio", 1.0)
        price = report.get("last_price", 0)
        atr = report.get("atr_proxy", price * 0.01)
        news_count = len(report.get("news") or [])

        if trend == "neutral" or price <= 0:
            return None

        if trend == "bullish" and mom > 0:
            side = "buy"
            stop = price - max(atr, price * (self.stop_pct / 100))
            target = price + (price - stop) * self.rr
            thesis = f"Bullish trend + positive momentum ({mom:.4f}). Volume ratio {vol_ratio:.1f}."
        elif trend == "bearish" and mom < 0:
            side = "sell"
            stop = price + max(atr, price * (self.stop_pct / 100))
            target = price - (stop - price) * self.rr
            thesis = f"Bearish trend + negative momentum ({mom:.4f}). Volume ratio {vol_ratio:.1f}."
        else:
            return None

        if news_count:
            thesis += f" {news_count} recent news items available."

        conf = 0.5
        conf += self.weights["trend_strength"] * (0.3 if abs(mom) > 0.005 else 0.1)
        conf += self.weights["momentum"] * min(abs(mom) * 20, 0.25)
        conf += self.weights["volume_confirmation"] * (0.15 if vol_ratio > 1.3 else 0.0)
        if news_count >= 2:
            conf += 0.05
        conf = max(0.0, min(1.0, conf))

        return TradeIdea(
            symbol=report["symbol"],
            side=side,
            confidence=round(conf, 3),
            entry=price,
            stop=round(stop, 4),
            target=round(target, 4),
            thesis=thesis,
        )

    def apply_risk_limits(
        self,
        ideas: List[TradeIdea],
        equity: float,
        current_positions: List[Dict],
        broker,
    ) -> List[TradeIdea]:
        approved = []
        for idea in ideas:
            if len(current_positions) + len(approved) >= self.max_positions:
                break

            qty = broker.calculate_position_size(
                equity=equity,
                entry_price=idea.entry,
                stop_price=idea.stop,
                risk_pct=self.risk_pct,
            )
            if qty < 1:
                continue

            idea.qty = qty
            approved.append(idea)
            console.print(
                f"[blue]Idea:[/] {idea.side.upper()} {idea.qty} {idea.symbol} "
                f"@ {idea.entry:.2f} | stop {idea.stop:.2f} | conf {idea.confidence:.2f}"
            )
            console.print(f"       [dim]{idea.thesis}[/]")

        return approved

    def update_weights(self, performance_stats: Dict[str, Any]):
        win_rate = performance_stats.get("win_rate", 0.5)
        if win_rate > 0.55:
            self.weights["trend_strength"] = min(0.45, self.weights["trend_strength"] + 0.02)
        elif win_rate < 0.45:
            self.weights["momentum"] = max(0.15, self.weights["momentum"] - 0.02)
        console.print(f"[magenta]Weights updated:[/] {self.weights}")
