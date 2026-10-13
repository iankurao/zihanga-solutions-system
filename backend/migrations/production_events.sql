-- Phase One production events.
--
-- The legacy operational tables remain intact.  New writes populate both the
-- legacy row and this canonical event envelope so existing reports continue
-- to work while Production Batch becomes the relational source of truth.

CREATE SEQUENCE IF NOT EXISTS production_event_seq AS BIGINT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'production_batches'::regclass
          AND conname = 'production_batches_scope_unique'
    ) THEN
        BEGIN
            ALTER TABLE production_batches
                ADD CONSTRAINT production_batches_scope_unique
                UNIQUE (id, farm_id, site_id, facility_id);
        EXCEPTION WHEN duplicate_object OR duplicate_table THEN
            -- A prior interrupted run may have left only the auto-created
            -- unique index.  It is safe to remove this migration-owned index
            -- and retry the constraint creation.
            DROP INDEX IF EXISTS production_batches_scope_unique;
            ALTER TABLE production_batches
                ADD CONSTRAINT production_batches_scope_unique
                UNIQUE (id, farm_id, site_id, facility_id);
        END;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS production_events (
    id BIGSERIAL PRIMARY KEY,
    event_code VARCHAR(40) NOT NULL UNIQUE DEFAULT (
        'EVT-' || to_char(CURRENT_DATE, 'YYYY') || '-' ||
        lpad(nextval('production_event_seq')::text, 6, '0')
    ),
    production_batch_id INTEGER NOT NULL
        REFERENCES production_batches(id) ON DELETE RESTRICT,
    farm_id INTEGER NOT NULL REFERENCES farms(id) ON DELETE RESTRICT,
    site_id INTEGER NOT NULL REFERENCES sites(id) ON DELETE RESTRICT,
    facility_id INTEGER NOT NULL REFERENCES facilities(id) ON DELETE RESTRICT,
    event_type VARCHAR(20) NOT NULL
        CHECK (event_type IN ('feeding', 'monitoring', 'health', 'harvest')),
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by_user_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    actor VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'recorded'
        CHECK (status IN ('recorded', 'voided')),
    quantity NUMERIC(14, 3) CHECK (quantity IS NULL OR quantity >= 0),
    unit VARCHAR(16),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (
        unit IS NULL OR unit IN (
            'kg', 'g', 'count', 'days', 'celsius', 'percent', 'ppm', 'none'
        )
    ),
    UNIQUE (id, farm_id, site_id, facility_id)
);

-- Expand the event vocabulary on databases where production_events predates
-- harvest linkage. Replacing the named check is repeatable and preserves rows.
ALTER TABLE production_events
    DROP CONSTRAINT IF EXISTS production_events_event_type_check;
ALTER TABLE production_events
    ADD CONSTRAINT production_events_event_type_check
    CHECK (event_type IN ('feeding', 'monitoring', 'health', 'harvest'));

