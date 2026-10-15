"""Market-data adapters with a common OHLCV DataFrame shape."""
import yfinance as yf

from .alpaca_api import get_alpaca_api
from .config import get_settings


def normalize_candles(frame, symbol: str):
    """Return one unambiguous column for each OHLCV field."""
    if frame is None or frame.empty:
        return frame

    wanted = {symbol.upper(), symbol.replace(".", "-").upper()}
    if getattr(frame.columns, "nlevels", 1) > 1:
        for level in range(frame.columns.nlevels):
            values = list(frame.columns.get_level_values(level))
            match = next((value for value in values if str(value).upper() in wanted), None)
            if match is not None:
                frame = frame.xs(match, axis=1, level=level, drop_level=True)
                break

    ohlcv = {"open": "Open", "high": "High", "low": "Low", "close": "Close",
             "adj close": "Adj Close", "volume": "Volume"}
    columns = []
    for column in frame.columns:
        parts = column if isinstance(column, tuple) else (column,)
        field = next((ohlcv.get(str(value).strip().lower()) for value in parts
                      if str(value).strip().lower() in ohlcv), None)
        columns.append(field or str(parts[-1]))
    frame = frame.copy()
    frame.columns = columns
    # yfinance can return repeated field names (including a duplicate Close),
    # which makes frame["Close"] a DataFrame and breaks scalar price reads.
    frame = frame.loc[:, ~frame.columns.duplicated(keep="first")]
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
