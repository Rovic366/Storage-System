"""Small template helpers for the dense UI."""

import json
from urllib.parse import parse_qsl, urlencode

from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def asjson(value) -> str:
    return mark_safe(json.dumps(value))


@register.filter
def set_query(querystring: str, kv: str) -> str:
    """Rebuild a querystring replacing/adding `key=value` (kv as 'key=value')."""
    key, _, value = kv.partition("=")
    pairs = [(k, v) for k, v in parse_qsl(querystring or "") if k != key]
    if value != "":
        pairs.append((key, value))
    return urlencode(pairs)


@register.filter
def drop_set_query(querystring: str, key: str) -> str:
    """Removes `key` (and optionally 'key' prefixed hidden fields)."""
    pairs = [(k, v) for k, v in parse_qsl(querystring or "") if k != key and not k.startswith(key)]
    return urlencode(pairs)


@register.filter
def sort_url(querystring: str, key: str) -> str:
    """Querystring for clicking a sortable column: toggles dir when already sorted."""
    try:
        pairs = parse_qsl(querystring)
    except ValueError:
        pairs = []
    current_sort = dict(pairs).get("sort")
    current_dir = dict(pairs).get("dir")
    if current_sort == key:
        if current_dir == "desc":
            # cycle complete: fall back to the template's default ordering
            pairs = [(k, v) for k, v in pairs if k not in ("sort", "dir")]
            return urlencode(pairs)
        new_dir = "desc"
    else:
        new_dir = "asc"
    pairs = [(k, v) for k, v in pairs if k not in ("sort", "dir", "page")]
    if new_dir:
        pairs += [("sort", key), ("dir", new_dir)]
    return urlencode(pairs)


@register.filter
def heat(value: int, peak: int) -> str:
    """Heatmap cell tone class from value and peak."""
    if not peak or not value:
        return "bg-panel-2/50"
    ratio = value / peak
    if ratio > 0.75:
        return "bg-cyan-400/80 text-surface"
    if ratio > 0.5:
        return "bg-cyan-400/55"
    if ratio > 0.3:
        return "bg-cyan-400/30"
    if ratio > 0.1:
        return "bg-cyan-400/15"
    return "bg-cyan-400/8"


@register.filter
def pct(value, total) -> str:
    if not total:
        return "0%"
    return f"{round(100 * (value or 0) / total)}%"


@register.filter
def money(value) -> str:
    try:
        return f"${float(value):,.0f}"
    except (TypeError, ValueError):
        return "—"


@register.filter
def money2(value) -> str:
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "—"


@register.filter
def delta_tone(card) -> str:
    direction = card.get("direction")
    tone = card.get("tone")
    if direction == "down":
        return "text-rose-400" if tone in ("rose", "amber", "warning") else "text-emerald-400"
    if direction == "+":
        return "text-emerald-400" if tone in ("info", "cyan") else "text-amber-400"
    return "text-ink-3"
