# BSF Farm Management System — Replit Reference

## Overview
A Black Soldier Fly (BSF) farm management application built with Flask (Python 3.11) and a vanilla HTML/CSS/JS frontend, developed by **Zehunger Solutions**. The system manages waste management, hatchery operations, larval feeding, drying processes, fly facility operations, sales, and analytics. It is served as a single Flask application that acts as both API backend and static file server.

---

## Tech Stack
- **Backend**: Flask 3.1.1, Python 3.11, Gunicorn 23.0.0 (WSGI server)
- **Database**: PostgreSQL 16 (Replit-managed, auto-provisioned)
- **Frontend**: Vanilla HTML5, CSS3, JavaScript — no build step required
- **Libraries**: Chart.js (analytics), SheetJS (Excel export), jsPDF (PDF export), Bootstrap 5, Font Awesome
- **Auth**: Flask-Login + Flask-Session (SQLAlchemy backend for persistent server-side sessions)
- **ORM / DB access**: psycopg2 (raw SQL with connection pooling) + Flask-SQLAlchemy (for Flask-Session only)

---

## Project Structure
```
.
├── backend/
│   ├── __init__.py                  # Python package marker (required — all imports use backend.*)
│   ├── app.py                       # Main Flask app: config, auth, routes, blueprints (1900+ lines)
│   ├── config.py                    # All configuration: DB, email, API endpoints, table names
│   ├── database.py                  # psycopg2 ThreadedConnectionPool singleton (DatabaseConnection)
│   ├── init_db.py                   # Creates all DB tables and runs migrations on startup
│   ├── waste_management_routes.py   # Flask Blueprint: waste & hatchery API routes
│   ├── fly_facility_routes.py       # Flask Blueprint: fly facility API routes (cage, eggs, etc.)
│   ├── migrations/                  # Historical SQL migration files (informational, already applied)
│   └── requirements.txt             # Python dependencies (also tracked in pyproject.toml)
├── frontend/
│   ├── main.html                    # Landing page — Admin vs Farmer portal selector (served at /)
│   ├── index.html                   # Main dashboard with all farm management sections
│   ├── analytics.html               # Analytics & reporting page (Chart.js dashboards)
│   ├── login.html                   # Login page (renders WTForms LoginForm)
│   ├── register.html                # Registration page (renders WTForms RegistrationForm)
│   ├── css/
│   │   ├── styles.css               # Dashboard and global styles
│   │   └── auth.css                 # Login/register specific styles
│   ├── images/
│   │   ├── logo.png                 # Zehunger Solutions logo
│   │   └── larvae.jpg               # Background image used in auth pages
│   └── js/
│       ├── scripts.js               # Core UI: section navigation, form handling, API calls
│       ├── dataManager.js           # localStorage CRUD for client-side form data persistence
│       ├── notificationManager.js   # Toast notification system
│       ├── analyticsManager.js      # Chart.js chart rendering and analytics data display
│       └── exportManager.js         # Excel export (SheetJS) and PDF export (jsPDF)
├── run.sh                           # Workflow startup: kill stale processes → init DB → Gunicorn
└── pyproject.toml                   # uv project manifest with all Python dependencies
```

---

## How to Set Up the Application (for Replit AI models)

## Phase One identifier strategy

Phase One user-facing identifiers are generated in PostgreSQL, not in Flask:
`WL` (waste lot), `SUB` (substrate batch), `BSF` (production batch), `HRV`
(harvest), `DRY` (drying batch), `LOT` (product lot), and `MOV` (inventory
movement), each formatted as `PREFIX-YYYY-00001`.

`backend/migrations/phase_one_business_identifiers.sql` creates one sequence
per entity and installs a `nextval()`-based default on each `business_id`
column. `RETURNING id, business_id` is used for create responses. Existing
integer primary keys and legacy text references are preserved, and historical
rows are backfilled without changing foreign keys. Runtime allocation never
uses `SELECT MAX(...) + 1`; the sequence-backed default is safe under
concurrent requests. The hatchery preview endpoint also uses its own sequence
instead of scanning `hatchery_feeding`.

