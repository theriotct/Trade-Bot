# Paper day-trading mode

This mode is for simulated intraday practice only. It does not connect to a broker or place real orders.

## Setup

1. Install the local data dependency if needed:

   ```powershell
   pip install -r requirements.txt
   ```

2. Copy the contents of [`.day-trading.env.example`](.day-trading.env.example) into `.env`.
3. Start the dashboard/API:

   ```powershell
   uvicorn backend.app:app --reload
   ```

4. In a second terminal, start the day-trading wrapper:

   ```powershell
   py -m backend.day_trader
   ```

It processes only regular US weekday hours from 9:35 a.m. through 3:55 p.m. Eastern time, works from completed five-minute candles, and attempts to close configured paper positions at 3:55 p.m. It observes first and will not enter a position immediately on startup.

## Start conservatively

The supplied preset scans only `SPY`, allows one small paper position, and limits paper daily loss to $50. Do not increase size until you have reviewed a meaningful number of paper trades, including costs and slippage, in the dashboard and backtest report.

Use `AUTO_STRATEGY=donchian` first, then test `macd`, `rsi`, or consensus modes separately. The free data source can be delayed or unavailable, so this is not a live execution system.
