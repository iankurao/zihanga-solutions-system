# BSF Production Chain: Current State

## Scope and reading notes

This is a repository-level trace of the imported application and later Phase One
production-chain implementation. It describes source files, not a verified
production database. The Step 8 and Step 9 implementation updates at the end
supersede older Harvest, Drying, and Product Lot linkage statements below; they
do not claim that the standalone ERP SQL file was applied or that legacy rows
were reconciled.

The operational app uses direct SQL from Flask handlers and `backend/init_db.py`; no ORM model classes for this chain were found. Most database tables are therefore described below by their SQL table definitions.

## Current state at a glance

```text
Waste sourcing
    ↓ ? no source lot is carried forward
Storage
    ↓ ? no storage record is tied to a waste lot
Processing
    ↓ ? no processing input/output link to storage or substrate
Substrate preparation
    ↓ ? legacy batch number is not a production-batch foreign key
BSF production
    ↓ ? no operational production-batch API or form
Feeding / Monitoring / Health intervention
    ↓ ? tray/batch identifiers are text, not enforced production links
Harvest
    ↓ Phase One Step 7: each new harvest event references its production batch
Drying
    ↓ Phase One Step 8: canonical inputs reference one or more harvests
Quality control
    ↓ Step 9: output-specific passing QC and approval gate Product Lot release
Product lot
    ↓ ? no inventory ledger or stock-movement UI
Inventory
```

The requested short form is:

```text
Waste ↓ ? ↓ Substrate ↓ ? ↓ Production Batch → Harvest ↓ ? ↓ Drying ↓ ? ↓ Product ↓ ? ↓ Inventory
```

The question marks mean missing enforced lineage, not necessarily missing data-entry screens. Some steps have working-looking forms and endpoints, but their records remain independent. The notable exception in the schema is an unconnected set of ERP-v2 tables, which has some foreign keys but no discovered route or form integration.

## Stages, tables, IDs, routes, and current links

