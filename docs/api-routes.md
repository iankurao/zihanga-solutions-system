# Route reference

Generated from the application by `python -m backend.routes_doc`; do not edit
by hand. **Access** is the permission the server checks (see
`backend/roles.py`); "signed in" means any signed-in user, with records
further limited to the farms, sites and facilities the user may access.
Routes under `/tour` and `/api/demo/*` exist only on demonstration databases.


## admin

| Method | Path | Access |
|---|---|---|
| GET | `/api/admin/activity` | super_admin |
| GET | `/api/admin/farmer/<string:username>/stats` | super_admin |
| GET | `/api/admin/farmers` | super_admin |
| GET | `/api/admin/farmers/export` | super_admin |
| GET | `/api/admin/inactive-farmers` | super_admin |
| GET | `/api/admin/me` | super_admin |
| GET | `/api/admin/overview` | super_admin |
| GET | `/api/admin/roles` | super_admin |
| POST | `/api/admin/users` | super_admin |
| DELETE | `/api/admin/users/<int:user_id>` | super_admin |
| PUT | `/api/admin/users/<int:user_id>` | super_admin |
| POST | `/api/admin/users/<int:user_id>/reset-password` | super_admin |
| POST | `/api/admin/users/<int:user_id>/toggle` | super_admin |
| GET | `/zehunger` | signed in |

## alerts

| Method | Path | Access |
|---|---|---|
| GET | `/alerts` | signed in |
| GET | `/api/alerts` | signed in |
| POST | `/api/alerts/<int:alert_id>/acknowledge` | alerts.manage |
| POST | `/api/alerts/<int:alert_id>/snooze` | alerts.manage |
| POST | `/api/alerts/refresh` | signed in |
| GET | `/api/alerts/summary` | signed in |
| GET | `/api/alerts/thresholds` | signed in |
| PUT | `/api/alerts/thresholds` | super_admin |
| DELETE | `/api/alerts/thresholds/<int:threshold_id>` | super_admin |
| GET | `/api/notifications` | signed in |
| POST | `/api/notifications/<int:notification_id>/read` | signed in |
| GET | `/api/notifications/email-status` | super_admin |
| GET | `/api/notifications/preferences` | signed in |
| PUT | `/api/notifications/preferences` | signed in |
| POST | `/api/notifications/read-all` | signed in |
| POST | `/api/notifications/test-email` | super_admin |
| GET | `/api/notifications/unread-count` | signed in |

## audit

| Method | Path | Access |
|---|---|---|
| GET | `/api/audit` | audit.read |
| GET | `/audit` | super_admin |

## auth

| Method | Path | Access |
|---|---|---|
| POST | `/api/auth/login` | public |
| POST | `/api/auth/register` | public |
| GET | `/api/me` | signed in |
| GET, POST | `/login` | public |
| GET | `/logout` | public |
| GET, POST | `/register` | public |

## batch360

| Method | Path | Access |
|---|---|---|
| GET | `/api/production/batches/<string:batch_ref>/360` | signed in |
| GET | `/batch-360` | signed in |

## dashboard

| Method | Path | Access |
|---|---|---|
| GET | `/api/dashboard` | signed in |
| GET | `/operations` | signed in |

## drying

| Method | Path | Access |
|---|---|---|
| POST | `/api/drying/batches` | production.write |
| GET | `/api/drying/batches/<string:batch_ref>` | signed in |
| POST | `/api/drying/batches/<string:batch_ref>/inputs` | production.write |
| POST | `/api/drying/batches/<string:batch_ref>/outputs` | production.write |
| POST | `/api/drying/batches/<string:batch_ref>/status` | production.write |

## farmer

| Method | Path | Access |
|---|---|---|
| GET | `/api/farmer/overview` | signed in |
| GET | `/farmer` | signed in |

## fly_facility_routes

| Method | Path | Access |
|---|---|---|
| POST | `/api/fly-facility/bait-preparation` | production.write |
| POST | `/api/fly-facility/cage-monitoring` | production.write |
| POST | `/api/fly-facility/egg-collection` | production.write |
| POST | `/api/fly-facility/maintenance` | production.write |
| POST | `/api/fly-facility/pupae-transition` | production.write |

## health

| Method | Path | Access |
|---|---|---|
| GET | `/healthz` | public |
| GET | `/readyz` | public |

## inventory

| Method | Path | Access |
|---|---|---|
| GET | `/api/inventory` | signed in |
| GET | `/api/inventory/locations` | signed in |
| POST | `/api/inventory/locations` | super_admin |
| POST | `/api/inventory/locations/<int:location_id>/status` | super_admin |
| POST | `/api/inventory/movements` | inventory.write |

## labels

| Method | Path | Access |
|---|---|---|
| GET | `/api/labels` | signed in |
| GET | `/api/labels/<string:kind>` | signed in |
| GET | `/labels` | signed in |
| GET | `/scan/<string:kind>/<path:ref>` | signed in |

