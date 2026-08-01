from dataclasses import dataclass

from .database import Database


@dataclass
class Execution:
    symbol: str
    action: str
    quantity: float
    price: float
    realized_pnl: float
    status: str = "filled"


class PaperBroker:
    def __init__(self, database: Database):
        self.database = database

    def execute(self, symbol: str, action: str, price: float, quantity: float, strategy: str) -> Execution:
        position = self.database.position(symbol)
        if action == "buy":
            old_qty = position["quantity"] if position else 0
            old_avg = position["average_price"] if position else 0
            old_slots = position["slot_count"] if position else 0
            new_qty = old_qty + quantity
            new_avg = ((old_qty * old_avg) + (quantity * price)) / new_qty
            self.database.save_position(symbol, new_qty, new_avg, price, old_slots + 1)
            self.database.record_trade(symbol, "buy", quantity, price, None, 0, strategy, "open")
            return Execution(symbol, action, quantity, price, 0)

        close_qty = position["quantity"] if action == "close" else min(quantity, position["quantity"])
        pnl = (price - position["average_price"]) * close_qty
        remaining = position["quantity"] - close_qty
        remaining_slots = max(1, position["slot_count"] - 1) if remaining > 0 else 0
        self.database.save_position(symbol, remaining, position["average_price"], price, remaining_slots)
        self.database.record_trade(symbol, "sell", close_qty, position["average_price"], price, pnl, strategy, "closed")
        return Execution(symbol, action, close_qty, price, pnl)