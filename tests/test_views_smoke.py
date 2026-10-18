"""HTTP smoke tests: auth, roles, pages, fragments, exports, JSON APIs."""

import datetime as dt

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------- anonymous

def test_anonymous_redirects_to_login(client):
    assert client.get(reverse("dashboard:index")).status_code == 302
    assert client.get(reverse("inventory:list")).status_code == 302


def test_login_page_renders(client):
    resp = client.get(reverse("accounts:login"))
    assert resp.status_code == 200
    assert b"STORAGE" in resp.content or b"Storage" in resp.content


# ---------------------------------------------------------------- dashboard

def test_dashboard_renders_for_admin(admin_client):
    resp = admin_client.get(reverse("dashboard:index"))
    assert resp.status_code == 200
    assert resp["X-Render-MS"]


def test_dashboard_fragment(admin_client):
    resp = admin_client.get(reverse("dashboard:grid"), {"range": "30"})
    assert resp.status_code == 200


def test_dashboard_feed(admin_client):
    resp = admin_client.get(reverse("dashboard:feed"))
    assert resp.status_code == 200


def test_api_dashboard_json(admin_client):
    import json

    resp = admin_client.get(reverse("dashboard:api_dashboard"))
    assert resp.status_code == 200
    data = json.loads(resp.content)
    for key in ("kpis", "movement_trend", "status_distribution", "overdue"):
        assert key in data, key


@pytest.mark.parametrize("slug", [
    "kpis", "trend", "categories", "statuses", "heatmap", "top_tools",
    "capacity", "low_stock", "overdue", "maintenance", "feed",
])
def test_api_widgets(admin_client, slug):
    resp = admin_client.get(f"/api/widget/{slug}/")
    assert resp.status_code == 200, slug


def test_api_widget_unknown(admin_client):
    assert admin_client.get("/api/widget/nope/").status_code == 404


def test_api_search(admin_client, make_tool):
    make_tool(sku="SPX-0001")
    resp = admin_client.get("/api/search/", {"q": "SPX"})
    assert resp.status_code == 200
    assert resp.json()["count"] >= 1


# ---------------------------------------------------------------- inventory

def test_inventory_list(admin_client, make_tool):
    make_tool()
    resp = admin_client.get(reverse("inventory:list"))
    assert resp.status_code == 200


def test_inventory_fragment(admin_client, make_tool):
    make_tool()
    resp = admin_client.get(reverse("inventory:list"), {"fragment": "table"})
    assert resp.status_code == 200
    assert b"data-bulk-url" in resp.content


def test_inventory_filters(admin_client, make_tool):
    make_tool(sku="FLX-01")
    for params in ({"q": "FLX"}, {"stock": "ok"}, {"sort": "qty", "dir": "desc"},
                   {}):
        assert admin_client.get(reverse("inventory:list"), params).status_code == 200


def test_drawer(admin_client, make_tool):
    tool = make_tool()
    resp = admin_client.get(reverse("inventory:drawer", args=[tool.pk]))
    assert resp.status_code == 200


def test_create_crud_pages(admin_client):
    assert admin_client.get(reverse("inventory:create")).status_code == 200


def test_detail_page(admin_client, make_tool):
    tool = make_tool()
    assert admin_client.get(reverse("inventory:detail", args=[tool.pk])).status_code == 200


def test_export_csv(admin_client, make_tool):
    make_tool(sku="CSV-01")
    resp = admin_client.get(reverse("inventory:export_csv"))
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/csv")


def test_quick_edit(admin_client, make_tool):
    from inventory.models import Tool

    tool = make_tool()
    resp = admin_client.post(reverse("inventory:quick_edit"),
                             {"tool_id": tool.pk, "quantity": 9,
                              "status": "", "back": "/inventory/"})
    assert resp.status_code == 302
    tool.refresh_from_db()
    assert tool.quantity_on_hand == 9


def test_bulk_move_and_retire(admin_client, make_tool, kit):
    from inventory.models import Location, Tool

    t1 = make_tool()
    t2 = make_tool()
    dest = Location.objects.create(warehouse="W9", zone="A", rack="01",
                                   shelf="1", bin="B", capacity=100,
                                   code="W9-A-01-1-B")
    resp = admin_client.post(reverse("inventory:bulk"),
                             {"action": "move", "ids": [t1.pk, t2.pk],
                              "target_location": dest.pk})
    assert resp.status_code == 302
    assert Tool.objects.filter(pk__in=[t1.pk, t2.pk],
                               location=dest).count() == 2


# ---------------------------------------------------------------- operations

def test_ops_page(admin_client):
    for op in ("receive", "issue", "transfer", "adjust"):
        assert admin_client.get(reverse("transactions:ops", args=[op])).status_code == 200


