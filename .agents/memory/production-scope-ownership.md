---
name: Production scope ownership
description: Canonical ownership rules for new BSF production records.
---

New production batches require explicit farm, site, and facility IDs. The database hierarchy, substrate input rows, and production batch must agree on that scope; legacy free-text substrate records remain unassigned until an operator maps them.

**Why:** Legacy `farm_site` text cannot prove facility ownership, and assigning it automatically would manufacture lineage.

**How to apply:** Require canonical scope on future production-chain APIs and reject substrate inputs whose canonical scope is missing or mismatched. Keep legacy records queryable without silently backfilling them.