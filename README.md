# Storage OS — Industrial Tool Crib

A Django 5 warehouse / tool-crib management system for industrial tools, with a
dense, dark, analytics-first dashboard, HTMX interactivity, Tailwind CSS v4
(standalone binary — no Node required), role-based access, a full stock ledger,
checkouts, maintenance scheduling, audit trail and CSV/PDF reporting.

## Stack

- Python 3.14 · Django 5.2 · SQLite (DatabaseURL ready)
- Tailwind CSS v4 via `django-tailwind` standalone binary (`manage.py tailwind build`)
- HTMX 1.9.12 · Alpine.js 3.14.1 · Chart.js 4.4.4 (version-pinned CDN)
- xhtml2pdf for PDF exports · python-decouple for env config · Pillow for tool images
- pytest-django for the test suite

## Quick start

```bat
:: 1. Virtualenv + deps
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

:: 2. Copy env and edit if desired
copy .env.example .env

:: 3. Migrate + build CSS
.venv\Scripts\python manage.py migrate
.venv\Scripts\python manage.py tailwind build

:: 4. Seed demo data (300 tools / 1065 movements / 900 checkouts including
::    14 overdue, maintenance schedules + logs, audit rows, users)
.venv\Scripts\python manage.py seed_demo_data --fresh

:: 5. Run
.venv\Scripts\python manage.py runserver
```

### Demo accounts (password `demo1234` from `SEED_PASSWORD`)

| user          | role         | notes |
|---------------|--------------|-------|
| `admin`       | (superuser)  | everything incl. audit |
| `storekeeper` | Storekeeper  | stock ops, checkouts, inventory writes, maintenance |
| `technician`  | Technician   | checkouts + maintenance |
| `viewer`      | Viewer       | read-only |
| `borrower1..6`| Borrower     | receive tool assignments |

Roles are Django groups (`accounts/roles.py`); superusers bypass every check.
`RoleRequiredMixin` maps capabilities → roles: `view`, `stock`, `checkout`,
`inventory_write`, `maintenance`, `audit`, `retire`.

## Domain model

```
inventory:   Category → Tool → Location(warehouse›zone›rack›shelf›bin, capacity)
             Supplier (lead time for reorder awareness)
transactions: StockMovement (receive/issue/return/transfer/adjust/scrap, immutable ledger)
             Checkout (open → overdue/returned, one live checkout per tool)
maintenance: MaintenanceSchedule (unique per tool+task; rolling next_due)
             MaintenanceLog (cost, notes, attachment)
accounts:    AuditLog — append-only trail for every privileged action
```

### Business rules (all in service layer, `transaction.atomic` + `select_for_update`)

- Every stock mutation writes a `StockMovement` row **and** an audit row.
- `receive` adds units (optionally re-bins the tool, checked against bin capacity).
- `transfer` moves the whole tool record — a tool has one storage address.
- `adjust` records stock-take deltas (can't go negative); `scrap` is a negative adjust.
- `check out` requires available status, on-hand quantity ≥ 1, no open checkout,
  future due date; qty is always 1. Status auto-flips to *Checked Out*.
- `return` restores quantity + condition, flips status back, writes a RETURN movement.
- `sweep_overdue_checkouts()` runs on dashboard load and flags past-due loans.
- A tool with an open checkout cannot be retired.

### KPI definitions (dashboard)

- **Utilization** = checked-out units ÷ (checked-out + available).
- **Accuracy** = share of tools whose status agrees with their open checkouts;
  delta shows the gap to 100%.
- Sparklines are **daily flow** series (movements per day in the selected window).

## Apps / URL map

| Prefix        | App         | Contents |
|---------------|-------------|----------|
| `/`           | dashboard   | KPI grid, charts, heatmap, warehouses, feed; partials `/partials/grid/`, `/partials/feed/`; JSON: `/api/dashboard/`, `/api/widget/<slug>/`, `/api/search/` |
| `/inventory/` | inventory   | filterable dense table (CSV export, bulk move/retire/export, quick edit, slide-over tool drawer with event timeline), create/edit/detail |
| `/transactions/` | transactions | stock ops (receive/issue/transfer/adjust, scan-style forms), checkout fast entry, checkout list (open/overdue/returned), returns |
| `/maintenance/` | maintenance | schedule board (due 7d / overdue / 31-day plan), task logging with rolling due dates |
| `/reports/`   | reports     | inventory valuation, movement history, overdue checkouts, maintenance history — HTML preview + CSV + PDF (audited exports) |
| `/accounts/`  | accounts    | login/logout, audit trail |

## UI notes

- Dark theme by default; toggle with `t`, density with `d` (persisted in localStorage).
- Command palette (`Ctrl-K` or `/`), table drawer (`row click`), keyboard nav:
  `g d` dashboard, `g i` inventory, `g o` stock ops, `g k` checkouts,
  `g m` maintenance, `g r` reports, `g a` audit.
- Repo includes a live-activity feed widget and per-warehouse capacity bars.
- KPI/charts publish JSON on the same service functions used by `/api/widget/`.

## Testing

```bat
.venv\Scripts\python -m pytest -q
```

Covers: stock service rules (receive/issue/transfer/adjust/scrap/quick-set/
retire guards + audit rows), checkout lifecycle + overdue sweep, maintenance
rolling due dates, HTTP smoke of every page + JSON endpoint, CSV/PDF exports,
role gating (403 for unauthorized roles, 302 for anonymous).

## Notes for productionization

- Swap `DATABASE_URL` to Postgres in `.env` (dj-database-url already wired).
- `collectstatic` for non-DEBUG deployments; serve `MEDIA` behind object storage.
- Add a callable sweep (e.g. celery beat) instead of the on-load sweep.
