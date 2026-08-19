"""Alpaca Paper Trading client wrapper with risk helpers."""

from __future__ import annotations

import os
from typing import Optional, List, Dict, Any

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
    GetOrdersRequest,
    ClosePositionRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.common.exceptions import APIError
from dotenv import load_dotenv
from rich.console import Console

load_dotenv()
console = Console()


class PaperBroker:
    """Thin, safe wrapper around Alpaca paper trading + market data."""

    def __init__(self):
        api_key = os.getenv("ALPACA_API_KEY")
        secret_key = os.getenv("ALPACA_SECRET_KEY")

        if not api_key or not secret_key:
            raise ValueError(
                "Missing ALPACA_API_KEY or ALPACA_SECRET_KEY. "
                "Copy .env.example → .env and fill in your free paper keys from "
                "https://app.alpaca.markets"
            )

        self.trading = TradingClient(api_key, secret_key, paper=True)
        self.data = StockHistoricalDataClient(api_key, secret_key)
        self._account_cache = None

    def get_account(self) -> Dict[str, Any]:
        account = self.trading.get_account()
        self._account_cache = account
        return {
            "equity": float(account.equity),
            "cash": float(account.cash),
            "buying_power": float(account.buying_power),
            "portfolio_value": float(account.portfolio_value),
            "status": account.status,
            "pattern_day_trader": account.pattern_day_trader,
            "trading_blocked": account.trading_blocked,
            "account_blocked": account.account_blocked,
        }

    def get_positions(self) -> List[Dict[str, Any]]:
        positions = self.trading.get_all_positions()
        result = []
        for p in positions:
            result.append({
                "symbol": p.symbol,
                "qty": float(p.qty),
                "side": p.side,
                "market_value": float(p.market_value),
                "avg_entry_price": float(p.avg_entry_price),
                "current_price": float(p.current_price),
                "unrealized_pl": float(p.unrealized_pl),
                "unrealized_plpc": float(p.unrealized_plpc),
                "change_today": float(p.change_today) if p.change_today else 0.0,
            })
        return result

    def get_open_orders(self) -> List[Dict[str, Any]]:
        req = GetOrdersRequest(status=QueryOrderStatus.OPEN)
        orders = self.trading.get_orders(req)
        return [
            {
                "id": str(o.id),
                "symbol": o.symbol,
                "side": o.side.value if o.side else None,
                "qty": float(o.qty) if o.qty else None,
                "type": o.type.value if o.type else None,
                "status": o.status.value if o.status else None,
            }
            for o in orders
        ]

    def submit_market_order(
        self,
        symbol: str,
        qty: float,
        side: str,
        time_in_force: str = "day",
    ) -> Dict[str, Any]:
        side_enum = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
        tif = TimeInForce.DAY if time_in_force.lower() == "day" else TimeInForce.GTC

        order_data = MarketOrderRequest(
            symbol=symbol.upper(),
            qty=abs(qty),
            side=side_enum,
            time_in_force=tif,
        )
        try:
            order = self.trading.submit_order(order_data)
            console.print(f"[green]Order submitted:[/] {side.upper()} {qty} {symbol} → {order.id}")
            return {
                "id": str(order.id),
                "symbol": order.symbol,
                "side": side,
                "qty": qty,
                "status": order.status.value if order.status else "submitted",
            }
        except APIError as e:
            console.print(f"[red]Order failed:[/] {e}")
            raise

    def close_position(self, symbol: str) -> bool:
        try:
            self.trading.close_position(symbol.upper())
            console.print(f"[yellow]Closed position:[/] {symbol}")
            return True
        except APIError as e:
            console.print(f"[red]Close failed:[/] {e}")
            return False

    def get_latest_quotes(self, symbols: List[str]) -> Dict[str, float]:
        req = StockLatestQuoteRequest(symbol_or_symbols=symbols)
        quotes = self.data.get_stock_latest_quote(req)
        return {sym: float(q.ask_price or q.bid_price or 0) for sym, q in quotes.items()}

    def get_bars(self, symbol: str, limit: int = 50) -> List[Dict[str, Any]]:
        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Minute,  # for short-term focus; change to Day if preferred
            limit=limit,
        )
        bars = self.data.get_stock_bars(req)
        data = bars[symbol]
        return [
            {
                "t": str(b.timestamp),
                "o": float(b.open),
                "h": float(b.high),
                "l": float(b.low),
                "c": float(b.close),
                "v": int(b.volume),
            }
            for b in data
        ]

    def calculate_position_size(
        self,
        equity: float,
        entry_price: float,
        stop_price: float,
        risk_pct: float = 1.0,
    ) -> float:
        """Risk-based position sizing. Returns share quantity."""
        if entry_price <= 0 or stop_price <= 0:
            return 0.0
        risk_per_share = abs(entry_price - stop_price)
        if risk_per_share == 0:
            return 0.0
        dollar_risk = equity * (risk_pct / 100.0)
        shares = dollar_risk / risk_per_share
        # Round down to whole shares for simplicity (Alpaca supports fractional too)
        return max(0.0, round(shares, 2))
