"""Role groups and permission helpers for the Storage System.

Roles are implemented as Django Groups. Superusers bypass every check.
"""

from __future__ import annotations

ADMIN = "Admin"
STOREKEEPER = "Storekeeper"
TECHNICIAN = "Technician"
VIEWER = "Viewer"
BORROWER = "Borrower"

ALL_ROLES = (ADMIN, STOREKEEPER, TECHNICIAN, VIEWER, BORROWER)

#: Role matrix used by RoleRequiredMixin-driven views.
ROLE_MATRIX = {
    ADMIN: ("view", "stock", "checkout", "inventory_write", "maintenance", "audit", "retire"),
    STOREKEEPER: ("view", "stock", "checkout", "inventory_write", "maintenance"),
    TECHNICIAN: ("view", "checkout", "maintenance"),
    VIEWER: ("view",),
}

#: Reverse lookup: capability -> roles allowed.
CAPABILITY_ROLES = {
    cap: [role for role, caps in ROLE_MATRIX.items() if cap in caps]
    for cap in ("view", "stock", "checkout", "inventory_write", "maintenance", "audit", "retire")
}


def role_string(capability: str) -> tuple[str, ...]:
    return tuple(CAPABILITY_ROLES.get(capability, ())) or ("__none__",)


def get_groups_by_role():
    from django.contrib.auth.models import Group

    groups = {g.name: g for g in Group.objects.filter(name__in=ALL_ROLES)}
    missing = [r for r in ALL_ROLES if r not in groups]
    if missing:
        groups.update(ensure_role_groups())
    return groups


def ensure_role_groups() -> dict[str, "Group"]:
    """Idempotently creates the role groups (Admin, Storekeeper, ...)."""
    from django.contrib.auth.models import Group

    created = {}
    for role in ALL_ROLES:
        group, _ = Group.objects.get_or_create(name=role)
        created[role] = group
    return created


def user_groups(user) -> frozenset[str]:
    if not getattr(user, "is_authenticated", False):
        return frozenset()
    return frozenset(user.groups.values_list("name", flat=True))


def has_role(user, *roles: str) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True
    gs = user_groups(user)
    return bool(gs & set(roles) if roles else gs)


def has_capability(user, capability: str) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True
    allowed = CAPABILITY_ROLES.get(capability)
    if not allowed:
        return False
    return bool(user_groups(user) & set(allowed))


def get_role(user) -> str:
    """Highest-priority role for display purposes ('' if none)."""
    for role in (ADMIN, STOREKEEPER, TECHNICIAN, VIEWER, BORROWER):
        if has_role(user, role):
            return role
    return ""
