-- Phase One Step 20: physical production units (trays, beds, bio-pods) and
-- which production batch occupies them.  Replaces free-text tray labels.
-- Additive and safe to run at every application startup.

CREATE TABLE IF NOT EXISTS production_units (
    id SERIAL PRIMARY KEY,
    unit_code VARCHAR(30) NOT NULL CHECK (length(trim(unit_code)) > 0),
    name VARCHAR(100) NOT NULL CHECK (length(trim(name)) > 0),
    unit_type VARCHAR(20) NOT NULL DEFAULT 'bio_pod'
        CHECK (unit_type IN ('bio_pod', 'tray', 'bed', 'rack', 'other')),
    capacity_kg NUMERIC(14, 3) CHECK (capacity_kg IS NULL OR capacity_kg > 0),
    farm_id INTEGER NOT NULL REFERENCES farms(id) ON DELETE RESTRICT,
    site_id INTEGER NOT NULL,
    facility_id INTEGER NOT NULL,
    status VARCHAR(15) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'maintenance', 'retired')),
    created_by VARCHAR(100) NOT NULL,
    created_by_user_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (facility_id, unit_code),
    FOREIGN KEY (site_id, farm_id) REFERENCES sites(id, farm_id) ON DELETE RESTRICT,
    FOREIGN KEY (facility_id, site_id) REFERENCES facilities(id, site_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_production_units_scope
    ON production_units(farm_id, site_id, facility_id);

CREATE TABLE IF NOT EXISTS production_batch_units (
    id SERIAL PRIMARY KEY,
    production_batch_id INTEGER NOT NULL REFERENCES production_batches(id) ON DELETE RESTRICT,
    production_unit_id INTEGER NOT NULL REFERENCES production_units(id) ON DELETE RESTRICT,
    allocated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    released_at TIMESTAMPTZ,
    allocated_by VARCHAR(100) NOT NULL,
    allocated_by_user_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    release_reason TEXT,
    CHECK (released_at IS NULL OR released_at >= allocated_at)
);

-- A unit holds at most one batch at a time; history rows stay.
CREATE UNIQUE INDEX IF NOT EXISTS uq_production_batch_units_occupied
    ON production_batch_units(production_unit_id) WHERE released_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_production_batch_units_batch
    ON production_batch_units(production_batch_id);
