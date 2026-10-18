"""Maintenance scheduling business logic."""

from __future__ import annotations

import datetime as dt

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.services import audit
from inventory.services import StockError


def log_task(schedule, performed_by, *, date: dt.date | None = None, cost=0, notes: str = "",
             task_type: str = "", attachments=None):
    """Record a completed maintenance task and roll the schedule forward.

    next_due is computed from the completion date: date + interval_days.
    Creates the MaintenanceLog (with optional attachment), updates the
    schedule and writes an audit row — atomically.
    """
    from maintenance.models import MaintenanceLog

    date = date or timezone.localdate()
    if date > timezone.localdate():
        raise StockError("A maintenance task cannot be logged in the future.")
    cost = cost or 0
    task_type = task_type or schedule.task_type
    with transaction.atomic():
        log = MaintenanceLog.objects.create(
            tool=schedule.tool, task_type=task_type,
            schedule=schedule, performed_by=performed_by, cost=cost,
            notes=notes, date=date,
            **({"attachments": attachments} if attachments else {}),
        )
        schedule.last_done = date
        schedule.next_due = date + dt.timedelta(days=schedule.interval_days)
        schedule.save(update_fields=["last_done", "next_due"])
        audit(performed_by, "MAINTENANCE_LOG", log,
              meta={"tool": schedule.tool.sku, "task_type": task_type,
                    "next_due": schedule.next_due.isoformat(), "cost": str(cost)})
        return log, schedule


def schedule_overdue_count() -> int:
    from maintenance.models import MaintenanceSchedule

    return MaintenanceSchedule.objects.overdue().count()


def next_due_preview(schedule) -> dt.date:
    """The next_due that will result if the task is completed today."""
    return timezone.localdate() + dt.timedelta(days=schedule.interval_days)


def validate_schedule_dates(last_done, next_due, interval_days: int):
    if last_done and next_due:
        expected = last_done + dt.timedelta(days=interval_days)
        if abs((next_due - expected).days) > 7:
            raise ValidationError(
                {"next_due": "next_due differs from last_done + interval by more than a week."}
            )
