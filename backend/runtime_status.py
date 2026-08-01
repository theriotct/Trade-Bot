"""Small, file-backed heartbeat for displaying worker status in the dashboard."""
import json
from datetime import UTC, datetime
from pathlib import Path


STATUS_PATH = Path("database/runtime_status.json")


def publish(worker: str, **details: object) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        current = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        current = {}
    current[worker] = {"updated_at": datetime.now(UTC).isoformat(), **details}
    STATUS_PATH.write_text(json.dumps(current, indent=2), encoding="utf-8")


def read() -> dict:
    try:
        return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
