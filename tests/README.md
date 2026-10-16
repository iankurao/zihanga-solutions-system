# Phase One test suite

## Running

```bash
# With a PostgreSQL test database (all tests):
export DATABASE_URL=postgresql://user@host:5432/zehunger_test PGHOST=host PGPORT=5432 PGUSER=user PGDATABASE=zehunger_test
python -m pytest

# Without a database, only the database-free tests run (the rest skip):
python -m pytest
```

Use a dedicated test database: the suite creates and removes its own
organizations, farms, users and records, but the audit log is append-only by
design, so its entries remain.

Route coverage - which API endpoints the suite calls:

```bash
ROUTE_COVERAGE=route-coverage.txt python -m pytest
```

The file lists every endpoint with its call count and any never called
(currently 138 of 138 are exercised).

## Files

| File | What it covers |
|---|---|
| `test_phase_one_end_to_end.py` | **The full chain** Waste Lot > Substrate > Production > Harvest > Drying > QC > Product Lot > Inventory > Order > Delivery, with real sign-in and each step done by its role, then traceability both ways, mass balance, ledger, Batch 360, reports, dashboard, notifications, audit trail, label scan and outsider isolation |
| `test_access_and_admin.py` | Facility / site / farm / organization isolation matrix, admin portal API, location setup and grants, low-stock minimums, HTML sign-in and registration forms, page routes and static files |
| `test_legacy_records.py` | The retired write routes (no location) are gone; legacy reads are super-admin only; legacy sales history is read-only; legacy feeding routes write canonical events |
| `test_farm_operations.py` | Hatchery, fly facility and waste-handling logs: every kind needs a location and access, is validated, stored with its location and audited; outsiders cannot see them; the database refuses rows without a location; hatchery numbering and feeding checks; the drying pick-lists follow a batch from harvest to approval |
| `test_production_batch_chain_integration.py` | Detailed rules for each stage (validation, limits, transitions, concurrency), inventory ledger, orders, traceability, alerts, notifications, reports, dashboard, units, farmer portal, QR labels, roles and security, audit log |
| `test_waste_substrate_chain_integration.py` | Waste lots and substrate preparation: scope, lineage, over-consumption, concurrency |
| `test_business_identifiers.py`, `test_location_hierarchy.py` | Business ID sequences and the location hierarchy migration |
| `test_architecture.py` | Module boundaries: core never imports domains, no import cycles, thin entry point |
| `test_frontend_design.py` | Every page uses the design system and shared navigation; no retired palettes or classes; WCAG token contrast; a badge tone for every schema status |
| `test_frontend_logic.py` | `js/ui.js` status tones and labels, run in Node (skipped without Node) |
| `test_demo_seed.py` | `python -m backend.demo`: the demo dataset covers every chain state with ledger-derived stock, history and audit; refuses databases with real records; rebuilds only with `--reset`; no email from a demo; the `demo` flag on `/api/me` |
| `test_demo_tour.py` | Investor demo mode: `/tour` and guest access exist only on a demo database; guest access needs `DEMO_GUEST_ACCESS` and an active viewer account; the guest is read only, refused cross-site and audited; staff with sales access get the orders chapter |
| `test_deployment.py` | Deployment readiness: every unsafe setting fails and every risky one warns; `APP_ENV=production` refuses to start with unsafe settings; `DATABASE_URL` wins over `PG*`; `/healthz` and `/readyz` (fail closed, no details); `python -m backend.preflight` database checks and exit code; `deploy/backup.sh` and `restore-check.sh` with stand-in PostgreSQL tools; gunicorn, systemd, nginx and `.env.example` files; production requirements match the project pins |

`support.py` is the shared harness for scenario tests: it builds locations and
accounts through the API as a super admin and signs each user in with their own
session (`make_farm`, `make_user`, `make_batch`).

## Phase One areas

