from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_path: Path = Path("database/trading.db")
    starting_cash: float = 100_000
    risk_percent: float = 1
    max_open_positions: int = 3
    max_daily_loss: float = 250
    max_position_value: float = 10_000
    symbol_whitelist: str = "AAPL,MSFT,SPY,QQQ,TSLA,NVDA"
    market_data_provider: str = "yfinance"
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    alpaca_data_feed: str = "iex"
    execution_mode: str = "local"
    news_provider: str = "alpaca"
    news_enabled: bool = False
    news_min_sentiment: int = Field(default=2, ge=1, le=20)
    news_hold_bars: int = Field(default=6, ge=1, le=100)
    news_max_age_minutes: int = Field(default=30, ge=1, le=1440)

    @field_validator("market_data_provider")
    @classmethod
    def validate_market_data_provider(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"yfinance", "alpaca"}:
            raise ValueError("MARKET_DATA_PROVIDER must be yfinance or alpaca")
        return normalized

    @field_validator("execution_mode")
    @classmethod
    def validate_execution_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"local", "alpaca_paper"}:
            raise ValueError("EXECUTION_MODE must be local or alpaca_paper")
        return normalized

    @field_validator("alpaca_data_feed")
    @classmethod
    def validate_alpaca_data_feed(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized != "iex":
            raise ValueError("Basic-plan configuration uses ALPACA_DATA_FEED=iex")
        return normalized

    @field_validator("news_provider")
    @classmethod
    def validate_news_provider(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"alpaca", "disabled"}:
            raise ValueError("NEWS_PROVIDER must be alpaca or disabled")
        return normalized

    @property
    def allowed_symbols(self) -> set[str]:
        return {symbol.strip().upper() for symbol in self.symbol_whitelist.split(",") if symbol.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()

