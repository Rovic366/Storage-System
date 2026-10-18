from __future__ import annotations

import csv
from datetime import datetime

from django.contrib import messages
from django.db.models import Exists, F, OuterRef
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import CreateView, DetailView, FormView, ListView, UpdateView

from accounts.mixins import RoleRequiredMixin
from common.utils import paginate_qs
from inventory import services
from inventory.models import Location, Supplier, Tool
from transactions.models import Checkout

from .forms import QuickEditForm, ToolForm

SORT_MAP = {
    "sku": "sku",
    "name": "name",
    "category": "category__name",
    "location": "location__code",
    "warehouse": "location__warehouse",
    "qty": "quantity_on_hand",
    "cost": "unit_cost",
    "value": "total_value",
    "status": "status",
    "updated": "updated_at",
}

STOCK_STATES = {
    "ok": lambda qs: qs.filter(
        status__in=Tool.objects.active().values("status"),
        quantity_on_hand__gt=F("reorder_level"),
    ),
    "low": lambda qs: qs.low_stock(),
    "out": lambda qs: qs.out_of_stock(),
}


def filtered_tools(request) -> tuple:
    """Multi-filter + sort pipeline shared by the list view and CSV export."""
    qs = Tool.objects.select_related("category", "location", "supplier").annotate(
        total_value=F("unit_cost") * F("quantity_on_hand"),
        has_open_chk=Exists(
            Checkout.objects.open().filter(tool=OuterRef("pk"))
        ),
    )
    g = request.GET
    filters = {}
    if q := g.get("q", "").strip():
        qs = qs.search(q)
        filters["q"] = q
    if cat := g.get("cat"):
        qs = qs.filter(category_id=cat)
        filters["cat"] = cat
    if status := g.get("status"):
        if status in Tool.Status.values:
            qs = qs.filter(status=status)
            filters["status"] = status
    if sup := g.get("sup"):
        qs = qs.filter(supplier_id=sup)
        filters["sup"] = sup
    if wh := g.get("wh"):
        qs = qs.filter(location__warehouse=wh)
        filters["wh"] = wh
    if loc := g.get("loc"):
        qs = qs.filter(location_id=loc)
        filters["loc"] = loc
    if cond := g.get("cond"):
        if cond in Tool.Condition.values:
            qs = qs.filter(condition=cond)
            filters["cond"] = cond
    if stock_state := g.get("stock"):
        fn = STOCK_STATES.get(stock_state)
        if fn:
            qs = fn(qs)
            filters["stock"] = stock_state
    sort = SORT_MAP.get(g.get("sort", "sku"), "sku")
    desc = g.get("dir") == "desc"
    qs = qs.order_by(("-" if desc else "") + sort, "sku")
    return qs, filters


class InventoryListView(RoleRequiredMixin, ListView):
    context_object_name = "tools"
    paginate_by = 50

    def get_queryset(self):
        queryset, self.filters = filtered_tools(self.request)
        return queryset

    def get(self, request, *args, **kwargs):
        if request.GET.get("fragment") == "table":
            self.template_name = "inventory/partials/tool_table.html"
        else:
            self.template_name = "inventory/list.html"
        return super().get(request, *args, **kwargs)

    def get_paginate_by(self, queryset):
        try:
            size = int(self.request.GET.get("page_size", 50))
        except (TypeError, ValueError):
            size = 50
        return size if size in (25, 50, 100) else 50

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(
            filters=self.filters,
            col_toggles=[
                ("warehouse", "WH"), ("value", "Value"),
                ("condition", "Cond"), ("updated", "Updated"),
                ("quickedit", "Quick"),
            ],
            categories=Tool.objects.values("category_id", "category__name").distinct(),
            suppliers=Supplier.objects.order_by("name"),
            locations=Location.objects.order_by("warehouse", "code"),
            warehouses=Location.objects.order_by("warehouse")
            .values_list("warehouse", flat=True)
            .distinct(),
            statuses=Tool.Status.choices,
            conditions=Tool.Condition.choices,
            stock_states=[("ok", "In stock"), ("low", "Low"), ("out", "Out"), ("", "All")],
            sort=self.request.GET.get("sort", "sku"),
            sort_dir="desc" if self.request.GET.get("dir") == "desc" else "asc",
            querystring=self.request.GET.urlencode(),
            total_count=self.object_list.count(),
            page_sizes=(25, 50, 100),
        )
        return ctx


