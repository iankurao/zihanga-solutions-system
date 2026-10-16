# Phase One review and handover

Review date: 15 October 2026 (Step 30 of the Phase One plan).

## Verdict

Phase One is **complete and ready for a supervised pilot** on a real server,
following [DEPLOYMENT.md](../DEPLOYMENT.md). The full chain from waste to
customer delivery works end to end, is enforced on the server, traceable both
ways and audited, and the automated test suite passes in full.

It is **not yet proven with real farm data or a real server**: no real
records have been migrated and email has not been sent through a real mail
server. The backup and restore drill has passed with real PostgreSQL 16.6
tools on the development machine and should be repeated once on the server.
Those checks belong in the first week of the pilot (see
[Before go-live](#before-go-live)).

## What Phase One delivers

| Steps | Area | Delivered |
|---|---|---|
| 1-11 | Foundation and core chain | Business IDs (`WL-`, `SUB-`, `BSF-`, `HRV-`, `DRY-`, `LOT-`, `MOV-`), the organization > farm > site > facility hierarchy with per-user access, waste lots, substrate batches, production batches with feeding / monitoring / health / harvest events, drying batches, quality checks and approvals, product lot release. These existed when this work began and were completed (canonical scope on every new record, scoped reads, legacy record mapping) |
| 12 | Inventory | Stock derived only from a ledger of posted movements; one receipt per released lot; transfers, adjustments, wastage, dispatch; stock can never go negative, even under concurrent requests |
| 13 | Batch 360 | One page with a batch's whole life: inputs, events, yields, drying, QC, lots, stock, alerts |
| 14 | Traceability | Any record traced up to its waste and down to its customers, with hidden placeholders for records the user may not see |
| 15 | Orders and deliveries | Customers, orders, reservations against approved stock only, dispatch, confirmed delivery |
| 16-17 | Alerts and notifications | Rules for overdue / due harvests, open health issues, failed or pending QC, low stock, late orders; in-app bell and email with per-user preferences; background jobs worker |
| 18-19 | Reports and dashboard | 12 reports with CSV, Excel and PDF; live operations dashboard by farm, facility and period |
| 20 | Farmer portal | Mobile-first portal for operators; bio-pods (production units) |
| 21 | QR labels | Printable labels; scanning opens the record only for people allowed to see it |
| 22 | Roles and security | Seven roles, every write permission-checked on the server, cross-site request protection, HTTPS-only cookies, sign-in throttling, password rules |
| 23 | Audit log | Append-only, trigger-based on 28 tables with the acting user; sign-in and security events; `/audit` page |
| 24 | Architecture | `backend/core` (shared layers) and `backend/domains` (one module per area), with tests that keep the layering |
| 25 | Design system | One stylesheet of tokens and components, shared navigation, accessible contrast, used by every page |
| 26 | Test suite | Role-by-role end-to-end chain, access isolation, legacy forms, front-end logic, route coverage |
| 27-28 | Demo | `python -m backend.demo seed` builds two demo farms with three months of history through the real API; guided investor tour with optional read-only guest access |
| 29 | Deployment | `python -m backend.preflight`, production start-up guard, `/healthz` and `/readyz`, gunicorn / systemd / nginx files, verified backups and a restore drill, `DEPLOYMENT.md` |
| 30 | Review | This document; Replit removed; the fixes below |

## How it was verified

- **Automated tests:** 155 tests pass against PostgreSQL 16 (plus 152
  subtests), including the whole chain performed role by role with real
  sign-ins. All 137 of the application's endpoints are called by the suite
  (`ROUTE_COVERAGE`).
- **Browser:** every page loaded as the super admin on the demo database with
  no failed requests or script errors; the investor tour walked end to end as
  the guest; phone-width layouts checked for the dashboard, tour and tour bar.
- **Code review sweeps (this step):** no route reachable without sign-in other
  than the intended public pages; no SQL built from user input (table and
  column names come from fixed lists, values are parameters); no database
  error text returned to users; no unused front-end files; every script parses.

## Fixed in this review

| Problem | Effect | Fix |
|---|---|---|
| Legacy analytics tables inserted record text as HTML | **Stored cross-site scripting:** text typed into a legacy form could run as script in a super admin's browser | All values escaped; a test renders all 24 panels with HTML in every field |
| Server messages inserted as HTML on the data-entry dashboard and registration page | Same class of problem, lower risk | Inserted as text |
| Signing out with an expired session asked the user to sign in, then signed them out again | Confusing loop | Sign-out works without a session; sign-in never redirects to sign-out |
| Deployment guide offered Ubuntu 22.04 | Its Python 3.10 cannot run the app (3.11+ needed) | Ubuntu 24.04 LTS |
| Replit workspace files, preview-iframe setting and project name | Platform lock-in; a setting that weakened cookies and framing | Removed (`EMBEDDED_PREVIEW` now has no effect); attachments moved out of the repository |
| Agent memory notes in `.agents/` | Useful rules hidden in a tool folder | Kept as [engineering-rules.md](engineering-rules.md) |

## Retiring the forms without a location (16 October 2026)

After the review the owner chose to retire every form whose records had no
farm, site and facility. Checking each form showed the problem was larger
than the review said: besides the hatchery, fly facility, waste-handling and
legacy sales forms, the **drying batch, input and output forms** also wrote
records without a location, and no page could create a traceable drying
batch at all. That was only possible through the API, so in practice the
drying, QC and release steps could not be run from the screens. The review's
verdict above should be read with that correction.

| Before | Now |
|---|---|
| 13 hatchery, fly facility and waste-handling forms wrote rows with no location | Same forms, same fields, now with a farm / site / facility picker; records saved through `/api/farm-operations/<kind>` with type and range checks, location access, the audit log, and a database rule that refuses new rows without a location. Readable by everyone with access to the location (`GET /api/farm-operations/<kind>`) |
| Hatchery feeding filled its batch field with a newly generated batch number (every page load used one up) | Feeding is chosen from the farm's real hatchery batches; numbers are assigned when a batch is saved |
| Drying batch / input / output forms wrote rows with no location; QC, approval and release asked for internal ID numbers | Start a drying batch (facility + harvest), add harvests, move to the next stage, record output, QC check, QC decision and release: all from pick-lists fed by `GET /api/drying/batches` and `GET /api/drying/available-harvests`, through the scoped drying API |
| QC officers could not reach the drying section from the menu | The drying menu entry shows for production and QC roles |
| Legacy sales, deliveries and feedback forms | Removed; old records stay as read-only history for super admins; new sales are customer orders |
| 31 old write routes (plus a duplicate fly-facility blueprint) | Removed; a test checks every one answers 404/405 |

The farmer portal links to the hatchery, fly facility and waste-handling
forms. Every screen in the system now records a farm, site and facility,
except compatibility copies the scoped waste and substrate flows write
alongside their scoped records.

Checked in the browser on the demo database as a farmer and a QC officer: a
harvest from the farmer portal, a hatchery batch and its feeding, a cage
check, then a drying batch through every stage, QC check, approval and
release of LOT-2026-00005, which traces back to its waste lot.

## Figures and reports read the production chain (16 October 2026)

The admin portal and several report panels still counted only the old
tables, which nothing writes to any more: on the demo data the admin overview
showed 0 kg harvested, 0 kg dried and 0 revenue while the chain held 389 kg
harvested, 119.3 kg dried and 5 customer orders.

- **Admin portal** (overview, farmer list and details, activity feed,
  inactive farmers, CSV export) now counts waste lots, recorded harvests,
  drying outputs, feeding events and confirmed deliveries, attributed to the
  person who recorded them; "last activity" comes from the audit log, so every
  kind of record counts. Orders carry no prices, so the revenue tile became
  **kg delivered to customers**.
- **Retired** (they read only the old tables): the six `/api/statistics/*`
  endpoints and the harvest-efficiency panel, the 24 legacy analytics panels on
  the reports page with their 23 endpoints, the seven "list everything"
  endpoints and the old sales / deliveries / feedback lists, and the unused
  waste-management blueprint. The operational reports and dashboard replace
  them; a new **Farm operation logs** report covers the hatchery, fly facility
  and waste-handling logs, by area, farm, facility and dates.
- **Kept as the plain history view:** the super-admin records lookup on the
  data-entry page (records by date and section), now with a Sales section for
  the old sales, deliveries and feedback.
- The harvest report email only listed the old harvest table; it now lists
  recorded harvests too, and says so when email is not set up or sending
  failed instead of reporting success.

The breeding cycle (hatchery, fly facility) is still recorded per location
but not linked to production batches; see Suggested Phase Two.

## Known limitations

1. **Old records have no location.** Hatchery, fly facility, waste-handling
   and drying records entered before 16 October 2026 have no farm, site and
   facility (unless an administrator mapped them). They stay as history for
   super admins and are not part of traceability or stock.
2. **Stock receipt time is the release time.** A lot enters stock at the
   moment QC releases it; it cannot be backdated. This matters when entering
   historical records (and is why demo stock movements are dated the day the
   demo was built).
3. **Notifications go to everyone with access to the location** whose role
   may see that kind of alert (commercial alerts only to sales roles), not to
   a narrower list per alert type.
4. **No self-registration** (owner's decision, 16 October 2026): an
   administrator creates every account in the Admin portal with its role,
   then grants its locations. `/register` only sends old links to sign-in.
5. **Sign-out is a plain link (GET)**, so another site could sign a user out.
   It cannot do anything else.
6. **Not load-tested.** Sizing guidance in DEPLOYMENT.md (2 workers x 4
   threads) is an estimate for a few dozen staff.
7. **No automated browser tests.** Pages are covered by structure tests and
   the API tests behind them; clicking through was done by hand.
8. **Dependency audit not run.** The pinned versions (`backend/requirements.txt`)
   have no advisories I am aware of, but run `pip-audit` before go-live.
   The pins suit Python 3.11-3.12; Python 3.13 needs `psycopg2-binary` 2.9.10.
9. **`uv.lock` was renamed by hand** (project name only). Run `uv lock` once
   where `uv` is installed to confirm it.

## Before go-live

1. **Restore drill on the server:** take a backup with `deploy/backup.sh`
   and restore it with `deploy/restore-check.sh` (DEPLOYMENT.md section 10).
   On the development machine (15 October 2026, PostgreSQL 16.6 tools) the
   demo database was backed up (356 KB, verified), restored into an empty
   database with identical record counts including 223 audit entries, the
   restored audit log still refused deletion, and the readiness check passed
   on the copy. The drill found and fixed a bug: `restore-check.sh` passed
   options to `psql` after the database address, which some `psql` builds
   ignore, so it would never restore.
2. **Email:** configure SMTP, trigger a test alert and confirm it arrives.
3. **Real data:** decide what of the old records to bring over. The original
   hosted development database was empty when inspected
   ([history/PHASE_ONE_DATABASE_MIGRATION_MAP.md](history/PHASE_ONE_DATABASE_MIGRATION_MAP.md)),
   so if live data exists elsewhere it has never been seen by this code.
   Import into a copy first and run `python -m backend.preflight`.
4. `python -m backend.preflight --strict` passes on the server.
5. Uptime monitor on `/readyz`; backups copied off the server daily.

## Decisions for the owner

| Decision | Options |
|---|---|
| Notification routing | Keep location-based, or route each alert type to chosen roles |
| Backdated stock entry | Needed for importing history? It would require a controlled "opening balance" movement type |

## Suggested Phase Two

- Hatchery and fly-facility records as linked batches (egg batch to larvae
  batch), like the production chain.
- Opening-balance and backdated stock movements for data import.
- Role-based notification routing; SMS or WhatsApp for critical alerts.
- Sign-out by POST.
- Automated browser tests for the main flows (Playwright).
- Offline support for the farmer portal (field sites with poor signal).
- Invoicing and payments on top of deliveries.
