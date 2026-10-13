-- Phase One Step 8: connect canonical Harvest records to the existing drying
-- workflow.  This migration is additive: the legacy singular drying tables
-- and their text references remain available for historical records.

CREATE SEQUENCE IF NOT EXISTS phase_one_quality_check_seq AS BIGINT;
CREATE SEQUENCE IF NOT EXISTS phase_one_quality_approval_seq AS BIGINT;

ALTER TABLE drying_batches
    ADD COLUMN IF NOT EXISTS batch_code VARCHAR(50),
    ADD COLUMN IF NOT EXISTS farm_id INTEGER,
    ADD COLUMN IF NOT EXISTS site_id INTEGER,
    ADD COLUMN IF NOT EXISTS facility_id INTEGER,
    ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS ended_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS created_by_user_id INTEGER,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;

UPDATE drying_batches
SET batch_code = batch_id
WHERE batch_code IS NULL;

UPDATE drying_batches
SET updated_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP)
WHERE updated_at IS NULL;

ALTER TABLE drying_batches
    ALTER COLUMN status SET DEFAULT 'DRAFT',
    ALTER COLUMN updated_at SET DEFAULT CURRENT_TIMESTAMP;

CREATE UNIQUE INDEX IF NOT EXISTS uq_drying_batches_batch_code
    ON drying_batches(batch_code)
    WHERE batch_code IS NOT NULL;

DO $$
BEGIN
    BEGIN
        ALTER TABLE drying_batches
            ADD CONSTRAINT drying_batches_farm_fk
            FOREIGN KEY (farm_id) REFERENCES farms(id) ON DELETE RESTRICT;
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
    BEGIN
        ALTER TABLE drying_batches
            ADD CONSTRAINT drying_batches_site_farm_fk
            FOREIGN KEY (site_id, farm_id) REFERENCES sites(id, farm_id)
            ON DELETE RESTRICT;
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
    BEGIN
        ALTER TABLE drying_batches
            ADD CONSTRAINT drying_batches_facility_site_fk
            FOREIGN KEY (facility_id, site_id) REFERENCES facilities(id, site_id)
            ON DELETE RESTRICT;
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
    BEGIN
        ALTER TABLE drying_batches
            ADD CONSTRAINT drying_batches_created_by_fk
            FOREIGN KEY (created_by_user_id) REFERENCES users(user_id)
            ON DELETE SET NULL;
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
END $$;

CREATE TABLE IF NOT EXISTS drying_batch_status_history (
    id BIGSERIAL PRIMARY KEY,
    drying_batch_id INTEGER NOT NULL
        REFERENCES drying_batches(id) ON DELETE RESTRICT,
    previous_status VARCHAR(20),
    new_status VARCHAR(20) NOT NULL
        CHECK (new_status IN ('DRAFT', 'RECEIVED', 'DRYING', 'QC_PENDING', 'COMPLETED')),
    actor_user_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    actor VARCHAR(100) NOT NULL,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reason TEXT,
    CHECK (
        previous_status IS NULL OR
        previous_status IN ('DRAFT', 'RECEIVED', 'DRYING', 'QC_PENDING', 'COMPLETED')
    )
);

CREATE TABLE IF NOT EXISTS drying_inputs (
    id BIGSERIAL PRIMARY KEY,
    drying_batch_id INTEGER NOT NULL
        REFERENCES drying_batches(id) ON DELETE RESTRICT,
    line_no INTEGER NOT NULL CHECK (line_no > 0),
    harvest_id BIGINT NOT NULL
        REFERENCES harvests(id) ON DELETE RESTRICT,
    quantity NUMERIC(14, 3) NOT NULL CHECK (quantity > 0),
    unit VARCHAR(16) NOT NULL CHECK (unit IN ('kg', 'g')),
    incoming_moisture_percent NUMERIC(5, 2)
        CHECK (
            incoming_moisture_percent IS NULL OR
            incoming_moisture_percent BETWEEN 0 AND 100
        ),
    added_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    recorded_by_user_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    recorded_by VARCHAR(100) NOT NULL,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (drying_batch_id, line_no),
    UNIQUE (drying_batch_id, harvest_id)
);

CREATE INDEX IF NOT EXISTS idx_drying_inputs_harvest
    ON drying_inputs(harvest_id);
