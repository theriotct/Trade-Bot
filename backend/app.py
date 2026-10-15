from contextlib import asynccontextmanager
import csv
import io
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .auto_trader import AutoTraderSettings
from .config import get_settings
from .database import Database
from .runtime_status import read as read_runtime_status
from .settings_store import DashboardSettings, current as current_settings, save as save_settings
from .strategy_lab import export_data, standings
from .news_lab import NewsLab
from .one_day_lab import OneDayLab
from .strategies import AVAILABLE
import yfinance as yf

settings = get_settings()
logger = logging.getLogger(__name__)
database = Database(settings.database_path)
dashboard_dir = Path(__file__).resolve().parent.parent / "dashboard"
EASTERN = ZoneInfo("America/New_York")
one_day_lab = OneDayLab(database)


class OneDayQueueRequest(BaseModel):
    target_date: date
    symbols: list[str] = Field(min_length=1, max_length=100)
    strategy: str
    loss_limit: float = Field(gt=0, le=5000)
    starting_amount: float = Field(ge=100, le=1_000_000)
    max_open_positions: int = Field(ge=1, le=1000)

    @field_validator("strategy")
    @classmethod
    def validate_strategy(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized != "all" and normalized not in AVAILABLE:
            raise ValueError("Choose a listed strategy or all strategies.")
        return normalized

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, values: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(value.strip().upper() for value in values if value.strip()))
        if not normalized:
            raise ValueError("Choose at least one symbol.")
        return normalized


class OneDayBacktestRequest(OneDayQueueRequest):
    symbols: list[str] = Field(min_length=1, max_length=20)


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


@app.get("/one-day-lab", include_in_schema=False)
def one_day_lab_page() -> FileResponse:
    return FileResponse(dashboard_dir / "one-day-lab.html")


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


@app.get("/api/one-day-lab")
def one_day_lab_view() -> dict:
    auto = AutoTraderSettings()
    symbols = sorted(set(auto.lab_symbols) | get_settings().allowed_symbols)
    return {
        "plans": one_day_lab.list_plans(), "symbols": symbols,
        "strategies": ["all", *sorted(AVAILABLE)], "timezone": "America/New_York",
        "session": {"open": "09:30", "liquidate_by": "15:55", "close": "16:00"},
    }


@app.post("/api/one-day-lab/queue")
def one_day_lab_queue(request: OneDayQueueRequest) -> dict:
    now = datetime.now(EASTERN)
    if request.target_date < now.date():
        raise HTTPException(status_code=422, detail="Choose today or a future weekday.")
    if request.target_date.weekday() >= 5:
        raise HTTPException(status_code=422, detail="Choose a weekday for the test session.")
    # Compare wall-clock minutes: aware and naive datetime.time values cannot be
    # compared directly on current Python versions.
    if request.target_date == now.date() and (now.hour * 60 + now.minute) >= (15 * 60 + 55):
        raise HTTPException(status_code=422, detail="Today’s session has ended. Choose a future weekday.")
    available = set(AutoTraderSettings().lab_symbols) | get_settings().allowed_symbols
    invalid = sorted(set(request.symbols) - available)
    if invalid:
        raise HTTPException(status_code=422, detail=f"Symbols are not in the configured allowed list: {', '.join(invalid)}")
    strategies = sorted(AVAILABLE) if request.strategy == "all" else [request.strategy]
    return one_day_lab.queue(
        request.target_date, request.symbols, strategies,
        request.loss_limit, request.starting_amount, request.max_open_positions,
    )


def _fetch_yfinance_backtest(symbol: str, target_day: date):
    start_day = target_day - timedelta(days=6)
    frame = yf.download(
        symbol.replace(".", "-"), start=start_day.isoformat(),
        end=(target_day + timedelta(days=1)).isoformat(), interval="1m",
        auto_adjust=True, progress=False, multi_level_index=False,
        threads=False, timeout=20,
    )
    if frame is None or frame.empty:
        raise ValueError("Yahoo Finance returned no one-minute bars")
    if getattr(frame.index, "tz", None) is None:
        frame.index = frame.index.tz_localize(EASTERN)
    else:
        frame.index = frame.index.tz_convert(EASTERN)
    cutoff = datetime.combine(target_day, time(15, 55), tzinfo=EASTERN)
    return frame.loc[frame.index <= cutoff]


@app.post("/api/one-day-lab/backtest")
def one_day_lab_backtest(request: OneDayBacktestRequest) -> dict:
    today = datetime.now(EASTERN).date()
    oldest_supported = today - timedelta(days=3)
    if not oldest_supported <= request.target_date < today:
        raise HTTPException(
            status_code=422,
            detail="Choose a completed weekday from the last three calendar days. Yahoo Finance only provides a short rolling window of one-minute history, and the test needs earlier bars to warm up its indicators.",
        )
    if request.target_date.weekday() >= 5:
        raise HTTPException(status_code=422, detail="Choose a weekday with a completed market session.")
    available = set(AutoTraderSettings().lab_symbols) | get_settings().allowed_symbols
    invalid = sorted(set(request.symbols) - available)
    if invalid:
        raise HTTPException(status_code=422, detail=f"Symbols are not in the configured allowed list: {', '.join(invalid)}")

    frames = {}
    failures = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(_fetch_yfinance_backtest, symbol, request.target_date): symbol for symbol in request.symbols}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                frame = future.result()
                if frame.empty:
                    raise ValueError("No bars available through 3:55 p.m. ET")
                frames[symbol] = frame
            except Exception as exc:
                failures[symbol] = str(exc)
    if failures:
        details = "; ".join(f"{symbol}: {reason}" for symbol, reason in sorted(failures.items()))
        raise HTTPException(status_code=502, detail=f"Historical data unavailable; no backtest was saved. {details}")

    strategies = sorted(AVAILABLE) if request.strategy == "all" else [request.strategy]
    plan = one_day_lab.queue(
        request.target_date, request.symbols, strategies,
        request.loss_limit, request.starting_amount, request.max_open_positions,
        mode="historical_backtest",
    )
    simulated_close = datetime.combine(request.target_date, time(15, 55), tzinfo=EASTERN)
    try:
        one_day_lab.tick(simulated_close, frames, market_open=True, market_close=True)
    except Exception as exc:
        logger.exception("Historical one-day backtest replay failed")
        raise HTTPException(status_code=500, detail="Historical replay failed. Check the server log for the backtest error.") from exc
    with database.connection() as connection:
        row = connection.execute("SELECT * FROM one_day_test_plans WHERE id=?", (plan["id"],)).fetchone()
        state = json.loads(row["state_json"])
        if state.get("report"):
            if row["status"] == "completed":
                state["report"]["summary"] = "Historical Yahoo Finance one-minute backtest; signals were replayed chronologically and paper positions closed by 3:55 p.m. ET."
            state["report"]["data_source"] = "Yahoo Finance · 1-minute bars"
            connection.execute(
                "UPDATE one_day_test_plans SET state_json=?,updated_at=? WHERE id=?",
                (json.dumps(state), datetime.now(EASTERN).isoformat(), plan["id"]),
            )
            row = connection.execute("SELECT * FROM one_day_test_plans WHERE id=?", (plan["id"],)).fetchone()
    return one_day_lab._decode(row)


@app.post("/api/one-day-lab/{plan_id}/cancel")
def one_day_lab_cancel(plan_id: str) -> dict:
    if not one_day_lab.cancel(plan_id):
        raise HTTPException(status_code=409, detail="This run is no longer queued or running.")
    return {"status": "cancelled", "id": plan_id}


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
