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

There are no webhook, TradingView, Gmail, broker, or live-trading endpoints. The local day-trader writes its paper-trading activity directly to the database.

## Start the worker when needed

The API/dashboard can remain online without using market-data requests. Start the paper day trader only when you want to scan and paper trade:

```powershell
.\.venv312\Scripts\python.exe -m backend.day_trader
```

See [OPERATIONS.md](OPERATIONS.md) to stop or reset either process.
