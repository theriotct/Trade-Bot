"""Long-only OHLC strategy signals used by the local auto trader and backtester."""
from dataclasses import dataclass
from math import isnan

import numpy as np


@dataclass(frozen=True)
class Signal:
    strategy: str
    action: str  # buy or close
    reason: str


def rsi(closes, length: int = 14):
    delta = closes.diff()
    gain = delta.clip(lower=0).rolling(length).mean()
    loss = -delta.clip(upper=0).rolling(length).mean()
    return 100 - (100 / (1 + gain / loss.replace(0, np.nan)))


def atr(candles, length: int = 14) -> float | None:
    previous_close = candles["Close"].shift(1)
    true_range = np.maximum(candles["High"] - candles["Low"], np.maximum((candles["High"] - previous_close).abs(), (candles["Low"] - previous_close).abs()))
    value = true_range.rolling(length).mean().iloc[-1]
    return None if isnan(value) else float(value)


def evaluate(name: str, candles) -> Signal | None:
    """Return a signal only when a new, completed-bar event occurs."""
    if len(candles) < 205:
        return None
    close = candles["Close"]
    current, previous = float(close.iloc[-1]), float(close.iloc[-2])

    if name == "trend":
        fast, slow = close.rolling(50).mean(), close.rolling(200).mean()
        if fast.iloc[-2] <= slow.iloc[-2] and fast.iloc[-1] > slow.iloc[-1]:
            return Signal(name, "buy", "50 SMA crossed above 200 SMA")
        if fast.iloc[-2] >= slow.iloc[-2] and fast.iloc[-1] < slow.iloc[-1]:
            return Signal(name, "close", "50 SMA crossed below 200 SMA")

    elif name == "donchian":
        upper = candles["High"].rolling(20).max().shift(1)
        lower = candles["Low"].rolling(20).min().shift(1)
        if current > upper.iloc[-1]:
            return Signal(name, "buy", "closed above 20-bar Donchian high")
        if current < lower.iloc[-1]:
            return Signal(name, "close", "closed below 20-bar Donchian low")

    elif name == "macd":
        macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
        signal = macd.ewm(span=9, adjust=False).mean()
        if macd.iloc[-2] <= signal.iloc[-2] and macd.iloc[-1] > signal.iloc[-1]:
            return Signal(name, "buy", "MACD crossed above signal")
        if macd.iloc[-2] >= signal.iloc[-2] and macd.iloc[-1] < signal.iloc[-1]:
            return Signal(name, "close", "MACD crossed below signal")

    elif name == "bollinger":
        middle = close.rolling(20).mean()
        deviation = close.rolling(20).std()
        lower, upper = middle - 2 * deviation, middle + 2 * deviation
        if previous >= lower.iloc[-2] and current < lower.iloc[-1]:
            return Signal(name, "buy", "closed below lower Bollinger band")
        if previous <= upper.iloc[-2] and current > upper.iloc[-1]:
            return Signal(name, "close", "closed above upper Bollinger band")

    elif name == "rsi":
        values = rsi(close)
        if values.iloc[-2] >= 30 and values.iloc[-1] < 30:
            return Signal(name, "buy", "RSI crossed below 30")
        if values.iloc[-2] <= 70 and values.iloc[-1] > 70:
            return Signal(name, "close", "RSI crossed above 70")

    elif name == "volatility_breakout":
        opening_range_high = candles["High"].rolling(20).max().shift(1)
        opening_range_low = candles["Low"].rolling(20).min().shift(1)
        if current > opening_range_high.iloc[-1]:
            return Signal(name, "buy", "20-bar volatility breakout")
        if current < opening_range_low.iloc[-1]:
            return Signal(name, "close", "20-bar volatility breakdown")

    elif name == "regression":
        values = close.tail(30).to_numpy(dtype=float)
        slope = np.polyfit(np.arange(len(values)), values, 1)[0]
        prior = close.iloc[-31:-1].to_numpy(dtype=float)
        prior_slope = np.polyfit(np.arange(len(prior)), prior, 1)[0]
        if prior_slope <= 0 < slope:
            return Signal(name, "buy", "30-bar regression slope turned positive")
        if prior_slope >= 0 > slope:
            return Signal(name, "close", "30-bar regression slope turned negative")
    return None


def selected_signals(candles, names: list[str]) -> list[Signal]:
    return [signal for name in names if (signal := evaluate(name, candles))]


AVAILABLE = {"trend", "donchian", "macd", "bollinger", "rsi", "volatility_breakout", "regression"}
