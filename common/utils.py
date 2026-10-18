"""Shared view helpers."""

from __future__ import annotations

from django.core.paginator import Paginator


def paginate_qs(request, queryset, page_sizes=(25, 50, 100), default_size=50, page_param="page"):
    try:
        size = int(request.GET.get("page_size", default_size))
    except (TypeError, ValueError):
        size = default_size
    if size not in page_sizes:
        size = default_size
    paginator = Paginator(queryset, size)
    try:
        page_number = int(request.GET.get(page_param, 1))
    except (TypeError, ValueError):
        page_number = 1
    page_obj = paginator.get_page(page_number)
    return page_obj, paginator, size


def params_without(request, *keys_to_drop):
    params = request.GET.copy()
    for key in keys_to_drop:
        params.pop(key, None)
    if "fragment" in params:
        params.pop("fragment")
    return params
