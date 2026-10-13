# Phase One Database Migration Map

**Inspection date:** 2026-09-25  
**Status:** Blocked for live-data mapping; repository-level mapping only  
**Scope:** Read-only inspection before any Phase One table or data migration

## Executive result

The only database available for inspection in this workspace was the
Replit-managed **development** PostgreSQL database (`heliumdb`, PostgreSQL
16.10). Its only non-system schema was `public`, which contained **0 tables,
0 sequences, and 0 views**. There are no application rows in that database to
profile.

The workspace has **no production database** provisioned. Therefore this
inspection does not establish the schema or data used by any separately
deployed or external application. `replit.md` describes the app as using
Replit-provided PostgreSQL environment variables, but the deployed endpoint
could not be independently confirmed. Do not treat repository SQL or the empty
development database as proof of a production schema.

No startup workflow, initializer, or migration was run. No tables, sequences,
or application data were created or changed.

## Current database → target model

| Check | Observed result |
|---|---|
| Database available to this inspection | Development database `heliumdb`, PostgreSQL 16.10 |
| Non-system schemas | `public` only |
| Application tables / partitioned tables | 0 |
| Application views / materialized views | 0 |
| Application sequences | 0 |
| Exact row counts | Not applicable: there are no application tables |
| Columns, types, keys, constraints, indexes | Not applicable: there are no application tables |
| Status values, units, NULL patterns | Not observable |
| Duplicate business IDs / orphan records | Not observable |
| Production database | Not provisioned in this workspace |

The empty development database cannot establish whether the deployed database
has legacy tables or records. Counts and data-quality checks below are
**unknown**, not zero, unless they specifically refer to the inspected
development database.

## Target-table disposition

Every canonical target table is absent from the inspected empty development
database. The disposition below is therefore `CREATE` **for that database
only**. This is a documentation classification, not approval to create tables.
The production disposition remains unknown. No actual migration is specified
until the intended live database is reachable and its schema and rows are
inspected.

| Target table | Target primary key | Required direct relationships | Inspected development disposition |
|---|---|---|---|
| `farms` | `farm_id` | Creator → `users.user_id` | CREATE |
| `facilities` | `facility_id` | `farm_id` → `farms` | CREATE |
| `waste_sources` | `waste_source_id` | `farm_id` → `farms`; optional facility | CREATE |
| `waste_collection_runs` | `collection_run_id` | Farm, receiving facility; optional driver user | CREATE |
| `waste_collection_items` | `collection_item_id` | Run → `waste_collection_runs`; source → `waste_sources` | CREATE |
| `waste_lots` | `waste_lot_id` | Collection item; optional documented parent lot | CREATE |
| `substrate_batches` | `substrate_batch_id` | Farm and preparation facility | CREATE |
| `substrate_batch_inputs` | `substrate_batch_input_id` | Substrate batch; waste lot | CREATE |
| `production_batches` | `production_batch_id` | Farm and production facility | CREATE |
| `production_batch_inputs` | `production_batch_input_id` | Production batch; substrate batch | CREATE |
| `production_units` | `production_unit_id` | Farm and facility | CREATE |
| `production_batch_units` | `production_batch_unit_id` | Production batch; production unit | CREATE |
| `production_events` | `production_event_id` | Production batch, farm, facility; optional parent event | CREATE |
| `feeding_events` | `production_event_id` | One-to-one parent `production_events` row | CREATE |
| `monitoring_events` | `production_event_id` | One-to-one parent `production_events` row | CREATE |
| `health_events` | `production_event_id` | One-to-one parent `production_events` row | CREATE |
| `harvests` | `harvest_id` | Unique parent `production_event_id` | CREATE |
| `drying_batches` | `drying_batch_id` | Farm and facility | CREATE |
| `drying_inputs` | `drying_input_id` | Drying batch; harvest | CREATE |
| `products` | `product_id` | Product catalog; farm scope only if farm-specific | CREATE |
| `drying_outputs` | `drying_output_id` | Drying batch; product | CREATE |
| `quality_checks` | `quality_check_id` | Farm/facility and exactly one check target | CREATE |
| `quality_approvals` | `quality_approval_id` | Quality check; farm/facility | CREATE |
| `product_lots` | `product_lot_id` | Drying output, product, release approval, farm/facility | CREATE |
| `inventory_locations` | `inventory_location_id` | Farm and facility | CREATE |
| `inventory_movements` | `inventory_movement_id` | Product lot, farm, optional from/to locations | CREATE |

