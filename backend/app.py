from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .auto_trader import AutoTraderSettings
from .config import get_settings
from .database import Database
from .runtime_status import read as read_runtime_status
from .settings_store import DashboardSettings, current as current_settings, save as save_settings
from .strategy_lab import standings

settings = get_settings()
database = Database(settings.database_path)
dashboard_dir = Path(__file__).resolve().parent.parent / "dashboard"


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.initialize()
    yield


app = FastAPI(title="Local Paper Day Trader", version="0.3.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=dashboard_dir), name="static")


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(dashboard_dir / "index.html")


@app.get("/health")
def health() -> dict:
    active = get_settings()
    return {"status": "healthy", "mode": "paper", "database": str(active.database_path)}


@app.get("/positions")
def positions() -> list[dict]:
    result = database.positions()
    for position in result:
        position["unrealized_pnl"] = round((position["current_price"] - position["average_price"]) * position["quantity"], 2)
    return result


@app.get("/stats")
def stats() -> dict:
    active = get_settings()
    trades = database.recent_trades(1000)
    closed = [trade for trade in trades if trade["status"] == "closed"]
    winners = [trade for trade in closed if trade["pnl"] > 0]
    realized = sum(trade["pnl"] for trade in closed)
    unrealized = sum((p["current_price"] - p["average_price"]) * p["quantity"] for p in database.positions())
    positions = database.positions()
    used_slots = sum(int(position.get("slot_count", 1)) for position in positions)
    return {"account_value": round(active.starting_cash + realized + unrealized, 2), "daily_pnl": round(database.realized_pnl_today(), 2), "realized_pnl": round(realized, 2), "unrealized_pnl": round(unrealized, 2), "open_positions": len(positions), "used_entry_slots": used_slots, "max_entry_slots": active.max_open_positions, "win_rate": round((len(winners) / len(closed) * 100) if closed else 0, 1)}


@app.get("/api/trades")
def trades() -> list[dict]:
    return database.recent_trades()


@app.get("/api/alerts")
def alerts() -> list[dict]:
    return database.recent_alerts()


@app.get("/api/strategy-lab")
def strategy_lab() -> dict:
    result = standings()
    result["enabled"] = AutoTraderSettings().strategy_lab_enabled
    return result

@app.get("/api/reports")
def reports() -> dict:
    report_date = date.today().isoformat()
    today = database.daily_trade_summary(report_date)
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