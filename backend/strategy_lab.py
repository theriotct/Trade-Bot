"""Independent virtual portfolios used to compare every signal strategy."""
import json
from pathlib import Path

from .strategies import AVAILABLE, evaluate


class StrategyLab:
    def __init__(self, enabled: bool, path: Path = Path("database/strategy_lab.json")):
        self.enabled, self.path = enabled, path
        try:
            self.state = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            self.state = {"bars": {}, "portfolios": {}}

    def process(self, symbol: str, candles) -> None:
        if not self.enabled:
            return
        bar, price = str(candles.index[-1]), float(candles["Close"].iloc[-1])
        if self.state["bars"].get(symbol) == bar:
            return
        self.state["bars"][symbol] = bar
        for strategy in sorted(AVAILABLE):
            portfolio = self.state["portfolios"].setdefault(strategy, {})
            item = portfolio.setdefault(symbol, {"quantity": 0, "average_price": 0, "current_price": price, "realized_pnl": 0, "closed_trades": 0, "wins": 0})
            item["current_price"] = price
            signal = evaluate(strategy, candles)
            if signal and signal.action == "buy" and not item["quantity"]:
                item.update(quantity=1, average_price=price)
            elif signal and signal.action == "close" and item["quantity"]:
                trade_pnl = (price - item["average_price"]) * item["quantity"]
                item["realized_pnl"] += trade_pnl
                item["closed_trades"] += 1
                item["wins"] += int(trade_pnl > 0)
                item.update(quantity=0, average_price=0)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.state), encoding="utf-8")


    def close_all(self, prices: dict[str, float]) -> None:
        """Realize every virtual position at the regular-session end-of-day mark."""
        if not self.enabled:
            return
        for symbols in self.state.get("portfolios", {}).values():
            for symbol, item in symbols.items():
                if not item["quantity"]:
                    continue
                price = float(prices.get(symbol, item["current_price"]))
                trade_pnl = (price - item["average_price"]) * item["quantity"]
                item["realized_pnl"] += trade_pnl
                item["closed_trades"] += 1
                item["wins"] += int(trade_pnl > 0)
                item.update(quantity=0, average_price=0, current_price=price)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.state), encoding="utf-8")

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