## Phase One location scope and inventory ledger

- **Location scope** (`migrations/waste_lot_scope.sql`): new Waste Lots and
  Substrate Batches require `farm_id`, `site_id`, `facility_id`; substrate
  may only consume Waste Lots from the same farm and site. List/detail reads
  are filtered to the caller's location access (`_scope_visibility_clause`).
  Legacy lots keep NULL scope (never inferred from `farm_site` text) and are
  assigned once by a super admin: `POST /api/waste-lots/<ref>/location`.
- **Inventory ledger** (`migrations/inventory_ledger.sql`): stock is never a
  stored quantity. It is derived from posted `inventory_movements` per Product
  Lot and `inventory_locations` row. Types: `RECEIPT`, `TRANSFER` (one row,
  from + to), `ADJUSTMENT_IN`, `ADJUSTMENT_OUT`, `WASTAGE`. Releasing a Product
  Lot (`POST /api/product-lots`) requires `inventory_location_id` and posts
  its single `RECEIPT` in the same transaction. Movements lock the lot row,
  reject negative stock, cross-farm locations, and QC-blocked inbound moves;
  adjustments and wastage need a super admin and a reason. Do not use
  `product_lots.available_quantity_kg` (legacy, unused).
- Reads: `GET /api/inventory`, `GET /api/inventory/locations`,
  `GET /api/product-lots`, `GET /api/production/batches`; Product Lot detail
  includes `inventory` (balances + movement history).
- **Batch 360** (`/batch-360?ref=BSF-…`, `GET /api/production/batches/<ref>/360`):
  one read-only payload per production batch — source material, production,
  operations, harvest, drying, QC, product lots, stock, traceability and an
  audit trail — built only from stored relationships. A drying batch fed by
  several production batches is flagged as shared; its output is never split
  or estimated per batch.
- **Traceability** (`/traceability`, `GET /api/traceability?ref=…&type=…`,
  `GET /api/traceability/search?q=…`): trace any Waste Lot, Substrate Batch,
  Production Batch, Harvest, Drying Batch or Product Lot. Upstream follows
  stored edges backwards only and downstream forwards only, ending at current
  stock per inventory location. Linked records at locations the caller cannot
  access are returned as `restricted` with no identifiers or quantities.
  Do not use the legacy `traceability_nodes/edges` tables.
- **Customer orders** (`/orders`, `migrations/orders_deliveries.sql`): Customer
  Order → lines → allocations (a Product Lot at an inventory location) →
  deliveries. An allocation reserves stock without moving it; manual
  movements cannot take reserved stock. Dispatching posts one `DISPATCH`
  inventory movement per delivery line; confirming a delivery only records
  receipt. Cancelling (only before any dispatch) or releasing an allocation
  returns the undelivered quantity. Orders are visible to farm/organization
  users only. The legacy `sales` and `deliveries` tables are history and are
  not linked to stock — do not build on them.
- **Operational alerts** (`/alerts`, `migrations/operational_alerts.sql`):
  `_alert_candidates` evaluates rules over live records (harvest overdue/due,
  batch health alert, open health issues, QC pending >24 h or failed, blocked
  stock on hand, low free stock vs `inventory_alert_thresholds`, orders past
  requested date, deliveries unconfirmed >48 h). `_sync_alerts` keeps one
  active row per `alert_key`, resolves alerts when the condition clears, and
  reopens snoozed/acknowledged alerts that expire or escalate. Sync runs at
  most once a minute (on alert reads; forced refresh every 10 s). Alerts are
  never deleted. Production/QC/stock alerts follow facility access; order,
  delivery and low-stock alerts need farm access. Thresholds are super-admin
  only.
