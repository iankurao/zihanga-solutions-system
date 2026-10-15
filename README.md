# Zehunger ERP

Farm management and traceability for black soldier fly (BSF) farming, built
for **Zehunger Solutions**. It follows every kilogram from the organic waste
that comes in, through larvae production, harvest, drying and quality control,
to released product lots, stock and customer deliveries, and can trace any
bag of product back to the waste it was grown on.

Flask (Python 3.11+) and PostgreSQL, with plain HTML/CSS/JavaScript pages and
no front-end build step.

---

## What it does

| Area | Pages | What people do there |
|---|---|---|
| Waste and substrate | Data entry (`/dashboard`), Farmer portal (`/farmer`) | Record waste collections as lots; prepare substrate from them |
| Production | Production batches (`/production_batch.html`), Batch 360 (`/batch-360`) | Start batches in bio-pods, record feeding, monitoring, health and harvest; see one batch's whole life |
| Drying and QC | Data entry, Product lots (`/product-lot`) | Dry harvests, record outputs and quality checks; QC officers approve or reject |
| Stock | Product lots | Released lots enter stock through a ledger of receipts, transfers, wastage and dispatches |
| Sales | Orders (`/orders`) | Customers, orders, reservations against approved stock, dispatch and confirmed delivery |
| Traceability | Traceability (`/traceability`), QR labels (`/labels`) | Trace any record up to its waste or down to its customers; print and scan QR labels |
| Oversight | Operations dashboard (`/operations`), Alerts (`/alerts`), Reports (`/analytics`) | Live figures, automatic alerts (overdue harvests, health issues, failed QC, low stock, late orders) with notifications, 12 reports with CSV/Excel/PDF |
| Administration | Admin portal (`/zehunger`), Farm setup (`/setup`), Audit log (`/audit`) | Accounts and roles, organizations, farms, sites, facilities, stores and bio-pods, the append-only audit trail |

Every record belongs to an organization, farm, site and facility, and people
see and change only the places they have been given access to.

### Roles

| Role | Can |
|---|---|
| Super admin | Everything, including setup, accounts, legacy records and the audit log |
| Manager | Production, QC decisions, stock (including write-offs), sales, alerts |
| Production operator / farmer | Record waste, substrate, batches, events, harvest and drying |
| QC officer | Record quality checks and approve or reject output |
| Inventory officer | Stock transfers and dispatches (write-offs stay with managers) |
| Sales officer | Customers, orders and deliveries |
| Viewer | Look only |

Permissions are enforced on the server for every write (`backend/roles.py`);
the pages only hide what a role cannot use.

---

## Run it locally

You need Python 3.11+ and PostgreSQL 13+.

```bash
python -m venv venv
source venv/bin/activate                 # Windows: venv\Scripts\activate
pip install -r backend/requirements.txt pytest

createdb zehunger                         # an empty database
export DATABASE_URL=postgresql://postgres:PASSWORD@localhost:5432/zehunger
export SECRET_KEY=any-local-value          # production needs 32+ random characters

python -m backend.init_db                  # create the schema (safe to repeat)
python -m backend.create_super_admin       # first administrator
python -m flask --app backend.app run --port 5000
```

Open http://localhost:5000 and sign in. Sign-in cookies are HTTPS-only;
browsers accept them on `localhost` without HTTPS, but on any other address
use HTTPS (or `SESSION_COOKIE_SECURE=0` for local testing only).

Alerts and email are processed by a background command; run it alongside the
app when you want them:

```bash
python -m backend.jobs --loop 300
```

