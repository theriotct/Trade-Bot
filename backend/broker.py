from dataclasses import dataclass
import math
import time
import uuid

from .alpaca_api import AlpacaAPI, AlpacaAPIError
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

    def execute(self, symbol: str, action: str, price: float, quantity: float, strategy: str, client_order_id: str | None = None) -> Execution:
        symbol, action = _validate_order(symbol, action, price, quantity)
        pnl, filled_quantity = self.database.execute_paper_trade(symbol, action, price, quantity, strategy, client_order_id)
        return Execution(symbol, action, filled_quantity, price, pnl)


class AlpacaPaperBroker(PaperBroker):
    """Market-order adapter that always talks to Alpaca's paper endpoint."""

    def __init__(self, database: Database, api: AlpacaAPI):
        super().__init__(database)
        self.api = api

    def execute(self, symbol: str, action: str, price: float, quantity: float, strategy: str, client_order_id: str | None = None) -> Execution:
        symbol, action = _validate_order(symbol, action, price, quantity)
        if action in {"sell", "close"}:
            position = self.database.position(symbol)
            if not position:
                raise ValueError(f"No local paper position exists for {symbol}")
            quantity = position["quantity"] if action == "close" else quantity
            if quantity > position["quantity"]:
                raise ValueError(f"Cannot sell {quantity:g}; only {position['quantity']:g} shares are open")
        order_key = client_order_id or uuid.uuid4().hex
        order = self.api.order_by_client_id(order_key)
        if not order:
            try:
                order = self.api.submit_paper_order(symbol, "buy" if action == "buy" else "sell", quantity, order_key)
            except AlpacaAPIError:
                # A timed-out POST may still have reached Alpaca. Look up its
                # stable client ID before deciding it failed.
                order = self.api.order_by_client_id(order_key)
                if not order:
                    raise

        terminal = {"filled", "canceled", "expired", "rejected", "done_for_day"}
        for _ in range(6):
            status = str(order.get("status", "")).lower()
            if status in terminal:
                break
            if order.get("id"):
                time.sleep(0.4)
                order = self.api.order(str(order["id"]))

        status = str(order.get("status", "unknown")).lower()
        if status not in terminal:
            raise AlpacaAPIError(f"Alpaca paper order {order_key} is still {status}; retry will reuse the same client order ID")
        filled = float(order.get("filled_qty") or 0)
        if filled <= 0:
            raise AlpacaAPIError(f"Alpaca paper order {order_key} is {status}; retry will reuse the same client order ID")
        fill_price = float(order.get("filled_avg_price") or price)
        db_action = "buy" if action == "buy" else ("close" if filled >= quantity - 1e-9 else "sell")
        pnl, filled = self.database.execute_paper_trade(symbol, db_action, fill_price, filled, strategy, order_key)
        return Execution(symbol, action, filled, fill_price, pnl, str(order.get("status", "filled")))

    def sync_positions(self) -> None:
        """Import account positions at startup and reject ambiguous local/account state."""
        remote = {str(item["symbol"]).upper(): item for item in self.api.positions()}
        local = {item["symbol"]: item for item in self.database.positions()}
        if local and not remote:
            raise AlpacaAPIError("Local paper positions exist but the Alpaca paper account is flat. Reconcile/close local positions before changing EXECUTION_MODE.")
        if local and set(local) != set(remote):
            raise AlpacaAPIError("Local paper positions do not match the Alpaca paper account. Reconcile positions before starting the Alpaca execution mode.")
        if any(float(item["qty"]) <= 0 for item in remote.values()):
            raise AlpacaAPIError("This paper adapter supports long positions only. Close or reconcile non-long Alpaca positions before starting it.")
        for symbol in set(local).intersection(remote):
            if abs(float(local[symbol]["quantity"]) - float(remote[symbol]["qty"])) > 1e-6:
                raise AlpacaAPIError(f"Local quantity for {symbol} does not match Alpaca. Reconcile positions before starting the worker.")
        for symbol, item in remote.items():
            self.database.save_position(symbol, float(item["qty"]), float(item["avg_entry_price"]), float(item.get("current_price") or item["avg_entry_price"]))
        remote_symbols = set(remote)
        for symbol in set(local) - remote_symbols:
            self.database.save_position(symbol, 0, 0, 0)


def _validate_order(symbol: str, action: str, price: float, quantity: float) -> tuple[str, str]:
    normalized_symbol, normalized_action = symbol.strip().upper(), action.strip().lower()
    if normalized_action not in {"buy", "sell", "close"}:
        raise ValueError(f"Unsupported paper action: {action}")
    if not normalized_symbol:
        raise ValueError("Symbol cannot be empty")
    if not math.isfinite(float(price)) or float(price) <= 0:
        raise ValueError("Price must be a positive finite number")
    if not math.isfinite(float(quantity)) or float(quantity) <= 0:
        raise ValueError("Quantity must be a positive finite number")
    return normalized_symbol, normalized_action
