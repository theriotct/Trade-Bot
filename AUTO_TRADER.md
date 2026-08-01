# Strategy lab and auto trader

This paper-only service runs strategies locally from OHLC candles, from locally downloaded OHLC candles. It shares the project's risk checks, SQLite trade log, and dashboard.

## Supported selectable techniques

| Name | Signal |
| --- | --- |
| `trend` | 50/200 SMA golden/death cross |
| `donchian` | 20-bar high/low breakout |
| `macd` | MACD/signal-line cross |
| `bollinger` | Close outside the 20-period, 2-standard-deviation bands |
| `rsi` | Cross below 30 / above 70 |
| `volatility_breakout` | 20-bar range breakout/breakdown |
| `regression` | 30-bar linear-regression slope changes sign |

ATR is used for risk-based position sizing, protective stops, and a configurable take-profit target (default: 2× ATR). The bot ignores incomplete candles and establishes a no-trade baseline when it starts.

## Run one technique

Copy [`.auto-trader.env.example`](.auto-trader.env.example) into `.env`, then choose a strategy:

```text
AUTO_MODE=single
AUTO_STRATEGY=macd
```

Start the dashboard/API, then run:

```powershell
py -m backend.auto_trader
```

## Run a consensus

To require two or more strategies to agree on a completed candle:

```text
AUTO_MODE=consensus
AUTO_STRATEGIES=trend,macd,regression
AUTO_CONSENSUS_MIN=2
```

The scanner defaults to daily candles because the 50/200 trend model requires at least 200 completed bars. Keep `AUTO_PERIOD=2y` for that mode.

## Deliberately not simulated

Pairs/statistical arbitrage needs aligned multi-asset, cointegration-tested data. Options strategies require option-chain pricing and assignment modeling. Order-book imbalance and market making require a real-time Level 2 feed. News, earnings, sector rotation, and ML classifiers require dedicated data sources plus walk-forward model training. They are not represented by fake proxies here.

Before comparing any of these modes, use the same symbols, candle interval, costs, and slippage assumptions in a backtest. A paper trade log is useful for forward testing, but it does not prove a strategy will work in other market regimes.
