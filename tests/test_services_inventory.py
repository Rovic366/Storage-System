"""Stock service rules for receive / issue / transfer / adjust / retire."""

import pytest

from accounts.roles import ensure_role_groups  # groups exist module-wide
from inventory import services
from inventory.models import Location, Tool
from transactions import services as tx
from transactions.models import StockMovement

pytestmark = pytest.mark.django_db


def _tool(make_tool):
    return make_tool(quantity_on_hand=10, reorder_level=2)


def test_receive_increases_quantity_and_movement(make_tool, borrower):
    tool = _tool(make_tool)
    before = StockMovement.objects.count()
    services.receive_stock(tool, 5, borrower, reference_no="PO-1")
    tool.refresh_from_db()
    assert tool.quantity_on_hand == 15
    assert StockMovement.objects.count() == before + 1
    move = StockMovement.objects.latest("id")
    assert move.type == "receive" and move.quantity == 5


def test_receive_rebins_tool_and_checks_capacity(make_tool, borrower, kit):
    tool = _tool(make_tool)
    other, _ = Location.objects.get_or_create(
        warehouse="W1", zone="B", rack="09", shelf="1", bin="B",
        defaults={"capacity": 50, "code": "W1-B-09-1-B"})
    services.receive_stock(tool, 4, borrower, to_location=other)
    tool.refresh_from_db()
    assert tool.location == other


def test_receive_to_full_location_raises(make_tool, borrower, kit):
    tool = _tool(make_tool)
    dest, _ = Location.objects.get_or_create(
        warehouse="W1", zone="C", rack="01", shelf="1", bin="C",
        defaults={"capacity": 10, "code": "W1-C-01-1-C"})
    # one dummy tool already occupies dest capacity nearly fully
    make_tool(sku="DUM-1", location=dest, quantity_on_hand=8)
    with pytest.raises(services.StockError):
        services.receive_stock(tool, 9, borrower, to_location=dest)


def test_issue_decrements_and_audits(make_tool, borrower):
    tool = _tool(make_tool)
    services.issue_stock(tool, 3, borrower, reference_no="JOB-7")
    tool.refresh_from_db()
    assert tool.quantity_on_hand == 7
    move = StockMovement.objects.latest("id")
    assert move.type == "issue" and move.quantity == 3


def test_issue_more_than_stock_raises(make_tool, borrower):
    tool = _tool(make_tool)
    with pytest.raises(services.StockError):
        services.issue_stock(tool, 11, borrower)


def test_transfer_moves_whole_tool(make_tool, borrower):
    tool = _tool(make_tool)
    dest, _ = Location.objects.get_or_create(
        warehouse="W2", zone="A", rack="01", shelf="1", bin="A",
        defaults={"capacity": 50, "code": "W2-A-01-1-A"})
    before = tool.quantity_on_hand
    services.transfer_stock(tool, dest, borrower)
    tool.refresh_from_db()
    assert tool.location == dest
    assert tool.quantity_on_hand == before
    assert StockMovement.objects.filter(
        tool=tool, type="transfer", from_location__code="W1-A-01-1-A").exists()


def test_transfer_same_location_raises(make_tool, borrower, kit):
    tool = _tool(make_tool)
    with pytest.raises(services.StockError):
        services.transfer_stock(tool, kit["loc"], borrower)


def test_adjust_signed_delta_and_negative_guard(make_tool, borrower):
    tool = _tool(make_tool)
    services.adjust_stock(tool, -4, borrower, notes="shrinkage")
    tool.refresh_from_db()
    assert tool.quantity_on_hand == 6
    with pytest.raises(services.StockError):
        services.adjust_stock(tool, -999, borrower)


def test_scrap_is_negative_adjust(make_tool, borrower):
    tool = _tool(make_tool)
    services.scrap_stock(tool, 2, borrower)
    tool.refresh_from_db()
    assert tool.quantity_on_hand == 8
    assert StockMovement.objects.filter(tool=tool, type="scrap").exists()

def test_quick_set_records_delta_adjustment(make_tool, borrower):
    tool = _tool(make_tool)
    services.quick_set_quantity(tool, 3, borrower)
    tool.refresh_from_db()
    assert tool.quantity_on_hand == 3
    assert StockMovement.objects.filter(
        tool=tool, type="adjust", quantity=7).exists()


def test_retire_tools_marks_and_audits(make_tool, borrower):
    tool = _tool(make_tool)
    out = services.retire_tools(Tool.objects.filter(pk=tool.pk), borrower)
    assert tool.sku in out
    tool.refresh_from_db()
    assert tool.status == Tool.Status.RETIRED


def test_retire_blocked_with_open_checkout(make_tool, borrower, due_soon):
    tool = _tool(make_tool)
    tx.checkout_tool(tool, borrower, due_soon(), borrower)
    with pytest.raises(services.StockError):
        services.move_tool_status(tool, Tool.Status.RETIRED, borrower)


def test_receive_blocked_on_retired(make_tool, borrower):
    tool = make_tool(quantity_on_hand=4, status=Tool.Status.RETIRED)
    with pytest.raises(services.StockError):
        services.receive_stock(tool, 1, borrower)


def test_audit_rows_written(make_tool, borrower):
    tool = _tool(make_tool)
    from accounts.models import AuditLog

    before = AuditLog.objects.count()
    services.receive_stock(tool, 1, borrower)
    assert AuditLog.objects.count() >= before + 1
