"""Configurable local paper trader for multiple OHLC strategy techniques."""
import json
import logging
import time
from pathlib import Path

import yfinance as yf
from pydantic_settings import BaseSettings, SettingsConfigDict

from .broker import PaperBroker
from .config import get_settings
from .database import Database
from .risk import RiskManager, RiskRejected
from .runtime_status import publish
from .strategies import AVAILABLE, atr, selected_signals
from .strategy_lab import StrategyLab

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


class AutoTraderSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    auto_symbols: str = "SPY"
    auto_interval: str = "1d"
    auto_period: str = "2y"
    auto_poll_seconds: int = 300
    auto_mode: str = "single"  # single or consensus
    auto_strategy: str = "trend"
    auto_strategies: str = "trend,donchian,macd,bollinger,rsi,volatility_breakout,regression"
    auto_consensus_min: int = 2
    auto_max_quantity: float = 1
    auto_atr_stop_multiple: float = 2
    auto_atr_take_profit_multiple: float = 2
    auto_symbol_strategies: str = ""
    strategy_lab_enabled: bool = True

    @property
    def symbols(self) -> list[str]:
        values = [value.strip().upper() for value in self.auto_symbols.split(",") if value.strip()]
        return sorted(get_settings().allowed_symbols) if values == ["*"] else values

    @property
    def symbol_strategy_map(self) -> dict[str, str]:
        pairs = (part.split(":", 1) for part in self.auto_symbol_strategies.split(",") if ":" in part)
        return {symbol.strip().upper(): strategy.strip().lower() for symbol, strategy in pairs if strategy.strip().lower() in AVAILABLE}

    def strategy_for(self, symbol: str) -> str:
        return self.symbol_strategy_map.get(symbol.upper(), "donchian") if self.auto_strategy == "per_symbol" else self.auto_strategy
    @property
    def strategies(self) -> list[str]:
        names = [value.strip().lower() for value in self.auto_strategies.split(",") if value.strip()]
        invalid = set(names) - AVAILABLE
        if invalid:
            raise ValueError(f"Unknown strategies: {', '.join(sorted(invalid))}")
        return names


def load_state(path: Path) -> dict[str, object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(path: Path, state: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), encoding="utf-8")


def decide(candles, settings: AutoTraderSettings, symbol: str):
    selected = settings.strategy_for(symbol)
    names = [selected] if settings.auto_mode == "single" else settings.strategies
    if settings.auto_mode == "single" and selected not in AVAILABLE:
        raise ValueError(f"Unknown strategy for {symbol}: {selected}")
    signals = selected_signals(candles, names)
    if settings.auto_mode == "single":
        return signals[0] if signals else None
    buys = [signal for signal in signals if signal.action == "buy"]
    closes = [signal for signal in signals if signal.action == "close"]
    needed = max(1, settings.auto_consensus_min)
    if len(buys) >= needed:
        return "buy", "; ".join(signal.reason for signal in buys)
    if len(closes) >= needed:
        return "close", "; ".join(signal.reason for signal in closes)
    return None


