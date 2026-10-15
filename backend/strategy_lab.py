"""Independent virtual portfolios used to compare every strategy with live-equivalent exits."""
import json
from datetime import UTC, datetime
from pathlib import Path

from .strategies import AVAILABLE, atr, evaluate


class StrategyLab:
    def __init__(self, enabled: bool, path: Path = Path("database/strategy_lab.json")):
        self.enabled, self.path = enabled, path
        try:
            self.state = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            self.state = {"bars": {}, "portfolios": {}}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.state), encoding="utf-8")

    @staticmethod
    def _close(item: dict, price: float, reason: str, timestamp: str) -> None:
        quantity, entry_price = item["quantity"], item["average_price"]
        trade_pnl = (price - entry_price) * quantity
        item["realized_pnl"] += trade_pnl
        item["closed_trades"] += 1
        item["wins"] += int(trade_pnl > 0)
        item.setdefault("trades", []).append({
            "entry_time": item.get("entry_time"), "exit_time": timestamp,
            "quantity": quantity, "entry_price": entry_price, "exit_price": price,
            "pnl": round(trade_pnl, 4),
            "outcome": "win" if trade_pnl > 0 else "loss" if trade_pnl < 0 else "flat",
            "exit_reason": reason,
        })
        item.update(quantity=0, average_price=0, current_price=price)
        for key in ("entry_time", "entry_reason", "stop_price", "take_profit_price"):
            item.pop(key, None)

    def process(self, symbol: str, candles, settings) -> None:
        """Advance every strategy's separate virtual portfolio for one symbol/bar."""
        if not self.enabled:
            return
        bar, price = str(candles.index[-1]), float(candles["Close"].iloc[-1])
        if self.state["bars"].get(symbol) == bar:
            return
        self.state["bars"][symbol] = bar
        current_atr = atr(candles)
        for strategy in sorted(AVAILABLE):
            portfolio = self.state["portfolios"].setdefault(strategy, {})
            item = portfolio.setdefault(symbol, {"quantity": 0, "average_price": 0, "current_price": price, "realized_pnl": 0, "closed_trades": 0, "wins": 0})
            item["current_price"] = price
            if item["quantity"] and current_atr:
                item.setdefault("stop_price", round(item["average_price"] - current_atr * settings.auto_atr_stop_multiple, 4))
                item.setdefault("take_profit_price", round(item["average_price"] + current_atr * settings.auto_atr_take_profit_multiple, 4))
            if item["quantity"] and item.get("stop_price") is not None and float(candles["Low"].iloc[-1]) <= item["stop_price"]:
                self._close(item, float(item["stop_price"]), "ATR stop loss", bar)
                continue
            if item["quantity"] and item.get("take_profit_price") is not None and float(candles["High"].iloc[-1]) >= item["take_profit_price"]:
                self._close(item, float(item["take_profit_price"]), "ATR take profit", bar)
                continue
            signal = evaluate(strategy, candles)
            if signal and signal.action == "buy" and not item["quantity"]:
                item.update(quantity=1, average_price=price, current_price=price, entry_time=bar, entry_reason=signal.reason)
                if current_atr:
                    item["stop_price"] = round(price - current_atr * settings.auto_atr_stop_multiple, 4)
                    item["take_profit_price"] = round(price + current_atr * settings.auto_atr_take_profit_multiple, 4)
            elif signal and signal.action == "close" and item["quantity"]:
                self._close(item, price, signal.reason, bar)
        self._save()

    def close_all(self, prices: dict[str, float]) -> None:
        if not self.enabled:
            return
        timestamp = datetime.now(UTC).isoformat()
        for symbols in self.state.get("portfolios", {}).values():
            for symbol, item in symbols.items():
                if item["quantity"]:
                    self._close(item, float(prices.get(symbol, item["current_price"])), "end-of-day exit", timestamp)
        self._save()


