---
name: Repeatable DDL idempotency
description: PostgreSQL constraint migrations can leave a migration-owned index relation after an interrupted or partial ADD CONSTRAINT.
---

Repeatable PostgreSQL migrations must account for both an existing constraint and an orphaned auto-created index with the intended constraint name.

**Why:** A partially applied `ADD CONSTRAINT ... UNIQUE` can make the next startup fail with a duplicate relation error even though the constraint catalog entry is absent.

**How to apply:** Guard the catalog constraint, catch duplicate-relation errors, and remove only the specifically migration-owned orphan index before retrying.