To try the system with realistic records, load the demonstration data into a
separate database (see [Demonstration Data](#demonstration-data)).

### Tests

```bash
python -m pytest                           # needs DATABASE_URL pointing at a test database
```

Without a database only the database-free tests run. The suite covers the
whole chain role by role, every API route and the deployment files; see
[`tests/README.md`](tests/README.md).

---

## Project layout

```
backend/
  app.py              entry point (gunicorn backend.app:app)
  core/               shared layers: web app and settings, security, accounts, audit, scope
  domains/            one module per business area (waste, production, drying, quality,
                      inventory, sales, traceability, alerts, reports, dashboard, labels,
                      farmer, admin, audit, tour, health, legacy forms)
  migrations/         SQL applied by init_db on every start (idempotent)
  roles.py            roles and permissions
  notifications.py    in-app and email notifications
  jobs.py             background jobs (alerts, email, clean-up)
  preflight.py        deployment readiness check
  demo.py             demonstration dataset
  routes_doc.py       writes docs/api-routes.md
frontend/             pages, css/erp.css design system, js/ (one script per page)
deploy/               gunicorn, systemd, nginx, backup and restore scripts
docs/                 route reference, engineering rules, Phase One review, history
tests/                pytest suite
```

---

## Phase One business identifiers

Phase One production records keep their existing integer primary keys for
relationships and backward compatibility, but expose stable business IDs to
users and APIs:

| Record | Format |
|---|---|
| Waste Lot | `WL-YYYY-00001` |
| Substrate Batch | `SUB-YYYY-00001` |
| Production Batch | `BSF-YYYY-00001` |
| Harvest | `HRV-YYYY-00001` |
| Drying Batch | `DRY-YYYY-00001` |
| Product Lot | `LOT-YYYY-00001` |
| Inventory Movement | `MOV-YYYY-00001` |

The migration in `backend/migrations/phase_one_business_identifiers.sql`
creates one PostgreSQL sequence per entity and uses `nextval()` in the column
default. This is atomic under concurrent requests and deliberately does not
use `SELECT MAX(...) + 1`. Existing rows are backfilled from their preserved
primary keys; legacy fields such as `batch_no`, `batch_id`, `batch_code`, and
`lot_code` remain unchanged. Create responses return both the internal `id` and
the canonical `business_id`, while list and analytics responses include the
business ID for display.

---

## Demonstration Data

A separate database can be filled with about three months of linked,
invented records for demonstrations and training:

```bash
createdb zehunger_demo
DATABASE_URL=postgresql://user@host:5432/zehunger_demo PGDATABASE=zehunger_demo   python -m backend.demo seed --accounts-file demo-accounts.txt
python -m backend.demo status            # is this a demo database?
python -m backend.demo seed --reset      # rebuild it from scratch (demo databases only)
```

What it contains: the Zehunger Demo Co-operative with two farms (Kericho and
Nakuru), bio-pods, stores and seven staff accounts, one per role. Batches are
in every state: delivered to a customer, on the road, failed QC, in stock and
reserved, awaiting a QC decision, harvest overdue, an open health issue, ready
to harvest and just planned. Customers, orders, deliveries, stock movements,
alerts and the audit trail all come from the same records.

Safeguards:

- Seeding refuses any database that already holds farms, customers or orders
  and is not marked as a demo. `--reset` works only on a demo database.
- Everything is entered through the application's API by the matching role,
  so the demo follows every business rule.
- A demo database shows a **Demo data** badge in the app bar and never sends
  email. All addresses end in `example.com`.
- Account passwords are random on each seed and are written only to the
  `--accounts-file` (or printed). Keep that file out of version control.

### Investor demo mode

On a demo database, `/tour` is a guided tour for visitors: eight short
chapters (dashboard, one batch's life, tracing a sold product back to its
waste, the QC gate, stock, alerts, QR labels, reports), each opening the real
page at a real demo record. A tour bar with Back / Next follows the visitor
across pages. The sign-in page links to the tour, and the **Demo data** badge
opens it.

To let visitors in without an account, start the demo server with:

```bash
DEMO_GUEST_ACCESS=1
```

"Explore as a guest" then signs visitors in as the read-only *Investor
Guest* viewer: they can look at everything that role may see (no customer or
order details) and cannot change anything. Guest sign-ins are audited. The
switch is off by default, works only on a demo database, and refuses the
guest account if it has been given any role other than viewer. On a real
database `/tour` and the demo endpoints answer 404.

---

## Settings

| Variable              | Description                              | Default          |
|-----------------------|------------------------------------------|------------------|
| `DATABASE_URL`        | PostgreSQL connection URL; used for everything when set (add `?sslmode=require` for a remote server) | Required |
| `SECRET_KEY`          | Signs sessions (or `SESSION_SECRET`); 32+ random characters in production | random per start (development only) |
| `EMAIL_HOST`          | SMTP host for email notifications        | `smtp.gmail.com` |
| `EMAIL_PORT`          | SMTP port                                | `587`            |
| `EMAIL_HOST_USER`     | SMTP username                            | —                |
| `EMAIL_HOST_PASSWORD` | SMTP password / app password             | —                |
| `ADMIN_EMAIL`         | Admin notification email                 | —                |
| `APP_ENV`             | `production` refuses to start with unsafe settings (see `python -m backend.preflight`) | `development` |
| `PUBLIC_BASE_URL`     | Address printed on QR labels, e.g. `https://erp.example.com` | request host |
| `TRUSTED_PROXY_COUNT` | Proxies in front of the app whose `X-Forwarded-*` headers are trusted | `1` |
| `DB_POOL_MAX`         | Database connections each process may hold | `10` |
| `WEB_CONCURRENCY`, `GUNICORN_THREADS` | gunicorn workers and threads (`deploy/gunicorn.conf.py`) | `2`, `4` |
| `DEMO_GUEST_ACCESS`   | `1` lets visitors explore a demo database as the read-only guest (ignored on real databases) | off |
| `SESSION_COOKIE_SECURE` | `0` allows sign-in cookies over plain HTTP (local testing only; refused in production) | `1` |
| `CORS_ORIGINS`        | Other `https://` sites allowed to call the API (none needed for the app itself) | none |

Without `DATABASE_URL`, the `PG*` variables (`PGHOST`, `PGPORT`, `PGUSER`,
`PGPASSWORD`, `PGDATABASE`) are used. A complete production template is in
[`.env.example`](.env.example).

---

## Production deployment

See **[DEPLOYMENT.md](DEPLOYMENT.md)**: nginx with HTTPS, gunicorn and the
background jobs worker under systemd, nightly verified backups with a restore
drill, upgrade and rollback, and a checklist for after the first deployment.
Ready-made files are in `deploy/` and `.env.example`.

Before every deployment, with the production settings loaded:

```bash
python -m backend.preflight
```

It checks the settings, that the database is reachable with an up-to-date
schema and audit triggers, that a super admin exists, that the jobs worker and
email queue are healthy, and the database connection budget. With
`APP_ENV=production` the app itself refuses to start with unsafe settings.
`/healthz` and `/readyz` serve uptime monitors and load balancers.

---

## Documentation

| Document | For |
|---|---|
| [DEPLOYMENT.md](DEPLOYMENT.md) | Installing, upgrading, backing up and restoring a server |
| [docs/PHASE_ONE_REVIEW.md](docs/PHASE_ONE_REVIEW.md) | What Phase One delivered, how it was verified, known limitations and open decisions |
| [docs/api-routes.md](docs/api-routes.md) | Every route with the permission it requires (generated) |
| [docs/engineering-rules.md](docs/engineering-rules.md) | Invariants every change must keep (ledger stock, scope, migrations) |
| [tests/README.md](tests/README.md) | What the test suite covers |
| [docs/history/](docs/history) | Audits and designs written while Phase One was built |
| [docs/mern-conversion-guide.md](docs/mern-conversion-guide.md) | An earlier guide for rewriting the app as MERN (not used) |

---

## Troubleshooting

**Cannot connect to the database:** check `DATABASE_URL`, that PostgreSQL is
running, and run `python -m backend.preflight`.

**Signed in, but sent back to the sign-in page:** the site is reached over
plain HTTP on an address other than `localhost`, so the browser drops the
HTTPS-only cookie. Use HTTPS (or `SESSION_COOKIE_SECURE=0` for local testing).

**A user sees no records:** give them access to the organization, farm, site
or facility in the Admin portal; a role alone does not show any location.

**Schema errors after an upgrade:** run `python -m backend.init_db` (the
systemd service does this on every start).

**502 Bad Gateway from nginx:** `sudo systemctl status zehunger-web` and
`sudo journalctl -u zehunger-web -n 50`; gunicorn listens on `127.0.0.1:8000`.
