-- Phase One production batch -> substrate input relationship and lifecycle.
-- This migration is additive and safe to run at every application startup.

ALTER TABLE substrate_batches
    ADD COLUMN IF NOT EXISTS farm_id INTEGER,
    ADD COLUMN IF NOT EXISTS site_id INTEGER,
    ADD COLUMN IF NOT EXISTS facility_id INTEGER;

ALTER TABLE production_batches
    ADD COLUMN IF NOT EXISTS farm_id INTEGER,
    ADD COLUMN IF NOT EXISTS site_id INTEGER,
    ADD COLUMN IF NOT EXISTS facility_id INTEGER,
    ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS expected_harvest_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS harvest_limit_kg NUMERIC(14, 3);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'production_batches'::regclass
          AND conname = 'production_batches_harvest_limit_check'
    ) THEN
        ALTER TABLE production_batches
            ADD CONSTRAINT production_batches_harvest_limit_check
            CHECK (harvest_limit_kg IS NULL OR harvest_limit_kg > 0);
    END IF;
END $$;

-- These composite references enforce that the selected facility belongs to the
-- selected site and that the selected site belongs to the selected farm.
DO $$
BEGIN
    BEGIN
        ALTER TABLE substrate_batches
            ADD CONSTRAINT substrate_batches_site_farm_fk
            FOREIGN KEY (site_id, farm_id) REFERENCES sites(id, farm_id);
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
    BEGIN
        ALTER TABLE substrate_batches
            ADD CONSTRAINT substrate_batches_facility_site_fk
            FOREIGN KEY (facility_id, site_id) REFERENCES facilities(id, site_id);
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
    BEGIN
        ALTER TABLE production_batches
            ADD CONSTRAINT production_batches_site_farm_fk
            FOREIGN KEY (site_id, farm_id) REFERENCES sites(id, farm_id);
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
    BEGIN
        ALTER TABLE production_batches
            ADD CONSTRAINT production_batches_facility_site_fk
            FOREIGN KEY (facility_id, site_id) REFERENCES facilities(id, site_id);
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
END $$;

ALTER TABLE production_batches
    ALTER COLUMN status SET DEFAULT 'PLANNED';

-- Keep existing legacy casing readable while constraining the vocabulary.
DO $$
BEGIN
    BEGIN
        ALTER TABLE production_batches
            ADD CONSTRAINT production_batches_status_check
            CHECK (UPPER(status) IN (
                'PLANNED', 'ACTIVE', 'MONITORING', 'READY_FOR_HARVEST',
                'HARVESTED', 'COMPLETED', 'PAUSED', 'HEALTH_ALERT', 'CANCELLED'
            ));
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
END $$;

CREATE TABLE IF NOT EXISTS production_batch_inputs (
    id SERIAL PRIMARY KEY,
    production_batch_id INTEGER NOT NULL
        REFERENCES production_batches(id) ON DELETE RESTRICT,
    substrate_batch_id INTEGER NOT NULL
        REFERENCES substrate_batches(id) ON DELETE RESTRICT,
    quantity_issued NUMERIC(14, 3) NOT NULL CHECK (quantity_issued > 0),
    unit VARCHAR(16) NOT NULL DEFAULT 'kg' CHECK (unit = 'kg'),
    issued_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actor_user_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    actor VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (production_batch_id, substrate_batch_id)
);

CREATE INDEX IF NOT EXISTS idx_production_batch_inputs_batch
    ON production_batch_inputs(production_batch_id);
CREATE INDEX IF NOT EXISTS idx_production_batch_inputs_substrate
    ON production_batch_inputs(substrate_batch_id);

CREATE TABLE IF NOT EXISTS production_batch_status_history (
    id BIGSERIAL PRIMARY KEY,
    production_batch_id INTEGER NOT NULL
        REFERENCES production_batches(id) ON DELETE RESTRICT,
    previous_status VARCHAR(30),
    new_status VARCHAR(30) NOT NULL,
    actor_user_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    actor VARCHAR(100) NOT NULL,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reason TEXT,
    CHECK (UPPER(new_status) IN (
        'PLANNED', 'ACTIVE', 'MONITORING', 'READY_FOR_HARVEST',
        'HARVESTED', 'COMPLETED', 'PAUSED', 'HEALTH_ALERT', 'CANCELLED'
    ))
);

CREATE INDEX IF NOT EXISTS idx_production_batch_status_history_batch_time
    ON production_batch_status_history(production_batch_id, changed_at);