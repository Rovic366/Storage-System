from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from inventory.models import Tool


class MaintenanceScheduleQuerySet(models.QuerySet):
    def overdue(self):
        return self.filter(next_due__lt=timezone.localdate())

    def due_within(self, days: int = 7):
        limit = timezone.localdate() + timezone.timedelta(days=days)
        return self.filter(next_due__gte=timezone.localdate(), next_due__lte=limit)


class MaintenanceSchedule(models.Model):
    class TaskType(models.TextChoices):
        CALIBRATION = "calibration", "Calibration"
        INSPECTION = "inspection", "Inspection"
        REPAIR = "repair", "Repair"
        SERVICE = "service", "Service"

    tool = models.ForeignKey(Tool, on_delete=models.PROTECT, related_name="schedules")
    task_type = models.CharField(max_length=16, choices=TaskType.choices, db_index=True)
    interval_days = models.PositiveIntegerField(default=90)
    last_done = models.DateField(null=True, blank=True)
    next_due = models.DateField(db_index=True)

    objects = MaintenanceScheduleQuerySet.as_manager()

    class Meta:
        ordering = ["next_due", "tool__sku"]
        constraints = [
            models.UniqueConstraint(
                fields=["tool", "task_type"], name="uniq_schedule_per_tool_task"
            )
        ]
        indexes = [models.Index(fields=["next_due"])]

    def __str__(self):
        return f"{self.tool.sku} · {self.get_task_type_display()} every {self.interval_days}d"


class MaintenanceLog(models.Model):
    tool = models.ForeignKey(Tool, on_delete=models.PROTECT, related_name="maintenance_logs")
    task_type = models.CharField(max_length=16, choices=MaintenanceSchedule.TaskType.choices)
    schedule = models.ForeignKey(
        MaintenanceSchedule, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="logs",
    )
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="maintenance_logs"
    )
    cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    date = models.DateField(default=timezone.localdate, db_index=True)
    attachments = models.FileField(upload_to="maintenance/%Y/%m/", blank=True)

    class Meta:
        ordering = ["-date", "id"]
        indexes = [
            models.Index(fields=["tool", "date"]),
            models.Index(fields=["task_type", "date"]),
        ]

    def __str__(self):
        return f"{self.tool.sku} · {self.task_type} · {self.date}"
