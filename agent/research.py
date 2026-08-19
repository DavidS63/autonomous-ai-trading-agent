"""Market intelligence gathering - bars, technicals, Finnhub news, self-reflection."""

from __future__ import annotations

import os
from typing import Dict, Any, List
from datetime import datetime

import requests
from rich.console import Console

console = Console(force_terminal=False, emoji=False, legacy_windows=True)


class ResearchEngine:
    def __init__(self, broker, config: Dict[str, Any]):
        self.broker = broker
        self.config = config
        self.symbols = config.get("universe", {}).get("symbols", [])
        self.finnhub_key = os.getenv("FINNHUB_API_KEY")

    def _finnhub_news(self, symbol: str, limit: int = 8) -> List[Dict[str, Any]]:
        if not self.finnhub_key:
            return []
        try:
            url = "https://finnhub.io/api/v1/company-news"
            today = datetime.utcnow().strftime("%Y-%m-%d")
            params = {
                "symbol": symbol,
                "from": today,
                "to": today,
                "token": self.finnhub_key,
            }
            # broaden window a bit
            from datetime import timedelta
            start = (datetime.utcnow() - timedelta(days=5)).strftime("%Y-%m-%d")
            params["from"] = start
            r = requests.get(url, params=params, timeout=15)
            r.raise_for_status()
            news = r.json() or []
            out = []
            for n in news[:limit]:
                out.append({
                    "headline": n.get("headline") or n.get("summary") or "",
                    "source": n.get("source"),
                    "datetime": n.get("datetime"),
                    "url": n.get("url"),
                })
            return out
        except Exception as e:
            console.print(f"[dim]Finnhub news skip {symbol}: {e}[/]")
            return []

    def _features_from_bars(self, bars: List[Dict[str, Any]]) -> Dict[str, float]:
        if not bars or len(bars) < 5:
            return {}
        closes = [b["c"] for b in bars]
        volumes = [b["v"] for b in bars]
        last = closes[-1]
        prev = closes[-2] if len(closes) > 1 else last
        ma5 = sum(closes[-5:]) / min(5, len(closes))
        ma20 = sum(closes[-20:]) / min(20, len(closes)) if len(closes) >= 10 else ma5
        momentum = (last - closes[0]) / closes[0] if closes[0] else 0.0
        vol_avg = sum(volumes[:-1]) / max(1, len(volumes) - 1)
        vol_ratio = volumes[-1] / vol_avg if vol_avg else 1.0
        trend = 1.0 if last > ma5 > ma20 else (-1.0 if last < ma5 < ma20 else 0.0)
        return {
            "last": last,
            "momentum": momentum,
            "vol_ratio": vol_ratio,
            "trend": trend,
            "ma5": ma5,
            "ma20": ma20,
            "change_1d": (last - prev) / prev if prev else 0.0,
        }

    def run_full_scan(self) -> Dict[str, Any]:
        console.print("[cyan]> Running full market intelligence scan...[/]")
        account = self.broker.get_account()
        positions = self.broker.get_positions()
        symbol_reports = []

        for symbol in self.symbols:
            try:
                bars = self.broker.get_bars(symbol, limit=50)
                feats = self._features_from_bars(bars)
                if not feats:
                    console.print(f"[dim]Research skip {symbol}: no bars[/]")
                    continue
                news = self._finnhub_news(symbol)
                symbol_reports.append({
                    "symbol": symbol,
                    "features": feats,
                    "news": news,
                    "bars_count": len(bars),
                })
            except Exception as e:
                console.print(f"[dim]Research skip {symbol}: {e}[/]")

        console.print(f"[green]OK Scan complete[/] - {len(symbol_reports)} symbols analyzed")

        interesting = []
        for r in symbol_reports:
            f = r.get("features") or {}
            t = f.get("trend", 0)
            m = f.get("momentum", 0)
            if t > 0 and m > 0:
                interesting.append(f"{r['symbol']}:bullish")
            elif t < 0 and m < 0:
                interesting.append(f"{r['symbol']}:bearish")

        self_reflection = (
            "What new information has emerged that materially changes the probability distribution of price movement "
            f"for my current open positions ({len(positions)}) or for high-conviction candidate trades? "
            f"Interesting setups: {interesting[:8]}. News coverage available for {len(symbol_reports)} symbols."
        )

        return {
            "account": account,
            "open_positions": positions,
            "symbol_reports": symbol_reports,
            "self_reflection": self_reflection,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
