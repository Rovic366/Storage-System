"""Seed a believable industrial tool-crib dataset.

Usage:
    python manage.py seed_demo_data            # top up demo data
    python manage.py seed_demo_data --fresh    # wipe and reseed
    python manage.py seed_demo_data --scale 0.5

Budget (scale=1): 8 categories, 5 suppliers, 3 warehouses x 12 bins,
300 tools, ~1,000 stock movements over 6 months, ~900 checkouts
(14 overdue right now, ~20 open), ~100 schedules + ~44 maintenance logs,
audit trail rows created through the real services for retire/lost paths.
"""

from __future__ import annotations

import datetime as dt
import random
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import AuditLog
from accounts.roles import ensure_role_groups
from accounts.services import audit
from inventory.models import Category, Location, Supplier, Tool
from inventory.services import move_tool_status, retire_tools
from maintenance.models import MaintenanceLog, MaintenanceSchedule
from transactions.models import Checkout, StockMovement

User = get_user_model()

R = random.Random(20260101)

CATEGORIES = [
    "Power Tools",
    "Hand Tools",
    "Measuring & Calibration",
    "Cutting Tools",
    "Safety & PPE",
    "Welding & Fabrication",
    "Hydraulics & Pneumatics",
    "Rigging & Lifting",
]

SUPPLIERS = [
    ("Atlas Industrial Supply", "Dana Whitfield", 6),
    ("BoschPro Distribution", "Marcus Lindqvist", 4),
    ("IronPeak Equipment", "Sofia Grady", 10),
    ("NovaTech Instruments", "Priya Raghavan", 15),
    ("Custos Safety Ltd.", "Hugo Ferrand", 3),
]

NAMES = {
    "Power Tools": ["Cordless drill", "Impact wrench", "Angle grinder", "Rotary hammer",
                    "Orbital sander", "Circular saw", "Jig saw", "Heat gun"],
    "Hand Tools": ["Adjustable wrench", "Ball-peen hammer", "Pry bar", "Torque wrench",
                   "Screwdriver set", "Socket set", "Allen key kit", "Hacksaw"],
    "Measuring & Calibration": ["Digital caliper", "Micrometer set", "Laser level",
                                "Torque tester", "Multimeter", "Bore gauge",
                                "Dial indicator", "Thread gauge"],
    "Cutting Tools": ["HSS drill bit set", "Hole saw kit", "Tap & die set",
                      "Carbide endmill", "Abrasive disc", "Bandsaw blade"],
    "Safety & PPE": ["Safety glasses", "Welding helmet", "Cut-resistant gloves",
                     "Ear protectors", "Respirator kit", "Hi-vis vest"],
    "Welding & Fabrication": ["MIG welder", "TIG torch kit", "Welding rods",
                              "Clamp set", "Plasma cutter", "Flux core spool"],
    "Hydraulics & Pneumatics": ["Hydraulic jack", "Pneumatic ratchet",
                                "Airlift cylinder", "Pressure gauge",
                                "Hose crimp kit", "Regulator valve"],
    "Rigging & Lifting": ["Lever hoist", "Chain sling", "Come-along",
                          "Shackle set", "Load binder", "Webbing strap"],
}

BRANDS = ["Bosch", "DeWalt", "Makita", "Stanley", "Fluke", "Snap-On", "Atlas Copco", "3M"]
TASK_TYPES = ["calibration", "inspection", "service"]


def _aware(day: dt.date) -> dt.datetime:
    return timezone.make_aware(dt.datetime.combine(
        day, dt.time(R.randint(7, 17), R.randint(0, 59))))