CREATE INDEX IF NOT EXISTS idx_drying_inputs_batch
    ON drying_inputs(drying_batch_id);

CREATE TABLE IF NOT EXISTS drying_outputs (
    id BIGSERIAL PRIMARY KEY,
    drying_batch_id INTEGER NOT NULL
        REFERENCES drying_batches(id) ON DELETE RESTRICT,
    line_no INTEGER NOT NULL CHECK (line_no > 0),
    quantity NUMERIC(14, 3) NOT NULL CHECK (quantity > 0),
    unit VARCHAR(16) NOT NULL CHECK (unit IN ('kg', 'g')),
    moisture_percent NUMERIC(5, 2)
        CHECK (moisture_percent IS NULL OR moisture_percent BETWEEN 0 AND 100),
    output_date TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    operator VARCHAR(100) NOT NULL CHECK (length(trim(operator)) > 0),
    input_quantity_kg_at_output NUMERIC(14, 3)
        CHECK (input_quantity_kg_at_output IS NULL OR input_quantity_kg_at_output >= 0),
    yield_ratio NUMERIC(10, 6)
        CHECK (yield_ratio IS NULL OR yield_ratio BETWEEN 0 AND 1),
    yield_percentage NUMERIC(8, 3)
        CHECK (yield_percentage IS NULL OR yield_percentage BETWEEN 0 AND 100),
    recorded_by_user_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    recorded_by VARCHAR(100) NOT NULL,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (drying_batch_id, line_no)
);

CREATE INDEX IF NOT EXISTS idx_drying_outputs_batch
    ON drying_outputs(drying_batch_id);

ALTER TABLE drying_outputs
    ADD COLUMN IF NOT EXISTS input_quantity_kg_at_output NUMERIC(14, 3),
    ADD COLUMN IF NOT EXISTS yield_ratio NUMERIC(10, 6),
    ADD COLUMN IF NOT EXISTS yield_percentage NUMERIC(8, 3);

CREATE TABLE IF NOT EXISTS quality_checks (
    id BIGSERIAL PRIMARY KEY,
    check_code VARCHAR(50) NOT NULL UNIQUE DEFAULT (
        'QCK-' || to_char(CURRENT_DATE, 'YYYY') || '-' ||
        lpad(nextval('phase_one_quality_check_seq')::text, 5, '0')
    ),
    drying_batch_id INTEGER NOT NULL
        REFERENCES drying_batches(id) ON DELETE RESTRICT,
    status VARCHAR(20) NOT NULL DEFAULT 'submitted'
        CHECK (status IN ('draft', 'submitted', 'passed', 'failed', 'superseded')),
    moisture_percent NUMERIC(5, 2)
        CHECK (moisture_percent IS NULL OR moisture_percent BETWEEN 0 AND 100),
    parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    sampled_at TIMESTAMPTZ,
    checked_at TIMESTAMPTZ,
    inspector VARCHAR(100) NOT NULL,
    inspector_user_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_quality_checks_drying_batch
    ON quality_checks(drying_batch_id);

ALTER TABLE quality_checks
    ALTER COLUMN check_code SET DEFAULT (
        'QCK-' || to_char(CURRENT_DATE, 'YYYY') || '-' ||
        lpad(nextval('phase_one_quality_check_seq')::text, 5, '0')
    );

CREATE TABLE IF NOT EXISTS quality_approvals (
    id BIGSERIAL PRIMARY KEY,
    approval_code VARCHAR(50) NOT NULL UNIQUE DEFAULT (
        'QCA-' || to_char(CURRENT_DATE, 'YYYY') || '-' ||
        lpad(nextval('phase_one_quality_approval_seq')::text, 5, '0')
    ),
    quality_check_id BIGINT NOT NULL
        REFERENCES quality_checks(id) ON DELETE RESTRICT,
    decision VARCHAR(20) NOT NULL
        CHECK (decision IN ('approved', 'rejected', 'conditional', 'revoked')),
    rationale TEXT,
    decided_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    approver VARCHAR(100) NOT NULL,
    approver_user_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_quality_approvals_check
    ON quality_approvals(quality_check_id);

ALTER TABLE quality_approvals
    ALTER COLUMN approval_code SET DEFAULT (
        'QCA-' || to_char(CURRENT_DATE, 'YYYY') || '-' ||
        lpad(nextval('phase_one_quality_approval_seq')::text, 5, '0')
    );