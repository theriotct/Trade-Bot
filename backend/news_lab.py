"""Headline sentiment experiment kept separate from the price-strategy portfolios."""
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .alpaca_api import get_alpaca_api

POSITIVE = {"beat", "beats", "approval", "approved", "upgrade", "upgraded", "growth", "record", "surge", "surges", "profit", "profits", "strong", "partnership", "launch", "wins", "award", "raises", "raised", "buyback"}
NEGATIVE = {"miss", "misses", "investigation", "lawsuit", "downgrade", "downgraded", "decline", "declines", "loss", "losses", "weak", "warning", "warns", "cuts", "cut", "recall", "fraud", "breach", "default", "bankruptcy", "layoffs"}


def sentiment_score(text: str) -> int:
    words = set(re.findall(r"[a-z]+", text.lower()))
    return len(words & POSITIVE) - len(words & NEGATIVE)


class NewsLab:
    def __init__(self, database, path: Path = Path("database/news_lab.json")):
        self.database, self.path = database, path
        try:
            self.state = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            self.state = {"positions": {}, "trades": [], "last_bar": {}}

    def ingest(self, symbols: list[str]) -> int:
        """Fetch one batched news page and store deduplicated per-symbol headlines."""
        from .config import get_settings
        settings = get_settings()
        if not settings.news_enabled or settings.news_provider != "alpaca" or not symbols:
            return 0
        client = get_alpaca_api(settings.alpaca_api_key, settings.alpaca_secret_key)
        now = datetime.now(UTC).isoformat()
        cutoff = datetime.now(UTC) - timedelta(minutes=settings.news_max_age_minutes)
        inserted = 0
        wanted = set(symbols)
        for item in client.news(symbols):
            published = _iso_utc(item.get("created_at") or item.get("updated_at") or now)
            is_recent = datetime.fromisoformat(published).astimezone(UTC) >= cutoff
            title = str(item.get("headline") or "").strip()
            summary = str(item.get("summary") or "").strip()
            if not title:
                continue
            score = sentiment_score(title + " " + summary)
            source = item.get("source") or item.get("author") or "Alpaca News"
            symbols = item.get("symbols") or []
            for symbol in sorted(wanted.intersection(str(s).upper() for s in symbols)):
                inserted += self.database.save_news_article({
                    "article_id": str(item.get("id") or item.get("url") or title),
                    "symbol": symbol, "headline": title, "summary": summary,
                    "url": str(item.get("url") or ""), "source": str(source),
                    "published_at": published, "observed_at": now,
                    "sentiment_score": score,
                    "processing_status": "new" if is_recent else "stale",
                })
        return inserted

    def process(self, symbol: str, candles, settings) -> None:
        """Paper-test positive headlines; close on strongly negative news or a time exit."""
        bar = candles.index[-1]
        bar_time = bar.to_pydatetime().astimezone(UTC).isoformat() if hasattr(bar, "to_pydatetime") else str(bar)
        bar_id, price = str(bar), float(candles["Close"].iloc[-1])
        if self.state["last_bar"].get(symbol) == bar_id:
            return
        self.state["last_bar"][symbol] = bar_id
        position = self.state["positions"].get(symbol)
        action_taken = False
        for article in self.database.pending_news(symbol, bar_time):
            if action_taken:
                self.database.mark_news_article(article["article_id"], symbol, "observed")
                continue
            score = int(article["sentiment_score"])
            threshold = settings.news_min_sentiment
            if position and score <= -threshold:
                self._close(symbol, position, price, bar_time, f"Negative headline signal ({score})")
                position = None
                action_taken = True
                self.database.mark_news_article(article["article_id"], symbol, "exit_signal")
            elif not position and score >= threshold:
                position = {"quantity": 1.0, "average_price": price, "current_price": price, "bars_held": 0, "entry_time": bar_time, "article_id": article["article_id"], "headline": article["headline"], "last_bar": bar_id}
                self.state["positions"][symbol] = position
                action_taken = True
                self.database.mark_news_article(article["article_id"], symbol, "entry_signal")
            else:
                self.database.mark_news_article(article["article_id"], symbol, "observed")

        if position:
            position["current_price"] = price
            if position.get("last_bar") != bar_id:
                position["bars_held"] += 1
                position["last_bar"] = bar_id
            if position["bars_held"] >= settings.news_hold_bars:
                self._close(symbol, position, price, bar_time, "News Lab time exit")
        self._save()

    def _close(self, symbol: str, position: dict, price: float, timestamp: str, reason: str) -> None:
        pnl = (price - position["average_price"]) * position["quantity"]
        self.state["trades"].append({
            "symbol": symbol, "quantity": position["quantity"],
            "entry_price": position["average_price"], "exit_price": price,
            "pnl": round(pnl, 4), "entry_time": position["entry_time"],
            "exit_time": timestamp, "headline": position.get("headline", ""),
            "reason": reason,
        })
        self.state["positions"].pop(symbol, None)

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.state), encoding="utf-8")
        temporary.replace(self.path)

    def summary(self) -> dict:
        trades = self.state.get("trades", [])
        realized = sum(float(row["pnl"]) for row in trades)
        unrealized = sum((float(item["current_price"]) - float(item["average_price"])) * float(item["quantity"]) for item in self.state.get("positions", {}).values())
        wins = sum(float(row["pnl"]) > 0 for row in trades)
        return {
            "experiment": "headline_keyword_sentiment",
            "description": "Experimental keyword sentiment; paper-only, long-only, one share per symbol, time exit.",
            "realized_pnl": round(realized, 2), "unrealized_pnl": round(unrealized, 2),
            "total_pnl": round(realized + unrealized, 2), "closed_trades": len(trades),
            "win_rate": round(wins / len(trades) * 100, 1) if trades else 0,
            "open_positions": len(self.state.get("positions", {})),
            "positions": self.state.get("positions", {}), "recent_trades": list(reversed(trades[-25:])),
        }


def _iso_utc(value: str) -> str:
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized).astimezone(UTC).isoformat()