class Command(BaseCommand):
    help = "Seed demo/acceptance data for the industrial tool-crib storage system."

    def add_arguments(self, parser):
        parser.add_argument("--fresh", action="store_true",
                            help="Wipe demo tables before seeding")
        parser.add_argument("--scale", type=float, default=1.0,
                            help="Multiplier for data volumes (default 1.0)")

    def handle(self, *args, **options):
        self.scale = max(0.1, min(options["scale"], 5.0))
        self.today = timezone.localdate()
        self.start = self.today - dt.timedelta(days=180)

        with transaction.atomic():
            if options["fresh"]:
                self._wipe()
            R.seed(20260101)
            self._users()
            self._categories()
            self._suppliers()
            self._locations()
            self._tools()
            self._movement_history()
            self._checkout_history()
            self._final_status_pass()
            self._maintenance()
            self._audit_slice()

        self.stdout.write(self.style.SUCCESS(
            f"tools={Tool.objects.count()} "
            f"movements={StockMovement.objects.count()} "
            f"checkouts={Checkout.objects.count()} "
            f"(open={Checkout.objects.open().count()} "
            f"overdue={Checkout.objects.overdue().count()}) "
            f"schedules={MaintenanceSchedule.objects.count()} "
            f"logs={MaintenanceLog.objects.count()}"
        ))

    # ------------------------------------------------------------- wipe & base

    def _wipe(self):
        self.stdout.write("Wiping demo tables…")
        AuditLog.objects.all().delete()
        MaintenanceLog.objects.all().delete()
        MaintenanceSchedule.objects.all().delete()
        Checkout.objects.all().delete()
        StockMovement.objects.all().delete()
        Tool.objects.all().delete()
        Location.objects.all().delete()
        Supplier.objects.all().delete()
        Category.objects.all().delete()

    def _users(self):
        from decouple import config

        password = config("SEED_PASSWORD", default="demo1234")
        groups = ensure_role_groups()

        def make(username, *, email=None, is_staff=False, is_superuser=False, role=None):
            user, _ = User.objects.get_or_create(
                username=username,
                defaults={"email": email or f"{username}@crib.example",
                          "is_staff": is_staff, "is_superuser": is_superuser},
            )
            user.set_password(password)
            user.is_staff = is_staff or is_superuser
            user.is_superuser = is_superuser
            user.save()
            if role:
                user.groups.add(groups[role])
            return user

        self.admin = make("admin", email="admin@crib.example",
                          is_superuser=True, role="Admin")
        self.store = make("storekeeper", is_staff=True, role="Storekeeper")
        self.tech = make("technician", is_staff=True, role="Technician")
        make("viewer", role="Viewer")
        self.borrowers = [make(f"borrower{n}", role="Borrower") for n in range(1, 7)]

    def _categories(self):
        self.categories = []
        for name in CATEGORIES:
            cat, _ = Category.objects.get_or_create(name=name)
            self.categories.append(cat)

    def _suppliers(self):
        self.suppliers = []
        for name, contact, lead in SUPPLIERS:
            supplier, _ = Supplier.objects.get_or_create(
                name=name,
                defaults={"contact_person": contact,
                          "email": "sales@" + name.split()[0].lower() + ".example",
                          "lead_time_days": lead},
            )
            self.suppliers.append(supplier)

    def _locations(self):
        self.locations = []
        for wh in ("W1", "W2", "W3"):
            for zone in ("A", "B"):
                for rack in ("01", "02", "03", "04", "05", "06"):
                    loc, _ = Location.objects.get_or_create(
                        warehouse=wh, zone=zone, rack=rack, shelf="1", bin="A",
                        defaults={"capacity": R.randint(40, 160)},
                    )
                    self.locations.append(loc)

    # ------------------------------------------------------------------- tools

    def _tools(self):
        target = int(300 * self.scale)
        self.tools = []
        created = False
        n = 0
        while len(self.tools) < target:
            n += 1
            sku = f"TOOL-{n:05d}"
            existing = Tool.objects.filter(sku=sku).first()
            if existing:
                self.tools.append(existing)
                continue
            cat = self.categories[n % len(self.categories)]
            pool = NAMES[cat.name]
            base = pool[n % len(pool)]
            brand = BRANDS[n % len(BRANDS)]
            supplier = self.suppliers[n % len(self.suppliers)]
            location = self.locations[n % len(self.locations)]
            opening = R.choices(
                [0, 1, 2, 3, 5, 8, 12, 18, 26],
                weights=[6, 8, 12, 12, 20, 12, 8, 5, 3])[0]
            tool = Tool(
                sku=sku,
                name=f"{brand} {base}",
                description=f"Demo {base.lower()} for {cat.name.lower()}.",
                category=cat, supplier=supplier, manufacturer=brand,
                model_number=f"{brand}-{1000 + n % 9000}",
                serial_number=(f"SN-{100000 + n}"
                               if opening <= 1 and R.random() < 0.4 else ""),
                unit_cost=Decimal(R.randrange(12, 950)) + Decimal("0.99"),
                quantity_on_hand=opening,
                reorder_level=R.choice([2, 3, 4, 5, 8]),
                max_stock_level=None,
                location=location,
                status=Tool.Status.AVAILABLE,
                condition=R.choice(list(Tool.Condition.values)),
                requires_calibration=(
                    cat.name == "Measuring & Calibration" and R.random() < 0.8),
                barcode_value=f"BTC-{n:08d}",
            )
            if R.random() < 0.35:
                tool.max_stock_level = opening + R.randint(4, 30)
            self.tools.append(tool)
            created = True
        if created:
            Tool.objects.bulk_create(self.tools, batch_size=200)

    # -------------------------------------------------------- stock checkpoint

    def _movement_history(self):
        movements = []
        for tool in self.tools:
            running = tool.quantity_on_hand
            if running == 0:
                running = R.randint(4, 12)
            day = self.start + dt.timedelta(days=R.randint(0, 10))
            movements.append(StockMovement(
                tool=tool, type=StockMovement.Type.RECEIVE, quantity=running,
                to_location=tool.location, performed_by=self.store,
                reference_no=f"PO-2026-{R.randint(1000, 9999)}",
                notes="Opening stock", timestamp=_aware(day),
            ))
            ops = R.randint(2, 6)
            for _ in range(ops):
                day += dt.timedelta(days=R.randint(6, 30))
                if day >= self.today:
                    break
                kind = R.random()
                if kind < 0.55 and running >= 2:
                    q = max(1, running // R.choice([3, 4, 6]))
                    running -= q
                    movements.append(StockMovement(
                        tool=tool, type=StockMovement.Type.ISSUE, quantity=q,
                        from_location=tool.location, performed_by=self.store,
                        reference_no=f"JOB-{R.randint(500, 4999)}",
                        timestamp=_aware(day),
                    ))
                elif kind < 0.72:
                    dest = self.locations[R.randint(0, len(self.locations) - 1)]
                    if dest.pk == tool.location_id:
                        continue
                    movements.append(StockMovement(
                        tool=tool, type=StockMovement.Type.TRANSFER,
                        quantity=running, from_location=tool.location,
                        to_location=dest, performed_by=self.store,
                        timestamp=_aware(day),
                    ))
                    tool.location_id = dest.pk
                elif kind < 0.88:
                    delta = R.choice([-R.randint(1, 2), R.randint(1, 3)])
                    running = max(0, running + delta)
                    movements.append(StockMovement(
                        tool=tool, type=StockMovement.Type.ADJUST,
                        quantity=abs(delta),
                        from_location=tool.location if delta < 0 else None,
                        to_location=tool.location if delta > 0 else None,
                        performed_by=self.store, notes="Stock-take correction",
                        timestamp=_aware(day),
                    ))
                else:
                    q = R.randint(4, 14)
                    running += q
                    movements.append(StockMovement(
                        tool=tool, type=StockMovement.Type.RECEIVE, quantity=q,
                        to_location=tool.location, performed_by=self.store,
                        reference_no=f"PO-2026-{R.randint(1000, 9999)}",
                        timestamp=_aware(day),
                    ))
            tool.quantity_on_hand = running
            # guarantee a recent ledger event so 30d/90d trend windows aren't flat
            if R.random() < 0.85:
                r_day = self.today - dt.timedelta(days=R.randint(0, 40),
                                                  hours=R.randint(0, 23))
                if r_day > day:
                    if running >= 2 and R.random() < 0.5:
                        q = max(1, min(running - 1, R.randint(1, 4)))
                        running -= q
                        movements.append(StockMovement(
                            tool=tool, type=StockMovement.Type.ISSUE, quantity=q,
                            from_location=tool.location, performed_by=self.store,
                            reference_no=f"JOB-{R.randint(500, 4999)}",
                            timestamp=_aware(r_day),
                        ))
                    else:
                        q = R.randint(2, 8)
                        running += q
                        movements.append(StockMovement(
                            tool=tool, type=StockMovement.Type.RECEIVE, quantity=q,
                            to_location=tool.location, performed_by=self.store,
                            reference_no=f"PO-2026-{R.randint(1000, 9999)}",
                            timestamp=_aware(r_day),
                        ))
            tool.quantity_on_hand = running
        intended = [(m, m.timestamp) for m in movements]
        StockMovement.objects.bulk_create(movements, batch_size=500)
        for m, ts in intended:
            StockMovement.objects.filter(pk=m.pk).update(timestamp=ts)

    def _checkout_history(self):
        target = int(900 * self.scale)
        live_pin = self.tools[:]
        R.shuffle(live_pin)
        now = timezone.now()
        issue_by = R.choice([self.store, self.store, self.admin])
        checkouts, out_dates = [], []
        pairs = []  # (tool, out_at, back_at or None) -> ledger issue/return rows

        for i in range(target):
            if i < 14:  # overdue: still out, due in the past
                tool = live_pin[i % len(live_pin)]
                due = now - dt.timedelta(days=R.randint(1, 12), hours=R.randint(0, 23))
                out_at = due - dt.timedelta(days=R.randint(1, 4), hours=R.randint(0, 20))
                checkouts.append(Checkout(
                    tool=tool,
                    borrower=self.borrowers[R.randint(0, len(self.borrowers) - 1)],
                    issued_by=issue_by,
                    due_at=due,
                    condition_out=R.choice(list(Tool.Condition.values)[:2]),
                    notes=R.choice(["", "Line A repair", "Press fitting",
                                    "", "Off-site job", "Cell 2"]),
                    status=Checkout.Status.OVERDUE,
                ))
                out_dates.append(out_at)
                pairs.append((tool, out_at, None))
            elif i < 14 + 24:  # open: still out, due in the future
                tool = live_pin[i % len(live_pin)]
                due = now + dt.timedelta(days=R.randint(1, 12), hours=R.randint(0, 12))
                out_at = now - dt.timedelta(days=R.randint(0, 4), hours=R.randint(1, 16))
                checkouts.append(Checkout(
                    tool=tool,
                    borrower=self.borrowers[R.randint(0, len(self.borrowers) - 1)],
                    issued_by=issue_by,
                    due_at=due,
                    condition_out=R.choice(list(Tool.Condition.values)[:2]),
                    notes=R.choice(["", "Preventive", "Line 4", "Ramp lane"]),
                    status=Checkout.Status.OPEN,
                ))
                out_dates.append(out_at)
                pairs.append((tool, out_at, None))
            else:  # returned in the past
                tool = live_pin[R.randint(0, len(live_pin) - 1)]
                days_ago = R.randint(2, 176)
                out_at = now - dt.timedelta(days=days_ago, hours=R.randint(1, 10))
                back_at = out_at + dt.timedelta(days=R.randint(1, 8),
                                                hours=R.randint(0, 12))
                back_at = min(back_at, now - dt.timedelta(hours=R.randint(2, 72)))
                due_at = out_at + dt.timedelta(days=R.choice([2, 3, 5, 7, 14]))
                was_late = back_at > due_at
                cond_out = R.choice(list(Tool.Condition.values)[:3])
                cond_in = cond_out if not was_late else R.choice(
                    list(Tool.Condition.values))
                checkouts.append(Checkout(
                    tool=tool,
                    borrower=self.borrowers[R.randint(0, len(self.borrowers) - 1)],
                    issued_by=issue_by,
                    due_at=due_at,
                    returned_at=back_at,
                    condition_out=cond_out,
                    condition_in=cond_in,
                    notes=(R.choice(["", "Line A", "Job 5521", "",
                                     "Weekend"]) + (" | late" if was_late else "")),
                    status=Checkout.Status.RETURNED,
                ))
                out_dates.append(out_at)
                pairs.append((tool, out_at, back_at))

        # auto_now_add would stamp now(); QuerySet.update() bypasses it
        # (bulk_update refuses auto_now_add / non-editable fields)
        for co, out_at in zip(checkouts, out_dates):
            co.checked_out_at = out_at
        Checkout.objects.bulk_create(checkouts, batch_size=500)
        for co, out_at in zip(checkouts, out_dates):
            Checkout.objects.filter(pk=co.pk).update(checked_out_at=out_at)
        # mirror checkouts on the stock ledger: issue on hand-out, return on
        # hand-in; still-out rows keep the unit off-shelf
        co_move = []
        for tool, out_at, back_at in pairs:
            co_move.append(StockMovement(
                tool=tool, type=StockMovement.Type.ISSUE, quantity=1,
                from_location=tool.location, performed_by=issue_by,
                reference_no="Crib loan", timestamp=_aware(out_at),
            ))
            if back_at is not None:
                co_move.append(StockMovement(
                    tool=tool, type=StockMovement.Type.RETURN, quantity=1,
                    to_location=tool.location, performed_by=self.store,
                    reference_no="Crib loan", timestamp=_aware(back_at),
                ))
        intended2 = [(m, m.timestamp) for m in co_move]
        StockMovement.objects.bulk_create(co_move, batch_size=500)
        for m, ts in intended2:
            StockMovement.objects.filter(pk=m.pk).update(timestamp=ts)
        still_out = {}
        for tool, _out_at, back_at in pairs:
            if back_at is None:
                still_out[tool.pk] = still_out.get(tool.pk, 0) + 1
        for tool in self.tools:
            if still_out.get(tool.pk):
                tool.quantity_on_hand = max(0, tool.quantity_on_hand
                                            - still_out[tool.pk])
        Tool.objects.bulk_update(self.tools, ["quantity_on_hand"], batch_size=200)

    def _final_status_pass(self):
        live = Checkout.objects.exclude(status=Checkout.Status.RETURNED) \
            .values_list("tool_id", flat=True)
        open_ids = {tool_id for tool_id in live}
        for tool in self.tools:
            if tool.pk in open_ids:
                tool.status = Tool.Status.CHECKED_OUT
            elif tool.status == Tool.Status.CHECKED_OUT:
                tool.status = Tool.Status.AVAILABLE
        Tool.objects.bulk_update(self.tools, ["status"], batch_size=200)
        # exercise the real service paths for a few edge cases
        can_retire = [t for t in self.tools if t.status == Tool.Status.AVAILABLE][:5]
        if can_retire:
            retire_tools(Tool.objects.filter(pk__in=[t.pk for t in can_retire]),
                         self.admin)
        lost = [t for t in self.tools if t.status == Tool.Status.AVAILABLE][:3]
        for idx, tool in enumerate(Tool.objects.filter(
                pk__in=[t.pk for t in lost]).order_by("pk")):
            move_tool_status(tool, Tool.Status.LOST if idx % 2 == 0 else
                             Tool.Status.IN_MAINTENANCE, self.admin)

    # -------------------------------------------------------------- maintenance

    def _maintenance(self):
        cal_tools = Tool.objects.filter(
            category__name="Measuring & Calibration").order_by("sku")[:60]
        other_tools = Tool.objects.exclude(
            category__name="Measuring & Calibration").order_by("-sku")[:40]
        schedules = []
        seen_pairs = set()
        for tool in cal_tools:
            interval = R.choice([90, 180, 365])
            next_due = self.today + dt.timedelta(days=R.randint(-40, 120))
            if next_due < self.today:
                pass  # intentionally keep some overdue
            seen_pairs.add((tool.pk, "calibration"))
            schedules.append(MaintenanceSchedule(
                tool=tool, task_type="calibration", interval_days=interval,
                last_done=next_due - dt.timedelta(days=interval),
                next_due=next_due))
        for tool in other_tools:
            tt = R.choice(TASK_TYPES)
            if (tool.pk, tt) in seen_pairs:
                continue
            seen_pairs.add((tool.pk, tt))
            interval = R.choice([30, 60, 90])
            next_due = self.today + dt.timedelta(days=R.randint(-20, 200))
            schedules.append(MaintenanceSchedule(
                tool=tool, task_type=tt, interval_days=interval,
                last_done=next_due - dt.timedelta(days=interval),
                next_due=next_due))
        MaintenanceSchedule.objects.bulk_create(schedules, batch_size=200)

        # historical logs for a subset + exercise the real log_task roller
        historical = [s for s in schedules if s.next_due >= self.today][:int(30 * self.scale)]
        logs = []
        for s in historical:
            date = self.today - dt.timedelta(days=R.randint(20, 150))
            logs.append(MaintenanceLog(
                tool=s.tool, task_type=s.task_type, schedule=s,
                performed_by=self.tech, cost=Decimal(R.choice([0, 25, 60, 120, 175])),
                notes=R.choice(["Completed", "Passed", "Needs parts",
                                "Calibrated OK", "", "Replaced seal"]),
                date=date,
                attachments="",
            ))
        MaintenanceLog.objects.bulk_create(logs, batch_size=200)

    # ------------------------------------------------------------------ audits

    def _audit_slice(self):
        """Audit rows through real ops were already written for retire/lost;
        add a dense historical slice so /accounts/audit/ is populated."""
        rows = []
        actions = ["RECEIVE_STOCK", "ISSUE_STOCK", "CHECKOUT_TOOL", "RETURN_TOOL",
                   "TRANSFER_STOCK", "ADJUST_STOCK", "MAINTENANCE_LOG"]
        for i in range(140):
            tool = self.tools[R.randint(0, len(self.tools) - 1)]
            day = self.today - dt.timedelta(days=i % 12)
            rows.append(AuditLog(
                user=R.choice([self.store, self.admin, self.tech]),
                action=R.choice(actions),
                object_type="StockMovement" if i % 3 else "Checkout",
                object_id=str(R.randint(1, 5000)),
                object_repr=f"{tool.sku} · seeded {tool.name}",
                meta={"qty": R.randint(1, 6), "seeded": True},
                created_at=timezone.make_aware(dt.datetime.combine(
                    day, dt.time(R.randint(6, 19), 30))),
            ))
        AuditLog.objects.bulk_create(rows, batch_size=200)
