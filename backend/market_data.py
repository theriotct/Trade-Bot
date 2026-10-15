"""Market-data adapters with a common OHLCV DataFrame shape."""
import yfinance as yf

from .alpaca_api import get_alpaca_api
from .config import get_settings


def normalize_candles(frame, symbol: str):
    """Flatten yfinance's optional ticker level into standard OHLCV columns."""
    if frame is None or frame.empty or getattr(frame.columns, "nlevels", 1) == 1:
        return frame

    wanted = {symbol.upper(), symbol.replace(".", "-").upper()}
    for level in range(frame.columns.nlevels):
        labels = {str(value).upper() for value in frame.columns.get_level_values(level)}
        match = next((value for value in wanted if value in labels), None)
        if match is not None:
            actual = next(value for value in frame.columns.get_level_values(level) if str(value).upper() == match)
            frame = frame.xs(actual, axis=1, level=level, drop_level=True)
            break

    if getattr(frame.columns, "nlevels", 1) > 1:
        ohlcv = {"open", "high", "low", "close", "adj close", "volume"}
        frame.columns = [
            next((str(value) for value in column if str(value).lower() in ohlcv), str(column[-1]))
            for column in frame.columns
        ]
    return frame


def fetch_candles(symbol: str, period: str, interval: str):
    settings = get_settings()
    if settings.market_data_provider.lower() == "alpaca":
        client = get_alpaca_api(settings.alpaca_api_key, settings.alpaca_secret_key)
        return client.bars(symbol, interval, period)
    if settings.market_data_provider.lower() != "yfinance":
        raise ValueError("MARKET_DATA_PROVIDER must be yfinance or alpaca")
    frame = yf.download(symbol, period=period, interval=interval, auto_adjust=True, progress=False, multi_level_index=False, timeout=15)
    return normalize_candles(frame, symbol)