| Area | Main tests |
|---|---|
| Authentication | `test_registration_and_sign_in_forms`, `test_sign_in_is_throttled_and_does_not_reveal_accounts`, `test_password_reset_role_change_and_deactivation_end_sessions`, `test_login_only_redirects_to_same_site_paths` |
| Authorization | `test_every_write_route_declares_a_permission`, `test_role_permissions_are_enforced_server_side`, end-to-end role refusals, `test_legacy_records_are_super_admin_only` |
| Farm isolation | `test_access_level_decides_what_each_user_sees_and_records`, `test_reads_and_writes_are_limited_to_authorized_farms`, end-to-end outsider checks |
| Facility isolation | `test_access_level_decides_what_each_user_sees_and_records`, `test_scoped_lists_follow_the_same_rules`, end-to-end QC officer trace (restricted placeholders) |
| Waste | `test_collection_creates_lot_and_substrate_keeps_exact_lineage`, `test_waste_lot_and_substrate_require_canonical_scope`, legacy waste forms |
| Substrate | `test_negative_and_over_available_consumption_are_rejected`, `test_concurrent_substrate_batches_cannot_overdraw_a_lot` |
| Production | `test_invalid_status_transition_is_rejected_and_history_is_audited`, `test_insufficient_substrate_is_rejected_without_creating_a_batch`, `test_units_hold_one_batch_and_are_released_on_harvest` |
| Feeding / monitoring / health | `test_feeding_monitoring_and_health_events_are_batch_timeline_records`, `test_event_measurement_range_and_closed_batch_rules_are_enforced`, `test_feeding_form_blank_optional_fields_are_accepted` |
| Harvest | `test_harvest_requires_ready_state_and_configured_limit`, `test_excess_harvest_is_rejected_without_partial_write`, `test_valid_partial_harvests_keep_batch_lineage_and_aggregate_in_kg` |
| Drying | `test_drying_rejects_overconsumption_and_impossible_output`, `test_drying_can_use_another_facility_on_the_same_farm_only`, `test_shared_drying_batch_is_flagged_not_split` |
| QC | `test_failed_qc_blocks_product_lot_release`, `test_passed_qc_without_approval_cannot_create_available_lot`, `test_qc_pending_turns_into_qc_failed` |
| Product lots | `test_approved_output_creates_product_lot_with_quantity_and_full_trace`, `test_release_requires_a_receiving_location_on_the_same_farm` |
| Inventory | `test_release_posts_exactly_one_receipt_and_stock_is_ledger_derived`, `test_transfer_adjustment_and_negative_stock_rules`, `test_concurrent_withdrawals_cannot_drive_stock_negative` |
| Orders | `test_order_validation_and_qc_blocking`, `test_cancel_release_and_fulfilment_rules`, `test_concurrent_allocations_cannot_over_reserve_a_lot` |
| Deliveries | `test_order_to_delivery_reserves_dispatches_and_traces_to_waste`, end-to-end dispatch and confirmation |
| Traceability | `test_trace_reaches_waste_from_product_and_stock_from_waste`, `test_trace_follows_direction_without_pulling_in_sibling_batches`, `test_trace_redacts_records_at_locations_the_user_cannot_access`, `test_trace_errors_scope_and_search` |
| Reports | `test_reports_follow_the_chain_with_consistent_totals`, `test_reports_respect_location_and_commercial_access`, `test_report_validation_and_safe_csv`, end-to-end report and CSV checks |
| Notifications | `test_alert_notifications_reach_the_right_people_once`, `test_commercial_alerts_reach_only_sales_roles`, `test_email_outbox_retries_and_redacts_errors`, end-to-end health alert |
| Audit | `test_batch_changes_are_attributed_to_the_signed_in_user`, `test_audit_entries_cannot_be_changed_or_deleted`, end-to-end audit trail per role |

Not automated here: clicking through pages in a real browser. The pages were
checked manually in a browser at phone and desktop widths; their structure is
guarded by `test_frontend_design.py` and their data by the API tests.
