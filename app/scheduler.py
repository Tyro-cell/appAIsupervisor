from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Callable, Optional

from .storage import Storage

try:
    from plyer import notification as plyer_notification  # type: ignore
except Exception:  # pragma: no cover
    plyer_notification = None


class ReminderScheduler:
    """
    In-app reminder loop: checks due reminders and sends up to N local notifications.
    Note: This runs only while the app process is alive.
    """

    def __init__(
        self,
        storage: Storage,
        get_now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.storage = storage
        self.get_now = get_now
        self._lock = threading.RLock()
        self._running = False

    def start(self) -> None:
        with self._lock:
            self._running = True

    def stop(self) -> None:
        with self._lock:
            self._running = False

    def tick(self) -> None:
        with self._lock:
            if not self._running:
                return

        now = self.get_now()
        now_iso = now.isoformat(timespec="seconds")
        due = self.storage.list_due_reminders(now_iso=now_iso)

        grace_min = int(self.storage.get_setting("reminder_grace_min", "5") or "5")
        resend_min = int(self.storage.get_setting("reminder_resend_min", "15") or "15")
        max_sends = int(self.storage.get_setting("reminder_max_sends", "3") or "3")

        for r in due:
            reminder_id = int(r["id"])
            task_id = int(r["task_id"])
            sent_count = int(r["sent_count"])
            last_sent_at = str(r["last_sent_at"] or "")

            if self.storage.task_has_checkin(task_id):
                self.storage.bump_reminder(reminder_id, sent_count, last_sent_at, active=0)
                continue

            scheduled_at = datetime.fromisoformat(str(r["scheduled_at"]))
            if now < scheduled_at + timedelta(minutes=grace_min):
                continue

            if sent_count >= max_sends:
                self.storage.bump_reminder(reminder_id, sent_count, last_sent_at, active=0)
                continue

            if last_sent_at:
                try:
                    last = datetime.fromisoformat(last_sent_at)
                    if now < last + timedelta(minutes=resend_min):
                        continue
                except Exception:
                    pass

            title = "督学提醒：该汇报了"
            message = f"任务：{r['task_title']}（{r['task_day']}）\n请打开App打卡汇报，别糊弄自己。"
            self._notify(title, message)
            self.storage.bump_reminder(
                reminder_id,
                sent_count + 1,
                now.isoformat(timespec="seconds"),
                active=1,
            )

    def _notify(self, title: str, message: str) -> None:
        if plyer_notification is None:
            return
        try:
            plyer_notification.notify(title=title, message=message, app_name="AI督学师")
        except Exception:
            pass