| Stage | Repository tables and identifiers | Existing endpoints and Flask location | Frontend | Link status |
|---|---|---|---|---|
| **Waste sourcing** | Operational `waste_sourcing` (`id` PK; date/time, source type/name, waste type, `waste_weight`, segregation, contaminants, personnel). Separately, ERP v2 defines `waste_sources` (`id`, unique `source_code`), `waste_collection_runs` (`id`, unique `run_code`), and `waste_collection_items` (`id`, unique `lot_code`, `run_id` FK, `waste_source_id` FK). | `POST /api/waste-sourcing` in `backend/app.py:707-751`; `GET /api/waste-sourcing` in the `waste_management` blueprint (`backend/waste_management_routes.py:9-16`); duplicate authenticated list `GET /api/waste-sourcing/all` in `app.py:1292-1297`; analytics `GET /api/analytics/waste-sourcing`. | `wasteSourcingForm` in `frontend/index.html:110-211`: collection time/date, source, type/weight, segregation, personnel, contaminants, notes. | Legacy record has no outgoing FK or lot ID. ERP collection items do identify source and collection run, but no handler/UI was found to create or use them. |
| **Storage** | `storage_records` (`id` PK; date, method, conditions, duration, planned utilization, observations). | `POST /api/storage-records` in `app.py:753-787`; `GET /api/storage-records` in `waste_management_routes.py:18-25`; analytics `GET /api/analytics/storage-records`. | `storageRecordsForm` (`index.html:216-275`). | No waste lot, sourcing, or storage-location FK. The record cannot establish which sourced quantity was stored. |
| **Processing** | `processing_records` (`id` PK; date, type/method, `waste_processed`, `waste_reduction`, remarks). | `POST /api/processing-records` in `app.py:790-824`; `GET /api/processing-records` in `waste_management_routes.py:27-34`; analytics `GET /api/analytics/processing-records`. | `processingRecordsForm` (`index.html:278-328`). | No input-storage or output-substrate reference. |
| **Substrate preparation** | Operational `substrate_preparation` (`id` PK; `batch_no`, date, `organic_waste_source`, moisture/particle-size/foreign-matter fields, optional `substrate_introduced_kg`). ERP v2 separately defines `substrate_batches` (`id` PK, unique `batch_code`, input/output weights, moisture, particle size, approval fields, `waste_lot_ids TEXT`). | `POST /api/substrate-preparation`, `GET /api/substrate/batches/<batch_no>`, and analytics `GET /api/analytics/substrate-preparation` in `app.py:826-874,1389-1393`. | `substratePreparationForm` (`index.html:480-552`): batch number/date, organic waste source, moisture, particle size, foreign matter, substrate kg, operator, notes. | The operational `batch_no` is not a foreign key. ERP `waste_lot_ids` is text, not a relational link to ERP waste items. ERP `production_batches` does reference `substrate_batches`, but none of these ERP tables are connected to this form/route. |
| **BSF production** | No production-batch table in the schema built by `backend/init_db.py`. ERP v2 defines `production_batches` (`id` PK, unique `batch_code`, `substrate_batch_id` FK, dates/stage, `tray_ids TEXT`, egg/larvae/harvest/mortality fields) and `lifecycle_events` (`id` PK, `production_batch_id` FK, event type/date, from/to stage). | No production-batch or lifecycle-event API routes found. | No dedicated BSF production-batch form. Hatchery forms capture hatchery records, not the ERP `production_batches` lifecycle. | The ERP production → substrate link exists only in the SQL design; current operational code does not use it. |
| **Feeding** | `feeding_schedule` (`id` PK; date, `tray_batch_id`, larvae age/weight, feed type/quantity, start/end weight, consumption, operator). Separate `hatchery_feeding` has `id` and a plain-text `batch_id`. | `POST /api/feeding/schedule`, analytics `GET /api/analytics/feeding-schedule` (`app.py:1561-1600,1407-1411`). Hatchery feeding has `POST /api/hatchery/feeding` and alias `POST /api/hatchery/feeding-records` (`app.py:1895-1919,2025-2029`) plus hatchery analytics. | `feedingScheduleForm` (`index.html:557-615`) and a distinct hatchery `feedingRecordsForm` (`index.html:1587-1650`). | `tray_batch_id` and hatchery `batch_id` are strings with no FK to a production batch or substrate. The hatchery interface is a separate records path, not a link from the lifecycle schema. |
| **Monitoring** | `waste_monitoring` (`id` PK; waste conditions/pests/actions); `environmental_monitoring_larvaefeeding` (`id` PK; `tray_facility_id` text, temperature/humidity/ammonia); `cage_monitoring` (`id` PK; `cage_id` text and facility conditions); `hatchery_monitoring` (`id` PK). | Waste monitoring: `POST /api/waste-monitoring`; `GET /api/environmental-monitoring` in `waste_management` actually selects `waste_monitoring`; analytics aliases `/api/analytics/waste-monitoring` and `/api/analytics/waste-env-monitoring`. Larval: `POST /api/feeding/environmental-monitoring`, analytics `/api/analytics/larvae-env-monitoring`. Cage: direct app `POST /api/facility/cage-monitoring` and blueprint `POST /api/fly-facility/cage-monitoring`, plus analytics `/api/analytics/cage-monitoring`. Hatchery: `POST /api/hatchery/monitoring` and `/api/hatchery/environmental-monitoring` alias. | Waste environmental form (`index.html:334-407`), larval environmental form (`428-475`), cage monitoring (`1337+`), hatchery monitoring (`1654-1688`). | No monitoring record has a foreign key to a production batch. Waste, larvae, cage/facility, and hatchery monitoring are separate concepts and should not be treated as interchangeable. |
| **Health intervention** | `health_intervention` (`id` PK; `tray_batch_id` text, issue, severity, follow-up/resolution/action). Separate `hatchery_health_interventions` (`id` PK; hatchery issue/action/follow-up fields). The migrations also define a different `feeding_health_intervention` table. | `POST /api/feeding/health-intervention`, analytics `GET /api/analytics/health-intervention` (`app.py:1509-1533,1395-1399`). Hatchery has `POST /api/hatchery/health` (`app.py:1988-2016`). | `healthInterventionForm` (`index.html:671-728`) and separate hatchery problems/health interfaces. | Legacy intervention refers to a free-text tray/batch ID, not an enforced production batch; hatchery records are separate. |
| **Harvest** | Legacy `harvest_yield` remains historical and unlinked. New harvests use `production_events` (`event_type='harvest'`) and one-to-one child `harvests` rows with HRV codes, wet weight/unit, stage, operator, and location. | `POST /api/production/batches/<batch>/events/harvest` (also the legacy form route); batch detail joins harvest events and totals. | Harvest tab on `production_batch.html` and the linked harvest form in `index.html`. | Every new harvest is tied by the event FK to one production batch. Legacy `tray_batch_id` records are not backfilled. |
| **Drying** | Legacy tables remain: `drying_batches`, `drying_input`, `drying_output`, `drying_quality_control`, and `drying_review_approval`. Step 8 adds canonical scope/lifecycle fields to `drying_batches`, plus `drying_inputs`, `drying_outputs`, status history, `quality_checks`, and `quality_approvals` with typed foreign keys. | Existing drying routes remain available. Canonical routes include `/api/drying/batches`, `/api/drying/batches/<ref>`, `/inputs`, `/outputs`, `/status`, `/quality-checks`, and `/api/drying/quality-approvals`; legacy routes branch to the canonical path when canonical fields are supplied. | The existing Drying Process section now includes a Drying Batch Trace view with SOURCE, PROCESS, and OUTPUT panels. Legacy entry forms remain for historical records. | Canonical input rows reference harvest rows and lock/check available wet quantity. Canonical outputs store measured quantity, moisture, operator, input snapshot, yield ratio, and yield percentage. |
| **Quality control** | Canonical `quality_checks` can target a specific output through `drying_output_id`; decisions remain in append-only `quality_approvals`. | `POST /api/drying/outputs/<output_id>/quality-checks`; existing batch-check and approval routes remain. | Drying QC and review forms support output-specific checks and approvals. | Lot release requires the latest output-specific check to pass and its latest approval to be approved. |
| **Product lot** | Additive `product_lots` extension: unique `business_id`, `drying_output_id`, `release_approval_id`, farm, measured quantity in kg, unit, production date, optional storage location, and status. | `POST /api/product-lots` releases a referenced output; `GET /api/product-lots/<ref>` returns the lot and lineage. | Drying Process has a release form; `/product-lot?ref=...` is the authenticated detail screen. | One lot can be released per output. It is `AVAILABLE` only after output-specific passing QC and approved release on a completed Drying Batch. Old unlinked lots are not backfilled. |
| **Inventory** | No inventory table or stock-movement table found. The closest fields are ERP product lot `available_quantity_kg`, `storage_location`, and `status`. | No `/api/inventory` route found. | No inventory UI. Customer sales and deliveries are present, but they are not connected to product-lot stock. | No ledger, reservation, adjustment, or stock-decrement link exists. `available_quantity_kg` alone is not an inventory history. |