def test_ops_submit_receive(admin_client, make_tool):
    tool = make_tool()
    resp = admin_client.post(reverse("transactions:op_submit", args=["receive"]),
                             {"sku": tool.sku, "quantity": 2, "to_location": "",
                              "reference_no": "", "notes": ""})
    assert resp.status_code == 302
    tool.refresh_from_db()
    assert tool.quantity_on_hand == 7


def test_ops_submit_error_renders_400(admin_client, make_tool):
    from inventory.models import Tool

    tool = make_tool(status=Tool.Status.RETIRED)
    resp = admin_client.post(reverse("transactions:op_submit", args=["adjust"]),
                             {"sku": tool.sku, "delta": "1", "notes": ""},
                             raise_request_exception=False)
    assert resp.status_code == 400


def test_checkout_fast_flow(admin_client, make_tool):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    borrower = User.objects.create_user("bob", "bob@x.example", "pw-123456")
    tool = make_tool(quantity_on_hand=3)
    url = reverse("transactions:checkout_new")
    due = (dt.datetime.now() + dt.timedelta(days=2)).strftime("%Y-%m-%d")
    resp = admin_client.post(url, {"sku": tool.sku, "borrower": borrower.pk,
                                   "due_at_0": due, "due_at_1": "17:00",
                                   "notes": ""})
    assert resp.status_code == 302


def test_checkout_pages(admin_client, make_tool, borrower, due_soon):
    from transactions import services as tx

    tool = make_tool()
    tx.checkout_tool(tool, borrower, due_soon(), borrower)
    assert admin_client.get(reverse("transactions:checkout_list")).status_code == 200
    assert admin_client.get(reverse("transactions:checkout_list"),
                            {"tab": "overdue"}).status_code == 200


def test_return_form_flow(admin_client, make_tool, borrower, due_soon):
    from transactions import services as tx

    tool = make_tool()
    co = tx.checkout_tool(tool, borrower, due_soon(), borrower)
    assert admin_client.get(reverse("transactions:checkout_return",
                                    args=[co.pk])).status_code == 200
    resp = admin_client.post(reverse("transactions:checkout_return", args=[co.pk]),
                             {"condition_in": "good", "notes": ""})
    assert resp.status_code == 302


# ---------------------------------------------------------------- maintenance

def test_maintenance_pages(admin_client, make_tool):
    from maintenance.models import MaintenanceSchedule
    from django.utils import timezone
    import datetime as dt

    MaintenanceSchedule.objects.create(
        tool=make_tool(), task_type="inspection", interval_days=30,
        next_due=timezone.localdate())
    assert admin_client.get(reverse("maintenance:schedule")).status_code == 200
    assert admin_client.get(reverse("maintenance:create")).status_code == 200


def test_log_task_flow(admin_client, make_tool):
    import datetime as dt

    from maintenance.models import MaintenanceSchedule
    from django.utils import timezone

    schedule = MaintenanceSchedule.objects.create(
        tool=make_tool(), task_type="service", interval_days=60,
        next_due=timezone.localdate())
    url = reverse("maintenance:log_task", args=[schedule.pk])
    assert admin_client.get(url).status_code == 200
    resp = admin_client.post(url, {"task_type": "service", "date": str(timezone.localdate()),
                                   "cost": "0", "notes": ""})
    assert resp.status_code == 302


# ---------------------------------------------------------------- reports

@pytest.mark.parametrize("slug", [
    "inventory-valuation", "movement-history",
    "overdue-checkouts", "maintenance-history",
])
def test_report_pages(admin_client, slug):
    assert admin_client.get(f"/reports/{slug}/").status_code == 200


@pytest.mark.parametrize("kind", ["csv", "pdf"])
def test_report_exports(admin_client, kind):
    resp = admin_client.get(f"/reports/export/inventory-valuation.{kind}")
    assert resp.status_code == 200
    if kind == "csv":
        assert resp["Content-Type"] == "text/csv"
    else:
        assert resp.content[:5] == b"%PDF-"


# ---------------------------------------------------------------- audit

def test_audit_page(admin_client):
    assert admin_client.get(reverse("accounts:audit")).status_code == 200


# ---------------------------------------------------------------- role gating

def test_viewer_blocked_from_stock_role(tech_client):
    resp = tech_client.get(reverse("transactions:ops_default"),
                           raise_request_exception=False)
    assert resp.status_code == 403


def test_storekeeper_blocked_from_audit(store_client):
    resp = store_client.get(reverse("accounts:audit"), raise_request_exception=False)
    assert resp.status_code == 403


def test_admin_can_audit(admin_client):
    assert admin_client.get(reverse("accounts:audit")).status_code == 200
