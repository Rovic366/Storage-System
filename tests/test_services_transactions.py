"""Checkout / return / sweep business rules."""

import datetime as dt

import pytest
from django.utils import timezone

from inventory.models import Tool
from inventory.services import StockError
from transactions import services as tx
from transactions.models import Checkout, StockMovement

pytestmark = pytest.mark.django_db


def test_checkout_ok(make_tool, borrower, due_soon):
    tool = make_tool(quantity_on_hand=3)
    co = tx.checkout_tool(tool, borrower, due_soon(), borrower)
    assert co.status == Checkout.Status.OPEN
    tool.refresh_from_db()
    assert tool.quantity_on_hand == 2
    assert tool.status == Tool.Status.CHECKED_OUT
    assert StockMovement.objects.filter(tool=tool, type="issue").exists()


def test_checkout_duplicate_open_blocked(make_tool, borrower, due_soon):
    tool = make_tool(quantity_on_hand=2)
    tx.checkout_tool(tool, borrower, due_soon(), borrower)
    with pytest.raises(StockError):
        tx.checkout_tool(tool, borrower, due_soon(), borrower)


def test_checkout_requires_stock(make_tool, borrower, due_soon):
    tool = make_tool(quantity_on_hand=0)
    with pytest.raises(StockError):
        tx.checkout_tool(tool, borrower, due_soon(), borrower)


def test_checkout_past_due_blocked(make_tool, borrower):
    tool = make_tool(quantity_on_hand=2)
    past = timezone.now() - dt.timedelta(days=1)
    with pytest.raises(StockError):
        tx.checkout_tool(tool, borrower, past, borrower)


def test_checkout_blocked_states(make_tool, borrower, due_soon):
    for status in (Tool.Status.RETIRED, Tool.Status.LOST, Tool.Status.IN_MAINTENANCE):
        tool = make_tool(status=status)
        with pytest.raises(StockError):
            tx.checkout_tool(tool, borrower, due_soon(), borrower)


def test_return_restores(make_tool, borrower, due_soon):
    tool = make_tool(quantity_on_hand=4)
    co = tx.checkout_tool(tool, borrower, due_soon(), borrower)
    updated = tx.return_tool(co, borrower, condition_in="good", notes="wiped")
    assert updated.status == Checkout.Status.RETURNED
    assert updated.returned_at is not None
    assert updated.condition_in == "good"
    tool.refresh_from_db()
    assert tool.quantity_on_hand == 4
    assert tool.status == Tool.Status.AVAILABLE
    assert tool.condition == "good"
    assert StockMovement.objects.filter(tool=tool, type="return").exists()


def test_return_twice_blocked(make_tool, borrower, due_soon):
    tool = make_tool(quantity_on_hand=1)
    co = tx.checkout_tool(tool, borrower, due_soon(), borrower)
    tx.return_tool(co, borrower)
    with pytest.raises(StockError):
        tx.return_tool(co, borrower)


def test_sweep_flips_only_past_due(make_tool, borrower):
    tool = make_tool(quantity_on_hand=3)
    future = timezone.now() + dt.timedelta(days=2)
    co1 = tx.checkout_tool(tool, borrower, future, borrower)
    tool2 = make_tool(quantity_on_hand=3)
    co2 = tx.checkout_tool(tool2, borrower, future, borrower)

    # time passes: co1's due date lapses (simulated by direct update)
    Checkout.objects.filter(pk=co1.pk).update(
        due_at=timezone.now() - dt.timedelta(days=1))

    changed = tx.sweep_overdue_checkouts()
    assert changed >= 1
    co1.refresh_from_db()
    co2.refresh_from_db()
    assert co1.status == Checkout.Status.OVERDUE
    assert co2.status == Checkout.Status.OPEN

    open_qs = Checkout.objects.open()
    assert open_qs.filter(pk=co1.pk).exists()
    assert open_qs.filter(pk=co2.pk).exists()
    assert Checkout.objects.overdue().filter(pk=co1.pk).exists()
    assert not Checkout.objects.overdue().filter(pk=co2.pk).exists()


def test_sweep_idempotent(make_tool, borrower):
    tool = make_tool(quantity_on_hand=2)
    future = timezone.now() + dt.timedelta(days=1)
    co = tx.checkout_tool(tool, borrower, future, borrower)
    Checkout.objects.filter(pk=co.pk).update(
        due_at=timezone.now() - dt.timedelta(days=1))
    assert tx.sweep_overdue_checkouts() >= 1
    assert tx.sweep_overdue_checkouts() == 0
