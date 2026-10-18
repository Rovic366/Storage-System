import datetime as dt

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from inventory.models import Category, Location, Supplier, Tool

User = get_user_model()


@pytest.fixture
def admin_client(client, db):
    user = User.objects.create_superuser("root", "root@x.example", "root-secret-1")
    client.force_login(user)
    return client


@pytest.fixture
def store_client(client, db):
    from accounts.roles import ensure_role_groups

    user = User.objects.create_user("keeper", "keeper@x.example", "pw-123456")
    user.groups.add(ensure_role_groups()["Storekeeper"])
    client.force_login(user)
    return client


@pytest.fixture
def tech_client(client, db):
    from accounts.roles import ensure_role_groups

    user = User.objects.create_user("techie", "techie@x.example", "pw-123456")
    user.groups.add(ensure_role_groups()["Technician"])
    client.force_login(user)
    return client


@pytest.fixture
def any_client(client, db):
    """A plain authenticated user with no groups."""
    user = User.objects.create_user("nobody", "nobody@x.example", "pw-123456")
    client.force_login(user)
    return client


@pytest.fixture
def make_player(db):
    """Role-aware user factory: make_player('Storekeeper') -> staff user."""
    def _make(username="worker", roles=(), password="pw-123456"):
        from accounts.roles import ensure_role_groups

        user = User.objects.create_user(username, f"{username}@x.example", password)
        user.is_staff = True
        user.save()
        user.groups.add(*[ensure_role_groups()[r] for r in roles])
        return user
    return _make


@pytest.fixture
def kit(db):
    """One category, one supplier, one location, shared across tests."""
    cat = Category.objects.create(name="Power Tools")
    sup = Supplier.objects.create(name="Atlas Industrial", lead_time_days=4)
    loc = Location.objects.create(
        warehouse="W1", zone="A", rack="01", shelf="1", bin="A",
        code="W1-A-01-1-A", capacity=40)
    return {"cat": cat, "sup": sup, "loc": loc}


@pytest.fixture
def make_tool(db, kit):
    counter = {"n": 0}

    def _make(**kwargs):
        counter["n"] += 1
        defaults = dict(
            sku=f"TT-{counter['n']:04d}",
            name="Test drill",
            category=kit["cat"],
            supplier=kit["sup"],
            location=kit["loc"],
            unit_cost="29.99",
            quantity_on_hand=5,
            reorder_level=2,
        )
        defaults.update(kwargs)
        return Tool.objects.create(**defaults)
    return _make


@pytest.fixture
def borrower(db):
    return User.objects.create_user("borrower1", "b1@x.example", "pw-123456")


@pytest.fixture
def due_soon():
    def _make(hours=24):
        return timezone.now() + dt.timedelta(hours=hours)
    return _make
