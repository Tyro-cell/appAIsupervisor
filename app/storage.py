from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Optional


SCHEMA_VERSION = 1


def _default_db_path() -> Path:
    base = Path(os.environ.get("AI_SUPERVISOR_DATA_DIR", "")).expanduser()
    if str(base).strip():
        base.mkdir(parents=True, exist_ok=True)
        return base / "ai_supervisor.sqlite3"
    return Path.cwd() / "ai_supervisor.sqlite3"


@dataclass(frozen=True)
class TaskRow:
    id: int
    plan_id: int
    day: str
    start_time: str
    end_time: str
    title: str
    description: str
    status: str


class Storage:
    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or _default_db_path()
        self._lock = threading.RLock()
        self._ensure()

    @contextmanager
    def _conn(self) -> Iterable[sqlite3.Connection]:
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    def _ensure(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            version = conn.execute(
                "SELECT value FROM meta WHERE key='schema_version'"
            ).fetchone()
            if version is None:
                conn.execute(
                    "INSERT INTO meta(key, value) VALUES('schema_version', ?)",
                    (str(SCHEMA_VERSION),),
                )
                self._create_schema(conn)
            else:
                # Future migrations would go here.
                pass

    def _create_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                domain TEXT NOT NULL,
                long_goal TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_id INTEGER NOT NULL,
                day TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'todo',
                created_at TEXT NOT NULL,
                FOREIGN KEY(plan_id) REFERENCES plans(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_tasks_day ON tasks(day);
            CREATE INDEX IF NOT EXISTS idx_tasks_plan ON tasks(plan_id);

            CREATE TABLE IF NOT EXISTS checkins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                report_text TEXT NOT NULL,
                self_score INTEGER NOT NULL DEFAULT 0,
                ai_feedback TEXT NOT NULL DEFAULT '',
                suspicion_score INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_checkins_task ON checkins(task_id);

            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                scheduled_at TEXT NOT NULL,
                sent_count INTEGER NOT NULL DEFAULT 0,
                last_sent_at TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_reminders_task ON reminders(task_id);
            CREATE INDEX IF NOT EXISTS idx_reminders_scheduled ON reminders(scheduled_at);
            """
        )

    # ---- settings ----
    def get_setting(self, key: str, default: str = "") -> str:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key=?", (key,)
            ).fetchone()
            return str(row["value"]) if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def get_settings_json(self, key: str, default: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        raw = self.get_setting(key, "")
        if not raw:
            return default or {}
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else (default or {})
        except Exception:
            return default or {}

    def set_settings_json(self, key: str, value: dict[str, Any]) -> None:
        self.set_setting(key, json.dumps(value, ensure_ascii=False))

    # ---- plans ----
    def create_plan(
        self, title: str, domain: str, long_goal: str, start: date, end: date
    ) -> int:
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO plans(title, domain, long_goal, start_date, end_date, created_at)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (title, domain, long_goal, start.isoformat(), end.isoformat(), now),
            )
            return int(cur.lastrowid)

    def list_plans(self) -> list[sqlite3.Row]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM plans ORDER BY created_at DESC"
            ).fetchall()
            return list(rows)

    def get_plan(self, plan_id: int) -> Optional[sqlite3.Row]:
        with self._conn() as conn:
            return conn.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()

    # ---- tasks ----
    def create_task(
        self,
        plan_id: int,
        day: date,
        start_time: str,
        end_time: str,
        title: str,
        description: str,
    ) -> int:
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO tasks(plan_id, day, start_time, end_time, title, description, status, created_at)
                VALUES(?, ?, ?, ?, ?, ?, 'todo', ?)
                """,
                (plan_id, day.isoformat(), start_time, end_time, title, description, now),
            )
            task_id = int(cur.lastrowid)
            # Default reminder at end_time.
            scheduled_at = f"{day.isoformat()}T{end_time}:00"
            conn.execute(
                "INSERT INTO reminders(task_id, scheduled_at) VALUES(?, ?)",
                (task_id, scheduled_at),
            )
            return task_id

    def list_tasks_for_day(self, day: date) -> list[TaskRow]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, plan_id, day, start_time, end_time, title, description, status
                FROM tasks
                WHERE day=?
                ORDER BY start_time ASC
                """,
                (day.isoformat(),),
            ).fetchall()
            return [TaskRow(**dict(r)) for r in rows]

    def list_tasks_for_plan(self, plan_id: int) -> list[TaskRow]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, plan_id, day, start_time, end_time, title, description, status
                FROM tasks
                WHERE plan_id=?
                ORDER BY day ASC, start_time ASC
                """,
                (plan_id,),
            ).fetchall()
            return [TaskRow(**dict(r)) for r in rows]

    def set_task_status(self, task_id: int, status: str) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE tasks SET status=? WHERE id=?", (status, task_id))

    def get_task(self, task_id: int) -> Optional[TaskRow]:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id, plan_id, day, start_time, end_time, title, description, status
                FROM tasks
                WHERE id=?
                """,
                (task_id,),
            ).fetchone()
            return TaskRow(**dict(row)) if row else None

    def task_has_checkin(self, task_id: int) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM checkins WHERE task_id=? LIMIT 1", (task_id,)
            ).fetchone()
            return bool(row)

    # ---- checkins ----
    def create_checkin(
        self,
        task_id: int,
        report_text: str,
        self_score: int,
        ai_feedback: str,
        suspicion_score: int,
    ) -> int:
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO checkins(task_id, created_at, report_text, self_score, ai_feedback, suspicion_score)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (task_id, now, report_text, int(self_score), ai_feedback, int(suspicion_score)),
            )
            conn.execute("UPDATE tasks SET status='done' WHERE id=?", (task_id,))
            conn.execute("UPDATE reminders SET active=0 WHERE task_id=?", (task_id,))
            return int(cur.lastrowid)

    def list_checkins_recent(self, limit: int = 50) -> list[sqlite3.Row]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT c.*, t.title AS task_title, t.day AS task_day
                FROM checkins c
                JOIN tasks t ON t.id=c.task_id
                ORDER BY c.created_at DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
            return list(rows)

    def export_all(self) -> dict[str, Any]:
        with self._conn() as conn:
            plans = [dict(r) for r in conn.execute("SELECT * FROM plans ORDER BY id ASC").fetchall()]
            tasks = [dict(r) for r in conn.execute("SELECT * FROM tasks ORDER BY id ASC").fetchall()]
            checkins = [dict(r) for r in conn.execute("SELECT * FROM checkins ORDER BY id ASC").fetchall()]
            settings = [dict(r) for r in conn.execute("SELECT * FROM settings ORDER BY key ASC").fetchall()]
            meta = [dict(r) for r in conn.execute("SELECT * FROM meta ORDER BY key ASC").fetchall()]
        return {
            "exported_at": datetime.utcnow().isoformat(),
            "schema_version": SCHEMA_VERSION,
            "meta": meta,
            "settings": settings,
            "plans": plans,
            "tasks": tasks,
            "checkins": checkins,
        }

    # ---- reminders ----
    def list_due_reminders(self, now_iso: str) -> list[sqlite3.Row]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT r.*, t.title AS task_title, t.day AS task_day, t.end_time AS task_end_time
                FROM reminders r
                JOIN tasks t ON t.id=r.task_id
                WHERE r.active=1 AND r.scheduled_at<=?
                ORDER BY r.scheduled_at ASC
                """,
                (now_iso,),
            ).fetchall()
            return list(rows)

    def bump_reminder(self, reminder_id: int, sent_count: int, last_sent_at: str, active: int) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE reminders
                SET sent_count=?, last_sent_at=?, active=?
                WHERE id=?
                """,
                (int(sent_count), last_sent_at, int(active), int(reminder_id)),
            )
