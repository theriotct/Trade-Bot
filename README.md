# Trade Bot V2 · Paper Trading Lab

A local-first paper-trading lab. It compares independent price strategies, applies risk controls to the selected strategy, records fills and signals in SQLite, and displays results in a browser dashboard. Optional Alpaca integrations provide IEX market data, Alpaca paper-account execution, and a separate headline-sentiment experiment.

Execution is restricted to either the built-in local simulator or Alpaca's paper endpoint. There is no live-trading mode in this application.

## Start

Use Python 3.12 and install the project dependencies:

```powershell
py -3.12 -m venv .venv312
.\.venv312\Scripts\python.exe -m pip install -r requirements.txt
```

Start the dashboard:

```powershell
.\.venv312\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`, then start the paper day trader in a second terminal:

```powershell
.\.venv312\Scripts\python.exe -m backend.day_trader
```

## Alpaca paper setup

A local `.env` file is included with blank API-key fields and safe local defaults. Put your **paper-account** key and secret in `ALPACA_API_KEY` and `ALPACA_SECRET_KEY`. To use Alpaca for both market data and paper fills, set:

```dotenv
MARKET_DATA_PROVIDER=alpaca
ALPACA_DATA_FEED=iex
EXECUTION_MODE=alpaca_paper
```

To enable the separate news experiment, also set `NEWS_ENABLED=true`. Restart the worker after changing `.env`. Headlines older than `NEWS_MAX_AGE_MINUTES` (30 by default) are shown but excluded from the experiment so startup history does not create stale entries. The Basic feed is pinned to IEX, and the client limits itself to 180 requests per rolling minute to leave room below the documented historical-data request cap. Alpaca orders always go to `paper-api.alpaca.markets`.

You can leave `MARKET_DATA_PROVIDER=yfinance` and `EXECUTION_MODE=local` to use the existing local simulator without Alpaca credentials. In `AUTO_MODE=all_strategies`, the strategy sleeves remain virtual and independent of the selected broker mode.

## What it does

- Watches all whitelist symbols when `AUTO_SYMBOLS=*`.
- Evaluates completed candles only during US regular market hours.
- Supports trend, Donchian breakout, MACD, Bollinger, RSI, volatility-breakout, and regression modes.
- Runs every price strategy in its own virtual sleeve in all-strategies mode.
- Can source OHLCV candles from Alpaca IEX or Yahoo Finance.
- Includes a separate News Lab: a transparent keyword score paper experiment with one-share long entries, negative-headline exits, and configurable time exits.
- Uses ATR-based sizing and protective paper stops.
- Limits each symbol to one open paper position.
- Closes configured paper positions near the end of the trading day.

Read [OPERATIONS.md](OPERATIONS.md) for start, stop, reset, and status commands. Read [AUTO_TRADER.md](AUTO_TRADER.md) for strategy selection and [TAILSCALE_ACCESS.md](TAILSCALE_ACCESS.md) for private remote dashboard access.

## Safety

This is for simulation and learning. Headline scoring is a simple keyword baseline, not a trained model. Paper fills, IEX coverage, and market-data availability may differ from other feeds or live execution; no backtest or paper result guarantees future performance.