class ToolDrawerView(RoleRequiredMixin, DetailView):
    """Slide-over detail drawer partial with the full tool history timeline."""
    model = Tool
    template_name = "inventory/partials/tool_drawer.html"
    context_object_name = "tool"

    def get_queryset(self):
        return Tool.objects.select_related("category", "location", "supplier").prefetch_related(
            "movements__from_location",
            "movements__to_location",
            "movements__performed_by",
            "checkouts__borrower",
            "schedules",
            "maintenance_logs__performed_by",
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        tx_ctx = {
            "events": tool_events(self.object),
            "open_checkout": Checkout.objects.open().filter(tool=self.object).first(),
        }
        ctx.update(tx_ctx)
        return ctx


def tool_events(tool) -> list[dict]:
    """Merged, newest-first event stream for a tool (movements + checkouts + maintenance)."""
    events = []
    for mv in tool.movements.all().select_related("from_location", "to_location",
                                                  "performed_by")[:200]:
        events.append({
            "at": mv.timestamp,
            "kind": mv.get_type_display(),
            "tone": "emerald" if mv.type in ("receive", "return")
            else "sky" if mv.type == "issue" else "slate",
            "text": f"{mv.quantity} unit(s) · {mv.reference_no or 'no ref'}"
            + (f" · {mv.from_location.code}→{mv.to_location.code}"
               if mv.type == "transfer" and mv.from_location and mv.to_location else ""),
            "actor": mv.performed_by.username if mv.performed_by else "system",
            "notes": mv.notes,
        })
    for co in tool.checkouts.all().select_related("borrower", "issued_by")[:100]:
        if co.returned_at:
            note = f"Return · condition {co.get_condition_in_display() or '—'}"
        else:
            note = "Open" if co.status == Checkout.Status.OPEN else "Overdue"
        events.append({
            "at": co.checked_out_at,
            "kind": "Checkout",
            "tone": "sky" if co.returned_at else ("rose" if co.status == Checkout.Status.OVERDUE else "amber"),
            "text": f"{co.borrower.username} · due {co.due_at:%Y-%m-%d %H:%M}",
            "actor": co.issued_by.username if co.issued_by else "system",
            "notes": note,
        })
    for log in tool.maintenance_logs.all().select_related("performed_by")[:100]:
        events.append({
            "at": datetime.combine(log.date, datetime.min.time()).replace(
                tzinfo=__import__("django").utils.timezone.get_current_timezone()
            ),
            "kind": log.get_task_type_display(),
            "tone": "amber",
            "text": f"Cost {log.cost}",
            "actor": log.performed_by.username if log.performed_by else "system",
            "notes": log.notes,
        })
    events.sort(key=lambda e: e["at"], reverse=True)
    return events


class QuickEditToolView(RoleRequiredMixin, FormView):
    roles = ("stock",)
    form_class = QuickEditForm
    http_method_names = ["post"]

    def form_valid(self, form):
        tool = get_object_or_404(Tool, pk=form.cleaned_data["tool_id"])
        errors = []
        try:
            services.quick_set_quantity(
                tool, form.cleaned_data["quantity"], self.request.user,
                notes=form.cleaned_data.get("notes") or "",
            )
        except services.StockError as exc:
            errors.append(str(exc))
        new_status = form.cleaned_data.get("status")
        if new_status:
            try:
                services.move_tool_status(tool, new_status, self.request.user)
            except services.StockError as exc:
                errors.append(str(exc))
        if errors:
            for error in errors:
                messages.error(self.request, error)
        else:
            messages.success(self.request, f"{tool.sku} updated.")
        return redirect_back(self.request)


def redirect_back(request, fallback="inventory:list"):
    back = request.POST.get("back") or request.GET.get("back") or ""
    if back.startswith("/") and not back.startswith("//"):
        return redirect(back)
    return redirect(fallback)


class ToolBulkActionView(RoleRequiredMixin, FormView):
    roles = ("stock",)
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        ids = request.POST.getlist("ids")
        action = request.POST.get("action", "")
        qs = Tool.objects.filter(pk__in=ids) if ids else Tool.objects.none()
        if not qs:
            messages.warning(request, "No tools selected.")
            return redirect_back(request)
        if action == "export":
            return export_csv(request, queryset=qs)
        if action == "retire":
            services.retire_tools(qs, request.user)
            messages.success(request, f"{qs.count()} tool(s) retired.")
            return redirect_back(request)
        if action == "move":
            loc_id = request.POST.get("target_location")
            if not loc_id:
                messages.error(request, "Choose a destination location for the move.")
                return redirect_back(request)
            location = get_object_or_404(Location, pk=loc_id)
            moved, failed = 0, []
            for tool in qs:
                try:
                    services.transfer_stock(tool, location, request.user, notes="Bulk move")
                    moved += 1
                except services.StockError as ex:
                    failed.append(f"{tool.sku}: {ex}")
            msg = f"Moved {moved} tool(s) to {location.code}."
            if failed:
                messages.warning(request, msg + " Failed: " + "; ".join(failed))
            else:
                messages.success(request, msg)
            return redirect_back(request)
        messages.error(request, "Unknown bulk action.")
        return redirect_back(request)


def export_csv(request, queryset=None) -> HttpResponse:
    if queryset is None:
        queryset, _ = filtered_tools(request)
    from accounts.services import audit

    response = HttpResponse(content_type="text/csv")
    stamp = datetime.now().strftime("%Y%m%d")
    response["Content-Disposition"] = f'attachment; filename="inventory-{stamp}.csv"'
    writer = csv.writer(response)
    writer.writerow(
        ["SKU", "Name", "Category", "Supplier", "Location", "Warehouse",
         "Quantity", "Reorder level", "Unit cost", "Total value", "Status", "Condition"]
    )
    for tool in queryset.select_related("category", "supplier", "location"):
        writer.writerow(
            [tool.sku, tool.name, tool.category.name, tool.supplier.name,
             tool.location.code, tool.location.warehouse, tool.quantity_on_hand,
             tool.reorder_level, tool.unit_cost,
             round(tool.unit_cost * tool.quantity_on_hand, 2),
             tool.get_status_display(), tool.get_condition_display()]
        )
    audit(request.user, "EXPORT_CSV", None, meta={"kind": "inventory", "rows": len(queryset)})
    return response


class ToolCreateView(RoleRequiredMixin, CreateView):
    roles = ("inventory_write",)
    model = Tool
    form_class = ToolForm
    template_name = "inventory/crud.html"
    success_url_name = "inventory:list"

    def get_initial(self):
        next_n = Tool.objects.count() + 1
        return {"sku": f"TOOL-{next_n:05d}"}

    def form_valid(self, form):
        self.object = form.save(commit=False)
        initial_qty = form.cleaned_data.get("initial_quantity") or 0
        from django.db import transaction

        with transaction.atomic():
            self.object.save()
            if initial_qty > 0:
                services.receive_stock(self.object, initial_qty, self.request.user)
                self.object.refresh_from_db()
        messages.success(self.request, f"Tool {self.object.sku} created.")
        return redirect(reverse_detail(self.object))


class ToolUpdateView(RoleRequiredMixin, UpdateView):
    roles = ("inventory_write",)
    model = Tool
    form_class = ToolForm
    template_name = "inventory/crud.html"

    def form_valid(self, form):
        response = super().form_valid(form)
        from accounts.services import audit

        audit(self.request.user, "TOOL_UPDATED", self.object, meta={})
        messages.success(self.request, f"Tool {self.object.sku} saved.")
        return response

    def get_success_url(self):
        from django.urls import reverse

        return reverse("inventory:detail", args=[self.object.pk])


class ToolDetailView(RoleRequiredMixin, DetailView):
    model = Tool
    template_name = "inventory/detail.html"
    context_object_name = "tool"

    def get_queryset(self):
        return Tool.objects.select_related("category", "location", "supplier").prefetch_related(
            "movements__from_location", "movements__to_location",
            "movements__performed_by", "checkouts__borrower",
            "schedules", "maintenance_logs__performed_by",
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(
            events=tool_events(self.object),
            open_checkout=Checkout.objects.open().filter(tool=self.object).first(),
        )
        return ctx


def reverse_detail(tool):
    from django.urls import reverse

    return reverse("inventory:detail", args=[tool.pk])
