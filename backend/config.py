from functools import lru_cache
from pathlib import Path

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

    @property
    def allowed_symbols(self) -> set[str]:
        return {symbol.strip().upper() for symbol in self.symbol_whitelist.split(",") if symbol.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()

