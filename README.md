# Local Paper Day Trader

A local, paper-only day-trading lab. It pulls market candles locally, evaluates selectable strategies, applies risk controls, records simulated trades in SQLite, and displays everything in a browser dashboard.

It has no live-broker, TradingView, Gmail, or webhook integration.

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

## What it does

- Watches all whitelist symbols when `AUTO_SYMBOLS=*`.
- Evaluates completed candles only during US regular market hours.
- Supports trend, Donchian breakout, MACD, Bollinger, RSI, volatility-breakout, and regression modes.
- Uses ATR-based sizing and protective paper stops.
- Limits each symbol to one open paper position.
- Closes configured paper positions near the end of the trading day.

Read [OPERATIONS.md](OPERATIONS.md) for start, stop, reset, and status commands. Read [AUTO_TRADER.md](AUTO_TRADER.md) for strategy selection and [TAILSCALE_ACCESS.md](TAILSCALE_ACCESS.md) for private remote dashboard access.

## Safety

This is for simulation and learning. Free market data can be delayed or unavailable, and no backtest or paper result guarantees live performance.