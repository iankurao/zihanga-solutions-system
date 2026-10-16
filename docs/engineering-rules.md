# Engineering rules

Invariants that every change to the ERP must keep. Each one exists because
breaking it once would corrupt traceability, stock or business IDs.

## Inventory ledger

*Product Lot stock is derived only from posted inventory_movements; never add an editable stock quantity.*

Stock on hand is the sum of posted `inventory_movements` per Product Lot and inventory location. A transfer is one row with both locations. Every canonical Product Lot gets exactly one `RECEIPT`, posted inside the release transaction.

**Why:** A stored "available quantity" drifts from the movement history and breaks lot traceability and audit.

**How to apply:** Post a validated movement through `_record_inventory_movement` (or `_insert_inventory_movement` inside an existing transaction that already locked the lot). Never update `product_lots.available_quantity_kg`. Customer dispatches post `DISPATCH` movements; free stock = on hand minus outstanding `order_allocations` (`ALLOCATION_STATE_CTE`).

## Every record has a location

*New records always carry a farm, site and facility the user may access.*

Every write route takes `farm_id`, `site_id` and `facility_id`, checks them with
`_assert_production_location` and `_assert_production_scope_access`, and reads
are filtered with `_scope_visibility_clause`. Farm operation log tables also
refuse rows without a location in the database (`*_scope_required` CHECK
constraints, `migrations/farm_operation_logs.sql`).

**Why:** A record without a location cannot be traced, cannot be limited to the
people allowed to see it and cannot count in stock or reports.

**How to apply:** Add new record types to a scoped module (e.g. the `KINDS`
registry in `domains/farm_operations.py`), never as a free-standing legacy
form. Rows from before locations stay read-only history for super admins.

## Production scope ownership

*Canonical ownership rules for new BSF production records.*

New production batches require explicit farm, site, and facility IDs. The database hierarchy, substrate input rows, and production batch must agree on that scope; legacy free-text substrate records remain unassigned until an operator maps them.

**Why:** Legacy `farm_site` text cannot prove facility ownership, and assigning it automatically would manufacture lineage.

**How to apply:** Require canonical scope on future production-chain APIs and reject substrate inputs whose canonical scope is missing or mismatched. Keep legacy records queryable without silently backfilling them.

## Sequence migration safety

*Rules for repeatable PostgreSQL business-ID migrations in this project.*

Repeatable startup migrations must only move an identifier sequence forward. Aligning a sequence directly to the current maximum primary key can move it backward after deletes or prior allocations and eventually duplicate a business ID.

**Why:** The application runs additive schema initialization on every server start, so sequence alignment is not a one-time-only operation in practice.

**How to apply:** Use `GREATEST(sequence.last_value, legacy maximum, 1)` and preserve the sequence's called state; never reset a live sequence downward.

## Repeatable DDL idempotency

*PostgreSQL constraint migrations can leave a migration-owned index relation after an interrupted or partial ADD CONSTRAINT.*

Repeatable PostgreSQL migrations must account for both an existing constraint and an orphaned auto-created index with the intended constraint name.

**Why:** A partially applied `ADD CONSTRAINT ... UNIQUE` can make the next startup fail with a duplicate relation error even though the constraint catalog entry is absent.

**How to apply:** Guard the catalog constraint, catch duplicate-relation errors, and remove only the specifically migration-owned orphan index before retrying.