def process_symbol(symbol: str, settings: AutoTraderSettings, state: dict[str, object], database: Database, broker: PaperBroker, risk: RiskManager, lab: StrategyLab | None = None) -> None:
    candles = yf.download(symbol, period=settings.auto_period, interval=settings.auto_interval, auto_adjust=True, progress=False, multi_level_index=False, timeout=10).iloc[:-1]
    if len(candles) < 205:
        logger.warning("%s: need at least 205 completed bars", symbol)
        return
    bar_id, price = str(candles.index[-1]), float(candles["Close"].iloc[-1])
    if lab:
        lab.process(symbol, candles, settings)
    position = database.position(symbol)
    if position:
        database.save_position(symbol, position["quantity"], position["average_price"], price)
    record = state.get(symbol)
    if not record:
        state[symbol] = {"bar": bar_id}
        logger.info("%s: baseline established at %s", symbol, bar_id)
        return
    # Convert scanner state written by an earlier version, if present.
    if isinstance(record, str):
        record = {"bar": record}
        state[symbol] = record
    if record.get("bar") == bar_id:
        return
    record["bar"] = bar_id

    current_atr = atr(candles)
    position = database.position(symbol)
    if position and current_atr:
        record.setdefault("stop_price", round(position["average_price"] - current_atr * settings.auto_atr_stop_multiple, 4))
        record.setdefault("take_profit_price", round(position["average_price"] + current_atr * settings.auto_atr_take_profit_multiple, 4))
    stop_price = record.get("stop_price")
    take_profit_price = record.get("take_profit_price")
    execution_price = price
    # If both target and stop fall inside one candle, the conservative stop assumption wins.
    if position and stop_price is not None and float(candles["Low"].iloc[-1]) <= float(stop_price):
        action, reason = "close", f"ATR protective stop reached at {float(stop_price):.2f}"
        execution_price = float(stop_price)
    elif position and take_profit_price is not None and float(candles["High"].iloc[-1]) >= float(take_profit_price):
        action, reason = "close", f"ATR take-profit target reached at {float(take_profit_price):.2f}"
        execution_price = float(take_profit_price)
    else:
        result = decide(candles, settings, symbol)
        if not result:
            publish("auto_trader", status="no_signal", symbol=symbol, bar=bar_id, price=price, message="No selected strategy fired on this completed bar")
            return
        action, reason = (result.action, result.reason) if hasattr(result, "action") else result

    quantity = position["quantity"] if action == "close" and position else settings.auto_max_quantity
    if action == "buy" and current_atr:
        risk_dollars = get_settings().starting_cash * get_settings().risk_percent / 100
        quantity = min(quantity, max(0.0001, risk_dollars / (current_atr * settings.auto_atr_stop_multiple)))
    payload = json.dumps({"source": "local_auto_trader", "symbol": symbol, "action": action, "price": execution_price, "quantity": quantity, "reason": reason})
    try:
        if action == "close" and position:
            broker.execute(symbol, action, execution_price, quantity, f"Auto: {settings.auto_mode}")
        else:
            risk.validate(symbol, action, price, quantity)
            broker.execute(symbol, action, execution_price, quantity, f"Auto: {settings.auto_mode}")
        if action == "buy" and current_atr:
            record["stop_price"] = round(execution_price - current_atr * settings.auto_atr_stop_multiple, 4)
            record["take_profit_price"] = round(execution_price + current_atr * settings.auto_atr_take_profit_multiple, 4)
        elif action == "close":
            record.pop("stop_price", None)
            record.pop("take_profit_price", None)
        database.record_alert(symbol, action, payload, f"executed: {reason}")
        publish("auto_trader", status="executed", symbol=symbol, bar=bar_id, price=execution_price, action=action, message=reason)
        logger.info("%s %s at %.2f — %s", action.upper(), symbol, execution_price, reason)
    except RiskRejected as exc:
        database.record_alert(symbol, action, payload, f"rejected: {exc}")
        publish("auto_trader", status="rejected", symbol=symbol, bar=bar_id, price=price, action=action, message=str(exc))
        logger.warning("%s %s rejected: %s", action, symbol, exc)


def main() -> None:
    auto = AutoTraderSettings()
    settings = get_settings()
    database = Database(settings.database_path)
    database.initialize()
    state_path = Path("database/auto_trader_state.json")
    state = load_state(state_path)
    broker, risk = PaperBroker(database), RiskManager(database, settings)
    logger.info("Auto trader: mode=%s symbols=%s", auto.auto_mode, ", ".join(auto.symbols))
    while True:
        for symbol in auto.symbols:
            try:
                process_symbol(symbol, auto, state, database, broker, risk)
                save_state(state_path, state)
            except Exception as exc:
                logger.exception("%s failed: %s", symbol, exc)
        time.sleep(max(auto.auto_poll_seconds, 30))


if __name__ == "__main__":
    main()
