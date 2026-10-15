import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity REAL NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL,
    pnl REAL NOT NULL DEFAULT 0,
    strategy TEXT NOT NULL,
    status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    symbol TEXT,
    action TEXT,
    raw_payload TEXT NOT NULL,
    processing_status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS positions (
    symbol TEXT PRIMARY KEY,
    quantity REAL NOT NULL,
    average_price REAL NOT NULL,
    current_price REAL NOT NULL,
    slot_count INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS daily_reports (
    report_date TEXT PRIMARY KEY,
    realized_pnl REAL NOT NULL,
    closed_trades INTEGER NOT NULL,
    wins INTEGER NOT NULL,
    strategy_lab_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS strategy_positions (
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    quantity REAL NOT NULL,
    average_price REAL NOT NULL,
    current_price REAL NOT NULL,
    stop_price REAL,
    take_profit_price REAL,
    entry_time TEXT NOT NULL,
    PRIMARY KEY (symbol, strategy)
);
CREATE TABLE IF NOT EXISTS strategy_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity REAL NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL,
    pnl REAL NOT NULL DEFAULT 0,
    reason TEXT NOT NULL,
    status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS strategy_sleeve_bars (
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    bar_id TEXT NOT NULL,
    PRIMARY KEY (symbol, strategy)
);
CREATE TABLE IF NOT EXISTS strategy_sleeve_blocks (
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    blocked_date TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (symbol, strategy, blocked_date)
);
CREATE TABLE IF NOT EXISTS news_articles (
    article_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    headline TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    published_at TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    sentiment_score INTEGER NOT NULL DEFAULT 0,
    processing_status TEXT NOT NULL DEFAULT 'new',
    PRIMARY KEY (article_id, symbol)
);
CREATE TABLE IF NOT EXISTS paper_order_fills (
    client_order_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    action TEXT NOT NULL,
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    realized_pnl REAL NOT NULL,
    recorded_at TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path

    def connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self) -> None:
        with self.connection() as conn:
            conn.executescript(SCHEMA)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(positions)")}
            if "slot_count" not in columns:
                conn.execute("ALTER TABLE positions ADD COLUMN slot_count INTEGER NOT NULL DEFAULT 1")

    def record_alert(self, symbol: str, action: str, raw_payload: str, status: str) -> None:
        with self.connection() as conn:
            conn.execute("INSERT INTO alerts (timestamp, symbol, action, raw_payload, processing_status) VALUES (?, ?, ?, ?, ?)", (datetime.now(UTC).isoformat(), symbol, action, raw_payload, status))

    def positions(self) -> list[dict]:
        with self.connection() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM positions ORDER BY symbol")]

    def position(self, symbol: str) -> dict | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM positions WHERE symbol = ?", (symbol,)).fetchone()
            return dict(row) if row else None

    def save_position(self, symbol: str, quantity: float, average_price: float, current_price: float, slot_count: int = 1) -> None:
        with self.connection() as conn:
            if quantity <= 0:
                conn.execute("DELETE FROM positions WHERE symbol = ?", (symbol,))
            else:
                conn.execute("INSERT INTO positions (symbol, quantity, average_price, current_price, slot_count) VALUES (?, ?, ?, ?, ?) ON CONFLICT(symbol) DO UPDATE SET quantity=excluded.quantity, average_price=excluded.average_price, current_price=excluded.current_price, slot_count=excluded.slot_count", (symbol, quantity, average_price, current_price, max(1, slot_count)))

    def record_trade(self, symbol: str, side: str, quantity: float, entry_price: float, exit_price: float | None, pnl: float, strategy: str, status: str) -> None:
        with self.connection() as conn:
            conn.execute("INSERT INTO trades (timestamp, symbol, side, quantity, entry_price, exit_price, pnl, strategy, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (datetime.now(UTC).isoformat(), symbol, side, quantity, entry_price, exit_price, pnl, strategy, status))

    def execute_paper_trade(self, symbol: str, action: str, price: float, quantity: float, strategy: str, client_order_id: str | None = None) -> tuple[float, float]:
        """Apply a paper fill and its ledger row atomically. Return P/L and filled quantity."""
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if client_order_id:
                prior = conn.execute("SELECT realized_pnl, quantity FROM paper_order_fills WHERE client_order_id = ?", (client_order_id,)).fetchone()
                if prior:
                    return float(prior["realized_pnl"]), float(prior["quantity"])
            row = conn.execute("SELECT * FROM positions WHERE symbol = ?", (symbol,)).fetchone()
            position = dict(row) if row else None
            if action == "buy":
                old_qty = position["quantity"] if position else 0.0
                old_avg = position["average_price"] if position else 0.0
                new_qty = old_qty + quantity
                new_avg = ((old_qty * old_avg) + (quantity * price)) / new_qty
                slots = (position["slot_count"] if position else 0) + 1
                conn.execute("INSERT INTO positions (symbol, quantity, average_price, current_price, slot_count) VALUES (?, ?, ?, ?, ?) ON CONFLICT(symbol) DO UPDATE SET quantity=excluded.quantity, average_price=excluded.average_price, current_price=excluded.current_price, slot_count=excluded.slot_count", (symbol, new_qty, new_avg, price, slots))
                pnl = 0.0
                side, entry_price, exit_price, status = "buy", price, None, "open"
            else:
                if not position:
                    raise ValueError(f"No open position exists for {symbol}")
                if quantity > position["quantity"]:
                    raise ValueError(f"Cannot sell {quantity:g}; only {position['quantity']:g} shares are open")
                fill_qty = position["quantity"] if action == "close" else quantity
                pnl = (price - position["average_price"]) * fill_qty
                remaining = position["quantity"] - fill_qty
                if remaining <= 1e-12:
                    conn.execute("DELETE FROM positions WHERE symbol = ?", (symbol,))
                else:
                    slots = max(1, position["slot_count"] - 1) if action == "close" else position["slot_count"]
                    conn.execute("UPDATE positions SET quantity = ?, current_price = ?, slot_count = ? WHERE symbol = ?", (remaining, price, slots, symbol))
                side, entry_price, exit_price, status = "sell", position["average_price"], price, "closed"
                quantity = fill_qty
            conn.execute("INSERT INTO trades (timestamp, symbol, side, quantity, entry_price, exit_price, pnl, strategy, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (datetime.now(UTC).isoformat(), symbol, side, quantity, entry_price, exit_price, pnl, strategy, status))
            if client_order_id:
                conn.execute("INSERT INTO paper_order_fills (client_order_id, symbol, action, quantity, price, realized_pnl, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (client_order_id, symbol, action, quantity, price, pnl, datetime.now(UTC).isoformat()))
            return pnl, quantity

    def recent_trades(self, limit: int = 100) -> list[dict]:
        with self.connection() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,))]

    def recent_alerts(self, limit: int = 25) -> list[dict]:
        with self.connection() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,))]

    def save_news_article(self, article: dict) -> bool:
        with self.connection() as conn:
            cursor = conn.execute("INSERT OR IGNORE INTO news_articles (article_id, symbol, headline, summary, url, source, published_at, observed_at, sentiment_score, processing_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (article["article_id"], article["symbol"], article["headline"], article.get("summary", ""), article.get("url", ""), article.get("source", ""), article["published_at"], article["observed_at"], article["sentiment_score"], article.get("processing_status", "new")))
            return cursor.rowcount == 1

    def recent_news(self, limit: int = 50) -> list[dict]:
        with self.connection() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM news_articles ORDER BY published_at DESC, article_id DESC LIMIT ?", (limit,))]

    def pending_news(self, symbol: str, through_time: str, limit: int = 30) -> list[dict]:
        with self.connection() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM news_articles WHERE symbol = ? AND processing_status = 'new' AND observed_at < ? AND published_at <= ? ORDER BY published_at ASC LIMIT ?", (symbol, through_time, through_time, limit))]

    def mark_news_article(self, article_id: str, symbol: str, status: str) -> None:
        with self.connection() as conn:
            conn.execute("UPDATE news_articles SET processing_status = ? WHERE article_id = ? AND symbol = ?", (status, article_id, symbol))

    def strategy_positions(self) -> list[dict]:
        with self.connection() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM strategy_positions ORDER BY symbol, strategy")]

    def strategy_position(self, symbol: str, strategy: str) -> dict | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM strategy_positions WHERE symbol = ? AND strategy = ?", (symbol, strategy)).fetchone()
            return dict(row) if row else None

    def save_strategy_position(self, symbol: str, strategy: str, quantity: float, average_price: float, current_price: float, stop_price: float | None, take_profit_price: float | None, entry_time: str) -> None:
        with self.connection() as conn:
            if quantity <= 0:
                conn.execute("DELETE FROM strategy_positions WHERE symbol = ? AND strategy = ?", (symbol, strategy))
            else:
                conn.execute("INSERT INTO strategy_positions (symbol, strategy, quantity, average_price, current_price, stop_price, take_profit_price, entry_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(symbol, strategy) DO UPDATE SET quantity=excluded.quantity, average_price=excluded.average_price, current_price=excluded.current_price, stop_price=excluded.stop_price, take_profit_price=excluded.take_profit_price, entry_time=excluded.entry_time", (symbol, strategy, quantity, average_price, current_price, stop_price, take_profit_price, entry_time))

    def record_strategy_trade(self, symbol: str, strategy: str, side: str, quantity: float, entry_price: float, exit_price: float | None, pnl: float, reason: str, status: str) -> None:
        with self.connection() as conn:
            conn.execute("INSERT INTO strategy_trades (timestamp, symbol, strategy, side, quantity, entry_price, exit_price, pnl, reason, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (datetime.now(UTC).isoformat(), symbol, strategy, side, quantity, entry_price, exit_price, pnl, reason, status))

    def recent_strategy_trades(self, limit: int = 100) -> list[dict]:
        with self.connection() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM strategy_trades ORDER BY id DESC LIMIT ?", (limit,))]

    def sleeve_bar(self, symbol: str, strategy: str) -> str | None:
        with self.connection() as conn:
            row = conn.execute("SELECT bar_id FROM strategy_sleeve_bars WHERE symbol = ? AND strategy = ?", (symbol, strategy)).fetchone()
            return row["bar_id"] if row else None

    def save_sleeve_bar(self, symbol: str, strategy: str, bar_id: str) -> None:
        with self.connection() as conn:
            conn.execute("INSERT INTO strategy_sleeve_bars (symbol, strategy, bar_id) VALUES (?, ?, ?) ON CONFLICT(symbol, strategy) DO UPDATE SET bar_id=excluded.bar_id", (symbol, strategy, bar_id))

    def sleeve_blocked(self, symbol: str, strategy: str, trading_date: str) -> bool:
        with self.connection() as conn:
            return conn.execute("SELECT 1 FROM strategy_sleeve_blocks WHERE symbol = ? AND strategy = ? AND blocked_date = ?", (symbol, strategy, trading_date)).fetchone() is not None

    def block_sleeve(self, symbol: str, strategy: str, trading_date: str, reason: str) -> None:
        with self.connection() as conn:
            conn.execute("INSERT OR IGNORE INTO strategy_sleeve_blocks (symbol, strategy, blocked_date, reason, created_at) VALUES (?, ?, ?, ?, ?)", (symbol, strategy, trading_date, reason, datetime.now(UTC).isoformat()))

    def sleeve_recent_realized_pnl(self, symbol: str, strategy: str, minutes: int) -> float:
        cutoff = (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat()
        with self.connection() as conn:
            row = conn.execute("SELECT COALESCE(SUM(pnl), 0) AS total FROM strategy_trades WHERE symbol = ? AND strategy = ? AND status = 'closed' AND timestamp >= ?", (symbol, strategy, cutoff)).fetchone()
            return float(row["total"])

    def strategy_open_count(self) -> int:
        with self.connection() as conn:
            return int(conn.execute("SELECT COUNT(*) AS total FROM strategy_positions").fetchone()["total"])

    def strategy_realized_pnl_today(self) -> float:
        with self.connection() as conn:
            row = conn.execute("SELECT COALESCE(SUM(pnl), 0) AS total FROM strategy_trades WHERE status = 'closed' AND date(timestamp) = date('now')").fetchone()
            return float(row["total"])

    def save_daily_report(self, report_date: str, realized_pnl: float, closed_trades: int, wins: int, strategy_lab: dict) -> None:
        import json
        with self.connection() as conn:
            conn.execute("INSERT INTO daily_reports (report_date, realized_pnl, closed_trades, wins, strategy_lab_json) VALUES (?, ?, ?, ?, ?) ON CONFLICT(report_date) DO UPDATE SET realized_pnl=excluded.realized_pnl, closed_trades=excluded.closed_trades, wins=excluded.wins, strategy_lab_json=excluded.strategy_lab_json", (report_date, realized_pnl, closed_trades, wins, json.dumps(strategy_lab)))

    def daily_reports(self) -> list[dict]:
        import json
        with self.connection() as conn:
            records = [dict(row) for row in conn.execute("SELECT * FROM daily_reports ORDER BY report_date DESC")]
        for record in records:
            record["strategy_lab"] = json.loads(record.pop("strategy_lab_json"))
        return records

    def historical_trade_summaries(self) -> list[dict]:
        with self.connection() as conn:
            return [dict(row) for row in conn.execute("SELECT date(timestamp) AS report_date, COALESCE(SUM(pnl), 0) AS realized_pnl, COUNT(*) AS closed_trades, COALESCE(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), 0) AS wins FROM trades WHERE status = 'closed' GROUP BY date(timestamp) ORDER BY report_date DESC")]

    def daily_trade_summary(self, report_date: str) -> dict:
        with self.connection() as conn:
            row = conn.execute("SELECT COALESCE(SUM(pnl), 0) AS realized_pnl, COUNT(*) AS closed_trades, COALESCE(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), 0) AS wins FROM trades WHERE status = 'closed' AND date(timestamp) = ?", (report_date,)).fetchone()
            return dict(row)

    def strategy_daily_trade_summary(self, report_date: str) -> dict:
        """Summary for independent all-strategy paper sleeves."""
        with self.connection() as conn:
            row = conn.execute("SELECT COALESCE(SUM(pnl), 0) AS realized_pnl, COUNT(*) AS closed_trades, COALESCE(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), 0) AS wins FROM strategy_trades WHERE status = 'closed' AND date(timestamp) = ?", (report_date,)).fetchone()
            return dict(row)

    def realized_pnl_today(self) -> float:
        with self.connection() as conn:
            row = conn.execute("SELECT COALESCE(SUM(pnl), 0) AS total FROM trades WHERE date(timestamp) = date('now')").fetchone()
            return float(row["total"])