CREATE TABLE IF NOT EXISTS harvests (
    id BIGSERIAL PRIMARY KEY,
    harvest_code VARCHAR(40) NOT NULL UNIQUE,
    production_event_id BIGINT NOT NULL UNIQUE
        REFERENCES production_events(id) ON DELETE RESTRICT,
    wet_weight NUMERIC(14, 3) NOT NULL CHECK (wet_weight > 0),
    unit VARCHAR(16) NOT NULL CHECK (unit IN ('kg', 'g')),
    harvest_stage VARCHAR(80) NOT NULL CHECK (length(trim(harvest_stage)) > 0),
    operator VARCHAR(100) NOT NULL CHECK (length(trim(operator)) > 0),
    location VARCHAR(200) NOT NULL CHECK (length(trim(location)) > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_harvests_production_event
    ON harvests(production_event_id);

DO $$
BEGIN
    BEGIN
        ALTER TABLE production_events
            ADD CONSTRAINT production_events_batch_scope_fk
            FOREIGN KEY (production_batch_id, farm_id, site_id, facility_id)
            REFERENCES production_batches(id, farm_id, site_id, facility_id);
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
END $$;

CREATE TABLE IF NOT EXISTS feeding_events (
    production_event_id BIGINT PRIMARY KEY
        REFERENCES production_events(id) ON DELETE RESTRICT,
    feed_type VARCHAR(100) NOT NULL,
    quantity_offered NUMERIC(14, 3) NOT NULL CHECK (quantity_offered > 0),
    offered_unit VARCHAR(16) NOT NULL
        CHECK (offered_unit IN ('kg', 'g')),
    quantity_consumed NUMERIC(14, 3)
        CHECK (quantity_consumed IS NULL OR quantity_consumed >= 0),
    consumed_unit VARCHAR(16)
        CHECK (consumed_unit IS NULL OR consumed_unit IN ('kg', 'g')),
    larvae_biomass NUMERIC(14, 3)
        CHECK (larvae_biomass IS NULL OR larvae_biomass >= 0),
    biomass_unit VARCHAR(16)
        CHECK (biomass_unit IS NULL OR biomass_unit IN ('kg', 'g')),
    larvae_age_days INTEGER
        CHECK (larvae_age_days IS NULL OR larvae_age_days >= 0)
);

CREATE TABLE IF NOT EXISTS monitoring_events (
    production_event_id BIGINT PRIMARY KEY
        REFERENCES production_events(id) ON DELETE RESTRICT,
    monitoring_type VARCHAR(80) NOT NULL DEFAULT 'larval_environment',
    asset_reference VARCHAR(100),
    temperature NUMERIC(7, 2)
        CHECK (temperature IS NULL OR temperature BETWEEN -50 AND 100),
    temperature_unit VARCHAR(16)
        CHECK (temperature_unit IS NULL OR temperature_unit = 'celsius'),
    humidity NUMERIC(7, 2)
        CHECK (humidity IS NULL OR humidity BETWEEN 0 AND 100),
    humidity_unit VARCHAR(16)
        CHECK (humidity_unit IS NULL OR humidity_unit = 'percent'),
    ammonia NUMERIC(14, 3)
        CHECK (ammonia IS NULL OR ammonia >= 0),
    ammonia_unit VARCHAR(16)
        CHECK (ammonia_unit IS NULL OR ammonia_unit = 'ppm'),
    ammonia_odor VARCHAR(10)
        CHECK (ammonia_odor IS NULL OR ammonia_odor IN ('yes', 'no'))
);

CREATE TABLE IF NOT EXISTS health_events (
    production_event_id BIGINT PRIMARY KEY
        REFERENCES production_events(id) ON DELETE RESTRICT,
    status VARCHAR(20) NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'follow_up', 'resolved', 'closed')),
    observed_issue VARCHAR(255) NOT NULL,
    severity VARCHAR(20) NOT NULL
        CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    action_taken TEXT NOT NULL,
    follow_up_date DATE,
    resolved_at TIMESTAMPTZ,
    resolution_actor_user_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL
);

-- Canonical scope must match the batch and the hierarchy.
DO $$
BEGIN
    BEGIN
        ALTER TABLE production_events
            ADD CONSTRAINT production_events_site_farm_fk
            FOREIGN KEY (site_id, farm_id) REFERENCES sites(id, farm_id);
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
    BEGIN
        ALTER TABLE production_events
            ADD CONSTRAINT production_events_facility_site_fk
            FOREIGN KEY (facility_id, site_id) REFERENCES facilities(id, site_id);
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
END $$;

