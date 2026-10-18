from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from inventory.models import Location, Tool


class StockMovement(models.Model):
    class Type(models.TextChoices):
        RECEIVE = "receive", "Receive"
        ISSUE = "issue", "Issue"
        RETURN = "return", "Return"
        TRANSFER = "transfer", "Transfer"
        ADJUST = "adjust", "Adjust"
        SCRAP = "scrap", "Scrap"

    tool = models.ForeignKey(Tool, on_delete=models.PROTECT, related_name="movements")
    type = models.CharField(max_length=12, choices=Type.choices, db_index=True)
    quantity = models.PositiveIntegerField()
    from_location = models.ForeignKey(
        Location, on_delete=models.SET_NULL, null=True, blank=True, related_name="issues_at"
    )
    to_location = models.ForeignKey(
        Location, on_delete=models.SET_NULL, null=True, blank=True, related_name="receipts_at"
    )
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="movements"
    )
    reference_no = models.CharField(max_length=64, blank=True, db_index=True)
    notes = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["tool", "timestamp"]),
            models.Index(fields=["type", "timestamp"]),
            models.Index(fields=["from_location", "timestamp"]),
            models.Index(fields=["to_location", "timestamp"]),
        ]

    def __str__(self):
        return f"{self.type.title()} {self.quantity}× {self.tool.sku}"


class CheckoutQuerySet(models.QuerySet):
    def open(self):
        """Still out (not returned): OPEN plus overdue-flagged rows."""
        return self.filter(status__in=(Checkout.Status.OPEN, Checkout.Status.OVERDUE))

    def overdue(self):
        return self.open().filter(due_at__lt=timezone.now())

    def returned(self):
        return self.filter(status=Checkout.Status.RETURNED)


class Checkout(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        RETURNED = "returned", "Returned"
        OVERDUE = "overdue", "Overdue"

    tool = models.ForeignKey(Tool, on_delete=models.PROTECT, related_name="checkouts")
    borrower = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="checkouts"
    )
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="checkouts_issued"
    )
    checked_out_at = models.DateTimeField(auto_now_add=True, db_index=True)
    due_at = models.DateTimeField(db_index=True)
    returned_at = models.DateTimeField(null=True, blank=True, db_index=True)
    condition_out = models.CharField(
        max_length=12, choices=Tool.Condition.choices, default=Tool.Condition.NEW
    )
    condition_in = models.CharField(
        max_length=12, choices=Tool.Condition.choices, blank=True
    )
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.OPEN, db_index=True
    )
    notes = models.CharField(max_length=255, blank=True)

    objects = CheckoutQuerySet.as_manager()

    class Meta:
        ordering = ["-checked_out_at"]
        indexes = [
            models.Index(fields=["tool", "status"]),
            models.Index(fields=["status", "due_at"]),
        ]

    def __str__(self):
        return f"{self.tool.sku} → {self.borrower} ({self.status})"

    @property
    def is_overdue(self) -> bool:
        return self.returned_at is None and self.due_at < timezone.now()