- **Notifications** (`backend/notifications.py`, `migrations/notifications.sql`):
  when `_sync_alerts` opens or escalates an alert, or a snooze ends, it writes
  in-app `notifications` for every user who can see that alert (per their
  `notification_preferences`) and queues email in `notification_outbox` in
  the same transaction. Email is sent later by `deliver_pending` (claim with
  a lease, SMTP outside any transaction, retry 1/5/15/60 min, FAILED after 5
  attempts, secrets redacted), so mail failures never affect ERP writes. The
  bell (`js/notificationCenter.js`) is on every main page; settings are on
  `/alerts`. Do not call the legacy `send_email` for alerts.
  - Email settings: `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`,
    `EMAIL_HOST_PASSWORD`, optional `EMAIL_FROM`; set `PUBLIC_BASE_URL`
    (e.g. `https://your-app.replit.app`) so emailed links are absolute.
    Without SMTP settings only in-app notifications are created.
  - Schedule `python -m backend.jobs` every 5 minutes (Replit Scheduled
    Deployment or cron) so alerts and email go out when nobody is using the
    app; or run `python -m backend.jobs --loop 300` as a worker. Web traffic
    also triggers evaluation (at most once a minute) and delivery.

### 1. Python Environment
Replit manages Python packages via `uv` and the `.pythonlibs/` environment. All required packages are declared in `pyproject.toml`. On a fresh import, install them before starting the workflow; `run.sh` adds `.pythonlibs/bin/` to PATH for the server.

If packages are missing, restore the declared dependencies into the environment used by `run.sh`:
```bash
UV_PROJECT_ENVIRONMENT=.pythonlibs uv sync
```

### 2. Environment Variables (automatically provided by Replit)
These are set automatically — do NOT hard-code them:

| Variable        | Description                                |
|-----------------|--------------------------------------------|
| `DATABASE_URL`  | Full PostgreSQL URL (`postgresql://...`)   |
| `PGHOST`        | DB host                                    |
| `PGPORT`        | DB port (5432)                             |
| `PGUSER`        | DB user                                    |
| `PGPASSWORD`    | DB password                                |
| `PGDATABASE`    | DB name                                    |
| `SESSION_SECRET`| Used as Flask's `SECRET_KEY`               |

The app reads `SECRET_KEY` → `SESSION_SECRET` → auto-generated fallback (in that order).

### 3. Database Initialisation
Run once to create all tables:
```bash
python -m backend.init_db
```
This is called automatically by `run.sh` on every workflow start. It uses `CREATE TABLE IF NOT EXISTS` so it is safe to run repeatedly. All tables are defined in `backend/init_db.py`.

### 4. Starting the Application
The workflow command is:
```bash
bash run.sh
```
`run.sh` does three things in order:
1. `pkill -f "gunicorn.*backend.app:app"` — kills any leftover Gunicorn processes that hold port 5000
2. `python -m backend.init_db` — creates/verifies all DB tables
3. `gunicorn --bind 0.0.0.0:5000 --reuse-port ...` — starts the app

The workflow is named **BSF Farm Server** and must have `outputType: webview` and `waitForPort: 5000`.

### 5. Critical Replit Port 5000 Issue (READ THIS)
Port 5000 in Replit is held by the platform proxy until a `waitForPort: 5000` workflow starts. If a previous Gunicorn process crashed without being killed, it may continue holding port 5000, causing the next startup to fail with `[Errno 98] Address already in use`.

**The fix is already in `run.sh`** — it runs `pkill` before starting Gunicorn. If you ever see this error in logs:
```
[ERROR] Connection in use: ('0.0.0.0', 5000)
```
Identify and kill the stale process:
```bash
# Find and kill any lingering gunicorn process
python3 -c "
import os, subprocess
for pid in os.listdir('/proc'):
    if pid.isdigit():
        try:
            fds = os.listdir(f'/proc/{pid}/fd')
            for fd in fds:
                try:
                    link = os.readlink(f'/proc/{pid}/fd/{fd}')
                    if '19441635' in link:  # replace with actual socket inode
                        print(f'PID {pid} holds port 5000')
                except: pass
        except: pass
"
# Or simply:
pkill -9 -f "gunicorn.*backend.app:app"
```
Then restart the workflow.

---

## Application Architecture