### Linkage summary

**Links enforced by the ERP-v2 SQL design:**

- `waste_collection_items.waste_source_id` → `waste_sources.id`
- `waste_collection_items.run_id` → `waste_collection_runs.id`
- `production_batches.substrate_batch_id` → `substrate_batches.id`
- `lifecycle_events.production_batch_id` → `production_batches.id`
- `quality_checks.drying_output_id` → `drying_outputs.id`
- `product_lots.drying_output_id` → `drying_outputs.id`
- `product_lots.release_approval_id` → `quality_approvals.id`
- Downstream order: `farmer_orders.product_lot_id` → `product_lots.id`

`substrate_batches.waste_lot_ids` is not a foreign key. The canonical
`substrate_batch_inputs` relationship carries new substrate-to-waste lineage.
No relationship connects product lots to inventory movements.

**Operational links are mostly labels, not relations.** `batch_no`, `tray_batch_id`, `tray_facility_id`, `cage_id`, and drying `batch_id` are text identifiers. They may be entered consistently by people, but the schema cannot ensure the referenced record exists or that two values refer to the same production run.

## Flask structure and endpoint coverage

`backend/app.py` registers two blueprints (`app.py:102-104`), but most chain create/read/analytics routes are declared directly on `app`.

- `waste_management` (`backend/waste_management_routes.py`) provides unauthenticated GETs for `/api/waste-sourcing`, `/api/storage-records`, `/api/processing-records`, and `/api/environmental-monitoring`. The last one returns waste monitoring despite its broad path.
- `fly_facility` (`backend/fly_facility_routes.py`) provides POSTs for cage monitoring, facility maintenance, pupae transition, egg collection, and bait preparation at `/api/fly-facility/...` paths (configured in `backend/config.py:28-50`). The app also has a separate authenticated cage-monitoring POST at `/api/facility/cage-monitoring`.
- Direct authenticated `app.py` routes create most operational chain rows. The app normalizes many frontend camelCase field names to snake_case before SQL inserts.
- Analytics routes mostly expose per-table records. They do not construct a joined production genealogy. The analytics frontend's process-efficiency logic reads waste sourcing, harvest, and drying input/output, not the complete chain (`frontend/js/scripts.js:1018-1025`).
- Hatchery, fly-facility, sales, and delivery APIs are adjacent application features, not evidence that the listed production stages are linked. In particular, sales/deliveries do not decrement or reserve `product_lots.available_quantity_kg`.

