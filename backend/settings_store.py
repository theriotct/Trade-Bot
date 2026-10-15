"""Whitelisted runtime configuration stored in the local .env file."""
import re
from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator

from .auto_trader import AutoTraderSettings
from .backtest import BacktestSettings
from .config import Settings, get_settings


ENV_PATH = Path(".env")


class DashboardSettings(BaseModel):
    database_path: str = Field(min_length=1)
    starting_cash: float = Field(gt=0)
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    alpaca_key_configured: bool = False
    alpaca_secret_configured: bool = False
    clear_alpaca_credentials: bool = False
    market_data_provider: str = Field(pattern=r"^(yfinance|alpaca)$")
    alpaca_data_feed: str = Field(pattern=r"^iex$")
    execution_mode: str = Field(pattern=r"^(local|alpaca_paper)$")
    news_provider: str = Field(pattern=r"^(alpaca|disabled)$")
    news_enabled: bool
    news_min_sentiment: int = Field(ge=1, le=20)
    news_hold_bars: int = Field(ge=1, le=100)
    news_max_age_minutes: int = Field(ge=1, le=1440)
    symbol_whitelist: str = Field(min_length=1)
    auto_symbols: str = Field(min_length=1)
    auto_interval: str = Field(pattern=r"^(1m|2m|5m|15m|30m|60m|90m|1h|1d)$")
    auto_period: str = Field(pattern=r"^(max|[1-9][0-9]*(d|mo|y))$")
    auto_poll_seconds: int = Field(ge=30, le=86400)
    auto_mode: str = Field(pattern=r"^(single|consensus|all_strategies)$")
    auto_strategy: str = Field(pattern=r"^(trend|donchian|macd|bollinger|rsi|volatility_breakout|regression|per_symbol)$")
    auto_consensus_min: int = Field(ge=1, le=7)
    auto_max_quantity: float = Field(gt=0)
    auto_atr_stop_multiple: float = Field(gt=0, le=20)
    auto_atr_take_profit_multiple: float = Field(gt=0, le=20)
    auto_symbol_strategies: str = ""
    strategy_lab_enabled: bool = True
    auto_all_strategies_max_open: int = Field(ge=1, le=100)
    auto_strategy_loss_limit: float = Field(gt=0)
    auto_strategy_loss_window_minutes: int = Field(ge=5, le=1440)
    strategy_lab_extra_symbols: str = ""
    max_open_positions: int = Field(ge=1, le=50)
    max_daily_loss: float = Field(gt=0)
    max_position_value: float = Field(gt=0)
    risk_percent: float = Field(gt=0, le=10)
    auto_strategies: str = Field(min_length=1)
    backtest_symbol: str = Field(min_length=1)
    backtest_interval: str = Field(pattern=r"^(1m|2m|5m|15m|30m|60m|90m|1h|1d)$")
    backtest_period: str = Field(pattern=r"^(max|[1-9][0-9]*(d|mo|y))$")
    backtest_strategies: str = Field(min_length=1)
    backtest_starting_cash: float = Field(gt=0)
    backtest_cost_bps: float = Field(ge=0, le=1000)
    backtest_slippage_bps: float = Field(ge=0, le=1000)

    @model_validator(mode="after")
    def validate_slot_capacity(self):
        whitelist_count = len({symbol.strip() for symbol in self.symbol_whitelist.split(",") if symbol.strip()})
        if self.max_open_positions < whitelist_count:
            raise ValueError("Maximum entry slots must be at least the number of whitelist symbols")
        return self

    @field_validator("symbol_whitelist", "auto_symbols", "strategy_lab_extra_symbols", "backtest_symbol")
    @classmethod
    def uppercase_symbols(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("auto_strategies", "backtest_strategies")
    @classmethod
    def validate_strategy_list(cls, value: str) -> str:
        from .strategies import AVAILABLE
        selected = [item.strip().lower() for item in value.split(",") if item.strip()]
        if not selected or set(selected) - AVAILABLE:
            raise ValueError("Choose one or more supported strategies, separated by commas")
        return ",".join(dict.fromkeys(selected))


def current() -> DashboardSettings:
    get_settings.cache_clear()
    core, auto, backtest = Settings(), AutoTraderSettings(), BacktestSettings()
    return DashboardSettings(
        database_path=str(core.database_path),
        starting_cash=core.starting_cash,
        # Credential fields are write-only: never send stored values to the browser.
        alpaca_api_key="",
        alpaca_secret_key="",
        alpaca_key_configured=bool(core.alpaca_api_key),
        alpaca_secret_configured=bool(core.alpaca_secret_key),
        clear_alpaca_credentials=False,
        market_data_provider=core.market_data_provider,
        alpaca_data_feed=core.alpaca_data_feed,
        execution_mode=core.execution_mode,
        news_provider=core.news_provider,
        news_enabled=core.news_enabled,
        news_min_sentiment=core.news_min_sentiment,
        news_hold_bars=core.news_hold_bars,
        news_max_age_minutes=core.news_max_age_minutes,
        symbol_whitelist=core.symbol_whitelist,
        auto_symbols=auto.auto_symbols,
        auto_interval=auto.auto_interval,
        auto_period=auto.auto_period,
        auto_poll_seconds=auto.auto_poll_seconds,
        auto_mode=auto.auto_mode,
        auto_strategy=auto.auto_strategy,
        auto_consensus_min=auto.auto_consensus_min,
        auto_max_quantity=auto.auto_max_quantity,
        auto_atr_stop_multiple=auto.auto_atr_stop_multiple,
        auto_atr_take_profit_multiple=auto.auto_atr_take_profit_multiple,
        auto_symbol_strategies=auto.auto_symbol_strategies,
        strategy_lab_enabled=auto.strategy_lab_enabled,
        auto_all_strategies_max_open=auto.auto_all_strategies_max_open,
        auto_strategy_loss_limit=auto.auto_strategy_loss_limit,
        auto_strategy_loss_window_minutes=auto.auto_strategy_loss_window_minutes,
        strategy_lab_extra_symbols=auto.strategy_lab_extra_symbols,
        max_open_positions=core.max_open_positions,
        max_daily_loss=core.max_daily_loss,
        max_position_value=core.max_position_value,
        risk_percent=core.risk_percent,
        auto_strategies=auto.auto_strategies,
        backtest_symbol=backtest.backtest_symbol,
        backtest_interval=backtest.backtest_interval,
        backtest_period=backtest.backtest_period,
        backtest_strategies=backtest.backtest_strategies,
        backtest_starting_cash=backtest.backtest_starting_cash,
        backtest_cost_bps=backtest.backtest_cost_bps,
        backtest_slippage_bps=backtest.backtest_slippage_bps,
    )


def save(settings: DashboardSettings) -> DashboardSettings:
    data = settings.model_dump()
    clear_credentials = data.pop("clear_alpaca_credentials")
    api_key = data.pop("alpaca_api_key").strip()
    secret_key = data.pop("alpaca_secret_key").strip()
    data.pop("alpaca_key_configured")
    data.pop("alpaca_secret_configured")
    values = {key.upper(): str(value) for key, value in data.items()}
    if clear_credentials:
        values["ALPACA_API_KEY"] = ""
        values["ALPACA_SECRET_KEY"] = ""
    else:
        if api_key:
            values["ALPACA_API_KEY"] = api_key
        if secret_key:
            values["ALPACA_SECRET_KEY"] = secret_key
    text = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.exists() else ""
    for key, value in values.items():
        pattern = rf"(?m)^{re.escape(key)}=.*$"
        replacement = f"{key}={value}"
        text = re.sub(pattern, replacement, text) if re.search(pattern, text) else text + f"\n{replacement}\n"
    temporary = ENV_PATH.with_name(f"{ENV_PATH.name}.tmp")
    temporary.write_text(text.strip() + "\n", encoding="utf-8")
    temporary.replace(ENV_PATH)
    get_settings.cache_clear()
    return current()
