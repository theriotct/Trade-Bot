"""Market-data adapters with a common OHLCV DataFrame shape."""
import yfinance as yf

from .alpaca_api import get_alpaca_api
from .config import get_settings


def fetch_candles(symbol: str, period: str, interval: str):
    settings = get_settings()
    if settings.market_data_provider.lower() == "alpaca":
        client = get_alpaca_api(settings.alpaca_api_key, settings.alpaca_secret_key)
        return client.bars(symbol, interval, period)
    if settings.market_data_provider.lower() != "yfinance":
        raise ValueError("MARKET_DATA_PROVIDER must be yfinance or alpaca")
    return yf.download(symbol, period=period, interval=interval, auto_adjust=True, progress=False, multi_level_index=False, timeout=15)
