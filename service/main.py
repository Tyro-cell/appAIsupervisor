from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.scheduler import ReminderScheduler
from app.storage import Storage


def _android_db_path_fallback() -> Path:
    try:
        from android.storage import app_storage_path  # type: ignore

        return Path(app_storage_path()) / "ai_supervisor.sqlite3"
    except Exception:
        return Path.cwd() / "ai_supervisor.sqlite3"


def main() -> None:
    db_path = _android_db_path_fallback()
    storage = Storage(db_path=db_path)
    scheduler = ReminderScheduler(storage)
    scheduler.start()
    while True:
        scheduler.tick()
        time.sleep(30)


if __name__ == "__main__":
    main()
