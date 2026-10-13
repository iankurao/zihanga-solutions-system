-- First operational production-chain link:
-- waste_sourcing -> waste_lots -> substrate_batch_inputs -> substrate_batches.
-- This migration is additive and safe to run at every application startup.

CREATE TABLE IF NOT EXISTS waste_lots (
    id SERIAL PRIMARY KEY,
    business_id VARCHAR(30) NOT NULL UNIQUE,
    waste_sourcing_id INTEGER NOT NULL UNIQUE
        REFERENCES waste_sourcing(id) ON DELETE RESTRICT,
    farm_site VARCHAR(150) NOT NULL,
    source_type VARCHAR(50) NOT NULL,
    source_name VARCHAR(100) NOT NULL,
    waste_type VARCHAR(50) NOT NULL,
    collection_date DATE NOT NULL,
    quantity NUMERIC(14, 3) NOT NULL CHECK (quantity >= 0),
    unit VARCHAR(16) NOT NULL DEFAULT 'kg',
    quality_status VARCHAR(30) NOT NULL,
    status VARCHAR(20) NOT NULL
        CHECK (status IN ('available', 'quarantined', 'rejected', 'consumed')),
    recorded_by VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE substrate_batches
    ADD COLUMN IF NOT EXISTS farm_site VARCHAR(150);
ALTER TABLE substrate_batches
    ADD COLUMN IF NOT EXISTS particle_size VARCHAR(20);

CREATE TABLE IF NOT EXISTS substrate_batch_inputs (
    id SERIAL PRIMARY KEY,
    waste_lot_id INTEGER NOT NULL
        REFERENCES waste_lots(id) ON DELETE RESTRICT,
    substrate_batch_id INTEGER NOT NULL
        REFERENCES substrate_batches(id) ON DELETE RESTRICT,
    quantity_used NUMERIC(14, 3) NOT NULL CHECK (quantity_used > 0),
    unit VARCHAR(16) NOT NULL DEFAULT 'kg',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actor VARCHAR(100) NOT NULL,
    UNIQUE (substrate_batch_id, waste_lot_id)
);

CREATE INDEX IF NOT EXISTS idx_waste_lots_status_collection
    ON waste_lots(status, collection_date);
CREATE INDEX IF NOT EXISTS idx_waste_lots_farm_site
    ON waste_lots(farm_site);
CREATE INDEX IF NOT EXISTS idx_substrate_batch_inputs_waste_lot
    ON substrate_batch_inputs(waste_lot_id);
CREATE INDEX IF NOT EXISTS idx_substrate_batch_inputs_batch
    ON substrate_batch_inputs(substrate_batch_id);

-- Promote existing sourcing records into traceable lots. Historical records
-- have no site field, so mark that fact explicitly rather than inventing one.
-- Only positive measured quantities can become inventory lots.
INSERT INTO waste_lots (
    business_id,
    waste_sourcing_id,
    farm_site,
    source_type,
    source_name,
    waste_type,
    collection_date,
    quantity,
    unit,
    quality_status,
    status,
    recorded_by,
    created_at
)
SELECT
    ws.business_id,
    ws.id,
    'Unspecified legacy site',
    ws.source_type,
    ws.source_name,
    ws.waste_type,
    ws.collection_date,
    ws.waste_weight,
    'kg',
    COALESCE(NULLIF(LOWER(ws.segregation_status), ''), 'unknown'),
    CASE
        WHEN LOWER(COALESCE(ws.segregation_status, '')) = 'organic'
         AND COALESCE(NULLIF(BTRIM(ws.contaminants_found), ''), '') = ''
            THEN 'available'
        ELSE 'quarantined'
    END,
    COALESCE(NULLIF(ws.recorded_by, ''), 'legacy import'),
    COALESCE(ws.created_at, CURRENT_TIMESTAMP)
FROM waste_sourcing AS ws
WHERE ws.waste_weight > 0
ON CONFLICT (waste_sourcing_id) DO NOTHING;