`REUSE`, `ALTER`, `MIGRATE`, `LEGACY`, and `DEPRECATE` cannot be assigned to
live tables from this empty database. The source crosswalk below describes
repository-declared candidates only; none is verified as present in the
inspected or deployed database.

## Repository-declared source crosswalk (not live-schema evidence)

Source definitions below come from `backend/init_db.py` and
`backend/migrations/*.sql`. They identify candidate mappings and risks, but do
not prove that a table, column, index, or migration exists in any live
database. Where a source business ID is not explicitly defined, it is listed
as **none** rather than inferred.

| Repository source table/model | Source PK / business ID | Candidate target and classification | Mapping boundary |
|---|---|---|---|
| Operational `waste_sourcing` | `id` / `business_id` (`WL-…`) | Candidate `waste_lots`; split into source/run/item/lot only with evidence | One operational row does not establish a stable source master, collection run, receiving facility, acceptance decision, or a one-to-one item/lot policy. Keep `source_name` descriptive until source identity is reconciled. Do not copy a text label into a guessed relation. |
| ERP SQL `waste_sources` | `id` / `source_code` | Candidate `waste_sources` — REUSE concept and migrate if verified | The ERP SQL defines supplier identity and contact fields. Farm scope and actor links are absent there. Do not deduplicate operational source names into this table without identity evidence. |
| ERP SQL `waste_collection_runs` | `id` / `run_code` | Candidate `waste_collection_runs` — REUSE concept and migrate if verified | `planned_sources` is free text; it is not reliable item lineage. Add farm/facility scope only when supported by records. |
| ERP SQL `waste_collection_items` | `id` / `lot_code` | Candidate `waste_collection_items` and `waste_lots` — ALTER/MIGRATE if verified | Existing SQL links run and source IDs, but its `lot_code` combines item and lot concepts. Preserve original IDs/codes; distinguish collection from accepted lot quantities. |
| Operational `storage_records` | `id` / none | No direct target — LEGACY unless a lot-linked storage-event model is approved | No waste-lot FK or reliable source-to-lot key. Do not attach rows to lots by date, method, or label. |
| Operational `processing_records` | `id` / none | No direct target — LEGACY pending defined transformation semantics | `waste_reduction` has no established unit or clear input/output meaning. Do not turn it into substrate input/output quantities. |
| Operational `substrate_preparation` | `id` / `business_id` (`SUB-…`); legacy `batch_no` | Candidate `substrate_batches` — MIGRATE only after per-row validation | The batch identifier and preparation measurements are candidate fields. `organic_waste_source` is text, not a waste-lot FK. `substrate_introduced_kg` is not automatically output weight or a consumed input from a known lot. |
| ERP SQL `substrate_batches` | `id` / `batch_code` (and repository startup SQL adds `business_id`) | Candidate `substrate_batches` — ALTER/MIGRATE if verified | `waste_lot_ids TEXT` is not relational lineage. Map only through verified source-lot evidence into `substrate_batch_inputs`. Reconcile duplicate approval fields through explicit QC history rather than silently choosing one. |
| ERP SQL `production_batches` | `id` / `batch_code` (startup SQL adds `business_id`) | Candidate `production_batches` — ALTER/MIGRATE if verified | The source has one substrate FK and text `tray_ids`; canonical inputs and unit assignments are line tables. Preserve useful stage dates/status only after vocabulary review. Do not use its harvest summary as a duplicate of harvest records. |
| ERP SQL `lifecycle_events` | `id` / none | Candidate `production_events` — MIGRATE if verified | Preserve event date/type/details; actor text needs a verified mapping to `users.user_id`. Specialized event children require a defensible event-type mapping. |
| Operational `feeding_schedule` | `id` / none | Candidate `production_events` + `feeding_events` — MIGRATE when resolvable | `tray_batch_id` is text and quantity units/meanings require validation. Do not assume a label uniquely identifies a batch or unit. |
| Operational `environmental_monitoring_larvaefeeding` | `id` / none | Candidate `production_events` + `monitoring_events` — MIGRATE when resolvable | `tray_facility_id` is text. Preserve observations, but link a batch/unit only with independent evidence. |
| Operational `health_intervention` | `id` / none | Candidate `production_events` + `health_events` — MIGRATE when resolvable | `tray_batch_id` is text. Normalize severity/resolution vocabulary only after inspecting actual values; actor names need user resolution. |
| Operational `harvest_yield` | `id` / `business_id` (`HRV-…`); `tray_batch_id` | Candidate `production_events` + `harvests` — MIGRATE when resolvable | Preserve the harvest code and legacy key. Resolve its production batch with evidence. The unit and meaning of `larvae_collected` must be confirmed before loading quantity. |
| Operational `drying_batches` | `id` / `business_id` (`DRY-…`); unique text `batch_id` | Candidate `drying_batches` — ALTER/MIGRATE if verified | Preserve the integer key and both codes. A text batch code is not a harvest relation; statuses need normalization after actual values are inspected. |
| Operational `drying_input` | `id` / none; text `batch_id` | Candidate `drying_inputs` — MIGRATE only when harvest is identified | Its batch label does not identify a harvest. `wet_placed_for_drying_kg` is a candidate input measure; `dried_by_personnel_kg` is ambiguous and must not be auto-mapped. Sand quantities are not harvest quantities. |
| Operational `drying_output` | `id` / none; text `batch_id` | Candidate `drying_outputs` — MIGRATE after batch/product validation | Preserve measured dried output. A `product_id` requires product classification evidence. Keep `actual_ratio` and `yield_percentage` as historical values until calculation basis is defined. |
| Operational `drying_quality_control` | `id` / none; text `batch_id` | Candidate `quality_checks` — MIGRATE after target and unit validation | The batch label may identify a drying batch only if unique and verified. Convert free-text inspection measurements only with defined units and values. |
| Operational `drying_review_approval` | `id` / none; text `batch_id` | Candidate `quality_approvals` — MIGRATE only when linked to a specific check | A batch label alone cannot identify which of potentially multiple checks was approved. Preserve each decision; normalize status and resolve reviewer separately. |
| ERP SQL `product_lots` | `id` / `lot_code` (startup SQL adds `business_id`, `LOT-…`) | Candidate `product_lots` — ALTER/MIGRATE if verified | Current ERP design ties a lot to production batch and stores `available_quantity_kg`; target requires drying output, product, release approval, and ledger-based stock. Do not equate available snapshot with posted inventory. |
| ERP SQL `inventory_movements` (startup migration declaration) | `id` / `business_id` (`MOV-…`) | Candidate `inventory_movements` — ALTER/MIGRATE if verified | Declared source lacks canonical from/to locations, posting actor/time, and validated movement combinations. Preserve only rows whose product lot and quantity/unit are defensible. |
| Existing `users` | `user_id` / `username` (unique in the operational schema) | Reuse for actor FKs if present and validated | Match recorded/approved names to exact user identities only with reliable evidence. Unmatched names remain exceptions; never fabricate user references. |
| `organizations`, `farms`, `sites`, `facilities` in location migration | `id` / scoped codes | Candidate scope model; ALTER or CREATE only after choosing one hierarchy | The migration declares organization → farm → site → facility. The target model describes farm → facility. Do not collapse sites or attach operational rows to a location from text labels without a business decision. |
| `operational_location_links` | `id` / unique `(entity_table, entity_id)` | Candidate transitional location mapping | Its polymorphic `entity_table`/`entity_id` pair does not have a foreign key to every operational table. Any use needs validated entity IDs and location evidence. |
| ERP SQL `farmer_profiles`, `traceability_nodes`, `traceability_edges`, sales/orders | Varies / varies | LEGACY or adjacent; no direct Phase One production-lineage source | Farmer/person profiles are not farms; polymorphic traceability IDs do not replace typed FKs. Sales/orders do not represent posted inventory movements. |

