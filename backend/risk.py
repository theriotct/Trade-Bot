from .config import Settings
from .database import Database


class RiskRejected(Exception):
    pass


class RiskManager:
    def __init__(self, database: Database, settings: Settings):
        self.database = database
        self.settings = settings

    def validate(self, symbol: str, action: str, price: float, quantity: float) -> None:
        if symbol not in self.settings.allowed_symbols:
            raise RiskRejected(f"{symbol} is not in the symbol whitelist")
        if price * quantity > self.settings.max_position_value:
            raise RiskRejected("Order exceeds maximum position value")
        if self.database.realized_pnl_today() <= -self.settings.max_daily_loss:
            raise RiskRejected("Daily loss limit has been reached")

        positions = self.database.positions()
        existing = next((position for position in positions if position["symbol"] == symbol), None)
        if action == "buy":
            guaranteed_slots = len(self.settings.allowed_symbols)
            if self.settings.max_open_positions < guaranteed_slots:
                raise RiskRejected("Maximum entry slots must be at least the number of whitelist symbols")
            used_slots = sum(int(position.get("slot_count", 1)) for position in positions)
            if existing:
                shared_slots = self.settings.max_open_positions - guaranteed_slots
                extras_used = used_slots - len(positions)
                if extras_used >= shared_slots:
                    raise RiskRejected("Shared add-on entry slots are full")
            elif used_slots >= self.settings.max_open_positions:
                raise RiskRejected("All entry slots are full")
        if action in {"sell", "close"} and not existing:
            raise RiskRejected(f"No open position exists for {symbol}")