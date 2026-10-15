from contextlib import asynccontextmanager
import csv
import io
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .auto_trader import AutoTraderSettings
from .config import get_settings
from .database import Database
from .runtime_status import read as read_runtime_status
from .settings_store import DashboardSettings, current as current_settings, save as save_settings
from .strategy_lab import export_data, standings
from .news_lab import NewsLab

settings = get_settings()
database = Database(settings.database_path)
dashboard_dir = Path(__file__).resolve().parent.parent / "dashboard"


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.initialize()
    yield


app = FastAPI(title="Local Paper Day Trader", version="0.4.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=dashboard_dir), name="static")


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(dashboard_dir / "index.html")


@app.get("/strategy-lab", include_in_schema=False)
def strategy_lab_page() -> FileResponse:
    return FileResponse(dashboard_dir / "strategy-lab.html")


@app.get("/health")
def health() -> dict:
    active = get_settings()
    configured = bool(active.alpaca_api_key and active.alpaca_secret_key)
    return {"status": "healthy", "mode": "paper", "database": str(active.database_path), "execution_mode": active.execution_mode, "market_data_provider": active.market_data_provider, "alpaca_configured": configured}


@app.get("/positions")
def positions() -> list[dict]:
    result = []
    for position in database.positions():
        position.update(strategy="Selected strategy", position_type="main", unrealized_pnl=round((position["current_price"] - position["average_price"]) * position["quantity"], 2))
        result.append(position)
    for position in database.strategy_positions():
        position.update(slot_count=1, position_type="all_strategies_test", unrealized_pnl=round((position["current_price"] - position["average_price"]) * position["quantity"], 2))
        result.append(position)
    return sorted(result, key=lambda row: (row["symbol"], row.get("strategy", "")))


@app.get("/stats")
def stats() -> dict:
    active = get_settings()
    trades = [*database.recent_trades(1000), *database.recent_strategy_trades(1000)]
    closed = [trade for trade in trades if trade["status"] == "closed"]
    winners = [trade for trade in closed if trade["pnl"] > 0]
    realized = sum(trade["pnl"] for trade in closed)
    all_positions = positions()
    unrealized = sum(position["unrealized_pnl"] for position in all_positions)
    auto = AutoTraderSettings()
    max_slots = auto.auto_all_strategies_max_open if auto.auto_mode == "all_strategies" else active.max_open_positions
    return {"account_value": round(active.starting_cash + realized + unrealized, 2), "daily_pnl": round(database.realized_pnl_today() + database.strategy_realized_pnl_today(), 2), "realized_pnl": round(realized, 2), "unrealized_pnl": round(unrealized, 2), "open_positions": len(all_positions), "used_entry_slots": len(all_positions), "max_entry_slots": max_slots, "win_rate": round((len(winners) / len(closed) * 100) if closed else 0, 1), "execution_mode": active.execution_mode, "market_data_provider": active.market_data_provider}


@app.get("/api/trades")
def trades() -> list[dict]:
    records = database.recent_trades() + database.recent_strategy_trades()
    for record in records:
        record.setdefault("position_type", "main")
    return sorted(records, key=lambda row: row["timestamp"], reverse=True)[:100]


@app.get("/api/realized-history")
def realized_history() -> dict:
    """Closed trade points for the command-center cumulative realized P/L chart."""
    return database.realized_trade_curve(limit=5000)


@app.get("/api/export/trades.csv")
def export_trades_csv(days: int = Query(default=30, ge=1, le=30)) -> Response:
    """Download the selected strategy, Strategy Lab, and News Lab history as one CSV."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    cutoff_text = cutoff.isoformat()
    rows: list[dict] = []
    connection = database.connection()
    try:
        main_trades = connection.execute(
            "SELECT timestamp, symbol, side, quantity, entry_price, exit_price, pnl, strategy, status "
            "FROM trades WHERE timestamp >= ? ORDER BY timestamp", (cutoff_text,)
        )
        for trade in main_trades:
            rows.append({**dict(trade), "practice": "Selected strategy", "reason": "", "headline": "", "sentiment_score": ""})
        strategy_trades = connection.execute(
            "SELECT timestamp, symbol, side, quantity, entry_price, exit_price, pnl, strategy, status, reason "
            "FROM strategy_trades WHERE timestamp >= ? ORDER BY timestamp", (cutoff_text,)
        )
        for trade in strategy_trades:
            rows.append({**dict(trade), "practice": "Strategy Lab", "headline": "", "sentiment_score": ""})
    finally:
        connection.close()

    news_lab = NewsLab(database)

    def is_in_window(value: str) -> bool:
        try:
            timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return False
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        return timestamp.astimezone(UTC) >= cutoff

    for trade in news_lab.state.get("trades", []):
        timestamp = trade.get("exit_time") or trade.get("entry_time") or ""
        if timestamp and is_in_window(timestamp):
            rows.append({
                "timestamp": timestamp, "entry_time": trade.get("entry_time", ""),
                "symbol": trade.get("symbol", ""), "side": "round_trip",
                "quantity": trade.get("quantity", 1), "entry_price": trade.get("entry_price", ""),
                "exit_price": trade.get("exit_price", ""), "pnl": trade.get("pnl", 0),
                "strategy": "Headline keyword score", "status": "closed",
                "practice": "News Lab", "reason": trade.get("reason", ""),
                "headline": trade.get("headline", ""), "sentiment_score": "",
            })
    for symbol, position in news_lab.state.get("positions", {}).items():
        timestamp = position.get("entry_time", "")
        if timestamp and is_in_window(timestamp):
            rows.append({
                "timestamp": timestamp, "entry_time": timestamp, "symbol": symbol,
                "side": "long", "quantity": position.get("quantity", 1),
                "entry_price": position.get("average_price", ""), "exit_price": "",
                "pnl": round((float(position.get("current_price", 0)) - float(position.get("average_price", 0))) * float(position.get("quantity", 0)), 4),
                "strategy": "Headline keyword score", "status": "open",
                "practice": "News Lab", "reason": "Open virtual position",
                "headline": position.get("headline", ""), "sentiment_score": "",
            })

    fields = ["timestamp", "entry_time", "practice", "strategy", "symbol", "side", "quantity", "entry_price", "exit_price", "pnl", "status", "reason", "headline", "sentiment_score"]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in sorted(rows, key=lambda item: item.get("timestamp", "")):
        safe_row = {}
        for field in fields:
            value = row.get(field, "")
            if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                value = "'" + value
            safe_row[field] = value
        writer.writerow(safe_row)

    filename = f"trade-practices-last-{days}-days.csv"
    return Response(
        content=output.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/alerts")
def alerts() -> list[dict]:
    return database.recent_alerts()


@app.get("/api/strategy-lab")
def strategy_lab() -> dict:
    result = standings()
    result["enabled"] = AutoTraderSettings().strategy_lab_enabled
    return result


@app.get("/api/strategy-lab/charts")
def strategy_lab_charts(start: datetime, end: datetime) -> dict:
    start_utc = start.replace(tzinfo=UTC) if start.tzinfo is None else start.astimezone(UTC)
    end_utc = end.replace(tzinfo=UTC) if end.tzinfo is None else end.astimezone(UTC)
    if start_utc > end_utc:
        return JSONResponse(status_code=422, content={"detail": "Start timestamp must be on or before end timestamp."})
    result = standings(start=start_utc, end=end_utc)
    result["enabled"] = AutoTraderSettings().strategy_lab_enabled
    return result


@app.get("/api/strategy-lab/export")
def strategy_lab_export(start: datetime | None = None, end: datetime | None = None) -> JSONResponse:
    start_utc = start.replace(tzinfo=UTC) if start and start.tzinfo is None else start.astimezone(UTC) if start else None
    end_utc = end.replace(tzinfo=UTC) if end and end.tzinfo is None else end.astimezone(UTC) if end else None
    if start_utc and end_utc and start_utc > end_utc:
        return JSONResponse(status_code=422, content={"detail": "Start timestamp must be on or before end timestamp."})
    return JSONResponse(
        content=export_data(start=start_utc, end=end_utc),
        headers={"Content-Disposition": 'attachment; filename="strategy-lab-export.json"'},
    )


@app.get("/api/reports")
def reports() -> dict:
    report_date = date.today().isoformat()
    today = database.daily_trade_summary(report_date)
    sleeves = database.strategy_daily_trade_summary(report_date)
    today = {
        "realized_pnl": today["realized_pnl"] + sleeves["realized_pnl"],
        "closed_trades": today["closed_trades"] + sleeves["closed_trades"],
        "wins": today["wins"] + sleeves["wins"],
    }
    saved = {report["report_date"]: report for report in database.daily_reports()}
    for summary in database.historical_trade_summaries():
        saved.setdefault(summary["report_date"], {**summary, "strategy_lab": {"strategies": []}})
    history = [report for key, report in sorted(saved.items(), reverse=True) if key != report_date]
    return {"today": {"report_date": report_date, **today, "strategy_lab": standings()}, "history": history}


@app.get("/api/system")
def system_status() -> dict:
    return read_runtime_status()


@app.get("/api/news")
def news() -> dict:
    active = get_settings()
    grouped: dict[str, dict] = {}
    for article in database.recent_news(100):
        key = article["article_id"]
        if key not in grouped:
            grouped[key] = {**article, "symbols": [article["symbol"]]}
        else:
            grouped[key]["symbols"].append(article["symbol"])
    articles = sorted(grouped.values(), key=lambda item: item["published_at"], reverse=True)[:50]
    return {"enabled": active.news_enabled and active.news_provider != "disabled", "provider": active.news_provider, "configured": bool(active.alpaca_api_key and active.alpaca_secret_key), "articles": articles, "lab": NewsLab(database).summary()}


@app.get("/api/settings", response_model=DashboardSettings)
def settings_view() -> DashboardSettings:
    return current_settings()


@app.put("/api/settings", response_model=DashboardSettings)
def settings_update(updated: DashboardSettings) -> DashboardSettings:
    return save_settings(updated)
