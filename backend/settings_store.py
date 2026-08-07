"""Whitelisted runtime configuration stored in the local .env file."""
import re
from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator

from .auto_trader import AutoTraderSettings
from .config import Settings, get_settings


ENV_PATH = Path(".env")


class DashboardSettings(BaseModel):
    symbol_whitelist: str = Field(min_length=1)
    auto_symbols: str = Field(min_length=1)
    auto_interval: str = Field(pattern=r"^(1m|2m|5m|15m|30m|60m|90m|1h|1d)$")
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

    @model_validator(mode="after")
    def validate_slot_capacity(self):
        whitelist_count = len({symbol.strip() for symbol in self.symbol_whitelist.split(",") if symbol.strip()})
        if self.max_open_positions < whitelist_count:
            raise ValueError("Maximum entry slots must be at least the number of whitelist symbols")
        return self

    @field_validator("symbol_whitelist", "auto_symbols", "strategy_lab_extra_symbols")
    @classmethod
    def uppercase_symbols(cls, value: str) -> str:
        return value.strip().upper()


def current() -> DashboardSettings:
    get_settings.cache_clear()
    core, auto = Settings(), AutoTraderSettings()
    return DashboardSettings(
        symbol_whitelist=core.symbol_whitelist,
        auto_symbols=auto.auto_symbols,
        auto_interval=auto.auto_interval,
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
    )


def save(settings: DashboardSettings) -> DashboardSettings:
    values = {key.upper(): str(value) for key, value in settings.model_dump().items()}
    text = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.exists() else ""
    for key, value in values.items():
        pattern = rf"(?m)^{re.escape(key)}=.*$"
        replacement = f"{key}={value}"
        text = re.sub(pattern, replacement, text) if re.search(pattern, text) else text + f"\n{replacement}\n"
    ENV_PATH.write_text(text.strip() + "\n", encoding="utf-8")
    get_settings.cache_clear()
    return current()