### Static File Serving
Flask serves the entire `frontend/` directory via a catch-all route:
```python
app = Flask(__name__, static_folder='../frontend', template_folder='../frontend')

@app.route('/<path:filename>')
def serve_static(filename):
    return send_from_directory(app.static_folder, filename)
```

Page routes:
| Route        | File served              | Auth required |
|--------------|--------------------------|---------------|
| `/`          | `frontend/main.html`     | No            |
| `/dashboard` | `frontend/index.html`    | Yes           |
| `/analytics` | `frontend/analytics.html`| Yes           |
| `/login`     | `frontend/login.html`    | No            |
| `/register`  | `frontend/register.html` | No            |

### Blueprint Registration
Two Flask Blueprints must be imported AND registered in `backend/app.py`:
```python
from backend.waste_management_routes import waste_management
from backend.fly_facility_routes import fly_facility

app.register_blueprint(waste_management)
app.register_blueprint(fly_facility)
```
If either line is missing, that entire set of API routes will return 404.

### Database Connection
`backend/database.py` implements a singleton `DatabaseConnection` using `psycopg2.pool.ThreadedConnectionPool`. It is instantiated once at app startup (`db = DatabaseConnection()` in `app.py`) and shared across all requests. All queries use raw SQL via `db.execute_query()`, `db.fetch_all()`, and `db.fetch_one()`.

Flask-SQLAlchemy is initialised separately (`sqlalchemy_db = SQLAlchemy(app)`) and is used **only** for Flask-Session's SQLAlchemy session table (`flask_sessions`), not for application data.

### Session Configuration
Sessions are stored server-side in PostgreSQL using Flask-Session:
```python
app.config['SESSION_TYPE'] = 'sqlalchemy'
app.config['SESSION_SQLALCHEMY'] = sqlalchemy_db
app.config['SESSION_SQLALCHEMY_TABLE'] = 'flask_sessions'
app.config['SESSION_COOKIE_SAMESITE'] = 'None'   # required for Replit iframe
app.config['SESSION_COOKIE_SECURE'] = True        # required for SameSite=None
```
The `SameSite=None; Secure` cookie settings are required because Replit serves the app inside an iframe using a proxied domain.

---

## API Endpoints

### Auth (inline in app.py)
| Method | Route                  | Description          |
|--------|------------------------|----------------------|
| GET/POST | `/login`             | Login page + form    |
| GET/POST | `/register`          | Register page + form |
| GET    | `/logout`              | Logout               |
| POST   | `/api/auth/login`      | JSON login           |
| POST   | `/api/auth/register`   | JSON register        |

### Waste Management Blueprint
| Method | Route                                           |
|--------|-------------------------------------------------|
| POST   | `/api/waste-sourcing`                           |
| GET    | `/api/waste-sourcing`                           |
| POST   | `/api/storage-records`                          |
| POST   | `/api/processing-records`                       |
| POST   | `/api/environmental-monitoring-waste`           |
| POST   | `/api/environmental-monitoring-larvaefeeding`   |
| POST   | `/api/substrate-preparation`                    |
| POST   | `/api/larvae-feeding`                           |
| POST   | `/api/health-intervention`                      |
| POST   | `/api/harvest-yield`                            |
| POST   | `/api/hatchery/batch-information`               |
| POST   | `/api/hatchery/feeding-records`                 |
| POST   | `/api/hatchery/environmental-monitoring`        |

### Fly Facility Blueprint
| Method | Route                                  |
|--------|----------------------------------------|
| POST   | `/api/fly-facility/cage-monitoring`    |
| POST   | `/api/fly-facility/maintenance`        |
| POST   | `/api/fly-facility/pupae-transition`   |
| POST   | `/api/fly-facility/egg-collection`     |
| POST   | `/api/fly-facility/bait-preparation`   |

---

## Known Issues Fixed

