"""PDF rendering for reports via xhtml2pdf."""

from __future__ import annotations

import io

from django.template.loader import render_to_string


NUMERIC_COLS = ("Qty", "Unit cost", "Total value", "Cost", "Value",
                "Days late", "Checkout")


def build_pdf(title: str, columns: list[str], rows: list[list], meta: dict) -> bytes:
    value_cols = {i for i, col in enumerate(columns) if col in NUMERIC_COLS}
    value_col_names = [col for col in columns if col in NUMERIC_COLS]
    context = {
        "title": title,
        "columns": columns,
        "rows": rows,
        "meta": meta,
        "generated_at": _now_label(),
        "value_cols": value_cols,
        "value_cols_names": value_col_names,
    }
    html = render_to_string("reports/pdf/base.html", context)
    out = io.BytesIO()
    from xhtml2pdf import pisa

    status = pisa.CreatePDF(
        html, dest=out, encoding="utf-8",
        link_callback=lambda path, rel, media: _media_resolver(path),
    )
    if status.err:
        raise RuntimeError("PDF generation failed")
    return out.getvalue()


def _now_label() -> str:
    from django.utils import timezone

    return timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M")


def _media_resolver(path):
    """Resolve STATIC/MEDIA paths for xhtml2pdf - static assets are not needed
    for our report layout; return None (no link)."""
    return None
