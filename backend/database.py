import sqlite3
from datetime import UTC, datetime
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
            conn.execute(
                "INSERT INTO alerts (timestamp, symbol, action, raw_payload, processing_status) VALUES (?, ?, ?, ?, ?)",
                (datetime.now(UTC).isoformat(), symbol, action, raw_payload, status),
            )

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
                conn.execute(
                    "INSERT INTO positions (symbol, quantity, average_price, current_price, slot_count) VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(symbol) DO UPDATE SET quantity=excluded.quantity, average_price=excluded.average_price, current_price=excluded.current_price, slot_count=excluded.slot_count",
                    (symbol, quantity, average_price, current_price, max(1, slot_count)),
                )

    def record_trade(self, symbol: str, side: str, quantity: float, entry_price: float, exit_price: float | None, pnl: float, strategy: str, status: str) -> None:
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO trades (timestamp, symbol, side, quantity, entry_price, exit_price, pnl, strategy, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (datetime.now(UTC).isoformat(), symbol, side, quantity, entry_price, exit_price, pnl, strategy, status),
            )

    def recent_trades(self, limit: int = 100) -> list[dict]:
        with self.connection() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,))]

    def recent_alerts(self, limit: int = 25) -> list[dict]:
        with self.connection() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,))]

    def save_daily_report(self, report_date: str, realized_pnl: float, closed_trades: int, wins: int, strategy_lab: dict) -> None:
        import json
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO daily_reports (report_date, realized_pnl, closed_trades, wins, strategy_lab_json) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(report_date) DO UPDATE SET realized_pnl=excluded.realized_pnl, closed_trades=excluded.closed_trades, wins=excluded.wins, strategy_lab_json=excluded.strategy_lab_json",
                (report_date, realized_pnl, closed_trades, wins, json.dumps(strategy_lab)),
            )

    def daily_reports(self) -> list[dict]:
        import json
        with self.connection() as conn:
            records = [dict(row) for row in conn.execute("SELECT * FROM daily_reports ORDER BY report_date DESC")]
        for record in records:
            record["strategy_lab"] = json.loads(record.pop("strategy_lab_json"))
        return records

    def historical_trade_summaries(self) -> list[dict]:
        with self.connection() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT date(timestamp) AS report_date, COALESCE(SUM(pnl), 0) AS realized_pnl, COUNT(*) AS closed_trades, COALESCE(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), 0) AS wins FROM trades WHERE status = 'closed' GROUP BY date(timestamp) ORDER BY report_date DESC"
            )]
    def daily_trade_summary(self, report_date: str) -> dict:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(pnl), 0) AS realized_pnl, COUNT(*) AS closed_trades, COALESCE(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), 0) AS wins FROM trades WHERE status = 'closed' AND date(timestamp) = ?",
                (report_date,),
            ).fetchone()
            return dict(row)
    def realized_pnl_today(self) -> float:
        with self.connection() as conn:
            row = conn.execute("SELECT COALESCE(SUM(pnl), 0) AS total FROM trades WHERE date(timestamp) = date('now')").fetchone()
            return float(row["total"])