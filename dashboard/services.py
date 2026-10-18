"""Dashboard analytics: every widget's data is computed here.

All functions return JSON-serializable structures so they can be consumed by
templates, HTMX partials and the /api/dashboard/ JSON endpoint.

Global filter semantics:
- `range` in {"7","30","90"} days; `wh` = warehouse name or "" (all).
- KPI deltas compare against the preceding equal-length window.
- Sparklines are daily FLOW series across the current window (documented in
  README): SKUs created/day (cumulative), flow-value/day, issue-return
  balance/day (cumulative), overdue-snapshot/day, low-stock activity/day,
  maintenance completions/day, returns/day (ledger-repair events).

Metric definitions (README repeats these):
- Utilization % = checked-out units / (checked-out + available units).
- Stock Accuracy % = share of tool rows whose status/open-checkout linkage is
  internally consistent as of query time; delta = gap to 100% (pts).
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict

from django.db.models import Count, Exists, F, OuterRef, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from inventory.models import Location, Tool
from maintenance.models import MaintenanceLog, MaintenanceSchedule
from transactions.models import Checkout, StockMovement

STATUS_COLORS = {
    Tool.Status.AVAILABLE: "#34d399",
    Tool.Status.CHECKED_OUT: "#38bdf8",
    Tool.Status.IN_MAINTENANCE: "#fbbf24",
    Tool.Status.RETIRED: "#64748b",
    Tool.Status.LOST: "#fb7185",
}

STATUS_LABELS = dict(Tool.Status.choices)


# ----------------------------------------------------------------- primitives


def _window(range_str) -> tuple[dt.datetime, dt.datetime, int]:
    days = int(range_str) if str(range_str) in ("7", "30", "90") else 30
    end = timezone.now()
    start = end - dt.timedelta(days=days)
    return start, end, days


def _tool_wh(wh: str):
    return Q(location__warehouse=wh) if wh else Q()


def _day_label(d, days: int) -> str:
    return d.strftime("%m/%d") if days > 30 else d.strftime("%m-%d")


def _dates_ascending(end, days) -> list[dt.date]:
    return [end.date() - dt.timedelta(days=days - 1 - i) for i in range(days)]


def _series(points_by_day: dict[dt.date, float], dates: list[dt.date], days: int,
            cumulate: bool = False) -> list[dict]:
    out = []
    running = 0.0
    for d in dates:
        val = float(points_by_day.get(d, 0.0))
        if cumulate:
            running += val
            out.append({"x": _day_label(d, days), "y": round(running, 2)})
        else:
            out.append({"x": _day_label(d, days), "y": round(val, 2)})
    return out


def _pct(prev: float, now: float) -> str:
    if prev == 0:
        return f"+{now:,}" if now else "0%"
    return f"{100 * (now - prev) / prev:+.1f}%"


def _dir(delta: str | float) -> str:
    s = str(delta)
    if delta == 0 or s == "0.0%" or s == "0%":
        return "flat"
    if s.startswith("-"):
        return "down"
    if s.startswith("+"):
        return "+"
    return "flat"


def _card(key, label, value, delta, delta_kind, tone, series, tooltip) -> dict:
    return {
        "key": key, "label": label, "value": value, "delta": delta,
        "delta_kind": delta_kind, "direction": _dir(delta), "tone": tone,
        "series": series, "tooltip": tooltip,
    }


# ------------------------------------------------------------------- widgets


def kpi_cards(range_str="30", wh="") -> list[dict]:
    start, end, days = _window(range_str)
    prev_start = start - dt.timedelta(days=days)
    dates = _dates_ascending(end, days)
    wh_q = _tool_wh(wh)

    tools = Tool.objects.filter(wh_q)
    flows = StockMovement.objects.filter(_tool_wh_for_movement(wh),
                                         timestamp__range=(start, end))
    flows_prev = StockMovement.objects.filter(_tool_wh_for_movement(wh),
                                              timestamp__range=(prev_start, start))

    def flow_totals(qs):
        data = {r["type"]: r["q"] for r in qs.values("type").annotate(q=Sum("quantity"))}
        inbound = data.get(StockMovement.Type.RECEIVE, 0) + data.get(StockMovement.Type.RETURN, 0)
        outbound = data.get(StockMovement.Type.ISSUE, 0) + data.get(StockMovement.Type.SCRAP, 0)
        return data, inbound, outbound

    totals, inbound, outbound = flow_totals(flows)
    _, inbound_prev, outbound_prev = flow_totals(flows_prev)

    # --- 1. Total SKUs -----------------------------------------------------
    total_skus = tools.count()
    skus_prev = Tool.objects.filter(wh_q, created_at__lt=start).count()
    new_by_day = (
        Tool.objects.filter(wh_q, created_at__range=(start, end))
        .annotate(day=TruncDate("created_at"))
        .values("day").annotate(q=Count("id"))
    )
    new_map = {r["day"].date() if isinstance(r["day"], dt.datetime) else r["day"]: r["q"]
               for r in new_by_day}
    skus_series = _series(new_map, dates, days, cumulate=True)

    # --- 2. Inventory value ------------------------------------------------
    value_now = tools.valuation()
    value_rows = (
        flows.annotate(day=TruncDate("timestamp"))
        .values("day", "tool__unit_cost", "type")
        .annotate(q=Sum("quantity"))
    )
    signed_moves_by_day: dict[dt.date, float] = defaultdict(float)
    SIGN = {StockMovement.Type.RECEIVE: 1, StockMovement.Type.RETURN: 1,
            StockMovement.Type.ISSUE: -1, StockMovement.Type.SCRAP: -1,
            StockMovement.Type.ADJUST: 0}
    for row in value_rows:
        day_val = row["day"].date() if isinstance(row["day"], dt.datetime) else row["day"]
        signed_moves_by_day[day_val] += (
            SIGN.get(row["type"], 0) * row["q"] * float(row["tool__unit_cost"])
        )
    value_delta = sum(signed_moves_by_day.values())
    value_series = []
    running = float(value_now)
    for day in reversed(dates):
        value_series.append({"x": _day_label(day, days), "y": round(running, 0)})
        running -= signed_moves_by_day.get(day, 0.0)
    value_series.reverse()

    # --- 3. Checked out / utilization ---------------------------------------
    open_exists = Exists(Checkout.objects.open().filter(tool=OuterRef("pk")))
    out_now = tools.filter(open_exists).aggregate(q=Sum("quantity_on_hand"))["q"] or 0
    available_now = tools.filter(status=Tool.Status.AVAILABLE).aggregate(
        q=Sum("quantity_on_hand"))["q"] or 0
    denom = out_now + available_now
    util_now = round(100 * out_now / denom, 1) if denom else 0.0

    out_prev = Checkout.objects.filter(
        tool__location__warehouse=wh if wh else Q(),
        checked_out_at__lt=start,
    ).filter(Q(returned_at__isnull=True) | Q(returned_at__gte=start)).count()
    available_prev = max(0, available_now - inbound + outbound)
    denom_prev = out_prev + available_prev
    util_prev = 100 * out_prev / denom_prev if denom_prev else 0.0

    check_by_day = (
        Checkout.objects.filter(tool__location__warehouse=wh if wh else Q(),
                                checked_out_at__range=(start, end))
        .annotate(day=TruncDate("checked_out_at"))
        .values("day").annotate(q=Count("id"))
    )
    ret_by_day = (
        Checkout.objects.filter(tool__location__warehouse=wh if wh else Q(),
                                returned_at__range=(start, end))
        .annotate(day=TruncDate("returned_at"))
        .values("day").annotate(q=Count("id"))
    )
    chk_map = {r["day"].date() if isinstance(r["day"], dt.datetime) else r["day"]: r["q"]
               for r in check_by_day}
    ret_map = {r["day"].date() if isinstance(r["day"], dt.datetime) else r["day"]: r["q"]
               for r in ret_by_day}
    net_map = {d: chk_map.get(d, 0) - ret_map.get(d, 0) for d in dates}
    checked_series = _series(net_map, dates, days, cumulate=True)

    # --- 4. Overdue ---------------------------------------------------------
    overdue_now = Checkout.objects.open().filter(due_at__lt=timezone.now()).filter(
        tool__location__warehouse=wh if wh else Q()).count()
    overdue_at_start = Checkout.objects.filter(
        tool__location__warehouse=wh if wh else Q(),
        due_at__lt=start,
        checked_out_at__lt=start,
    ).filter(Q(returned_at__isnull=True) | Q(returned_at__gte=start)).count()
    overdue_pairs = list(Checkout.objects.filter(
        tool__location__warehouse=wh if wh else Q(),
        due_at__lte=end,
        checked_out_at__lte=end,
    ).values_list("due_at", "returned_at"))
    tz = timezone.get_current_timezone()
    overdue_series = []
    for day in dates:
        eod = timezone.make_aware(
            dt.datetime.combine(day + dt.timedelta(days=1), dt.time.min), tz
        )
        count = sum(
            1
            for due_at, returned_at in overdue_pairs
            if due_at <= eod and (returned_at is None or returned_at > eod)
            and due_at >= start - dt.timedelta(days=365)
        )
        overdue_series.append({"x": _day_label(day, days), "y": count})

    # --- 5. Low stock --------------------------------------------------------
    low_now = tools.low_stock().count()
    low_rows = tools.low_stock()
    low_tool_ids = set(low_rows.values_list("id", flat=True))
    low_flow = flows.filter(tool_id__in=low_tool_ids)
    low_by_day = (
        low_flow.annotate(day=TruncDate("timestamp")).values("day").annotate(q=Count("id"))
    )
    low_map = {r["day"].date() if isinstance(r["day"], dt.datetime) else r["day"]: r["q"]
               for r in low_by_day}
    low_series = _series(low_map, dates, days, cumulate=False)
    low_flow_prev = flows_prev.filter(tool_id__in=low_tool_ids)
    low_prev_count = low_flow_prev.count()

    # --- 6. Maintenance due ---------------------------------------------------
    schedules = MaintenanceSchedule.objects.filter(_tool_wh(wh))
    due_now = schedules.due_within(7).count()
    due_at_start = schedules.filter(
        next_due__lte=(start.date() + dt.timedelta(days=7))).count()
    maint_by_day = (
        MaintenanceLog.objects.filter(
            Q(tool__location__warehouse=wh) if wh else Q(),
            date__range=(start.date(), end.date()),
        )
        .values("date").annotate(q=Count("id"))
    )
    maint_map = {r["date"]: r["q"] for r in maint_by_day}
    maint_series = _series(maint_map, dates, days, cumulate=False)

    # --- 7. Utilization card ---------------------------------------------------
    util_series = [
        {"x": s["x"], "y": s["y"] * 100} for s in checked_series
    ]  # flow-scaled proxy, documented

    # --- 8. Accuracy -------------------------------------------------------------
    open_tool_ids = set(Checkout.objects.open().values_list("tool_id", flat=True))
    inconsistent = set()
    for tool in tools.exclude(pk__in=open_tool_ids).filter(status=Tool.Status.CHECKED_OUT):
        inconsistent.add(tool.pk)
    for tool in tools.filter(pk__in=open_tool_ids).exclude(status=Tool.Status.CHECKED_OUT):
        inconsistent.add(tool.pk)
    consistency = 100 - (100 * len(inconsistent) / max(1, total_skus))
    return_events = list(ret_map.values())
    ret_series = _series(ret_map, dates, days, cumulate=False)

    return [
        _card("skus", "Total SKUs", f"{total_skus:,}", _pct(skus_prev, total_skus), "pct",
              "cyan", skus_series, "Distinct SKUs on file"),
        _card("value", "Inventory Value",
              f"${float(value_now):,.0f}", f"{value_delta:+,.0f}", "abs", "info",
              value_series, "Sum of unit cost x quantity on hand"),
        _card("checked_out", "Items Checked Out", f"{out_now:,}",
              _pct(out_prev, out_now), "pct", "sky", checked_series,
              "Units at borrowers right now"),
        _card("overdue", "Overdue Returns", f"{overdue_now:,}",
              _pct(overdue_at_start, overdue_now), "pct", "rose", overdue_series,
              "Open checkouts past due date"),
        _card("low_stock", "Low-Stock Alerts", f"{low_now:,}",
              _pct(low_prev_count, low_now), "activity", "amber", low_series,
              "Active tools at or below reorder level"),
        _card("maintenance", "Maintenance Due (7d)", f"{due_now:,}",
              _pct(due_at_start, due_now), "pct", "amber", maint_series,
              "Schedules due within the next 7 days"),
        _card("utilization", "Utilization", f"{util_now:.0f}%",
              f"{util_now - util_prev:+.1f} pts", "pts", "warning", util_series,
              "Checked-out units / (checked-out + available)"),
        _card("accuracy", "Stock Accuracy", f"{consistency:.1f}%",
              f"{consistency - 100:+.1f} pts", "gap", "sky",
              ret_series if return_events else checked_series,
              "Rows whose status matches open-checkout ledger; delta = gap to 100%"),
    ]


def _tool_wh_for_movement(wh: str):
    return Q(tool__location__warehouse=wh) if wh else Q()


def movement_trend(range_str="30", wh="") -> dict:
    start, end, days = _window(range_str)
    dates = _dates_ascending(end, days)
    groups = {
        "receive": [StockMovement.Type.RECEIVE],
        "issue": [StockMovement.Type.ISSUE, StockMovement.Type.SCRAP],
        "return": [StockMovement.Type.RETURN],
    }
    out = {"days": [_day_label(d, days) for d in dates], "series": {}}
    totals = {}
    for name, types in groups.items():
        rows = (
            StockMovement.objects.filter(
                _tool_wh_for_movement(wh), timestamp__range=(start, end), type__in=types)
            .annotate(day=TruncDate("timestamp"))
            .values("day").annotate(q=Sum("quantity"))
        )
        m = {r["day"].date() if isinstance(r["day"], dt.datetime) else r["day"]: r["q"]
             for r in rows}
        totals[name] = sum(m.values())
        out["series"][name] = _series(m, dates, days, cumulate=False)
    out["totals"] = totals
    out["range"] = days
    return out


def value_by_category(wh="") -> list[dict]:
    rows = (
        Tool.objects.filter(_tool_wh(wh), quantity_on_hand__gt=0)
        .values("category__name").annotate(v=Sum(F("unit_cost") * F("quantity_on_hand")))
        .order_by("-v")
    )
    return [{"label": r["category__name"], "value": float(r["v"])} for r in rows]


def status_distribution(wh="") -> list[dict]:
    rows = Tool.objects.filter(_tool_wh(wh)).values("status").annotate(q=Count("id"))
    counts = {r["status"]: r["q"] for r in rows}
    return [
        {"key": status, "label": STATUS_LABELS[status], "value": counts.get(status, 0),
         "color": color}
        for status, color in STATUS_COLORS.items()
    ]


def checkout_heatmap(range_str="30", wh="") -> dict:
    start, end, days = _window(range_str)
    hours = list(range(6, 22))  # 06:00 - 21:59
    weekday_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    matrix = [[0] * len(hours) for _ in range(7)]
    qs = Checkout.objects.filter(
        tool__location__warehouse=wh if wh else Q(),
        checked_out_at__range=(start, end),
    )
    for checked_at in qs.values_list("checked_out_at", flat=True):
        local = timezone.localtime(checked_at)
        if local.weekday() < 7 and local.hour in hours:
            matrix[local.weekday()][hours.index(local.hour)] += 1
    peak = max((max(row) for row in matrix), default=0)
    rows = [{"label": weekday_labels[w], "cells": matrix[w]} for w in range(7)]
    return {"hours": [f"{h:02d}" for h in hours], "weekdays": weekday_labels,
            "matrix": matrix, "rows": rows, "max": peak}


def top_tools(range_str="30", wh="", limit=10) -> list[dict]:
    start, end, _ = _window(range_str)
    usage = (
        StockMovement.objects.filter(
            _tool_wh_for_movement(wh),
            timestamp__range=(start, end),
            type__in=[StockMovement.Type.ISSUE, StockMovement.Type.SCRAP],
        )
        .values("tool_id")
        .annotate(n=Sum("quantity"))
        .order_by("-n")[:limit]
    )
    rows = []
    for row in usage:
        tool = Tool.objects.filter(pk=row["tool_id"]).values("sku", "name", "category__name").first()
        if tool:
            rows.append({"sku": tool["sku"], "name": tool["name"], "category": tool["category__name"],
                         "count": row["n"]})
    return rows


def warehouse_capacity(wh="") -> dict:
    where = Q(warehouse=wh) if wh else Q()
    locs = Location.objects.filter(where, is_active=True)
    warehouses = (
        Tool.objects.filter(location__in=locs)
        .values("location__warehouse")
        .annotate(o=Sum("quantity_on_hand"))
    )
    occupancy_wh = {r["location__warehouse"]: r["o"] or 0 for r in warehouses}
    capacity_wh = (
        locs.values("warehouse").annotate(c=Sum("capacity"))
        .order_by("warehouse")
    )
    cap_map = {r["warehouse"]: r["c"] or 1 for r in capacity_wh}
    out = [
        {"label": w, "kind": "warehouse", "occupied": occupancy_wh.get(w, 0),
         "capacity": cap_map.get(w, 0),
         "pct": min(100, round(100 * occupancy_wh.get(w, 0) / max(1, cap_map.get(w, 1))))}
        for w in cap_map
    ]
    zones = (
        Tool.objects.filter(location__in=locs)
        .values("location__warehouse", "location__zone")
        .annotate(o=Sum("quantity_on_hand"))
    )
    occ_zone = {(r["location__warehouse"], r["location__zone"]): r["o"] or 0 for r in zones}
    zones_cap = (
        locs.values("warehouse", "zone").annotate(c=Sum("capacity"))
        .order_by("warehouse", "zone")
    )
    cap_zone = {(r["warehouse"], r["zone"]): r["c"] or 1 for r in zones_cap}
    zone_rows = [
        {"label": f"{wh_name}/{zone}", "kind": "zone",
         "occupied": occ_zone.get((wh_name, zone), 0),
         "capacity": cap_zone.get((wh_name, zone), 0),
         "pct": min(100, round(100 * occ_zone.get((wh_name, zone), 0)
                               / max(1, cap_zone.get((wh_name, zone), 1))))}
        for wh_name, zone in cap_zone
    ]
    zone_rows = sorted(zone_rows, key=lambda r: -r["pct"])[:12]
    return {"warehouses": out, "zones": zone_rows}


def low_stock_rows(wh="", limit=20) -> list[dict]:
    rows = (
        Tool.objects.low_stock().filter(_tool_wh(wh))
        .order_by(F("quantity_on_hand").asc(), "sku")
        .select_related("location")[:limit]
    )
    return [{
        "pk": t.pk, "sku": t.sku, "name": t.name, "location": t.location.code,
        "warehouse": t.location.warehouse, "qty": t.quantity_on_hand,
        "reorder": t.reorder_level, "needed": max(1, t.reorder_level - t.quantity_on_hand),
        "state": t.stock_state,
    } for t in rows]


def overdue_rows(wh="", limit=20) -> list[dict]:
    now = timezone.now()
    rows = (
        Checkout.objects.open()
        .filter(due_at__lt=now)
        .filter(tool__location__warehouse=wh if wh else Q())
        .order_by("due_at")
        .select_related("tool", "borrower")[:limit]
    )
    return [{
        "pk": c.pk, "tool_pk": c.tool.pk, "sku": c.tool.sku, "tool_name": c.tool.name,
        "borrower": c.borrower.username, "due_at": c.due_at,
        "days_late": max(1, (now - c.due_at).days), "condition_out": c.condition_out,
    } for c in rows]


def upcoming_maintenance(wh="", limit=15) -> list[dict]:
    today = timezone.localdate()
    qs = MaintenanceSchedule.objects.filter(_tool_wh(wh)).order_by("next_due")
    rows = qs.select_related("tool", "tool__location")[:limit]
    return [{
        "pk": s.pk, "sku": s.tool.sku, "tool_name": s.tool.name,
        "task_type": s.task_type, "next_due": s.next_due, "last_done": s.last_done,
        "interval": s.interval_days,
        "state": ("overdue" if s.next_due < today else
                  "due" if s.next_due <= today + dt.timedelta(days=7) else "later"),
        "days": (s.next_due - today).days,
    } for s in rows]


def recent_movements(wh="", limit=15) -> list[dict]:
    rows = (
        StockMovement.objects.filter(_tool_wh(wh))
        .select_related("tool", "from_location", "to_location", "performed_by")
        .order_by("-timestamp")[:limit]
    )
    return [{
        "pk": m.pk, "type": m.type, "type_label": m.get_type_display(),
        "sku": m.tool.sku, "tool": m.tool.name, "qty": m.quantity,
        "from_loc": m.from_location.code if m.from_location else "—",
        "to_loc": m.to_location.code if m.to_location else "—",
        "actor": m.performed_by.username if m.performed_by else "system",
        "reference": m.reference_no, "timestamp": m.timestamp,
    } for m in rows]


def dashboard_payload(range_str="30", wh="") -> dict:
    """Full bundle used by /api/dashboard/ and the HTMX grid partial."""
    return {
        "range": range_str,
        "wh": wh or None,
        "kpis": kpi_cards(range_str, wh),
        "movement_trend": movement_trend(range_str, wh),
        "value_by_category": value_by_category(wh),
        "status_distribution": status_distribution(wh),
        "checkout_heatmap": checkout_heatmap(range_str, wh),
        "top_tools": top_tools(range_str, wh),
        "warehouse_capacity": warehouse_capacity(wh),
        "low_stock": low_stock_rows(wh),
        "overdue": overdue_rows(wh),
        "maintenance": upcoming_maintenance(wh),
        "recent_movements": recent_movements(wh, 15),
    }


def chart_payloads(range_str="30", wh="") -> dict:
    """Chart.js-ready payloads keyed by canvas data-chart attribute."""
    return {
        "trend": movement_trend(range_str, wh),
        "value_cat": {"items": value_by_category(wh)},
        "status_dist": {"items": status_distribution(wh)},
        "top_tools": {"items": top_tools(range_str, wh)},
    }
