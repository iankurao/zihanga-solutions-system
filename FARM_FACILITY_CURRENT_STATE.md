# Farm, Site & Facility Current State

## Audit date

2026-09-25

## Scope

This audit covers the imported Flask/PostgreSQL BSF Farm Management System and
the Phase One production-chain migrations. It was completed before introducing
the canonical location hierarchy.

## 1. Current implementation

### Organization, farm, site, and facility

- No `organizations`, `farms`, `sites`, or canonical `facilities` tables exist.
- `facility_maintenance` and the `fly_facility_*` tables are operational
  record tables, not facility master data.
- `farmer_profiles` has legacy free-text `farm_name` and `farm_location` fields
  in the historical ERP migration, but that migration is not the active source
  of the application schema.
- The waste-to-substrate chain has a legacy free-text `farm_site` on
  `waste_lots` and `substrate_batches`.

### Users, roles, permissions, and farmer relationships

- `users` is the active identity table with `user_id`, username, email,
  `is_active`, and a free-text `role`.
- The application currently distinguishes `super_admin` from other roles.
  There are no permission or role-permission tables.
- There is no active user-to-farm, user-to-site, or user-to-facility
  authorization relationship.
- `farmer_profiles` in `erp_schema_v2.sql` can relate a profile to `users`, but
  it is not created by `backend/init_db.py` and does not establish location
  authorization.

### Operational tables

The active initializer creates these operational areas:

- Waste: `waste_sourcing`, `storage_records`, `processing_records`,
  `waste_monitoring`
- Substrate and feeding: `substrate_preparation`, `substrate_batches`,
  `substrate_batch_inputs`, `feeding_schedule`, `health_intervention`,
  `environmental_monitoring_larvaefeeding`
- Hatchery: `hatchery_batches`, `hatchery_feeding`, `hatchery_monitoring`,
  `hatchery_cleaning`, `hatchery_problems`, `hatchery_health_interventions`
- Fly facility: `cage_monitoring`, `facility_maintenance`,
  `pupae_transition`, `egg_collection`, `bait_preparation`
- Harvest and drying: `harvest_yield`, `drying_batches`, `drying_input`,
  `drying_output`, `drying_quality_control`, `drying_review_approval`
- Sales: `customers`, `sales`, `customer_feedback`, `deliveries`
- Phase One chain: `production_batches`, `product_lots`,
  `inventory_movements`, and waste-lot tables from the additive migrations

New canonical Product Lots inherit their farm from the source Drying Batch and
are authorized against that batch's farm/site/facility scope. They do not
create or infer a separate location assignment. Existing Product Lots without
a canonical drying-output relationship remain unlinked.

Most of these tables have no location foreign key. Many have a
`recorded_by` username string, which provides actor attribution but not
authorization or a stable user foreign key.

## 2. What can be reused

- The existing `users.user_id` is the identity foreign key for access grants.
- The existing `users.role = 'super_admin'` behavior remains the unrestricted
  administrative role.
- Existing operational primary keys and business IDs remain unchanged.
- Existing legacy fields such as `farm_site`, `storage_location`, cage IDs,
  tray IDs, and batch IDs remain available for backward compatibility.
- The existing Flask app, `DatabaseConnection` pool, and repeatable
  `backend.init_db` startup migration are reused.

## 3. What needs modification

- Add canonical organization → farm → site → facility master data.
- Add explicit access grants for users at each hierarchy level.
- Add a stable link between an existing operational record and a canonical
  location without rewriting every operational table or guessing legacy
  locations.
- Add API endpoints for creating the hierarchy, granting access, listing the
  caller's accessible locations, and checking facility access.

## 4. What is missing

- Canonical location IDs and parent foreign keys.
- User location access grants.
- A durable location link for operational records.
- A permission model beyond the current super-admin check.
- Location selectors and location IDs in the existing operational forms.

## 5. Location information already present

| Area | Existing location information | Quality |
|---|---|---|
| Waste sourcing | `farm_site` request field and legacy text | Ambiguous free text |
| Waste lots | `farm_site` | Ambiguous free text |
| Substrate batches | `farm_site` | Ambiguous free text |
| Fly facility records | Cage/barrel/love-cage identifiers | Asset identifiers, not canonical facilities |
| Drying | `storage_location` / batch identifiers in historical schema | Free text or indirect |
| Farmer profiles | `farm_name`, `farm_location` in historical schema | Free text and not active |
| Sales and customer records | Customer address and product storage text | Not farm hierarchy |

## 6. Operational tables without a location relationship

The active schemas for storage, processing, monitoring, feeding, health
interventions, harvest, hatchery, fly-facility operations, drying, inventory,
sales, and deliveries do not contain canonical organization, farm, site, or
facility foreign keys.

## 7. Ambiguous or missing records

Existing records cannot be safely assigned to a canonical location from the
current data alone. A value such as `Main Farm`, a cage ID, or a free-text
`farm_site` does not uniquely identify an organization/farm/site/facility.
The implementation therefore does not backfill guessed relationships.

## Canonical Phase One decision

The canonical hierarchy is:

```text
Organization
└── Farm
    └── Site
        └── Facility
```

The new schema is additive. The location-link table is the transition point
for mapping records after an authorized user confirms their location. Existing
operational data remains queryable during the transition.

## Deferred work

1. Populate the hierarchy with approved real locations.
2. Map legacy records using an operator-reviewed mapping process.
3. Add location selectors and access-aware filtering to each operational form
   and endpoint.
4. Replace or supplement free-text actor/location fields with stable foreign
   keys where the migration plan has been approved.