from __future__ import annotations

import time

from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.generic import TemplateView

from accounts.mixins import RoleRequiredMixin
from inventory.models import Tool
from transactions import services as tx


def _filters(request) -> dict:
    """Global dashboard filters: range (7/30/90 days) + warehouse name."""
    wh_options = _warehouse_names()
    rng = request.GET.get("range") or "30"
    if rng not in ("7", "30", "90"):
        rng = "30"
    wh = request.GET.get("wh") or ""
    if wh and wh not in wh_options:
        wh = ""
    return {"range": rng, "wh": wh}


def _warehouse_names() -> list[str]:
    from inventory.models import Location

    return list(
        Location.objects.order_by("warehouse").values_list("warehouse", flat=True).distinct()
    )


class DashboardView(RoleRequiredMixin, TemplateView):
    template_name = "dashboard/index.html"

    def get(self, request, *args, **kwargs):
        started = time.perf_counter()
        tx.sweep_overdue_checkouts()
        response = super().get(request, *args, **kwargs)
        elapsed = (time.perf_counter() - started) * 1000
        response["X-Render-MS"] = f"{elapsed:.0f}"
        return response

    def get_context_data(self, **kwargs):
        from dashboard.services import (
            chart_payloads, checkout_heatmap, kpi_cards, low_stock_rows, movement_trend,
            overdue_rows, recent_movements, status_distribution, top_tools,
            upcoming_maintenance, value_by_category, warehouse_capacity,
        )

        ctx = super().get_context_data(**kwargs)
        f = _filters(self.request)
        ctx = {
            "kpis": kpi_cards(f["range"], f["wh"]),
            "charts": chart_payloads(f["range"], f["wh"]),
            "heatmap": checkout_heatmap(f["range"], f["wh"]),
            "top_tools": top_tools(f["range"], f["wh"]),
            "capacity": warehouse_capacity(f["wh"]),
            "low_stock": low_stock_rows(f["wh"]),
            "overdue": overdue_rows(f["wh"]),
            "maintenance": upcoming_maintenance(f["wh"]),
            "feed": recent_movements(f["wh"], 15),
            "filters": f,
        }
        return ctx


def dashboard_fragment(request):
    """HTMX partial: re-renders the whole dashboard grid for the topbar filters."""
    from dashboard.services import (
        chart_payloads, checkout_heatmap, kpi_cards, low_stock_rows, overdue_rows,
        recent_movements, top_tools, upcoming_maintenance, warehouse_capacity,
    )

    if not request.user.is_authenticated:
        return redirect("accounts:login")
    f = _filters(request)
    html = render(request, "dashboard/partials/grid.html", {
        "kpis": kpi_cards(f["range"], f["wh"]),
        "charts": chart_payloads(f["range"], f["wh"]),
        "heatmap": checkout_heatmap(f["range"], f["wh"]),
        "top_tools": top_tools(f["range"], f["wh"]),
        "capacity": warehouse_capacity(f["wh"]),
        "low_stock": low_stock_rows(f["wh"]),
        "overdue": overdue_rows(f["wh"]),
        "maintenance": upcoming_maintenance(f["wh"]),
        "feed": recent_movements(f["wh"], 15),
        "filters": f,
    })
    response = HttpResponse(html)
    response["HX-Push-Url"] = request.path + f"?range={f['range']}&wh={f['wh']}"
    return response


def dashboard_feed(request):
    """HTMX polling partial for the recent-movements live feed."""
    from dashboard.services import recent_movements

    if not request.user.is_authenticated:
        return redirect("accounts:login")
    f = _filters(request)
    return render(request, "dashboard/partials/widgets/_feed_rows.html", {
        "feed": recent_movements(f["wh"], 15),
    })


def api_dashboard(request):
    """REST-style JSON bundle of every dashboard widget."""
    from django.http import JsonResponse

    if not request.user.is_authenticated:
        return JsonResponse({"error": "authentication required"}, status=401)
    f = _filters(request)
    from dashboard.services import dashboard_payload

    return JsonResponse(dashboard_payload(f["range"], f["wh"]))


def api_widget(request, slug: str):
    """JSON for one widget: kpis | trend | categories | statuses | heatmap |
    top_tools | capacity | low_stock | overdue | maintenance | feed."""
    import json as jsonlib
    from datetime import date, datetime
    from decimal import Decimal

    from django.http import JsonResponse

    from dashboard import services as S

    if not request.user.is_authenticated:
        return JsonResponse({"error": "authentication required"}, status=401)
    f = _filters(request)
    rng, wh = f["range"], f["wh"]
    mapping = {
        "kpis": lambda: S.kpi_cards(rng, wh),
        "trend": lambda: S.movement_trend(rng, wh),
        "categories": lambda: S.value_by_category(wh),
        "statuses": lambda: S.status_distribution(wh),
        "heatmap": lambda: S.checkout_heatmap(rng, wh),
        "top_tools": lambda: S.top_tools(rng, wh),
        "capacity": lambda: S.warehouse_capacity(wh),
        "low_stock": lambda: S.low_stock_rows(wh),
        "overdue": lambda: S.overdue_rows(wh),
        "maintenance": lambda: S.upcoming_maintenance(wh),
        "feed": lambda: S.recent_movements(wh, 15),
    }
    fn = mapping.get(slug)
    if fn is None:
        return JsonResponse({"error": f"unknown widget '{slug}'"}, status=404)
    data = fn()

    def _default(obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        raise TypeError(f"Unserializable {type(obj)}")

    return JsonResponse({
        "widget": slug, "range": rng, "wh": wh or None,
        "data": jsonlib.loads(jsonlib.dumps(data, default=_default)),
    })


def api_search(request):
    """Command-palette endpoint: match tools by SKU / name / barcode."""
    from django.http import JsonResponse

    if not request.user.is_authenticated:
        return JsonResponse({"error": "authentication required"}, status=401)
    q = (request.GET.get("q") or "").strip()
    limit = min(25, int(request.GET.get("limit", 12) or 12))
    qs = []
    if q:
        from dashboard.services import _tool_wh

        for tool in (
            Tool.objects.filter(_tool_wh(request.GET.get("wh") or ""))
            .search(q).select_related("location", "category")[:limit]
        ):
            qs.append({
                "sku": tool.sku, "name": tool.name, "status": tool.status,
                "qty": tool.quantity_on_hand, "location": tool.location.code,
                "state": tool.stock_state,
                "url": f"/inventory/{tool.pk}/", "drawer": f"/inventory/{tool.pk}/drawer/",
                "checkout_url": "/transactions/checkout/new/",
            })
    return JsonResponse({"count": len(qs), "results": qs})
