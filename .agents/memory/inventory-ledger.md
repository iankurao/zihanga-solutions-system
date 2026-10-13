---
name: Inventory ledger
description: Product Lot stock is derived only from posted inventory_movements; never add an editable stock quantity.
---

Stock on hand is the sum of posted `inventory_movements` per Product Lot and inventory location. A transfer is one row with both locations. Every canonical Product Lot gets exactly one `RECEIPT`, posted inside the release transaction.

**Why:** A stored "available quantity" drifts from the movement history and breaks lot traceability and audit.

**How to apply:** Post a validated movement through `_record_inventory_movement` (or `_insert_inventory_movement` inside an existing transaction that already locked the lot). Never update `product_lots.available_quantity_kg`. Sales and dispatch work (Step 15) should add new movement types that use the same ledger.
