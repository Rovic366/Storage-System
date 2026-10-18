from __future__ import annotations

from .models import AuditLog


def audit(user, action: str, target=None, *, meta: dict | None = None) -> AuditLog:
    """Append an audit entry.

    Called inside the caller's transaction.atomic() block so the audit row is
    committed (or rolled back) together with the change it describes.
    """
    meta = meta or {}
    from django.utils.html import strip_tags

    object_type = type(target).__name__ if target is not None else ""
    object_id = str(getattr(target, "pk", "")) if target is not None else ""
    object_repr = ""
    if target is not None:
        object_repr = strip_tags(str(target))[:255]
    return AuditLog.objects.create(
        user=user if getattr(user, "is_authenticated", False) else None,
        action=action,
        object_type=object_type,
        object_id=object_id,
        object_repr=object_repr,
        meta=meta,
    )
