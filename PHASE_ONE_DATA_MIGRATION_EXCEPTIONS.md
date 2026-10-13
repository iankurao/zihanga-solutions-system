# Phase One Data Migration Exceptions

**Inspection date:** 2026-09-25  
**Status:** Live record-level reconciliation not possible

## Scope and database availability

The reachable Replit development database (`heliumdb`, PostgreSQL 16.10) had
no application tables, sequences, or views. The workspace has no production
database provisioned. Therefore:

- There are no records in the inspected development database to enumerate or
  reconcile.
- This does **not** establish that a deployed or external database has zero
  records.
- The deployed database endpoint, schema, and rows remain unverified.
- No application data or schema was changed. Startup initialization and
  migrations were not run.

All row-specific counts below are **unknown / not inspectable**, not zero.

## Unperformed checks

| Requested check | Result | Reason |
|---|---|---|
| Existing table and column inventory | Not available for an application schema | The inspected development database has no application relations. |
| Data types, primary/foreign keys, unique/check constraints, indexes | Not available | No application tables are present. |
| Existing identity columns and sequence values | Not available | No application sequences are present. |
| Exact row counts | Not available per source table | There are no source tables in the inspected database. |
| Existing status values and units | Not available | No application rows exist there to profile. |
| NULL patterns | Not available | No application columns or records exist there to profile. |
| Duplicate business IDs | Not available | No business-ID columns or records exist there to check. |
| Orphan records and actual relationship coverage | Not available | No application relations exist there to inspect. |
| Production equivalents of these checks | Not available | No production database has been provisioned in this workspace. |

## Unresolved record categories

These are categories known from repository-declared operational schemas. Their
current presence and record counts in the live database are unknown. Keep
affected records in legacy storage or an exception set until a database-specific
audit supplies evidence.

| Category | Source reference in repository | Why it cannot be safely reconciled from current evidence |
|---|---|---|
| Waste supplier/source identity | `waste_sourcing.source_name`; ERP `waste_sources.source_code` | Similar names are not proof that rows refer to the same supplier. A source master cannot be safely deduplicated from labels alone. |
| Collection run and receiving facility | Operational waste rows; ERP run fields | Operational rows do not establish which loads belong to a shared run or which farm/facility received them. Do not infer from matching dates or source labels. |
| Accepted waste quantity and status | `waste_sourcing.waste_weight`, `segregation_status`, `contaminants_found` | Acceptance, partial rejection, and the quantity converted to accepted lots require explicit business rules and value profiling. |
| Storage lineage | `storage_records` | There is no waste-lot FK. Date, method, or planned utilization cannot identify the stored lot. |
| Processing lineage and units | `processing_records.waste_processed`, `waste_reduction` | Input/output semantics and the meaning/unit of reduction are not established. Do not convert these into substrate or inventory quantities. |
| Substrate input lots | `substrate_preparation.organic_waste_source`; ERP `substrate_batches.waste_lot_ids` | Operational source is descriptive text and ERP source IDs are stored as text. Each lot/input needs verified relational evidence and quantity. |
| Substrate batch identity and output | `substrate_preparation.batch_no`, `substrate_introduced_kg`; ERP `substrate_batches` | Similar batch numbers do not prove same record. Introduced/input weight is not necessarily measured output. Approval fields may duplicate QC decisions. |
| Production-to-substrate inputs | ERP `production_batches.substrate_batch_id` | This source relationship exists only in repository SQL; it is not confirmed in the database. Canonical many-to-many input quantities may not be recoverable from a single FK. |
| Production units / tray allocation | ERP `production_batches.tray_ids`; operational `tray_batch_id`, `tray_facility_id`, `cage_id` | Free-text labels may be reused, incomplete, or refer to different facilities and time periods. Never infer a production-unit or batch relation from a matching label alone. |
| Feeding event quantities | `feeding_schedule` | Quantity fields do not carry sufficient unit/meaning metadata to distinguish amount offered, consumed, biomass, or start/end readings for every record. |
| Monitoring batch/facility link | `environmental_monitoring_larvaefeeding` | `tray_facility_id` is text and does not establish a production batch or physical unit. |
| Health event batch and status | `health_intervention` | `tray_batch_id`, severity, resolution, and follow-up are not enforced relations or controlled values in the declared schema. |
| Harvest-to-production link | `harvest_yield.tray_batch_id` | The batch is a text value, not an FK. The measured unit and interpretation of `larvae_collected` must be confirmed before migrating quantity. |
| Harvest-to-drying input | `drying_input.batch_id`, `wet_harvested_kg`, `wet_placed_for_drying_kg` | A drying batch label does not identify a particular harvest. Multiple harvests, partial use, or reused labels cannot be reconstructed without evidence. |
| Ambiguous drying input quantity | `drying_input.dried_by_personnel_kg` | The column name does not establish whether it is input, output, an individual measurement, or an aggregate. Do not map it automatically. |
| Drying output product identity | `drying_output.dried_produced_kg` | Output weight may be measurable, but product catalog identity and output-line grouping are not established by the current text references. |
| Historical yield calculations | `drying_output.actual_ratio`, `yield_percentage` | Numerator, denominator, moisture basis, and rounding rules are undefined. Preserve as historical values only; do not treat them as canonical calculated quantities. |
| QC measurements and units | `drying_quality_control` | Inspection values such as `moisture_level` and `sand_removal` are text. Their values, units, thresholds, and acceptable status vocabulary must be profiled and specified. |
| QC approval-to-check relation | `drying_review_approval.batch_id` | The approval points to a text batch, not a specific quality-check row. If a batch has multiple checks, the approved check cannot be selected by the batch label alone. |
| Reviewer/recorder identity | `recorded_by`, personnel/name fields in operational and ERP schemas | A display name or username-like string does not prove a `users.user_id`. Resolve exact users from reliable evidence; unmatched names stay unresolved. |
| Farm/site/facility assignment | Operational location labels; location migration tables | The declared location hierarchy includes organizations, farms, sites, and facilities; the target model is farm/facility-oriented. Do not collapse levels or assign scope from free text without an explicit mapping. |
| Product-lot origin and quality release | ERP `product_lots.production_batch_id`; operational drying and QC tables | Production-batch association does not prove the originating drying output or approval. Product lot creation must cite the required QC approval. |
| Inventory balances and movements | ERP `product_lots.available_quantity_kg`; repository `inventory_movements` | A stored available-quantity snapshot is not a movement ledger. Opening balances require a verified conversion plan and source evidence; sales/deliveries do not by themselves prove stock postings. |
| Status vocabulary | All free-text operational status fields and ERP statuses | No live values were available. Do not write a guessed normalization map; profile the actual distinct values and define per-entity transitions first. |
| Mass units and conversions | Decimal fields without unit columns; legacy gram/kg columns | A column suffix or UI label is not sufficient evidence for every historical row. Convert only when unit is established for that row/category. |
| Duplicate business identifiers | `business_id`, `batch_no`, `batch_id`, `batch_code`, `lot_code` | Uniqueness and collisions cannot be checked without live values. Human-readable IDs are references, not FKs. |
| ID collisions and referential orphans | Integer `id` keys and possible source FKs | No live PK/FK values are available to build and validate old-to-new ID maps. |

