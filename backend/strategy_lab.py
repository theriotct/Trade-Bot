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


def export_data(path: Path = Path("database/strategy_lab.json")) -> dict:
    """Return the complete local lab record without settings or credentials."""
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        state = {"bars": {}, "portfolios": {}}
    portfolios = []
    for strategy, symbols in sorted(state.get("portfolios", {}).items()):
        for symbol, item in sorted(symbols.items()):
            closed = int(item.get("closed_trades", 0))
            wins = int(item.get("wins", 0))
            portfolios.append({
                "strategy": strategy, "symbol": symbol, "closed_trades": closed,
                "wins": wins, "losses": closed - wins,
                "realized_pnl": round(float(item.get("realized_pnl", 0)), 4),
                "unrealized_pnl": round((float(item.get("current_price", 0)) - float(item.get("average_price", 0))) * float(item.get("quantity", 0)), 4),
                "open_position": bool(item.get("quantity", 0)), "quantity": item.get("quantity", 0),
                "entry_price": item.get("average_price") if item.get("quantity", 0) else None,
                "current_price": item.get("current_price"), "entry_time": item.get("entry_time"),
                "entry_reason": item.get("entry_reason"), "stop_price": item.get("stop_price"),
                "take_profit_price": item.get("take_profit_price"), "trades": item.get("trades", []),
            })
    return {"format": "trade-bot-strategy-lab-v1", "generated_at": datetime.now(UTC).isoformat(), "last_completed_bar_by_symbol": state.get("bars", {}), "portfolios": portfolios}


def standings(path: Path = Path("database/strategy_lab.json")) -> dict:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"enabled": False, "strategies": [], "best_by_symbol": [], "strategy_rankings": {}}
    rows, by_symbol, strategy_rankings = [], {}, {}
    for strategy, symbols in state.get("portfolios", {}).items():
        realized = sum(item["realized_pnl"] for item in symbols.values())
        unrealized = sum((item["current_price"] - item["average_price"]) * item["quantity"] for item in symbols.values())
        pnl = realized + unrealized
        rows.append({"strategy": strategy, "pnl": round(pnl, 2), "realized_pnl": round(realized, 2), "open_positions": sum(1 for item in symbols.values() if item["quantity"]), "closed_trades": sum(item["closed_trades"] for item in symbols.values())})
        for symbol, item in symbols.items():
            value = item["realized_pnl"] + (item["current_price"] - item["average_price"]) * item["quantity"]
            strategy_rankings.setdefault(symbol, []).append({"strategy": strategy, "pnl": round(value, 2), "realized_pnl": round(item["realized_pnl"], 2), "open_position": bool(item["quantity"])})
            if symbol not in by_symbol or value > by_symbol[symbol]["pnl"]:
                by_symbol[symbol] = {"symbol": symbol, "strategy": strategy, "pnl": round(value, 2)}
    rankings = {symbol: sorted(values, key=lambda row: row["pnl"], reverse=True) for symbol, values in strategy_rankings.items()}
    return {"enabled": True, "strategies": sorted(rows, key=lambda row: row["pnl"], reverse=True), "best_by_symbol": sorted(by_symbol.values(), key=lambda row: row["symbol"]), "strategy_rankings": rankings}