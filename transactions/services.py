"""Checkout / return / movement operations.

Re-exports the stock operations from inventory.services so views/forms can
import everything from one place.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from accounts.services import audit
from inventory.models import Tool
from inventory.services import StockError
from transactions.models import Checkout, StockMovement

# convenience re-exports
from inventory.services import (  # noqa: F401
    adjust_stock,
    quick_set_quantity,
    receive_stock,
    scrap_stock,
    transfer_stock,
)


def checkout_tool(tool, borrower, due_at, issued_by, *, condition_out: str = Tool.Condition.NEW,
                  notes: str = "") -> Checkout:
    """Check out one unit of a tool to a borrower.

    Rule set: tool must be active, Available, have units on hand, no duplicate
    open checkout, and a due date in the future. Records the ISSUE movement,
    flips tool status to CHECKED_OUT and writes an audit row — all atomic.
    """
    if timezone.is_naive(due_at):
        due_at = timezone.make_aware(due_at, timezone.get_current_timezone())
    if due_at <= timezone.now():
        raise StockError("Due date/time must be in the future.")
    if tool.status in (Tool.Status.RETIRED, Tool.Status.LOST, Tool.Status.IN_MAINTENANCE):
        raise StockError(f"Tool {tool.sku} is {tool.get_status_display()}; cannot check out.")
    if tool.quantity_on_hand < 1:
        raise StockError(f"Tool {tool.sku} has no units on hand to check out.")
    with transaction.atomic():
        locked_tool = Tool.objects.select_for_update().get(pk=tool.pk)
        if locked_tool.checkouts.open().exists():
            raise StockError(f"Tool {locked_tool.sku} already has an open checkout.")
        checkout = Checkout.objects.create(
            tool=locked_tool, borrower=borrower, issued_by=issued_by,
            due_at=due_at, condition_out=condition_out, notes=notes,
        )
        Tool.objects.filter(pk=locked_tool.pk).update(
            quantity_on_hand=locked_tool.quantity_on_hand - 1,
            status=Tool.Status.CHECKED_OUT,
        )
        StockMovement.objects.create(
            tool=locked_tool, type=StockMovement.Type.ISSUE, quantity=1,
            from_location=locked_tool.location, performed_by=issued_by,
            reference_no=f"CHK-{checkout.pk}", notes=f"Checkout to {borrower}",
        )
        audit(issued_by, "CHECKOUT_TOOL", checkout,
              meta={"tool": locked_tool.sku, "borrower": borrower.username,
                    "due_at": due_at.isoformat()})
        checkout.refresh_from_db()
        tool.quantity_on_hand = max(0, tool.quantity_on_hand - 1)
        tool.status = Tool.Status.CHECKED_OUT
        return checkout


def return_tool(checkout, performed_by, *, condition_in: str = "", notes: str = "") -> Checkout:
    """Record a return: sets returned_at, final status, inbound condition;
    flips the tool back to Available (when no other open checkouts remain);
    records the RETURN movement; writes an audit row — all atomic."""
    if checkout.returned_at is not None:
        raise StockError("This checkout was already returned.")
    condition_in = condition_in or checkout.condition_out
    if condition_in not in Tool.Condition.values:
        raise StockError("Invalid returned condition.")
    with transaction.atomic():
        locked = Checkout.objects.select_for_update().get(pk=checkout.pk)
        if locked.returned_at is not None:  # race guard
            raise StockError("This checkout was already returned.")
        now = timezone.now()
        locked.returned_at = now
        locked.status = Checkout.Status.RETURNED
        locked.condition_in = condition_in
        if notes:
            locked.notes = (locked.notes + f" | {notes}").strip(" |")
        locked.save(update_fields=["returned_at", "status", "condition_in", "notes"])
        tool = locked.tool
        other_open = tool.checkouts.open().exists()
        new_status = Tool.Status.CHECKED_OUT if other_open else Tool.Status.AVAILABLE
        # A return delivers the unit back into crib stock and can restore an
        # item reported lost before checkout to "in stock" accounting.
        Tool.objects.filter(pk=tool.pk).update(
            quantity_on_hand=tool.quantity_on_hand + 1,
            status=new_status,
            condition=condition_in,
        )
        StockMovement.objects.create(
            tool=tool, type=StockMovement.Type.RETURN, quantity=1,
            to_location=tool.location, performed_by=performed_by,
            reference_no=f"CHK-{locked.pk}", notes=f"Return from {locked.borrower}",
        )
        audit(performed_by, "RETURN_TOOL", locked,
              meta={"tool": tool.sku, "borrower": locked.borrower.username,
                    "condition_in": condition_in,
                    "was_overdue": locked.due_at < now})
        locked.refresh_from_db()
        tool.quantity_on_hand += 1
        tool.status = new_status
        tool.condition = condition_in
        return locked


def sweep_overdue_checkouts() -> int:
    """Mark still-open checkouts past their due date as OVERDUE.

    Idempotent; called on dashboard load and by the maintenance command.
    """
    return (
        Checkout.objects.open()
        .filter(due_at__lt=timezone.now(), status=Checkout.Status.OPEN)
        .update(status=Checkout.Status.OVERDUE)
    )
