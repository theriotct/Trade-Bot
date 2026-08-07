"""Independent paper-execution sleeves for the all-strategies test mode."""
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import yfinance as yf

from .config import get_settings
from .database import Database
from .strategies import AVAILABLE, atr, evaluate
from .strategy_lab import StrategyLab

logger = logging.getLogger(__name__)
EASTERN = ZoneInfo("America/New_York")


def _close(database: Database, symbol: str, strategy: str, position: dict, price: float, reason: str) -> float:
    pnl = (price - position["average_price"]) * position["quantity"]
    database.save_strategy_position(symbol, strategy, 0, 0, price, None, None, position["entry_time"])
    database.record_strategy_trade(symbol, strategy, "sell", position["quantity"], position["average_price"], price, pnl, reason, "closed")
    database.record_alert(symbol, "close", json.dumps({"source": "all_strategies_test", "symbol": symbol, "strategy": strategy, "price": price, "reason": reason}), f"executed: {strategy} sleeve closed — {reason}")
    return pnl


def _maybe_block(database: Database, symbol: str, strategy: str, settings) -> None:
    loss = database.sleeve_recent_realized_pnl(symbol, strategy, settings.auto_strategy_loss_window_minutes)
    if loss <= -settings.auto_strategy_loss_limit:
        date = datetime.now(EASTERN).date().isoformat()
        reason = f"{settings.auto_strategy_loss_window_minutes}-minute realized P/L {loss:.2f} reached -${settings.auto_strategy_loss_limit:.2f}"
        database.block_sleeve(symbol, strategy, date, reason)
        database.record_alert(symbol, "block", json.dumps({"source": "all_strategies_test", "strategy": strategy, "loss": loss}), f"blocked: {strategy} sleeve — {reason}")


def process_all_strategies_symbol(symbol: str, settings, database: Database, lab: StrategyLab | None = None) -> None:
    """Run each strategy in a separate paper sleeve for one live-allowed symbol."""
    candles = yf.download(symbol, period=settings.auto_period, interval=settings.auto_interval, auto_adjust=True, progress=False, multi_level_index=False, timeout=10).iloc[:-1]
    if len(candles) < 205:
        logger.warning("%s: need at least 205 completed bars for all-strategies test", symbol)
        return
    if lab:
        lab.process(symbol, candles, settings)
    bar, price = str(candles.index[-1]), float(candles["Close"].iloc[-1])
    current_atr = atr(candles)
    trade_date = datetime.now(EASTERN).date().isoformat()

    for strategy in sorted(AVAILABLE):
        if database.sleeve_bar(symbol, strategy) == bar:
            continue
        database.save_sleeve_bar(symbol, strategy, bar)
        position = database.strategy_position(symbol, strategy)
        if position:
            database.save_strategy_position(symbol, strategy, position["quantity"], position["average_price"], price, position["stop_price"], position["take_profit_price"], position["entry_time"])
            if position["stop_price"] is not None and float(candles["Low"].iloc[-1]) <= position["stop_price"]:
                _close(database, symbol, strategy, position, float(position["stop_price"]), "ATR protective stop")
                _maybe_block(database, symbol, strategy, settings)
                continue
            if position["take_profit_price"] is not None and float(candles["High"].iloc[-1]) >= position["take_profit_price"]:
                _close(database, symbol, strategy, position, float(position["take_profit_price"]), "ATR take-profit target")
                _maybe_block(database, symbol, strategy, settings)
                continue

        signal = evaluate(strategy, candles)
        if signal and signal.action == "close" and position:
            _close(database, symbol, strategy, position, price, signal.reason)
            _maybe_block(database, symbol, strategy, settings)
            continue
        if not signal or signal.action != "buy" or position:
            continue
        if database.sleeve_blocked(symbol, strategy, trade_date):
            continue
        if database.strategy_open_count() >= settings.auto_all_strategies_max_open:
            database.record_alert(symbol, "buy", json.dumps({"source": "all_strategies_test", "strategy": strategy}), "rejected: all-strategies open-sleeve limit reached")
            continue
        quantity = settings.auto_max_quantity
        if price * quantity > get_settings().max_position_value:
            database.record_alert(symbol, "buy", json.dumps({"source": "all_strategies_test", "strategy": strategy}), "rejected: order exceeds maximum position value")
            continue
        stop = round(price - current_atr * settings.auto_atr_stop_multiple, 4) if current_atr else None
        target = round(price + current_atr * settings.auto_atr_take_profit_multiple, 4) if current_atr else None
        database.save_strategy_position(symbol, strategy, quantity, price, price, stop, target, bar)
        database.record_strategy_trade(symbol, strategy, "buy", quantity, price, None, 0, signal.reason, "open")
        database.record_alert(symbol, "buy", json.dumps({"source": "all_strategies_test", "strategy": strategy, "price": price, "quantity": quantity}), f"executed: {strategy} sleeve — {signal.reason}")


def close_all_strategy_sleeves(database: Database, prices: dict[str, float]) -> None:
    """Close every open sleeve at end of day."""
    for position in database.strategy_positions():
        price = float(prices.get(position["symbol"], position["current_price"]))
        _close(database, position["symbol"], position["strategy"], position, price, "end-of-day exit")