## legacy

| Method | Path | Access |
|---|---|---|
| GET | `/api/analytics/bait-preparation` | legacy.read |
| GET | `/api/analytics/cage-monitoring` | legacy.read |
| GET | `/api/analytics/customers` | legacy.read |
| GET | `/api/analytics/deliveries` | legacy.read |
| GET | `/api/analytics/drying-batches` | legacy.read |
| GET | `/api/analytics/egg-collection` | legacy.read |
| GET | `/api/analytics/facility-maintenance` | legacy.read |
| GET | `/api/analytics/feedback` | legacy.read |
| GET | `/api/analytics/feeding-schedule` | legacy.read |
| GET | `/api/analytics/harvest-yield` | legacy.read |
| GET | `/api/analytics/hatchery-batches` | legacy.read |
| GET | `/api/analytics/hatchery-feeding` | legacy.read |
| GET | `/api/analytics/hatchery-monitoring` | legacy.read |
| GET | `/api/analytics/health-intervention` | legacy.read |
| GET | `/api/analytics/larvae-env-monitoring` | legacy.read |
| GET | `/api/analytics/processing-records` | legacy.read |
| GET | `/api/analytics/pupae-transition` | legacy.read |
| GET | `/api/analytics/sales` | legacy.read |
| GET | `/api/analytics/storage-records` | legacy.read |
| GET | `/api/analytics/substrate-preparation` | legacy.read |
| GET | `/api/analytics/waste-env-monitoring` | legacy.read |
| GET | `/api/analytics/waste-monitoring` | legacy.read |
| GET | `/api/analytics/waste-sourcing` | legacy.read |
| GET | `/api/deliveries` | legacy.read |
| POST | `/api/deliveries` | legacy.write |
| PUT | `/api/deliveries/<int:delivery_id>` | legacy.write |
| POST | `/api/drying/batch` | production.write |
| POST | `/api/drying/input` | production.write |
| GET | `/api/drying/input/all` | legacy.read |
| POST | `/api/drying/output` | production.write |
| GET | `/api/drying/output/all` | legacy.read |
| POST | `/api/drying/qc` | quality.decide |
| GET | `/api/drying/qc/all` | legacy.read |
| POST | `/api/drying/quality-control` | quality.decide |
| POST | `/api/drying/remarks` | production.write |
| GET | `/api/drying/remarks/all` | legacy.read |
| POST | `/api/drying/review` | quality.decide |
| GET | `/api/drying/review/all` | legacy.read |
| POST | `/api/facility/bait-preparation` | production.write |
| POST | `/api/facility/cage-monitoring` | production.write |
| POST | `/api/facility/egg-collection` | production.write |
| POST | `/api/facility/maintenance` | production.write |
| POST | `/api/facility/pupae-transition` | production.write |
| GET | `/api/feedback` | legacy.read |
| POST | `/api/feedback` | legacy.write |
| PUT | `/api/feedback/<int:feedback_id>` | legacy.write |
| POST | `/api/feeding/environmental-monitoring` | production.write |
| POST | `/api/feeding/harvest-yield` | production.write |
| GET | `/api/feeding/harvest/all` | legacy.read |
| POST | `/api/feeding/health-intervention` | production.write |
| POST | `/api/feeding/schedule` | production.write |
| POST | `/api/hatchery/batch` | production.write |
| POST | `/api/hatchery/batch-information` | production.write |
| POST | `/api/hatchery/cleaning` | production.write |
| POST | `/api/hatchery/environmental-monitoring` | production.write |
| POST | `/api/hatchery/feeding` | production.write |
| POST | `/api/hatchery/feeding-records` | production.write |
| POST | `/api/hatchery/health` | production.write |
| POST | `/api/hatchery/monitoring` | production.write |
| GET | `/api/hatchery/next-batch-id` | signed in |
| POST | `/api/hatchery/problems` | production.write |
| GET | `/api/records` | legacy.read |
| GET | `/api/sales` | legacy.read |
| POST | `/api/sales` | legacy.write |
| PUT | `/api/sales/<int:sale_id>` | legacy.write |
| POST | `/api/send-harvest-report` | legacy.read |
| GET | `/api/statistics/daily-report` | legacy.read |
| GET | `/api/statistics/environmental` | legacy.read |
| GET | `/api/statistics/harvest-efficiency` | legacy.read |
| GET | `/api/statistics/larval-growth` | legacy.read |
| GET | `/api/statistics/system-efficiency` | legacy.read |
| GET | `/api/statistics/waste-processing` | legacy.read |
| POST | `/api/waste-monitoring` | production.write |
| GET | `/api/waste-sourcing/all` | legacy.read |

## location_routes

