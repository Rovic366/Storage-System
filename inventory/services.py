"""Inventory business logic.

Every stock mutation goes through exactly one of these functions inside
transaction.atomic(); views must never touch quantity_on_hand directly.
Each function validates, updates stock with a row lock, writes a StockMovement
and an AuditLog entry within the same transaction.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Sum

from accounts.services import audit
from transactions.models import StockMovement


class StockError(Exception):
    """Domain validation error, surfaced to forms as a friendly message."""


def location_occupancy(location) -> int:
    return location.tools.aggregate(u=Sum("quantity_on_hand"))["u"] or 0


def capacity_remaining(location) -> int:
    return max(0, location.capacity - location_occupancy(location))


def _check_capacity(location, incoming: int):
    if location.is_active is False:
        raise StockError(f"Location {location.code} is inactive.")
    remaining = capacity_remaining(location)
    if incoming > remaining:
        raise StockError(
            f"Location {location.code} has no capacity: {location_occupancy(location)}/"
            f"{location.capacity} units occupied, remaining {remaining} < {incoming} incoming."
        )


def _ensure_active_tool(tool):
    if tool.status in (tool.Status.RETIRED, tool.Status.LOST):
        raise StockError(f"Tool {tool.sku} is {tool.get_status_display()}; stock ops are blocked.")


def receive_stock(tool, qty, performed_by, to_location=None,
                  *, reference_no: str = "", notes: str = ""):
    """Add units to a tool. Optionally re-bin the tool (moves the record)."""
    if qty <= 0:
        raise StockError("Receive quantity must be at least 1.")
    _ensure_active_tool(tool)
    location = to_location or tool.location
    with transaction.atomic():
        locked = type(tool).objects.select_for_update().get(pk=tool.pk)
        if to_location is not None and locked.location.pk != to_location.pk:
            _check_capacity(to_location, qty)
            _check_capacity(to_location, 0)
            new_location = to_location
        else:
            _check_capacity(locked.location, qty)
            new_location = locked.location
        new_qty = locked.quantity_on_hand + qty
        type(tool).objects.filter(pk=locked.pk).update(
            quantity_on_hand=new_qty, location=new_location
        )
        StockMovement.objects.create(
            tool=locked, type=StockMovement.Type.RECEIVE, quantity=qty,
            to_location=new_location, performed_by=performed_by,
            reference_no=reference_no, notes=notes,
        )
        audit(performed_by, "RECEIVE_STOCK", locked,
              meta={"qty": qty, "location": new_location.code, "reference": reference_no})
        locked.refresh_from_db()
        tool.quantity_on_hand = locked.quantity_on_hand
        tool.location = locked.location
        return tool


def issue_stock(tool, qty, performed_by, *, reference_no: str = "", notes: str = ""):
    if qty <= 0:
        raise StockError("Issue quantity must be at least 1.")
    _ensure_active_tool(tool)
    with transaction.atomic():
        locked = type(tool).objects.select_for_update().get(pk=tool.pk)
        if locked.quantity_on_hand < qty:
            raise StockError(
                f"Insufficient stock: {locked.sku} has {locked.quantity_on_hand} on hand, "
                f"cannot issue {qty}."
            )
        type(tool).objects.filter(pk=locked.pk).update(
            quantity_on_hand=locked.quantity_on_hand - qty
        )
        StockMovement.objects.create(
            tool=locked, type=StockMovement.Type.ISSUE, quantity=qty,
            from_location=locked.location, performed_by=performed_by,
            reference_no=reference_no, notes=notes,
        )
        audit(performed_by, "ISSUE_STOCK", locked,
              meta={"qty": qty, "location": locked.location.code, "reference": reference_no})
        locked.refresh_from_db()
        tool.quantity_on_hand = locked.quantity_on_hand
        return tool


def transfer_stock(tool, to_location, performed_by, *, reference_no: str = "", notes: str = ""):
    """Whole-tool transfer: a tool record has a single storage address, so the
    transfer moves its full on-hand quantity to the target bin."""
    _ensure_active_tool(tool)
    if to_location.pk == tool.location.pk:
        raise StockError("Target location equals the tool's current location.")
    with transaction.atomic():
        locked = type(tool).objects.select_for_update().get(pk=tool.pk)
        _check_capacity(to_location, locked.quantity_on_hand)
        from_location = locked.location
        locked.location = to_location
        locked.save(update_fields=["location", "updated_at"])
        StockMovement.objects.create(
            tool=locked, type=StockMovement.Type.TRANSFER, quantity=locked.quantity_on_hand,
            from_location=from_location, to_location=to_location, performed_by=performed_by,
            reference_no=reference_no, notes=notes,
        )
        audit(performed_by, "TRANSFER_STOCK", locked,
              meta={"qty": locked.quantity_on_hand,
                    "from": from_location.code, "to": to_location.code,
                    "reference": reference_no})
        tool.location = to_location
        return tool


def adjust_stock(tool, delta, performed_by, *, notes: str = "", scrap: bool = False):
    """Stock-take delta: positive restock, negative shrinkage."""
    if delta == 0:
        raise StockError("Adjustment amount must not be zero.")
    _ensure_active_tool(tool)
    with transaction.atomic():
        locked = type(tool).objects.select_for_update().get(pk=tool.pk)
        new_qty = locked.quantity_on_hand + delta
        if new_qty < 0:
            raise StockError(
                f"Adjustment would go negative: {locked.sku} has {locked.quantity_on_hand} "
                f"on hand, delta {delta}."
            )
        type(tool).objects.filter(pk=locked.pk).update(quantity_on_hand=new_qty)
        StockMovement.objects.create(
            tool=locked,
            type=StockMovement.Type.SCRAP if (scrap and delta < 0) else StockMovement.Type.ADJUST,
            quantity=abs(delta),
            from_location=locked.location if delta < 0 else None,
            to_location=locked.location if delta > 0 else None,
            performed_by=performed_by, notes=notes or ("Scrap" if scrap and delta < 0 else ""),
        )
        action = "SCRAP_STOCK" if (scrap and delta < 0) else "ADJUST_STOCK"
        audit(performed_by, action, locked,
              meta={"delta": delta, "new_qty": new_qty, "location": locked.location.code})
        locked.refresh_from_db()
        tool.quantity_on_hand = locked.quantity_on_hand
        return tool


def scrap_stock(tool, qty, performed_by, *, notes: str = ""):
    if qty <= 0:
        raise StockError("Scrap quantity must be at least 1.")
    return adjust_stock(tool, -abs(qty), performed_by, notes=notes, scrap=True)


def quick_set_quantity(tool, new_qty, performed_by, *, notes: str = ""):
    """Inline quick edit records the delta as a normal adjustment."""
    if new_qty < 0:
        raise StockError("Quantity cannot be negative.")
    with transaction.atomic():
        locked = type(tool).objects.select_for_update().get(pk=tool.pk)
        delta = new_qty - locked.quantity_on_hand
        if delta == 0:
            return tool
        adjust_stock(tool, delta, performed_by, notes=notes or "Quick edit")
    return tool


def move_tool_status(tool, new_status, performed_by):
    """Direct status change (e.g. bulk Retire). Audited; guards open checkouts."""
    if new_status not in tool.Status.values:
        raise StockError(f"Unknown status '{new_status}'.")
    if tool.status == new_status:
        return tool
    with transaction.atomic():
        locked = type(tool).objects.select_for_update().get(pk=tool.pk)
        has_open = locked.checkouts.open().exists()
        if has_open and new_status not in (tool.Status.CHECKED_OUT, tool.Status.AVAILABLE):
            raise StockError(
                f"{locked.sku} still has open checkout(s); settle them before changing status."
            )
        locked.status = new_status
        locked.save(update_fields=["status", "updated_at"])
        audit(performed_by, "STATUS_CHANGE", locked, meta={"to": new_status})
        tool.status = new_status
        return tool


def retire_tools(tools, performed_by):
    """Bulk retire with audit rows."""
    retired = []
    with transaction.atomic():
        for tool in tools.select_for_update():
            if tool.status == tool.Status.RETIRED:
                continue
            tool.status = tool.Status.RETIRED
            tool.save(update_fields=["status", "updated_at"])
            audit(performed_by, "RETIRE_TOOL", tool, meta={"from": tool.Status.RETIRED})
            retired.append(tool.sku)
    return retired