| Issue | Root Cause | Fix Applied |
|-------|-----------|-------------|
| `ModuleNotFoundError: No module named 'psycopg2'` on startup | `run.sh` used system Python without `.pythonlibs` on PATH | `.pythonlibs/bin` is now on PATH by default in Replit; `run.sh` no longer needs to set it manually |
| `[Errno 98] Address already in use` on port 5000 | Previous Gunicorn process not cleaned up on workflow restart | `run.sh` now runs `pkill -f "gunicorn.*backend.app:app"` before starting |
| `gunicorn: not found` | Workflow `Start application` used wrong command (`gunicorn main:app`) | Removed that workflow; only `BSF Farm Server` runs `bash run.sh` |
| Fly facility API endpoints returning 404 | `fly_facility` blueprint defined in `fly_facility_routes.py` but never imported or registered in `app.py` | Added `from backend.fly_facility_routes import fly_facility` and `app.register_blueprint(fly_facility)` to `app.py` |
| Duplicate workflows conflicting | Both `BSF Farm Server` and `Start application` tried to bind port 5000 | Removed `Start application` workflow; only `BSF Farm Server` is active |
| Deployment (publish) run command incorrect | Replit deployment config pointed to `main:app` — no `main.py` exists at root | Updated deployment run command to `backend.app:app` to match the actual entry point |
| Packages missing in Replit environment | Replit environment was fresh with no installed packages | Installed all required packages via `uv add`: `flask`, `flask-sqlalchemy`, `psycopg2-binary`, `email-validator`, `gunicorn`, and all transitive dependencies; pinned in `pyproject.toml` |
| `GET /api/substrate/batches/:id` returns 404 silently | Route called by `validateSubstrateBatchId()` in `scripts.js` line 131 but never defined in `app.py` | Added `GET /api/substrate/batches/<batch_no>` route querying `substrate_preparation` table |
| Full Process Flow chart always shows 0 for all values | 4 field name mismatches in `scripts.js` Full Process Flow analysis: `harvest_yield` uses `tray_batch_id` (not `batch_id`); `drying_input` column is `wet_placed_for_drying_kg` (not `wet_placed`); `drying_output` column is `dried_produced_kg` (not `dried_produced`); `waste_sourcing` key was wrong order | Fixed all 4 field name lookups in `scripts.js` lines 973–995 to use correct DB column names with camelCase fallbacks |
| Duplicate `POST /api/environmental-monitoring` inserting duplicate rows | `app.py` had two POST handlers inserting to `waste_monitoring`: one at `/api/environmental-monitoring` (dead) and one at `/api/waste-monitoring` | Removed the dead handler; only `POST /api/waste-monitoring` remains |

---

## Gunicorn Command Reference
```bash
gunicorn \
  --bind 0.0.0.0:5000 \
  --reuse-port \
  --workers 1 \
  --threads 4 \
  --timeout 120 \
  --access-logfile - \
  --error-logfile - \
  backend.app:app
```
- **`--workers 1`**: Single worker keeps Flask-Login session state consistent (sessions are server-side in DB so multiple workers are safe, but 1 is sufficient for this workload)
- **`--threads 4`**: Handles concurrent requests within the single worker
- **`--reuse-port`**: Allows restart without waiting for socket TIME_WAIT
- **`backend.app:app`**: Module path from project root; requires `backend/__init__.py` to exist

---

## Setup History
- **October 2025**: Initial development; configured for Replit (PostgreSQL, Gunicorn, port 5000); added `__init__.py`; switched to module-style invocation
- **March 2026**: Completed Replit environment import — installed all Python packages via `uv add` (pinned in `pyproject.toml`); fixed deployment run command from `main:app` → `backend.app:app` (no `main.py` exists at root); resolved port 5000 conflict with `pkill` guard in `run.sh`; fixed duplicate workflow (`Start application` removed, only `BSF Farm Server` remains); registered missing `fly_facility` blueprint in `app.py`; updated `pyproject.toml` description; confirmed database auto-initialises cleanly on first boot; updated all documentation. Deep API/frontend audit completed: added missing `GET /api/substrate/batches/<batch_no>` route; fixed 4 wrong DB column names in Full Process Flow Efficiency analysis (all values were reading as 0); removed duplicate dead `POST /api/environmental-monitoring` handler that shadowed the active `-waste` variant.
