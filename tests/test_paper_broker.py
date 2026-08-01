from pathlib import Path
from backend.broker import PaperBroker
from backend.database import Database

def test_buy_then_close_calculates_profit(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.db")
    database.initialize()
    broker = PaperBroker(database)
    broker.execute("SPY", "buy", 100, 10, "test")
    execution = broker.execute("SPY", "close", 110, 10, "test")
    assert execution.realized_pnl == 100
    assert database.positions() == []
