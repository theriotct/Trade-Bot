"""Configurable local paper trader for multiple OHLC strategy techniques."""
import json
import hashlib
import logging
import time
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from .alpaca_api import AlpacaAPIError, get_alpaca_api
from .broker import AlpacaPaperBroker, PaperBroker
from .config import get_settings
from .database import Database
from .market_data import fetch_candles
from .risk import RiskManager, RiskRejected
from .runtime_status import publish
from .strategies import AVAILABLE, atr, selected_signals
from .strategy_lab import StrategyLab
from .news_lab import NewsLab

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


class AutoTraderSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    auto_symbols: str = "SPY"
    auto_interval: str = "1d"
    auto_period: str = "2y"
    auto_poll_seconds: int = 300
    auto_mode: str = "single"  # single, consensus, or all_strategies
    auto_strategy: str = "trend"
    auto_strategies: str = "trend,donchian,macd,bollinger,rsi,volatility_breakout,regression"
    auto_consensus_min: int = 2
    auto_max_quantity: float = 1
    auto_atr_stop_multiple: float = 2
    auto_atr_take_profit_multiple: float = 2
    auto_symbol_strategies: str = ""
    strategy_lab_enabled: bool = True
    auto_all_strategies_max_open: int = 42
    auto_strategy_loss_limit: float = 3
    auto_strategy_loss_window_minutes: int = 180
    strategy_lab_extra_symbols: str = ""

    @property
    def symbols(self) -> list[str]:
        values = [value.strip().upper() for value in self.auto_symbols.split(",") if value.strip()]
        return sorted(get_settings().allowed_symbols) if values == ["*"] else values

    @property
    def lab_symbols(self) -> list[str]:
        """The live symbols plus optional lab-only symbols that can never place main-account trades."""
        extras = [value.strip().upper() for value in self.strategy_lab_extra_symbols.split(",") if value.strip()]
        return list(dict.fromkeys([*self.symbols, *extras]))

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


def process_lab_symbol(symbol: str, settings: AutoTraderSettings, lab: StrategyLab) -> None:
    """Scan a lab-only symbol without touching the paper account or risk ledger."""
    candles = fetch_candles(symbol, settings.auto_period, settings.auto_interval).iloc[:-1]
    if len(candles) < 205:
        logger.warning("%s: need at least 205 completed bars for Strategy Lab", symbol)
        return
    lab.process(symbol, candles, settings)


def process_symbol(symbol: str, settings: AutoTraderSettings, state: dict[str, object], database: Database, broker: PaperBroker, risk: RiskManager, lab: StrategyLab | None = None, news_lab: NewsLab | None = None) -> None:
    candles = fetch_candles(symbol, settings.auto_period, settings.auto_interval).iloc[:-1]
    if len(candles) < 205:
        logger.warning("%s: need at least 205 completed bars", symbol)
        return
    bar_id, price = str(candles.index[-1]), float(candles["Close"].iloc[-1])
    if lab:
        lab.process(symbol, candles, settings)
    if news_lab:
        news_lab.process(symbol, candles, get_settings())
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
    previous_bar = record.get("bar")
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
    client_order_id = hashlib.sha256(f"{symbol}|{bar_id}|{action}|{settings.auto_mode}".encode()).hexdigest()[:32]
    try:
        if action == "close" and position:
            execution = broker.execute(symbol, action, execution_price, quantity, f"Auto: {settings.auto_mode}", client_order_id)
        else:
            risk.validate(symbol, action, price, quantity)
            execution = broker.execute(symbol, action, execution_price, quantity, f"Auto: {settings.auto_mode}", client_order_id)
        if action == "buy" and current_atr:
            record["stop_price"] = round(execution.price - current_atr * settings.auto_atr_stop_multiple, 4)
            record["take_profit_price"] = round(execution.price + current_atr * settings.auto_atr_take_profit_multiple, 4)
        elif action == "close":
            record.pop("stop_price", None)
            record.pop("take_profit_price", None)
        database.record_alert(symbol, action, payload, f"executed: {reason}; fill {execution.price:.4f} x {execution.quantity:g} ({execution.status})")
        publish("auto_trader", status="executed", symbol=symbol, bar=bar_id, price=execution.price, action=action, message=reason)
        logger.info("%s %s at %.4f — %s", action.upper(), symbol, execution.price, reason)
    except RiskRejected as exc:
        database.record_alert(symbol, action, payload, f"rejected: {exc}")
        publish("auto_trader", status="rejected", symbol=symbol, bar=bar_id, price=price, action=action, message=str(exc))
        logger.warning("%s %s rejected: %s", action, symbol, exc)

    except AlpacaAPIError as exc:
        record["bar"] = previous_bar
        database.record_alert(symbol, action, payload, f"pending: {exc}")
        publish("auto_trader", status="broker_pending", symbol=symbol, bar=bar_id, price=price, action=action, message=str(exc))
        logger.warning("%s %s awaits Alpaca paper fill: %s", symbol, action, exc)


def main() -> None:
    auto = AutoTraderSettings()
    settings = get_settings()
    database = Database(settings.database_path)
    database.initialize()
    state_path = Path("database/auto_trader_state.json")
    state = load_state(state_path)
    broker: PaperBroker = PaperBroker(database)
    if settings.execution_mode == "alpaca_paper":
        broker = AlpacaPaperBroker(database, get_alpaca_api(settings.alpaca_api_key, settings.alpaca_secret_key))
        broker.sync_positions()
    risk = RiskManager(database, settings)
    news_lab = NewsLab(database)
    logger.info("Auto trader: mode=%s symbols=%s", auto.auto_mode, ", ".join(auto.symbols))
    while True:
        for symbol in auto.symbols:
            try:
                process_symbol(symbol, auto, state, database, broker, risk, news_lab=news_lab)
                save_state(state_path, state)
            except Exception as exc:
                logger.exception("%s failed: %s", symbol, exc)
        time.sleep(max(auto.auto_poll_seconds, 30))


if __name__ == "__main__":
    main()