### Source key and business-ID notes

The repository's `phase_one_business_identifiers.sql` declares
`business_id` additions for operational sourcing, substrate preparation,
harvest, and drying batches, and canonical/ERP-style business IDs for
substrate batches, production batches, waste collection items, product lots,
and inventory movements. These are source-code intentions only; the empty
database has none of the corresponding columns or sequences to inspect.

The target model uses distinct target keys and codes such as `waste_lot_id` /
`lot_code`, `harvest_id` / `harvest_code`, and
`inventory_movement_id` / `movement_code`. Mapping a legacy integer PK to the
target PK is permissible only after row counts, FK coverage, and ID collisions
are checked in the real source database. A business code must not be used as a
foreign key.

## Required migrations and data mapping

**Required database changes identified from live evidence: none.** There is no
live application schema in the inspected development database to alter or
migrate, and the production database is unavailable. Creating the target model
now would violate the instruction to stop before table creation.

When the correct database is available, a new audit must first record, per
actual table: exact row count; column type/null/default/identity; PK, FK,
unique/check constraints and validation state; indexes; sequences and sequence
state; status and unit distributions; NULL counts; duplicate business IDs;
orphan counts; and relationship evidence. Then revise each target disposition
from observed evidence. The source crosswalk above is not a substitute for
that audit.

