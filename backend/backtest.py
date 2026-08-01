"""Comparable long-only backtests for the local OHLC strategy modes."""
import json
from dataclasses import asdict, dataclass
from math import sqrt
from pathlib import Path

import yfinance as yf
from pydantic_settings import BaseSettings, SettingsConfigDict

from .strategies import AVAILABLE, evaluate


class BacktestSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    backtest_symbol: str = "SPY"
    backtest_interval: str = "1d"
    backtest_period: str = "5y"
    backtest_strategies: str = "trend,donchian,macd,bollinger,rsi,volatility_breakout,regression"
    backtest_starting_cash: float = 100_000
    backtest_cost_bps: float = 5
    backtest_slippage_bps: float = 5

    @property
    def strategies(self) -> list[str]:
        result = [item.strip().lower() for item in self.backtest_strategies.split(",") if item.strip()]
        invalid = set(result) - AVAILABLE
        if invalid:
            raise ValueError(f"Unknown strategies: {', '.join(sorted(invalid))}")
        return result


@dataclass
class Result:
    strategy: str
    total_return_pct: float
    annualized_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    calmar_ratio: float
    completed_trades: int


def run_strategy(candles, name: str, settings: BacktestSettings) -> Result:
    cash, shares, entries, trades = settings.backtest_starting_cash, 0.0, 0, 0
    equity = []
    cost = (settings.backtest_cost_bps + settings.backtest_slippage_bps) / 10_000
    for index in range(205, len(candles)):
        history = candles.iloc[: index + 1]
        price = float(history["Close"].iloc[-1])
        signal = evaluate(name, history)
        if signal and signal.action == "buy" and shares == 0:
            fill = price * (1 + cost)
            shares = cash / fill
            cash = 0
            entries += 1
        elif signal and signal.action == "close" and shares > 0:
            cash = shares * price * (1 - cost)
            shares = 0
            if entries:
                trades += 1
        equity.append(cash + shares * price)
    if shares:
        cash = shares * float(candles["Close"].iloc[-1]) * (1 - cost)
        trades += 1
        equity[-1] = cash
    returns = [equity[i] / equity[i - 1] - 1 for i in range(1, len(equity)) if equity[i - 1] > 0]
    peak, max_drawdown = settings.backtest_starting_cash, 0.0
    for value in equity:
        peak = max(peak, value)
        max_drawdown = max(max_drawdown, (peak - value) / peak)
    total = cash / settings.backtest_starting_cash - 1
    years = max((len(candles) - 205) / 252, 1 / 252)
    annualized = (1 + total) ** (1 / years) - 1 if total > -1 else -1
    mean = sum(returns) / len(returns) if returns else 0
    variance = sum((value - mean) ** 2 for value in returns) / max(len(returns) - 1, 1)
    sharpe = (mean / sqrt(variance) * sqrt(252)) if variance > 0 else 0
    calmar = annualized / max_drawdown if max_drawdown > 0 else 0
    return Result(name, round(total * 100, 2), round(annualized * 100, 2), round(max_drawdown * 100, 2), round(sharpe, 2), round(calmar, 2), trades)


def main() -> None:
    settings = BacktestSettings()
    candles = yf.download(settings.backtest_symbol, period=settings.backtest_period, interval=settings.backtest_interval, auto_adjust=True, progress=False, multi_level_index=False, timeout=15)
    if len(candles) < 210:
        raise RuntimeError("Not enough bars returned for a 50/200 moving-average backtest")
    results = [asdict(run_strategy(candles, name, settings)) for name in settings.strategies]
    report = {"symbol": settings.backtest_symbol, "interval": settings.backtest_interval, "period": settings.backtest_period, "cost_bps": settings.backtest_cost_bps, "slippage_bps": settings.backtest_slippage_bps, "results": results}
    Path("database").mkdir(exist_ok=True)
    Path("database/backtest_results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
