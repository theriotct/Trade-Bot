"""US regular-hours wrapper for the local paper-only auto trader."""
import json
import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import yfinance as yf

from .auto_trader import AutoTraderSettings, load_state, process_symbol, save_state
from .broker import PaperBroker
from .config import get_settings
from .database import Database
from .risk import RiskManager
from .runtime_status import publish
from .strategy_lab import StrategyLab, standings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
EASTERN = ZoneInfo("America/New_York")


def market_phase(now: datetime) -> str:
    if now.weekday() >= 5:
        return "closed"
    clock = now.time()
    if clock < datetime.strptime("09:35", "%H:%M").time():
        return "closed"
    if clock >= datetime.strptime("15:55", "%H:%M").time():
        return "liquidate"
    return "trade"


def close_at_end_of_day(symbol: str, database: Database, broker: PaperBroker) -> float | None:
    candles = yf.download(symbol, period="1d", interval="1m", auto_adjust=True, progress=False, multi_level_index=False, timeout=10)
    if candles.empty:
        logger.warning("Could not obtain a closing price for %s", symbol)
        return None
    price = float(candles["Close"].iloc[-1])
    position = database.position(symbol)
    if not position:
        # The Strategy Lab has independent virtual positions, so it still needs
        # a market-close price even if the primary paper account is flat.
        return price
    broker.execute(symbol, "close", price, position["quantity"], "Day-trader end-of-day exit")
    database.record_alert(symbol, "close", json.dumps({"source": "day_trader", "symbol": symbol, "action": "close", "price": price}), "executed: end-of-day exit")
    logger.info("Closed %s at %.2f for end of day", symbol, price)
    return price


def main() -> None:
    auto = AutoTraderSettings()
    settings = get_settings()
    database = Database(settings.database_path)
    database.initialize()
    broker, risk = PaperBroker(database), RiskManager(database, settings)
    lab = StrategyLab(auto.strategy_lab_enabled)
    state_path = __import__("pathlib").Path("database/day_trader_state.json")
    state = load_state(state_path)
    closed_dates: set[str] = set()
    logger.info("Starting paper day trader for %s", ", ".join(auto.symbols))

    while True:
        # Dashboard changes take effect without restarting the worker.
        get_settings.cache_clear()
        auto = AutoTraderSettings()
        settings = get_settings()
        risk.settings = settings
        lab.enabled = auto.strategy_lab_enabled
        now = datetime.now(EASTERN)
        phase = market_phase(now)
        publish("day_trader", status=phase, symbols=auto.symbols, mode=auto.auto_mode, strategy=auto.auto_strategy, market_time=now.isoformat())
        if phase == "trade":
            for symbol in auto.symbols:
                try:
                    process_symbol(symbol, auto, state, database, broker, risk, lab)
                    save_state(state_path, state)
                except Exception as exc:
                    logger.exception("%s failed: %s", symbol, exc)
        elif phase == "liquidate" and now.date().isoformat() not in closed_dates:
            closing_prices: dict[str, float] = {}
            for symbol in auto.symbols:
                try:
                    price = close_at_end_of_day(symbol, database, broker)
                    if price is not None:
                        closing_prices[symbol] = price
                except Exception as exc:
                    logger.exception("Could not close %s: %s", symbol, exc)
            lab.close_all(closing_prices)
            summary = database.daily_trade_summary(now.date().isoformat())
            database.save_daily_report(now.date().isoformat(), summary["realized_pnl"], summary["closed_trades"], summary["wins"], standings())
            closed_dates.add(now.date().isoformat())
        time.sleep(max(auto.auto_poll_seconds, 30))


if __name__ == "__main__":
    main()