def export_data(
    path: Path = Path("database/strategy_lab.json"),
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict:
    """Return Strategy Lab history in an optional timestamp window."""
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        state = {"bars": {}, "portfolios": {}}
    bounded = start is not None or end is not None

    def normalized(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    start_utc = normalized(start) if start else None
    end_utc = normalized(end) if end else None

    def in_window(value: str | None) -> bool:
        if not bounded:
            return True
        try:
            timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return False
        timestamp = normalized(timestamp)
        return (start_utc is None or timestamp >= start_utc) and (end_utc is None or timestamp <= end_utc)

    portfolios = []
    for strategy, symbols in sorted(state.get("portfolios", {}).items()):
        for symbol, item in sorted(symbols.items()):
            trades = item.get("trades", [])
            if bounded:
                trades = [trade for trade in trades if in_window(trade.get("exit_time") or trade.get("entry_time"))]
                open_in_window = bool(item.get("quantity", 0)) and in_window(item.get("entry_time"))
                if not trades and not open_in_window:
                    continue
                closed = len(trades)
                wins = sum(trade.get("outcome") == "win" for trade in trades)
                realized_pnl = sum(float(trade.get("pnl", 0)) for trade in trades)
            else:
                open_in_window = bool(item.get("quantity", 0))
                closed = int(item.get("closed_trades", 0))
                wins = int(item.get("wins", 0))
                realized_pnl = float(item.get("realized_pnl", 0))
            quantity = item.get("quantity", 0) if open_in_window else 0
            entry_price = item.get("average_price") if open_in_window else None
            portfolios.append({
                "strategy": strategy, "symbol": symbol, "closed_trades": closed,
                "wins": wins, "losses": closed - wins,
                "realized_pnl": round(realized_pnl, 4),
                "unrealized_pnl": round((float(item.get("current_price", 0)) - float(item.get("average_price", 0))) * float(quantity), 4),
                "open_position": bool(quantity), "quantity": quantity,
                "entry_price": entry_price,
                "current_price": item.get("current_price"), "entry_time": item.get("entry_time") if open_in_window else None,
                "entry_reason": item.get("entry_reason") if open_in_window else None,
                "stop_price": item.get("stop_price") if open_in_window else None,
                "take_profit_price": item.get("take_profit_price") if open_in_window else None,
                "trades": trades,
            })
    bars = {symbol: bar for symbol, bar in state.get("bars", {}).items() if in_window(bar)}
    return {
        "format": "trade-bot-strategy-lab-v2", "generated_at": datetime.now(UTC).isoformat(),
        "filters": {"start": start_utc.isoformat() if start_utc else None, "end": end_utc.isoformat() if end_utc else None},
        "last_completed_bar_by_symbol": bars, "portfolios": portfolios,
    }


def standings(
    path: Path = Path("database/strategy_lab.json"),
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"enabled": False, "strategies": [], "best_by_symbol": [], "strategy_rankings": {}}
    bounded = start is not None or end is not None

    def normalized(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    start_utc = normalized(start) if start else None
    end_utc = normalized(end) if end else None

    def in_window(value: str | None) -> bool:
        if not bounded:
            return True
        try:
            timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return False
        timestamp = normalized(timestamp)
        return (start_utc is None or timestamp >= start_utc) and (end_utc is None or timestamp <= end_utc)

    rows, by_symbol, strategy_rankings = [], {}, {}
    for strategy, symbols in state.get("portfolios", {}).items():
        realized = 0.0
        unrealized = 0.0
        open_positions = 0
        closed_trades = 0
        pnl = realized + unrealized
        for symbol, item in symbols.items():
            if bounded:
                selected_trades = [trade for trade in item.get("trades", []) if in_window(trade.get("exit_time"))]
                item_open = bool(item.get("quantity")) and in_window(item.get("entry_time"))
                item_realized = sum(float(trade.get("pnl", 0)) for trade in selected_trades)
                item_unrealized = (item["current_price"] - item["average_price"]) * item["quantity"] if item_open else 0.0
                item_closed = len(selected_trades)
                item_wins = sum(float(trade.get("pnl", 0)) > 0 for trade in selected_trades)
                item_losses = sum(float(trade.get("pnl", 0)) < 0 for trade in selected_trades)
                item_flats = item_closed - item_wins - item_losses
                active_in_window = bool(selected_trades or item_open)
            else:
                item_open = bool(item["quantity"])
                item_realized = float(item["realized_pnl"])
                item_unrealized = (item["current_price"] - item["average_price"]) * item["quantity"]
                item_closed = int(item["closed_trades"])
                trade_history = item.get("trades", [])
                if trade_history:
                    item_wins = sum(float(trade.get("pnl", 0)) > 0 for trade in trade_history)
                    item_losses = sum(float(trade.get("pnl", 0)) < 0 for trade in trade_history)
                    item_flats = item_closed - item_wins - item_losses
                else:
                    item_wins = int(item.get("wins", 0))
                    item_losses = max(item_closed - item_wins, 0)
                    item_flats = 0
                active_in_window = True

            realized += item_realized
            unrealized += item_unrealized
            open_positions += int(item_open)
            closed_trades += item_closed
            if bounded and not active_in_window:
                continue
            value = item_realized + item_unrealized
            strategy_rankings.setdefault(symbol, []).append({
                "strategy": strategy, "pnl": round(value, 2),
                "realized_pnl": round(item_realized, 2), "open_position": item_open,
                "closed_trades": item_closed, "wins": item_wins,
                "losses": item_losses, "flats": item_flats,
            })
            if symbol not in by_symbol or value > by_symbol[symbol]["pnl"]:
                by_symbol[symbol] = {"symbol": symbol, "strategy": strategy, "pnl": round(value, 2)}
        pnl = realized + unrealized
        rows.append({"strategy": strategy, "pnl": round(pnl, 2), "realized_pnl": round(realized, 2), "open_positions": open_positions, "closed_trades": closed_trades})
    rankings = {symbol: sorted(values, key=lambda row: row["pnl"], reverse=True) for symbol, values in strategy_rankings.items()}
    return {"enabled": True, "strategies": sorted(rows, key=lambda row: row["pnl"], reverse=True), "best_by_symbol": sorted(by_symbol.values(), key=lambda row: row["symbol"]), "strategy_rankings": rankings}