## Existing frontend entry points

`frontend/index.html` is a single operations page with forms grouped into Waste Management, Larval Feeding, Drying Process, Hatchery, Fly Facility, Records/Reports, and Sales/Deliveries. There is no single end-to-end production view. `frontend/analytics.html` presents database-backed analytics tabs but is not a production genealogy. `frontend/zehunger_portal.html` and `frontend/js/zehungerPortal.js` manage the farmer/admin portal rather than this chain.

The generic form submission map is in `frontend/js/scripts.js:89-113`; it posts JSON to the operational app endpoints. Drying uses a separate submit path around `scripts.js:900-960`. `frontend/js/dataManager.js` has a localStorage helper, but the operational form submission path posts to the backend; it is not the chain's persistence implementation.

## Existing migrations and schema conflicts

The repository contains these SQL files under `backend/migrations/`:

| File(s) | Relevance and observed risk |
|---|---|
| `erp_schema_v2.sql` | Defines ERP waste aggregation, substrate/production lifecycle, product lots, farmer orders, traceability graph, roles, and other ERP modules. The chain-relevant portions are detailed below. No reference from the Flask app or `init_db.py` to applying this file was found. |
| `feeding_schedule_table_migration.sql`, `feeding_harvest_yield_table_migration.sql`, `feeding_health_intervention_table_migration.sql`, `feeding_environmental_monitoring_table_migration.sql` | Define alternate feeding/harvest/health/monitoring tables, names, IDs, and units that differ from the operational tables used by `app.py`. Some drop and recreate tables. |
| `feeding_tables_migration.sql`, `update_hatchery_feeding_table.sql` | Replace or recreate feeding/hatchery tables; the former backs up and then drops operational feeding/harvest/health tables before defining hatchery tables. |
| `add_recorded_by_to_feeding_and_facility_tables.sql`, `add_recorded_by_to_feeding_harvest_yield.sql`, `add_recorded_by_to_feeding_health_intervention.sql` | Add audit columns to migration-era table names; those names do not consistently match the active `init_db.py` schema and app insert targets. |
| `drying_tables_migration.sql`, `recreate_drying_batches_table.sql`, `consolidate_drying_tables.sql` | Three incompatible drying designs: child tables with numeric batch IDs/FKs; then text batch IDs with child FKs and different columns; then a destructive consolidation into a single wide table. These conflict with the active `init_db.py` layout and current app SQL. |
| `fly_facility_bait_preparation_table_migration.sql`, `fly_facility_cage_monitoring_table_migration.sql`, `fly_facility_egg_collection_table_migration.sql`, `fly_facility_maintenance_table_migration.sql`, `fly_facility_pupae_transition_table_migration.sql`, `add_recorded_by_to_fly_facility_all_tables.sql` | Alternate fly-facility-prefixed table definitions and audit-column alterations. Active `init_db.py` and parts of the Flask app use unprefixed table names instead. |