| Method | Path | Access |
|---|---|---|
| POST | `/api/locations/<string:scope>/<int:scope_id>/status` | super_admin |
| DELETE, POST | `/api/locations/access` | super_admin |
| GET | `/api/locations/access/check` | signed in |
| POST | `/api/locations/facilities` | super_admin |
| POST | `/api/locations/farms` | super_admin |
| GET | `/api/locations/hierarchy` | signed in |
| POST | `/api/locations/organizations` | super_admin |
| POST | `/api/locations/record-links` | super_admin |
| POST | `/api/locations/sites` | super_admin |
| GET | `/api/locations/users/<int:user_id>/access` | super_admin |

## pages

| Method | Path | Access |
|---|---|---|
| GET | `/` | public |
| GET | `/analytics` | signed in |
| GET | `/dashboard` | signed in |
| GET | `/design-system` | signed in |
| GET | `/setup` | super_admin |

## production

| Method | Path | Access |
|---|---|---|
| GET | `/api/production/batches` | signed in |
| POST | `/api/production/batches` | production.write |
| GET | `/api/production/batches/<string:batch_ref>` | signed in |
| POST | `/api/production/batches/<string:batch_ref>/events/feeding` | production.write |
| POST | `/api/production/batches/<string:batch_ref>/events/harvest` | production.write |
| POST | `/api/production/batches/<string:batch_ref>/events/health` | production.write |
| POST | `/api/production/batches/<string:batch_ref>/events/monitoring` | production.write |
| PATCH, PUT | `/api/production/batches/<string:batch_ref>/harvest-limit` | production.write |
| PATCH, POST | `/api/production/batches/<string:batch_ref>/status` | production.write |

## quality

| Method | Path | Access |
|---|---|---|
| POST | `/api/drying/batches/<string:batch_ref>/quality-approvals` | quality.decide |
| POST | `/api/drying/batches/<string:batch_ref>/quality-checks` | quality.decide |
| POST | `/api/drying/outputs/<int:output_id>/quality-checks` | quality.decide |
| POST | `/api/drying/quality-approvals` | quality.decide |
| GET | `/api/product-lots` | signed in |
| POST | `/api/product-lots` | quality.decide |
| GET | `/api/product-lots/<string:lot_ref>` | signed in |
| GET | `/product-lot` | signed in |

## reports

| Method | Path | Access |
|---|---|---|
| GET | `/api/reports` | signed in |
| GET | `/api/reports/<string:report_key>` | signed in |

## sales

| Method | Path | Access |
|---|---|---|
| GET | `/api/customers` | sales.read |
| POST | `/api/customers` | sales.write |
| PUT | `/api/customers/<int:customer_id>` | sales.write |
| POST | `/api/deliveries/<string:delivery_ref>/confirm` | sales.write |
| GET | `/api/orders` | sales.read |
| POST | `/api/orders` | sales.write |
| GET | `/api/orders/<string:order_ref>` | sales.read |
| POST | `/api/orders/<string:order_ref>/allocations` | sales.write |
| POST | `/api/orders/<string:order_ref>/allocations/<int:allocation_id>/release` | sales.write |
| GET | `/api/orders/<string:order_ref>/available-stock` | sales.read |
| POST | `/api/orders/<string:order_ref>/cancel` | sales.write |
| POST | `/api/orders/<string:order_ref>/deliveries` | sales.write |
| GET | `/orders` | signed in |

## tour

| Method | Path | Access |
|---|---|---|
| POST | `/api/demo/guest` | public |
| GET | `/api/demo/info` | public |
| GET | `/api/demo/tour` | signed in |
| GET | `/tour` | public |

## traceability

| Method | Path | Access |
|---|---|---|
| GET | `/api/traceability` | signed in |
| GET | `/api/traceability/search` | signed in |
| GET | `/traceability` | signed in |

## units

| Method | Path | Access |
|---|---|---|
| POST | `/api/production/batches/<string:batch_ref>/units` | production.write |
| POST | `/api/production/batches/<string:batch_ref>/units/<int:unit_id>/release` | production.write |
| GET | `/api/production/units` | signed in |
| POST | `/api/production/units` | super_admin |
| POST | `/api/production/units/<int:unit_id>/status` | super_admin |

## waste

| Method | Path | Access |
|---|---|---|
| POST | `/api/processing-records` | production.write |
| POST | `/api/storage-records` | production.write |
| GET | `/api/substrate-batches` | signed in |
| POST | `/api/substrate-preparation` | production.write |
| GET | `/api/substrate/batches/<string:batch_no>` | signed in |
| GET | `/api/waste-lots` | signed in |
| POST | `/api/waste-lots/<string:lot_ref>/location` | super_admin |
| POST | `/api/waste-sourcing` | production.write |

## waste_management_routes

| Method | Path | Access |
|---|---|---|
| GET | `/api/environmental-monitoring` | legacy.read |
| GET | `/api/processing-records` | legacy.read |
| GET | `/api/storage-records` | legacy.read |
| GET | `/api/waste-sourcing` | legacy.read |

## web

| Method | Path | Access |
|---|---|---|
| GET | `/<path:filename>` | public |
