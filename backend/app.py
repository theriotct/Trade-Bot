from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .auto_trader import AutoTraderSettings
from .config import get_settings
from .database import Database
from .runtime_status import read as read_runtime_status
from .settings_store import DashboardSettings, current as current_settings, save as save_settings
from .strategy_lab import export_data, standings

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
    return {"status": "healthy", "mode": "paper", "database": str(active.database_path)}


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
    return {"account_value": round(active.starting_cash + realized + unrealized, 2), "daily_pnl": round(database.realized_pnl_today() + database.strategy_realized_pnl_today(), 2), "realized_pnl": round(realized, 2), "unrealized_pnl": round(unrealized, 2), "open_positions": len(all_positions), "used_entry_slots": len(all_positions), "max_entry_slots": max_slots, "win_rate": round((len(winners) / len(closed) * 100) if closed else 0, 1)}


@app.get("/api/trades")
def trades() -> list[dict]:
    records = database.recent_trades() + database.recent_strategy_trades()
    for record in records:
        record.setdefault("position_type", "main")
    return sorted(records, key=lambda row: row["timestamp"], reverse=True)[:100]


@app.get("/api/alerts")
def alerts() -> list[dict]:
    return database.recent_alerts()


@app.get("/api/strategy-lab")
def strategy_lab() -> dict:
    result = standings()
    result["enabled"] = AutoTraderSettings().strategy_lab_enabled
    return result


@app.get("/api/strategy-lab/export")
def strategy_lab_export() -> JSONResponse:
    return JSONResponse(content=export_data(), headers={"Content-Disposition": 'attachment; filename="strategy-lab-export.json"'})


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


@app.get("/api/settings", response_model=DashboardSettings)
def settings_view() -> DashboardSettings:
    return current_settings()


@app.put("/api/settings", response_model=DashboardSettings)
def settings_update(updated: DashboardSettings) -> DashboardSettings:
    return save_settings(updated)