The migration SQL mostly uses MySQL-specific `AUTO_INCREMENT`, `ENUM`, and `AFTER` syntax, while `backend/config.py`, `backend/database.py`, `backend/init_db.py`, and the app use PostgreSQL conventions (`SERIAL`, PostgreSQL connection settings, and `%s` parameters). Several scripts contain `DROP TABLE` statements. Their presence does not prove they were applied; verify the actual target database before any migration or cleanup.

### `erp_schema_v2.sql` portions relevant to this chain

- **Lines 9-69, Waste Aggregation:** source master, collection run, and collected item/lot, with FKs from item to source and run.
- **Lines 75-93, Substrate:** substrate batch and its input/output and quality fields; `waste_lot_ids` is a plain text field, so it is not a relational bridge.
- **Lines 95-134, Production Lifecycle:** production batch points to substrate; lifecycle events point to production batch.
- **Lines 136-157, Product Lots:** lot points to production batch and carries quantities/quality/storage metadata; no FK to drying or QC.
- **Lines 243-260, Farmer Orders:** orders can point to a product lot, but do not constitute inventory control.
- **Lines 270-294, Traceability:** generic `traceability_nodes`/`traceability_edges` can connect typed IDs and transfer quantities. The nodes store polymorphic type/ID fields without FKs to the business tables; the generic graph is not wired to the operational APIs.

The remaining ERP-v2 modules (farmer training/enrollment, social-impact measurements, roles/permissions, and audit log) are not production transformations. They may support other application needs, but do not close the production-chain gaps.

## Duplicate/conflicting implementations

1. **Two waste models:** `waste_sourcing` is the operational insert target; ERP v2 separately models source masters, collection runs, and lot items. There is no adapter or shared identifier.
2. **Two substrate models:** `substrate_preparation` is used by the current form/handler; `substrate_batches` is only in ERP-v2 SQL.
3. **Production model is schema-only:** ERP-v2 has `production_batches`/`lifecycle_events`, while current feeding, health, and harvest handlers accept text tray/batch IDs. There is no production route to create or resolve the ERP IDs.
4. **Feeding, monitoring, and health overlap by domain:** larval feeding and hatchery feeding are separate record sets; waste monitoring, larval environmental monitoring, hatchery monitoring, and cage monitoring are distinct scopes. Migration-era tables create yet more alternate names. They should not be merged just because their labels overlap.
5. **Harvest quantity appears in two designs:** operational `harvest_yield.larvae_collected` and ERP `production_batches.harvest_weight_kg`; neither is linked to the other.
6. **Drying has multiple incompatible legacy schemas:** active Python table definitions, old linked-child migration, recreated linked-child migration, and consolidated-wide-table migration do not agree on columns, primary-key types, or foreign keys. Step 8 adds a non-destructive canonical layer without selecting those historical scripts as authoritative.
7. **QC route aliases:** `/api/drying/quality-control` delegates to `/api/drying/qc`; `/api/drying/remarks` returns 404, and its list route always returns an empty list.
8. **Facility monitoring has duplicate paths:** an app route accepts `/api/facility/cage-monitoring`, while the blueprint exposes `/api/fly-facility/cage-monitoring`, both inserting into `cage_monitoring` with different request/validation code.
9. **Generic traceability is a second, unused connection strategy:** ERP-v2's node/edge graph and its direct production/product foreign keys coexist, but neither connects current operational rows.
10. **LocalStorage is a parallel helper:** `DataManager` is included in the HTML, but the main operational form mapping uses backend fetches. It should not be mistaken for the persistent source of truth.

