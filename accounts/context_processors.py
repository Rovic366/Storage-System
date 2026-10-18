"""Global context for the persistent chrome (sidebar, topbar, alerts bell)."""

from __future__ import annotations

from maintenance.models import MaintenanceSchedule
from transactions.models import Checkout
from inventory.models import Location, Tool

from . import roles


def ui_context(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}
    warehouses = (
        Location.objects.order_by("warehouse").values_list("warehouse", flat=True).distinct()
    )
    overdue_open = Checkout.objects.open().filter(due_at__lt=timezone_now()).count()
    low_stock = Tool.objects.low_stock().count()
    due_maint = MaintenanceSchedule.objects.due_within(7).count()
    return {
        "nav_user": user,
        "nav_role": roles.get_role(user),
        "warehouses": list(warehouses),
        "bell_counts": {
            "overdue": overdue_open,
            "low_stock": low_stock,
            "maintenance": due_maint,
            "total": overdue_open + low_stock + due_maint,
        },
    }


def timezone_now():
    from django.utils import timezone

    return timezone.now()
