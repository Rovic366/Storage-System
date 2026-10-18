from __future__ import annotations

import csv
import datetime as dt

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import render
from django.template.loader import get_template
from django.views.generic import ListView, TemplateView

from accounts.mixins import RoleRequiredMixin
from accounts.services import audit
from inventory.models import Tool

from .services import report_rows

SLUGS = [
    ("inventory-valuation", "Inventory valuation", "Stock value by SKU with category totals"),
    ("movement-history", "Movement history", "Every stock movement in a time window"),
    ("overdue-checkouts", "Overdue checkouts", "Open checkouts past their due date"),
    ("maintenance-history", "Maintenance history", "Calibration, inspection and repair logs"),
]


class ReportIndexView(RoleRequiredMixin, TemplateView):
    template_name = "reports/index.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["reports"] = SLUGS
        return ctx


class ReportTableView(RoleRequiredMixin, ListView):
    """Inline HTML preview of a report table (dense)."""
    template_name = "reports/table.html"
    context_object_name = "rows"
    paginate_by = 200

    def get(self, request, *args, **kwargs):
        self.slug = kwargs["slug"]
        if self.slug not in {entry[0] for entry in SLUGS}:
            messages.error(request, "Unknown report.")
            return render(request, "reports/index.html",
                          {"reports": SLUGS}, status=404)
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        self.title, self.columns, rows, self.meta = report_rows(self.slug, self.request)
        numeric = ("Qty", "Unit cost", "Total value", "Cost", "Value",
                   "Days late", "Checkout")
        self.value_cols = [i for i, c in enumerate(self.columns) if c in numeric]
        self.value_col_names = [c for c in self.columns if c in numeric]
        return rows

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        warehouses = set(
            Tool.objects.exclude(location__warehouse="")
            .values_list("location__warehouse", flat=True)
        )
        ctx.update(title=self.title, columns=self.columns, meta=self.meta,
                   slug=self.slug, reports=SLUGS,
                   value_cols=self.value_cols,
                   value_cols_names=self.value_col_names,
                   warehouses=sorted(warehouses),
                   querystring=self.request.GET.urlencode())
        return ctx


def _file_response(request, slug: str, kind: str) -> HttpResponse:
    slug = slug.replace(".csv", "").replace(".pdf", "")
    if kind == "csv":
        title, columns, rows, meta = report_rows(slug, request)
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = (
            f'attachment; filename="{slug}-{dt.date.today():%Y%m%d}.csv"'
        )
        writer = csv.writer(response)
        writer.writerow([title])
        for meta_key, meta_val in meta.items():
            writer.writerow([f"{meta_key.replace('_', ' ').title()}: {meta_val}"])
        writer.writerow([])
        writer.writerow(columns)
        for row in rows:
            writer.writerow(row)
        audit(request.user, "EXPORT_REPORT", None,
              meta={"kind": "csv", "report": slug, "rows": len(rows)})
        return response
    if kind == "pdf":
        title, columns, rows, meta = report_rows(slug, request)
        from .pdf import build_pdf

        pdf_bytes = build_pdf(title, columns, rows, meta)
        response = HttpResponse(bytes(pdf_bytes), content_type="application/pdf")
        response["Content-Disposition"] = (
            f'attachment; filename="{slug}-{dt.date.today():%Y%m%d}.pdf"'
        )
        audit(request.user, "EXPORT_REPORT", None,
              meta={"kind": "pdf", "report": slug, "rows": len(rows)})
        return response
    return HttpResponse(status=400)


class ReportExportView(RoleRequiredMixin, TemplateView):
    """Handles /reports/export/<slug>.csv|pdf"""

    def get(self, request, filename: str):
        if filename.endswith(".csv"):
            return _file_response(request, filename, "csv")
        if filename.endswith(".pdf"):
            return _file_response(request, filename, "pdf")
        return HttpResponse(status=404)
