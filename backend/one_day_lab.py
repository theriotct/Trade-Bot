"""Queued, one-session paper strategy experiments."""
import json
import logging
import uuid
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from .database import Database
from .strategies import AVAILABLE, evaluate

logger = logging.getLogger(__name__)
EASTERN = ZoneInfo("America/New_York")
OPEN = time(9, 30)
CLOSE = time(16, 0)


class OneDayLab:
    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _decode(row) -> dict:
        config = json.loads(row["config_json"])
        state = json.loads(row["state_json"])
        report = state.get("report") if state.get("report") else None
        pairs = list(state.get("pairs", {}).values())
        return {
            "id": row["id"], "target_date": row["target_date"], **config,
            "status": row["status"], "created_at": row["created_at"],
            "updated_at": row["updated_at"], "report": report,
            "progress": {
                "open_positions": sum(bool(pair.get("quantity")) for pair in pairs),
                "closed_trades": sum(int(pair.get("closed_trades", 0)) for pair in pairs),
                "stopped_pairs": sum(bool(pair.get("stopped")) for pair in pairs),
                "realized_pnl": round(sum(float(pair.get("realized_pnl", 0)) for pair in pairs), 2),
            },
        }

    def list_plans(self) -> list[dict]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM one_day_test_plans ORDER BY target_date DESC, created_at DESC LIMIT 50"
            ).fetchall()
        return [self._decode(row) for row in rows]

    def queue(self, target_date: date, symbols: list[str], strategies: list[str], loss_limit: float, starting_amount: float, max_open_positions: int) -> dict:
        now = datetime.now(EASTERN).isoformat()
        identifier = uuid.uuid4().hex
        config = {
            "symbols": symbols, "strategies": strategies, "loss_limit": loss_limit,
            "starting_amount": starting_amount, "max_open_positions": max_open_positions,
        }
        pairs = {
            f"{symbol}:{strategy}": {
                "symbol": symbol, "strategy": strategy, "quantity": 0,
                "average_price": 0.0, "realized_pnl": 0.0,
                "starting_amount": starting_amount, "cash_balance": starting_amount,
                "closed_trades": 0, "wins": 0, "losses": 0, "flats": 0,
                "stopped": False, "skipped_entries": 0, "trades": [],
            }
            for symbol in symbols for strategy in strategies
        }
        state = {"pairs": pairs, "last_bar_by_symbol": {}, "last_prices": {}, "report": None}
        with self.database.connection() as connection:
            connection.execute(
                "INSERT INTO one_day_test_plans(id,target_date,config_json,status,state_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (identifier, target_date.isoformat(), json.dumps(config), "queued", json.dumps(state), now, now),
            )
            row = connection.execute("SELECT * FROM one_day_test_plans WHERE id=?", (identifier,)).fetchone()
        return self._decode(row)

    def cancel(self, identifier: str) -> bool:
        now = datetime.now(EASTERN).isoformat()
        with self.database.connection() as connection:
            row = connection.execute("SELECT * FROM one_day_test_plans WHERE id=?", (identifier,)).fetchone()
            if not row or row["status"] not in {"queued", "running"}:
                return False
            if row["status"] == "queued":
                state = json.loads(row["state_json"])
                status = "cancelled"
            else:
                config = json.loads(row["config_json"])
                state = json.loads(row["state_json"])
                for pair in state["pairs"].values():
                    if pair["quantity"]:
                        price = state["last_prices"].get(pair["symbol"], pair["average_price"])
                        self._close(pair, float(price), now, "Run stopped by user")
                status = "cancelled"
                pairs = list(state["pairs"].values())
                total_capital = float(config["starting_amount"]) * len(pairs)
                total_pnl = round(sum(float(pair["realized_pnl"]) for pair in pairs), 2)
                state["report"] = {
                    "completed_at": now, "summary": "Run stopped by the user; open paper positions were closed at the latest recorded prices.",
                    "pairs": pairs, "starting_amount_per_run": config["starting_amount"],
                    "total_starting_amount": round(total_capital, 2), "realized_pnl": total_pnl,
                    "return_pct": round(total_pnl / total_capital * 100, 2) if total_capital else 0,
                    "closed_trades": sum(int(pair["closed_trades"]) for pair in pairs),
                    "wins": sum(int(pair["wins"]) for pair in pairs),
                    "losses": sum(int(pair["losses"]) for pair in pairs),
                    "skipped_entries": sum(int(pair.get("skipped_entries", 0)) for pair in pairs),
                }
            result = connection.execute(
                "UPDATE one_day_test_plans SET status=?,state_json=?,updated_at=? WHERE id=? AND status=?",
                (status, json.dumps(state), now, identifier, row["status"]),
            )
        return result.rowcount == 1

    def due_symbols(self, today: date) -> list[str]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT config_json FROM one_day_test_plans WHERE status IN ('queued','running') AND target_date=?",
                (today.isoformat(),),
            ).fetchall()
        return sorted({symbol for row in rows for symbol in json.loads(row["config_json"]).get("symbols", [])})

    @staticmethod
    def _close(pair: dict, price: float, timestamp: str, reason: str) -> None:
        quantity = float(pair["quantity"])
        entry_price = float(pair["average_price"])
        trade_pnl = round((price - entry_price) * quantity, 4)
        pair["realized_pnl"] = round(float(pair["realized_pnl"]) + trade_pnl, 4)
        pair["cash_balance"] = round(float(pair.get("cash_balance", 0)) + price * quantity, 4)
        pair["closed_trades"] += 1
        pair["wins"] += int(trade_pnl > 0)
        pair["losses"] += int(trade_pnl < 0)
        pair["flats"] += int(trade_pnl == 0)
        pair["trades"].append({
            "entry_time": pair.get("entry_time"), "exit_time": timestamp,
            "quantity": quantity, "entry_price": entry_price,
            "exit_price": round(price, 4), "pnl": trade_pnl,
            "entry_reason": pair.get("entry_reason", ""), "reason": reason,
        })
        pair.update(quantity=0, average_price=0.0)
        pair.pop("entry_time", None)
        pair.pop("entry_reason", None)

    @staticmethod
    def _local_timestamp(index_value) -> datetime:
        stamp = index_value.to_pydatetime() if hasattr(index_value, "to_pydatetime") else index_value
        if stamp.tzinfo is None:
            return stamp.replace(tzinfo=EASTERN)
        return stamp.astimezone(EASTERN)

    def tick(self, now: datetime, candles_by_symbol: dict, market_open: bool, market_close: bool) -> None:
        now = now.astimezone(EASTERN) if now.tzinfo else now.replace(tzinfo=EASTERN)
        with self.database.connection() as connection:
            plans = connection.execute(
                "SELECT * FROM one_day_test_plans WHERE status IN ('queued','running') AND target_date<=? ORDER BY target_date,created_at",
                (now.date().isoformat(),),
            ).fetchall()

        for row in plans:
            plan_id, old_status = row["id"], row["status"]
            target_day = date.fromisoformat(row["target_date"])
            config = json.loads(row["config_json"])
            state = json.loads(row["state_json"])
            status = old_status
            if target_day < now.date():
                if old_status == "queued":
                    status = "missed"
                    state["report"] = {"completed_at": now.isoformat(), "summary": "The scheduled date passed before the paper worker ran.", "pairs": list(state["pairs"].values())}
                else:
                    status = "failed"
                    state["report"] = {"completed_at": now.isoformat(), "summary": "The session ended before the worker could finalize this run.", "pairs": list(state["pairs"].values())}
            elif target_day == now.date():
                if market_open or market_close:
                    status = "running"
                    for symbol in config["symbols"]:
                        candles = candles_by_symbol.get(symbol)
                        if candles is None or candles.empty:
                            continue
                        state["last_prices"][symbol] = float(candles["Close"].iloc[-1])
                        last_bar = state["last_bar_by_symbol"].get(symbol)
                        for index_value, bar in candles.iterrows():
                            local_time = self._local_timestamp(index_value)
                            bar_id = str(index_value)
                            if local_time.date() != target_day or not OPEN <= local_time.time().replace(tzinfo=None) < CLOSE:
                                continue
                            state["observed_session_data"] = True
                            if last_bar and bar_id <= last_bar:
                                continue
                            history = candles.loc[:index_value]
                            if len(history) < 205:
                                last_bar = bar_id
                                continue
                            price = float(bar["Close"])
                            low = float(bar["Low"])
                            for strategy in config["strategies"]:
                                pair = state["pairs"][f"{symbol}:{strategy}"]
                                if pair["stopped"]:
                                    continue
                                if pair["quantity"]:
                                    worst_pnl = float(pair["realized_pnl"]) + (low - float(pair["average_price"])) * float(pair["quantity"])
                                    if worst_pnl <= -float(config["loss_limit"]):
                                        stop_price = float(pair["average_price"]) + (-float(config["loss_limit"]) - float(pair["realized_pnl"])) / float(pair["quantity"])
                                        self._close(pair, max(low, stop_price), local_time.isoformat(), "Daily loss limit")
                                        pair["stopped"] = True
                                        continue
                                    signal = evaluate(strategy, history)
                                    if signal and signal.action == "close":
                                        self._close(pair, price, local_time.isoformat(), signal.reason)
                                elif float(pair["realized_pnl"]) <= -float(config["loss_limit"]):
                                    pair["stopped"] = True
                                else:
                                    signal = evaluate(strategy, history)
                                    if signal and signal.action == "buy":
                                        cash = float(pair.get("cash_balance", config["starting_amount"]))
                                        quantity = cash / price if price > 0 else 0
                                        open_pairs = sum(bool(item["quantity"]) for item in state["pairs"].values())
                                        if open_pairs >= int(config["max_open_positions"]):
                                            pair["skipped_entries"] += 1
                                        elif quantity:
                                            pair.update(quantity=quantity, average_price=price, cash_balance=0.0, entry_time=local_time.isoformat(), entry_reason=signal.reason)
                            last_bar = bar_id
                        if last_bar:
                            state["last_bar_by_symbol"][symbol] = last_bar

                if market_close:
                    finished = [pair for pair in state["pairs"].values()]
                    if not state.get("observed_session_data"):
                        status = "missed"
                        summary = "No regular-session bars were returned for this date; the test may have fallen on a market holiday or a data outage."
                    else:
                        for pair in finished:
                            if pair["quantity"]:
                                price = state["last_prices"].get(pair["symbol"], pair["average_price"])
                                self._close(pair, float(price), now.isoformat(), "End of session")
                        status = "completed"
                        summary = "Paper run closed at the end of the scheduled session."
                    total_starting_amount = float(config["starting_amount"]) * len(finished)
                    total_pnl = round(sum(float(pair["realized_pnl"]) for pair in finished), 2)
                    state["report"] = {
                        "completed_at": now.isoformat(), "summary": summary,
                        "pairs": finished,
                        "starting_amount_per_run": config["starting_amount"],
                        "total_starting_amount": round(total_starting_amount, 2),
                        "realized_pnl": total_pnl,
                        "return_pct": round(total_pnl / total_starting_amount * 100, 2) if total_starting_amount else 0,
                        "closed_trades": sum(int(pair["closed_trades"]) for pair in finished),
                        "wins": sum(int(pair["wins"]) for pair in finished),
                        "losses": sum(int(pair["losses"]) for pair in finished),
                        "skipped_entries": sum(int(pair.get("skipped_entries", 0)) for pair in finished),
                    }

            updated = datetime.now(EASTERN).isoformat()
            with self.database.connection() as connection:
                connection.execute(
                    "UPDATE one_day_test_plans SET status=?,state_json=?,updated_at=? WHERE id=? AND status=?",
                    (status, json.dumps(state), updated, plan_id, old_status),
                )
