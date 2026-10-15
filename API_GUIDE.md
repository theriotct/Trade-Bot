# Local API guide

Start the local dashboard/API:

```powershell
.\.venv312\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Open the interactive API guide at `http://127.0.0.1:8000/docs`.

## Read-only endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Confirms the local paper-trading service is online. |
| `GET /positions` | Lists current open paper positions. |
| `GET /stats` | Returns account value, P/L, win rate, and position count. |
| `GET /api/trades` | Returns recent simulated trade history. |
| `GET /api/alerts` | Returns recent local strategy events and rejections. |
| `GET /api/system` | Returns the day-trader heartbeat, watched symbols, strategy, and market state. |
| `GET /api/news` | Returns saved headlines, keyword scores, and the isolated News Lab paper results. |

The app has no webhook, TradingView, Gmail, or live-trading endpoint. The optional Alpaca execution adapter is paper-only and writes confirmed paper fills to the local SQLite ledger. API credentials stay in the local `.env` file and are never returned by these endpoints.

## Optional Alpaca integration

The main process uses `MARKET_DATA_PROVIDER=alpaca` for IEX bars and `EXECUTION_MODE=alpaca_paper` for Alpaca paper orders. Set `NEWS_ENABLED=true` to enable the separate News Lab. Configure paper keys in `.env`; the order host is fixed to `paper-api.alpaca.markets`.

## Start the worker when needed

The API/dashboard can remain online without using market-data requests. Start the paper day trader only when you want to scan and paper trade:

```powershell
.\.venv312\Scripts\python.exe -m backend.day_trader
```

See [OPERATIONS.md](OPERATIONS.md) to stop or reset either process.