## Must-not-infer rules

Do not create lineage solely because values match in:

- source names or supplier labels;
- batch, lot, or collection-run numbers;
- tray, cage, facility, or site labels;
- usernames, operator names, or reviewer names;
- dates, timestamps, or coincident quantities.

An explicit matching rule requires an independent, auditable source (for
example, an existing FK, a verified operational register, or an approved
one-to-one crosswalk). Otherwise retain the record as unlinked legacy data.

## QC release dependency

Phase One release order is:

**Drying Batch → Drying Output → Quality Check → Quality Approval → Product Lot → Inventory**

The approval used to create/release a product lot must be for a passing quality
check on the relevant drying output/batch. Do not require that already-created
product lot as the target of the same release-gating check; that would create a
circular dependency. If post-release product QC is needed later, model it as a
separate check that does not replace the pre-release approval.

## Reconciliation gate

Before any migration design is treated as executable, inspect the confirmed
application database and append actual table/row counts plus record-level
exception counts to this report. At minimum, validate:

1. source-to-target count reconciliation and preservation of legacy keys;
2. PK/FK coverage, unique code collisions, and orphan records;
3. unit and status distributions, NULL patterns, and quantity totals;
4. the event, actor, farm, facility, and location crosswalks;
5. the harvest → drying input → output → QC → approval lineage;
6. sequence state against preserved IDs without moving any live sequence
   backward; and
7. product-lot balances against the proposed posted-movement ledger.

Until that audit is possible, unresolved rows must remain unmapped and no
production-data migration should be prepared from repository declarations
alone.

## Step 7 harvest implementation boundary

New harvest writes use a canonical harvest row whose parent production event
references one explicit `production_batches` row. The application does not
backfill legacy `harvest_yield.tray_batch_id` values into this relationship:
those labels and the legacy `larvae_collected` unit remain unresolved until an
operator-approved crosswalk and unit validation are available. The explicit
per-batch `harvest_limit_kg` applies to new harvest events only; it is not
inferred from substrate input, egg weight, or historical harvest totals.

## Step 8 drying implementation boundary

New drying writes use canonical `drying_batches`, `drying_inputs`, and
`drying_outputs` relations layered onto the existing Drying Process routes.
Input rows require an explicit Step 7 `harvests.id`/`harvest_code` and measured
quantity. The API rejects quantities above the harvest's remaining wet amount,
including concurrent consumption attempts, and does not rewrite the harvest.

Canonical batches move only through `DRAFT`, `RECEIVED`, `DRYING`, `QC_PENDING`,
and `COMPLETED`. Completion requires a passed `quality_checks` row and a
separate approved `quality_approvals` row. Historical text `batch_id` rows are
not backfilled or treated as harvest relations, and no product sale or
inventory availability is created in this step.

## Step 9 Product Lot release implementation boundary

New product-lot releases require an explicit canonical Drying Output, an
output-specific passed QC check, its latest approved decision, and a completed
Drying Batch. The Product Lot references that output and approval; its quantity
is derived from the measured output and converted to kg. A database trigger
applies the same release gate to canonical lot inserts and status changes.

No source relationship is inferred for legacy `product_lots`, text-based
drying/QC records, or approvals that do not point to the exact output check.
The detail API displays only the recorded chain from output and drying inputs
through harvest, production, substrate, and waste-lot relations. The
development database snapshot and production-data reconciliation limitations
above are unchanged.
