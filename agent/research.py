"""Market intelligence gathering – bars, technicals, Finnhub news, self-reflection."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional

import requests
from rich.console import Console
from agent.broker import PaperBroker

console = Console()


class ResearchEngine:
    def __init__(self, broker: PaperBroker, config: Dict[str, Any]):
        self.broker = broker
        self.config = config
        self.symbols = config.get("universe", {}).get("symbols", ["SPY", "QQQ"])
        self.log_path = Path(config.get("logging", {}).get("research_log", "logs/research.jsonl"))
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.finnhub_key = os.getenv("FINNHUB_API_KEY")

    def run_full_scan(self) -> Dict[str, Any]:
        """Core daily / continuous research cycle."""
        console.print("[bold cyan]▶ Running full market intelligence scan...[/]")

        account = self.broker.get_account()
        positions = self.broker.get_positions()
        quotes = self.broker.get_latest_quotes(self.symbols)

        symbol_reports = []
        for sym in self.symbols:
            try:
                bars = self.broker.get_bars(
                    sym, limit=self.config.get("research", {}).get("lookback_bars", 50)
                )
                report = self._analyze_symbol(sym, bars, quotes.get(sym))
                # Attach recent company news from Finnhub when available
                report["news"] = self._fetch_company_news(sym)
                symbol_reports.append(report)
            except Exception as e:
                console.print(f"[yellow]Research skip {sym}:[/] {e}")

        research = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "account": account,
            "open_positions": positions,
            "quotes": quotes,
            "symbol_reports": symbol_reports,
            "self_reflection": self._self_reflection_prompt(positions, symbol_reports),
            "notes": (
                "Technical + Finnhub news scan. "
                "LLM decision head (if configured) further refines theses and confidence."
            ),
        }

        self._log(research)
        console.print(f"[green]✓ Scan complete[/] – {len(symbol_reports)} symbols analyzed")
        return research

    def _analyze_symbol(
        self, symbol: str, bars: List[Dict], last_price: Optional[float]
    ) -> Dict[str, Any]:
        if not bars or len(bars) < 10:
            return {"symbol": symbol, "error": "insufficient bars"}

        closes = [b["c"] for b in bars]
        volumes = [b["v"] for b in bars]
        latest = closes[-1]
        prev = closes[-2] if len(closes) > 1 else latest

        sma_fast = sum(closes[-10:]) / 10
        sma_slow = sum(closes[-30:]) / min(30, len(closes)) if len(closes) >= 20 else sma_fast
        atr_proxy = (max(closes[-14:]) - min(closes[-14:])) if len(closes) >= 14 else abs(latest - prev)
        vol_avg = sum(volumes[-10:]) / 10 if volumes else 0
        vol_ratio = volumes[-1] / vol_avg if vol_avg else 1.0

        momentum = (latest - sma_slow) / sma_slow if sma_slow else 0
        trend = (
            "bullish"
            if sma_fast > sma_slow and momentum > 0.002
            else "bearish"
            if sma_fast < sma_slow and momentum < -0.002
            else "neutral"
        )

        return {
            "symbol": symbol,
            "last_price": latest,
            "change_pct": ((latest - prev) / prev * 100) if prev else 0,
            "sma_fast": round(sma_fast, 4),
            "sma_slow": round(sma_slow, 4),
            "momentum": round(momentum, 5),
            "atr_proxy": round(atr_proxy, 4),
            "volume_ratio": round(vol_ratio, 2),
            "trend": trend,
            "bars_count": len(bars),
        }

    def _fetch_company_news(self, symbol: str, days: int = 5) -> List[Dict[str, Any]]:
        """Pull recent company news from Finnhub (free tier)."""
        if not self.finnhub_key:
            return []

        try:
            to_date = datetime.now(timezone.utc).date()
            from_date = to_date - timedelta(days=days)
            url = "https://finnhub.io/api/v1/company-news"
            params = {
                "symbol": symbol,
                "from": from_date.isoformat(),
                "to": to_date.isoformat(),
                "token": self.finnhub_key,
            }
            r = requests.get(url, params=params, timeout=8)
            r.raise_for_status()
            articles = r.json()[:8]  # keep it light
            return [
                {
                    "headline": a.get("headline"),
                    "summary": (a.get("summary") or "")[:280],
                    "source": a.get("source"),
                    "datetime": a.get("datetime"),
                    "url": a.get("url"),
                }
                for a in articles
            ]
        except Exception as e:
            console.print(f"[dim]Finnhub news skip {symbol}: {e}[/]")
            return []

    def _self_reflection_prompt(self, positions: List[Dict], reports: List[Dict]) -> str:
        open_syms = [p["symbol"] for p in positions]
        interesting = [
            r
            for r in reports
            if r.get("trend") in ("bullish", "bearish") and abs(r.get("momentum", 0)) > 0.003
        ]
        news_hits = sum(1 for r in reports if r.get("news"))
        return (
            f"What new information has emerged that materially changes the probability distribution "
            f"of price movement for my current open positions ({open_syms or 'none'}) "
            f"or for high-conviction candidate trades? "
            f"Interesting setups: {[r['symbol'] + ':' + r['trend'] for r in interesting[:5]]}. "
            f"News coverage available for {news_hits} symbols."
        )

    def _log(self, research: Dict[str, Any]):
        with open(self.log_path, "a") as f:
            f.write(json.dumps(research, default=str) + "\n")