CREATE INDEX IF NOT EXISTS idx_production_events_batch_time
    ON production_events(production_batch_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_production_events_scope
    ON production_events(farm_id, site_id, facility_id);
CREATE INDEX IF NOT EXISTS idx_production_events_type
    ON production_events(event_type, occurred_at DESC);

-- Nullable links preserve historical rows when their free-text batch label
-- cannot be reconciled with evidence.  New operational writes populate them.
ALTER TABLE feeding_schedule
    ADD COLUMN IF NOT EXISTS production_event_id BIGINT,
    ADD COLUMN IF NOT EXISTS production_batch_id INTEGER,
    ADD COLUMN IF NOT EXISTS actor_user_id INTEGER,
    ADD COLUMN IF NOT EXISTS occurred_at TIMESTAMPTZ;

ALTER TABLE environmental_monitoring_larvaefeeding
    ADD COLUMN IF NOT EXISTS production_event_id BIGINT,
    ADD COLUMN IF NOT EXISTS production_batch_id INTEGER,
    ADD COLUMN IF NOT EXISTS actor_user_id INTEGER,
    ADD COLUMN IF NOT EXISTS occurred_at TIMESTAMPTZ;

ALTER TABLE health_intervention
    ADD COLUMN IF NOT EXISTS production_event_id BIGINT,
    ADD COLUMN IF NOT EXISTS production_batch_id INTEGER,
    ADD COLUMN IF NOT EXISTS actor_user_id INTEGER,
    ADD COLUMN IF NOT EXISTS occurred_at TIMESTAMPTZ;

DO $$
BEGIN
    BEGIN
        ALTER TABLE feeding_schedule
            ADD CONSTRAINT feeding_schedule_event_fk
            FOREIGN KEY (production_event_id) REFERENCES production_events(id)
            ON DELETE RESTRICT;
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
    BEGIN
        ALTER TABLE feeding_schedule
            ADD CONSTRAINT feeding_schedule_batch_fk
            FOREIGN KEY (production_batch_id) REFERENCES production_batches(id)
            ON DELETE RESTRICT;
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
    BEGIN
        ALTER TABLE feeding_schedule
            ADD CONSTRAINT feeding_schedule_actor_fk
            FOREIGN KEY (actor_user_id) REFERENCES users(user_id)
            ON DELETE SET NULL;
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
    BEGIN
        ALTER TABLE environmental_monitoring_larvaefeeding
            ADD CONSTRAINT larval_monitoring_event_fk
            FOREIGN KEY (production_event_id) REFERENCES production_events(id)
            ON DELETE RESTRICT;
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
    BEGIN
        ALTER TABLE environmental_monitoring_larvaefeeding
            ADD CONSTRAINT larval_monitoring_batch_fk
            FOREIGN KEY (production_batch_id) REFERENCES production_batches(id)
            ON DELETE RESTRICT;
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
    BEGIN
        ALTER TABLE environmental_monitoring_larvaefeeding
            ADD CONSTRAINT larval_monitoring_actor_fk
            FOREIGN KEY (actor_user_id) REFERENCES users(user_id)
            ON DELETE SET NULL;
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
    BEGIN
        ALTER TABLE health_intervention
            ADD CONSTRAINT health_intervention_event_fk
            FOREIGN KEY (production_event_id) REFERENCES production_events(id)
            ON DELETE RESTRICT;
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
    BEGIN
        ALTER TABLE health_intervention
            ADD CONSTRAINT health_intervention_batch_fk
            FOREIGN KEY (production_batch_id) REFERENCES production_batches(id)
            ON DELETE RESTRICT;
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
    BEGIN
        ALTER TABLE health_intervention
            ADD CONSTRAINT health_intervention_actor_fk
            FOREIGN KEY (actor_user_id) REFERENCES users(user_id)
            ON DELETE SET NULL;
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
END $$;

CREATE INDEX IF NOT EXISTS idx_feeding_schedule_production_batch
    ON feeding_schedule(production_batch_id);
CREATE INDEX IF NOT EXISTS idx_larval_monitoring_production_batch
    ON environmental_monitoring_larvaefeeding(production_batch_id);
CREATE INDEX IF NOT EXISTS idx_health_intervention_production_batch
    ON health_intervention(production_batch_id);