## Repository implementation update — Step 7

The application now has an additive schema migration for canonical harvest
events and per-batch `harvest_limit_kg`. This does not change the recorded
development-database inspection above, prove the production schema, or migrate
legacy `harvest_yield` rows. New harvest writes are relational; legacy harvest
batch labels and units remain unresolved until the live-data reconciliation
gate is completed.

## QC release order

Keep the Phase One release sequence acyclic:

**Drying Batch → Drying Output → Quality Check → Quality Approval → Product Lot → Inventory**

The release approval must reference a passing check for the relevant drying
batch/output before product-lot creation or stock posting. Do not require a
quality check on an already-created product lot as the release gate for that
same lot. A separate post-release check, if later required, must be distinct
from the pre-release approval.

## Repository implementation update — Step 8

The existing Drying Process now has an additive canonical connection to the
Step 7 `harvests` rows. `drying_batches` retains its legacy table and gains
canonical farm/site/facility scope and lifecycle timestamps. New
`drying_inputs` rows reference `harvests` by FK and record measured quantity per
source; new `drying_outputs` rows record measured quantity, unit, optional
moisture, operator/date, and calculated input snapshot/yield values. The
`drying_batch_status_history`, `quality_checks`, and `quality_approvals` tables
provide the lifecycle audit and separate QC approval gate.

Legacy text-linked drying tables are preserved. The new API path is additive and
does not migrate historical rows because the documented batch-label and
harvest-lineage exceptions remain unresolved. Step 8 was initially limited to
drying; the following Step 9 repository implementation adds an explicit
output-to-lot release.

## Repository implementation update — Step 9

The additive migration adds output-specific `quality_checks.drying_output_id`
and a canonical `product_lots` relationship to `drying_outputs`, the
`quality_approvals` release row, and the inherited farm. It preserves unlinked
legacy lots and does not infer old drying or QC relations. A database trigger
and the release API require a completed Drying Batch, a passed check for that
exact output, and its latest approved decision before a lot can be marked
available. Quantity is taken from the output and normalized to kg.

The change is registered in the application initializer, but its presence in
the repository does not prove that an external or production database has
applied it. No inventory movement or stock-ledger migration is part of this
step.

## Risks

1. **Database identity risk:** only an empty development database was reachable;
   no production database is provisioned, and external endpoint parity is not
   confirmed.
2. **False “no data” conclusion:** zero rows are established only for the
   absence of tables in the inspected development database. Production record
   counts remain unknown.
3. **Startup side effects:** `run.sh` invokes `backend.init_db`, which creates
   tables and executes migrations. It was not run because this audit must not
   create schema or alter data.
4. **Incompatible roots:** repository location SQL has organization/site
   levels absent from the target's simpler farm/facility model.
5. **Unverified IDs and sequence state:** source business-ID backfills and
   sequence states have not been read from a live database. Do not apply
   sequence resets or assume generated IDs are collision-free.
6. **Unsupported lineage:** text source, batch, tray, facility, and actor values
   cannot be promoted to relational keys without evidence.
7. **QC cycle:** product-lot creation must stay downstream of drying-output QC
   approval; avoid a product-lot/QC circular dependency.
