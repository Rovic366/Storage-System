from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Category(models.Model):
    name = models.CharField(max_length=64)
    parent = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True, related_name="children"
    )
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["name", "parent"], name="uniq_category_name_per_parent"
            )
        ]
        verbose_name_plural = "categories"

    def __str__(self):
        return f"{self.parent.name} › {self.name}" if self.parent else self.name


class Supplier(models.Model):
    name = models.CharField(max_length=128, unique=True)
    contact_person = models.CharField(max_length=128, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=32, blank=True)
    lead_time_days = models.PositiveSmallIntegerField(default=7)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Location(models.Model):
    """A discrete storage address: warehouse › zone › rack › shelf › bin."""

    warehouse = models.CharField(max_length=64, db_index=True)
    zone = models.CharField(max_length=8, default="A")
    rack = models.CharField(max_length=8, default="1")
    shelf = models.CharField(max_length=8, default="1")
    bin = models.CharField(max_length=8, default="A")
    code = models.CharField(max_length=48, unique=True, db_index=True)
    capacity = models.PositiveIntegerField(default=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["warehouse", "zone", "rack", "shelf", "bin"]
        constraints = [
            models.UniqueConstraint(
                fields=["warehouse", "zone", "rack", "shelf", "bin"],
                name="uniq_location_address",
            )
        ]

    def __str__(self):
        return self.code

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = f"{self.warehouse}-{self.zone}-{self.rack}-{self.shelf}-{self.bin}"
        super().save(*args, **kwargs)


class ToolQuerySet(models.QuerySet):
    ACTIVE_STATUSES = ["available", "checked_out", "in_maintenance"]

    def active(self):
        return self.filter(status__in=self.ACTIVE_STATUSES)

    def low_stock(self):
        return self.active().filter(quantity_on_hand__lte=models.F("reorder_level")).filter(
            quantity_on_hand__gt=0
        )

    def out_of_stock(self):
        return self.active().filter(quantity_on_hand=0)

    def stock_alerts(self):
        return self.active().filter(
            quantity_on_hand__lte=models.F("reorder_level"),
        )

    def search(self, query: str):
        q = query.strip()
        if not q:
            return self
        from django.db.models import Q

        return self.filter(
            Q(sku__icontains=q)
            | Q(name__icontains=q)
            | Q(manufacturer__icontains=q)
            | Q(model_number__icontains=q)
            | Q(serial_number__icontains=q)
        )

    def valuation(self):
        return self.aggregate(
            total=models.Sum(
                models.ExpressionWrapper(
                    models.F("unit_cost") * models.F("quantity_on_hand"),
                    output_field=models.DecimalField(max_digits=16, decimal_places=2),
                )
            )
        )["total"] or Decimal("0")


class ToolManager(models.Manager.from_queryset(ToolQuerySet)):
    pass


class Tool(TimeStampedModel):
    class Status(models.TextChoices):
        AVAILABLE = "available", "Available"
        CHECKED_OUT = "checked_out", "Checked Out"
        IN_MAINTENANCE = "in_maintenance", "In Maintenance"
        RETIRED = "retired", "Retired"
        LOST = "lost", "Lost"

    class Condition(models.TextChoices):
        NEW = "new", "New"
        GOOD = "good", "Good"
        FAIR = "fair", "Fair"
        POOR = "poor", "Poor"

    sku = models.CharField("SKU", max_length=32, unique=True, db_index=True)
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="tools")
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="tools")
    manufacturer = models.CharField(max_length=128, blank=True)
    model_number = models.CharField(max_length=64, blank=True)
    serial_number = models.CharField(max_length=64, blank=True, db_index=True)

    unit_cost = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    quantity_on_hand = models.PositiveIntegerField(default=0)
    reorder_level = models.PositiveSmallIntegerField(default=5)
    max_stock_level = models.PositiveIntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(1)],
    )
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="tools")
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.AVAILABLE, db_index=True
    )
    condition = models.CharField(
        max_length=12, choices=Condition.choices, default=Condition.NEW
    )
    requires_calibration = models.BooleanField(default=False)
    image = models.ImageField(upload_to="tools/%Y/%m/", blank=True)
    barcode_value = models.CharField(max_length=64, unique=True, blank=True, db_index=True)

    objects = ToolManager()

    class Meta:
        ordering = ["sku"]
        indexes = [
            models.Index(fields=["status", "location"]),
            models.Index(fields=["location"]),
            models.Index(fields=["category", "status"]),
            models.Index(fields=["created_at"]),
        ]
        permissions = [("retire_tool", "Can retire a tool")]

    def __str__(self):
        return f"{self.sku} · {self.name}"

    def save(self, *args, **kwargs):
        if not self.barcode_value:
            self.barcode_value = self.sku
        super().save(*args, **kwargs)

    @property
    def stock_state(self) -> str:
        if self.status in (self.Status.RETIRED, self.Status.LOST):
            return "inactive"
        if self.quantity_on_hand == 0:
            return "out"
        if self.quantity_on_hand <= self.reorder_level:
            return "low"
        return "ok"

    @property
    def is_serialized(self) -> bool:
        return self.quantity_on_hand <= 1 and self.max_stock_level == 1