## Quantities duplicated or not consistently defined

- Waste is stored as operational `waste_sourcing.waste_weight`, ERP item `weight_kg`, and ERP run `total_weight_kg`. The run total can duplicate the sum of items; no constraint or route keeps it in sync.
- Substrate has operational `substrate_introduced_kg` and ERP `total_input_weight_kg`/`output_weight_kg`; source-lot weights are not reconciled against those totals.
- Processing stores `waste_processed` and `waste_reduction` without unit suffixes or a defined reconciliation to a substrate output.
- Feeding stores `larvae_weight`, `feed_quantity`, `start_weight`, `end_weight`, and `consumption`. The handler requires `_g`/`_kg` input names but inserts into unitless operational columns; migration alternatives use yet other names such as `larvae_weight_g`, `feed_quantity_kg`, and `consumption_g`.
- Harvest has `larvae_collected` in the operational table and `harvest_weight_kg` in ERP production. The API expects `larvae_collected_kg` then stores it in the unitless `larvae_collected` column.
- Drying stores wet harvested, wet placed, a field named `dried_by_personnel_kg`, dried produced, stored in silo, and sold quantities. It also stores `actual_ratio` and `yield_percentage`, calculated from related batch rows. These may represent separate process measurements or duplicated totals; the code does not define a single reconciliation rule.
- ERP product lots store both `quantity_kg` and `available_quantity_kg`. Without a movement ledger, the second field can become a separately updated copy of stock rather than an auditable balance. Orders also store `quantity_kg` but have no integration with current sales/inventory routes.

## Fields needing a business definition before implementation

- `storage_records.planned_utilization`: intended next process/product, with a free-form string rather than an enforced destination.
- `processing_records.waste_reduction`: whether this is mass lost, moisture loss, reject mass, or a percentage; its unit is absent.
- Operational `substrate_preparation.organic_waste_source` and ERP `substrate_batches.waste_lot_ids`: how one or many input lots are represented and whether mixed-lot batches are allowed.
- ERP `production_batches.tray_ids`: a text list, not a tray relation; define whether each tray is independently traceable or only a physical location label.
- `current_stage`/`status`, `lifecycle_events.event_type`, and free-text stage fields: no shared controlled vocabulary or transition rules are evident in this chain.
- Feeding weight units and meaning: larval biomass vs individual tray load, feed quantity vs feed consumed, and start/end weight vs recorded consumption.
- Harvest `processing_method` versus the later drying step: clarify whether it represents kill/pre-treatment, drying method, or another operation.
- Drying `dried_by_personnel_kg`: the name mixes an actor and a mass. Clarify whether it is a weight of dried product or a personnel field before mapping it.
- Drying `actual_ratio` and `yield_percentage`: define numerator/denominator, moisture basis, and whether ratio is input/output or output/input. Moisture level is a text label, not a numeric measurement.
- ERP `quality_approved`, `quality_grade`, and product-lot status: who can set them, which inspection is authoritative, and what prevents a non-approved batch from becoming saleable.
- ERP `quantity_kg` vs `available_quantity_kg`, and waste run `total_weight_kg` vs item totals: decide whether these are snapshots, calculated values, or independent recorded measurements.
- ERP `waste_lot_ids` and `tray_ids` are text. Their encoding and validation are unspecified, so they cannot safely serve as relational keys.

## Minimum target Phase One data flow

Phase One should establish one operational lineage path without replacing the whole app:

