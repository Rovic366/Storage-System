"""Report datasets: shared builders for CSV and PDF exports."""

from __future__ import annotations

import datetime as dt

from django.db.models import Q
from django.utils import timezone

from inventory.models import Tool
from maintenance.models import MaintenanceLog
from transactions.models import Checkout, StockMovement


def _parse_range(request) -> tuple[dt.datetime, dt.datetime, str]:
    now = timezone.now()
    try:
        days = int(request.GET.get("days", "30"))
    except (TypeError, ValueError):
        days = 30
    days = max(1, min(365, days))
    default_start = now - dt.timedelta(days=days)
    start_raw = request.GET.get("start") or ""
    end_raw = request.GET.get("end") or ""
    try:
        start = (dt.datetime.fromisoformat(start_raw) if start_raw else default_start)
        end = dt.datetime.fromisoformat(end_raw) if end_raw else now
    except ValueError:
        start, end = default_start, now
    if timezone.is_naive(start):
        start = timezone.make_aware(start, timezone.get_current_timezone())
    if timezone.is_naive(end):
        end = timezone.make_aware(end, timezone.get_current_timezone())
    if start > end:
        start, end = end, start
    return start, end, request.GET.get("wh") or ""


def inventory_valuation_rows(wh: str = ""):
    qs = (
        Tool.objects.filter(location__warehouse=wh if wh else Q_all())
        .select_related("category", "supplier", "location")
        .order_by("sku")
    )
    rows = []
    total = 0.0
    for tool in qs:
        value = float(tool.unit_cost) * tool.quantity_on_hand
        total += value
        rows.append([
            tool.sku, tool.name, tool.category.name, tool.supplier.name,
            tool.location.code, tool.location.warehouse, tool.quantity_on_hand,
            tool.reorder_level, float(tool.unit_cost), round(value, 2),
            tool.get_status_display(),
        ])
    return rows, round(total, 2)


def Q_all():
    from django.db.models import Q

    return Q()


def movement_history_rows(wh: str = "", start=None, end=None, limit=2000):
    qs = StockMovement.objects.select_related("tool", "from_location", "to_location",
                                              "performed_by")
    if wh:
        qs = qs.filter(tool__location__warehouse=wh)
    if start and end:
        qs = qs.filter(timestamp__range=(start, end))
    rows = []
    for m in qs.order_by("-timestamp")[:limit]:
        rows.append([
            timezone.localtime(m.timestamp).strftime("%Y-%m-%d %H:%M"),
            m.get_type_display(), m.tool.sku, m.tool.name, m.quantity,
            m.from_location.code if m.from_location else "—",
            m.to_location.code if m.to_location else "—",
            m.performed_by.username if m.performed_by else "",
            m.reference_no or "",
        ])
    return rows


def overdue_rows_report(wh: str = ""):
    now = timezone.now()
    qs = Checkout.objects.open().filter(due_at__lt=now)
    if wh:
        qs = qs.filter(tool__location__warehouse=wh)
    rows = []
    for c in qs.order_by("due_at").select_related("tool", "borrower"):
        rows.append([
            c.pk, c.tool.sku, c.tool.name, c.borrower.username,
            timezone.localtime(c.due_at).strftime("%Y-%m-%d %H:%M"),
            max(1, (now - c.due_at).days),
            c.borrower.email,
        ])
    return rows


def maintenance_history_rows(wh: str = "", start=None, end=None, limit=2000):
    qs = MaintenanceLog.objects.select_related("tool", "schedule", "performed_by")
    if wh:
        qs = qs.filter(tool__location__warehouse=wh)
    if start and getattr(start, "date", None):
        qs = qs.filter(date__gte=start.date())
    if end and getattr(end, "date", None):
        qs = qs.filter(date__lte=end.date())
    rows = []
    total_cost = 0.0
    for log in qs.order_by("-date")[:limit]:
        total_cost += float(log.cost)
        rows.append([
            log.date.strftime("%Y-%m-%d"), log.tool.sku, log.tool.name,
            log.get_task_type_display(),
            log.performed_by.username if log.performed_by else "",
            float(log.cost), (log.notes or "")[:80],
        ])
    return rows, round(total_cost, 2)


def report_rows(slug: str, request):
    """Dispatch: returns (title, columns, rows, meta)."""
    start, end, wh = _parse_range(request)
    if slug == "inventory-valuation":
        title = "Inventory Valuation"
        columns = ["SKU", "Name", "Category", "Supplier", "Location", "Warehouse",
                   "Qty", "Reorder", "Unit cost", "Total value", "Status"]
        rows, meta = inventory_valuation_rows(wh)
        meta = {"grand_total": meta}
    elif slug == "movement-history":
        title = "Movement History"
        columns = ["Timestamp", "Type", "SKU", "Tool", "Qty", "From", "To",
                   "By", "Reference"]
        rows = movement_history_rows(wh, start, end)
        meta = {"window": f"{start:%Y-%m-%d} → {end:%Y-%m-%d}"}
    elif slug == "overdue-checkouts":
        title = "Overdue Checkouts"
        columns = ["Checkout", "SKU", "Tool", "Borrower", "Due", "Days late", "Email"]
        rows = overdue_rows_report(wh)
        meta = {}
    elif slug == "maintenance-history":
        title = "Maintenance History"
        columns = ["Date", "SKU", "Tool", "Task", "Performed by", "Cost", "Notes"]
        rows, meta = maintenance_history_rows(wh, start, end)
        meta = {"total_cost": meta}
    else:
        raise KeyError(slug)
    return title, columns, rows, meta
