"""US regular-hours wrapper for the local paper-only auto trader."""
import json
import hashlib
import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from .auto_trader import AutoTraderSettings, load_state, process_lab_symbol, process_symbol, save_state
from .alpaca_api import get_alpaca_api
from .broker import AlpacaPaperBroker, PaperBroker
from .config import get_settings
from .database import Database
from .market_data import fetch_candles
from .news_lab import NewsLab
from .one_day_lab import OneDayLab
from .risk import RiskManager
from .runtime_status import publish
from .strategy_lab import StrategyLab, standings
from .strategy_sleeves import close_all_strategy_sleeves, process_all_strategies_symbol

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
    candles = fetch_candles(symbol, period="1d", interval="1m")
    if candles.empty:
        logger.warning("Could not obtain a closing price for %s", symbol)
        return None
    price = float(candles["Close"].iloc[-1])
    position = database.position(symbol)
    if not position:
        # The Strategy Lab has independent virtual positions, so it still needs
        # a market-close price even if the primary paper account is flat.
        return price
    client_order_id = hashlib.sha256(f"{symbol}|{datetime.now(EASTERN).date().isoformat()}|end-of-day".encode()).hexdigest()[:32]
    broker.execute(symbol, "close", price, position["quantity"], "Day-trader end-of-day exit", client_order_id)
    database.record_alert(symbol, "close", json.dumps({"source": "day_trader", "symbol": symbol, "action": "close", "price": price}), "executed: end-of-day exit")
    logger.info("Closed %s at %.2f for end of day", symbol, price)
    return price


def _broker_signature(settings) -> tuple[str, str, str]:
    if settings.execution_mode == "alpaca_paper":
        return settings.execution_mode, settings.alpaca_api_key, settings.alpaca_secret_key
    return settings.execution_mode, "", ""


def _build_broker(database: Database, settings) -> PaperBroker:
    if settings.execution_mode == "alpaca_paper":
        broker = AlpacaPaperBroker(database, get_alpaca_api(settings.alpaca_api_key, settings.alpaca_secret_key))
        broker.sync_positions()
        return broker
    return PaperBroker(database)


def main() -> None:
    auto = AutoTraderSettings()
    settings = get_settings()
    database = Database(settings.database_path)
    database.initialize()
    one_day_lab = OneDayLab(database)
    broker: PaperBroker = _build_broker(database, settings)
    broker_signature = _broker_signature(settings)
    broker_ready = True
    broker_config_error = ""
    risk = RiskManager(database, settings)
    lab = StrategyLab(auto.strategy_lab_enabled)
    news_lab = NewsLab(database)
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
        updated_signature = _broker_signature(settings)
        if updated_signature != broker_signature or not broker_ready:
            try:
                # Do not silently abandon open Alpaca positions when switching
                # to local simulation. Reconcile them before changing brokers.
                if settings.execution_mode == "local" and isinstance(broker, AlpacaPaperBroker):
                    if broker.api.positions():
                        raise AlpacaAPIError("Close all Alpaca paper positions before switching execution to the local simulator")
                broker = _build_broker(database, settings)
                broker_signature = updated_signature
                broker_ready = True
                broker_config_error = ""
                logger.info("Applied updated paper execution settings")
            except Exception as exc:
                broker_ready = False
                broker_config_error = str(exc)
                logger.exception("Could not apply updated paper execution settings")
        now = datetime.now(EASTERN)
        phase = market_phase(now)
        publish("day_trader", status=phase, symbols=auto.symbols, mode=auto.auto_mode, strategy=auto.auto_strategy, market_time=now.isoformat(), market_data_provider=settings.market_data_provider, execution_mode=settings.execution_mode, news_enabled=settings.news_enabled, execution_config_status="ready" if broker_ready else "error", message=broker_config_error or None)
        if phase in {"trade", "liquidate"}:
            test_symbols = one_day_lab.due_symbols(now.date())
            test_candles = {}
            for symbol in test_symbols:
                try:
                    candles = fetch_candles(symbol, period="5d", interval="1m")
                    if len(candles) > 1:
                        test_candles[symbol] = candles.iloc[:-1]
                except Exception as exc:
                    logger.exception("One-day paper test data fetch failed for %s: %s", symbol, exc)
            try:
                one_day_lab.tick(now, test_candles, market_open=phase == "trade", market_close=phase == "liquidate")
            except Exception as exc:
                logger.exception("One-day paper test processing failed: %s", exc)
        if phase == "trade":
            if settings.news_enabled and settings.news_provider == "alpaca":
                try:
                    added = news_lab.ingest(auto.symbols)
                    publish("news_lab", status="connected", provider="alpaca", new_articles=added)
                except Exception as exc:
                    logger.exception("News scan failed: %s", exc)
                    publish("news_lab", status="error", provider=settings.news_provider, message=str(exc))
            if broker_ready or auto.auto_mode == "all_strategies":
                for symbol in auto.symbols:
                    try:
                        if auto.auto_mode == "all_strategies":
                            process_all_strategies_symbol(symbol, auto, database, lab, news_lab)
                        else:
                            process_symbol(symbol, auto, state, database, broker, risk, lab, news_lab)
                            save_state(state_path, state)
                    except Exception as exc:
                        logger.exception("%s failed: %s", symbol, exc)
            else:
                logger.error("Main-account scan paused until execution settings are reconciled: %s", broker_config_error)
            if lab.enabled:
                live_symbols = set(auto.symbols)
                for symbol in auto.lab_symbols:
                    if symbol in live_symbols:
                        continue
                    try:
                        process_lab_symbol(symbol, auto, lab)
                    except Exception as exc:
                        logger.exception("Strategy Lab %s failed: %s", symbol, exc)
        elif phase == "liquidate" and now.date().isoformat() not in closed_dates:
            if not broker_ready:
                logger.error("End-of-day exits paused until execution settings are reconciled: %s", broker_config_error)
                time.sleep(max(auto.auto_poll_seconds, 30))
                continue
            closing_prices: dict[str, float] = {}
            for symbol in auto.lab_symbols:
                try:
                    price = close_at_end_of_day(symbol, database, broker)
                    if price is not None:
                        closing_prices[symbol] = price
                except Exception as exc:
                    logger.exception("Could not close %s: %s", symbol, exc)
            lab.close_all(closing_prices)
            if auto.auto_mode == 'all_strategies':
                close_all_strategy_sleeves(database, closing_prices)
            summary = database.daily_trade_summary(now.date().isoformat())
            if auto.auto_mode == 'all_strategies':
                sleeve_summary = database.strategy_daily_trade_summary(now.date().isoformat())
                summary = {
                    "realized_pnl": summary["realized_pnl"] + sleeve_summary["realized_pnl"],
                    "closed_trades": summary["closed_trades"] + sleeve_summary["closed_trades"],
                    "wins": summary["wins"] + sleeve_summary["wins"],
                }
            database.save_daily_report(now.date().isoformat(), summary["realized_pnl"], summary["closed_trades"], summary["wins"], standings())
            closed_dates.add(now.date().isoformat())
        time.sleep(max(auto.auto_poll_seconds, 30))


if __name__ == "__main__":
    main()
