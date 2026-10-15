"""Small, rate-aware Alpaca client. Trading URLs are deliberately paper-only."""
from __future__ import annotations

import threading
import time
from collections import deque
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import pandas as pd
import requests

from .config import Settings, get_settings

DATA_URL = "https://data.alpaca.markets"
PAPER_URL = "https://paper-api.alpaca.markets"


class AlpacaAPIError(RuntimeError):
    pass


class _RequestBudget:
    """Stay below the Basic plan's documented 200 historical requests/minute."""

    def __init__(self, limit: int = 180):
        self.limit = limit
        self.calls: deque[float] = deque()
        self.lock = threading.Lock()

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            while self.calls and now - self.calls[0] >= 60:
                self.calls.popleft()
            if len(self.calls) >= self.limit:
                time.sleep(max(0.05, 60 - (now - self.calls[0])))
                now = time.monotonic()
                while self.calls and now - self.calls[0] >= 60:
                    self.calls.popleft()
            self.calls.append(time.monotonic())


class AlpacaAPI:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        if not self.settings.alpaca_api_key or not self.settings.alpaca_secret_key:
            raise AlpacaAPIError("Alpaca API credentials are missing; set ALPACA_API_KEY and ALPACA_SECRET_KEY in .env")
        self.session = requests.Session()
        self.session.headers.update({
            "APCA-API-KEY-ID": self.settings.alpaca_api_key,
            "APCA-API-SECRET-KEY": self.settings.alpaca_secret_key,
            "Accept": "application/json",
            "User-Agent": "trade-bot-v2/1.0",
        })
        self._budget = _RequestBudget()

    def _request(self, method: str, url: str, **kwargs) -> dict | list:
        self._budget.wait()
        try:
            response = self.session.request(method, url, timeout=(5, 20), **kwargs)
            if response.status_code == 429:
                retry = response.headers.get("Retry-After", "60")
                raise AlpacaAPIError(f"Alpaca rate limit reached (HTTP 429); retry after {retry} seconds")
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            detail = ""
            if getattr(exc, "response", None) is not None:
                detail = f" (HTTP {exc.response.status_code}: {exc.response.text[:300]})"
            raise AlpacaAPIError(f"Alpaca request failed{detail}") from exc

    def bars(self, symbol: str, interval: str, period: str) -> pd.DataFrame:
        unit, amount = _timeframe(interval)
        start = datetime.now(UTC) - _period_delta(period)
        payload = self._request("GET", f"{DATA_URL}/v2/stocks/bars", params={
            "symbols": symbol.upper(), "timeframe": f"{amount}{unit}",
            "start": start.isoformat(), "end": datetime.now(UTC).isoformat(),
            "limit": 10000, "feed": self.settings.alpaca_data_feed,
            "adjustment": "all", "sort": "desc",
        })
        rows = payload.get("bars", {}).get(symbol.upper(), [])
        if not rows:
            return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
        frame = pd.DataFrame(rows).rename(columns={"t": "timestamp", "o": "Open", "h": "High", "l": "Low", "c": "Close", "v": "Volume"})
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        frame = frame.set_index("timestamp")[["Open", "High", "Low", "Close", "Volume"]]
        return frame.sort_index().astype(float)

    def news(self, symbols: list[str], limit: int = 50) -> list[dict]:
        if not symbols:
            return []
        payload = self._request("GET", f"{DATA_URL}/v1beta1/news", params={
            "symbols": ",".join(sorted(set(s.upper() for s in symbols))),
            "limit": min(max(1, limit), 50), "sort": "desc", "include_content": "false",
        })
        return payload.get("news", [])

    def submit_paper_order(self, symbol: str, side: str, quantity: float, client_order_id: str) -> dict:
        return self._request("POST", f"{PAPER_URL}/v2/orders", json={
            "symbol": symbol.upper(), "qty": str(quantity), "side": side,
            "type": "market", "time_in_force": "day", "client_order_id": client_order_id,
        })

    def order_by_client_id(self, client_order_id: str) -> dict:
        try:
            return self._request("GET", f"{PAPER_URL}/v2/orders:by_client_order_id", params={"client_order_id": client_order_id})
        except AlpacaAPIError as exc:
            if "HTTP 404" in str(exc):
                return {}
            raise

    def order(self, order_id: str) -> dict:
        result = self._request("GET", f"{PAPER_URL}/v2/orders/{order_id}")
        return result if isinstance(result, dict) else {}

    def positions(self) -> list[dict]:
        result = self._request("GET", f"{PAPER_URL}/v2/positions")
        return result if isinstance(result, list) else []

    def account(self) -> dict:
        result = self._request("GET", f"{PAPER_URL}/v2/account")
        return result if isinstance(result, dict) else {}


def _timeframe(interval: str) -> tuple[str, int]:
    normalized = interval.strip().lower()
    if normalized in {"60m", "1h"}:
        return "Hour", 1
    if normalized == "90m":
        raise ValueError("Alpaca supports minute bars up to 59 minutes; choose 30m or 1h")
    if normalized.endswith("m") and normalized[:-1].isdigit():
        return "Min", int(normalized[:-1])
    if normalized == "1d":
        return "Day", 1
    raise ValueError(f"Unsupported Alpaca candle interval: {interval}")


def _period_delta(period: str) -> timedelta:
    value = period.strip().lower()
    if value == "max":
        return timedelta(days=365 * 10)
    import re
    match = re.fullmatch(r"(\d+)(d|mo|y)", value)
    if not match:
        raise ValueError(f"Unsupported history period: {period}; use values such as 60d or 2y")
    amount, unit = int(match.group(1)), match.group(2)
    return timedelta(days=amount * {"d": 1, "mo": 30, "y": 365}[unit])


@lru_cache(maxsize=2)
def get_alpaca_api(api_key: str, secret_key: str) -> AlpacaAPI:
    return AlpacaAPI()
