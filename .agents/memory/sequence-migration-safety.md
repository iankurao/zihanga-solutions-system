---
name: Sequence migration safety
description: Rules for repeatable PostgreSQL business-ID migrations in this project.
---

Repeatable startup migrations must only move an identifier sequence forward. Aligning a sequence directly to the current maximum primary key can move it backward after deletes or prior allocations and eventually duplicate a business ID.

**Why:** The application runs additive schema initialization on every server start, so sequence alignment is not a one-time-only operation in practice.

**How to apply:** Use `GREATEST(sequence.last_value, legacy maximum, 1)` and preserve the sequence's called state; never reset a live sequence downward.