1. **Choose one canonical schema and identifier set first.** The code currently writes the `init_db.py` operational tables; the ERP-v2 chain is not wired in. Decide which model becomes authoritative, and make a non-destructive migration plan against the actual PostgreSQL schema. Do not execute the existing drop/recreate MySQL scripts as-is.
2. **Capture waste as a traceable lot.** Each sourced/accepted quantity needs a stable lot ID and source reference. Storage should refer to that lot; collection-run totals should be derived from or reconciled to collection-item quantities.
3. **Record transformations with input/output links.** Processing records need explicit source lot/storage inputs and measured outputs. A substrate batch needs one-to-many or many-to-many input lines so mixed lots can be recorded with the mass drawn from each. Keep quantities on the transformation/input/output events and record explicit units.
4. **Create one production batch per substrate batch.** Retain the existing ERP `production_batches.substrate_batch_id` concept if that schema is selected. Feeding, larval monitoring, and health interventions should each reference the production-batch ID; keep tray/location IDs separately for physical allocation.
5. **Link harvest to the production batch.** Store harvest output as a distinct event/record tied to the batch. Avoid separately editing an unlinked production summary harvest weight and an unrelated harvest row.
6. **Link drying to its harvest input.** A drying batch should reference the harvest event/lot it consumes. Its input, output, QC, and review rows should reference the drying batch via an actual FK (or be modeled as batch events), not a repeated free-text code.
7. **Release product lots from approved output.** Create a product lot from a specific drying output only after the agreed QC/review gate. The product lot can also retain a production-batch reference for backward traceability.
8. **Represent inventory as movements.** Inbound production, adjustment, reservation, sale, and dispatch should create stock movements referencing the product lot. Compute available stock from posted movements; do not maintain an untracked duplicate balance. Link existing sales/order quantities to these movements before using them to reduce stock.

This gives the minimum useful trace in both directions:

```text
Waste lot → storage/processing inputs → substrate batch → production batch
          → feeding/monitoring/intervention/harvest → drying input/output
          → QC release → product lot → inventory movements
```

Direct foreign keys are sufficient for this first pass. The ERP generic traceability graph can be considered later if cross-module or external trace queries require it; adding it now alongside direct relations would introduce another representation to keep synchronized.

## Step 8 implementation boundary — Harvest to Drying

New canonical drying writes use the existing Drying Process area and expose this
relational path:

```text
Harvest → drying_inputs → drying_batches → drying_outputs
```

Each input line references one recorded harvest, stores its own quantity/unit,
and is checked under a row lock against the harvest's remaining wet quantity.
Multiple harvest lines are supported on one batch. The original `harvests`
quantity is never updated.

Canonical drying batches move only through `DRAFT`, `RECEIVED`, `DRYING`,
`QC_PENDING`, and `COMPLETED`. Outputs preserve measured quantity and unit,
optional moisture, output date, operator, and cumulative input/output-based
`yield_ratio` and `yield_percentage` snapshots. Output cannot exceed total wet
input. Completion requires a passed quality check and a separate approved
quality-approval row. Step 8 originally stopped before Product Lot creation;
Step 9 below extends the chain without changing legacy drying tables.

## Step 9 implementation boundary — Approved Drying Output to Product Lot

New Product Lots reference one canonical `drying_outputs` row and the
`quality_approvals` row that released its output-specific passing QC check. The
source Drying Batch, farm scope, production date, and measured quantity are read
through these relationships where possible; quantity is normalized to kg in the
existing Product Lot quantity field. The database sequence generates a unique
business ID, while the existing lot-code field carries the lot number.

The release API and a database trigger reject missing, failed, unapproved, or
superseded output checks and reject outputs whose Drying Batch is not complete.
The detail API follows recorded drying inputs upstream through Harvests,
Production Batches, Substrate Batches, and Waste Lots. Legacy Product Lots and
text-linked drying/QC rows are not backfilled. Inventory movements, sales
integration, and stock-balance accounting remain out of scope.
