# Comparable backtests

Run each implemented strategy through the same long-only backtest engine with identical data, costs, and slippage:

```powershell
py -m backend.backtest
```

Results are printed and saved to `database/backtest_results.json`. By default, this evaluates all available strategies on five years of daily SPY data with 5 basis points of commission/fees and 5 basis points of slippage per fill.

Add these optional settings to `.env`:

```text
BACKTEST_SYMBOL=SPY
BACKTEST_INTERVAL=1d
BACKTEST_PERIOD=5y
BACKTEST_COST_BPS=5
BACKTEST_SLIPPAGE_BPS=5
BACKTEST_STRATEGIES=trend,donchian,macd,bollinger,rsi,volatility_breakout,regression
```

The report includes total and annualized return, maximum drawdown, Sharpe ratio, Calmar ratio, and completed trades. It does not establish that a strategy will perform live: use it to compare configurations, then forward-test in paper mode and repeat the analysis across symbols and market regimes. The annualization constants are designed for daily candles; do not compare intraday results directly without revising those assumptions.
