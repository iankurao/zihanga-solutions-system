-- Phase One canonical business identifiers.
--
-- Every new identifier is assigned by a PostgreSQL sequence in the INSERT
-- statement's column default.  Sequences are not derived from MAX(id), so
-- concurrent requests cannot receive the same business ID.  Existing integer
-- primary keys and legacy code columns remain unchanged for compatibility.

CREATE SEQUENCE IF NOT EXISTS phase_one_waste_lot_seq AS BIGINT;
CREATE SEQUENCE IF NOT EXISTS phase_one_substrate_batch_seq AS BIGINT;
CREATE SEQUENCE IF NOT EXISTS phase_one_production_batch_seq AS BIGINT;
CREATE SEQUENCE IF NOT EXISTS phase_one_harvest_seq AS BIGINT;
CREATE SEQUENCE IF NOT EXISTS phase_one_drying_batch_seq AS BIGINT;
CREATE SEQUENCE IF NOT EXISTS phase_one_product_lot_seq AS BIGINT;
CREATE SEQUENCE IF NOT EXISTS phase_one_inventory_movement_seq AS BIGINT;
CREATE SEQUENCE IF NOT EXISTS phase_one_hatchery_batch_seq AS BIGINT;

-- These tables are part of the Phase One chain but were not wired into the
-- operational app.  Create only when absent; never replace an existing table.
CREATE TABLE IF NOT EXISTS substrate_batches (
    id SERIAL PRIMARY KEY,
    batch_code VARCHAR(30),
    business_id VARCHAR(30),
    preparation_date DATE NOT NULL DEFAULT CURRENT_DATE,
    waste_lot_ids TEXT,
    total_input_weight_kg NUMERIC(14,3),
    output_weight_kg NUMERIC(14,3),
    quality_approved BOOLEAN DEFAULT FALSE,
    notes TEXT,
    recorded_by VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS production_batches (
    id SERIAL PRIMARY KEY,
    batch_code VARCHAR(30),
    business_id VARCHAR(30),
    substrate_batch_id INTEGER,
    start_date DATE NOT NULL DEFAULT CURRENT_DATE,
    current_stage VARCHAR(20) NOT NULL DEFAULT 'feeding',
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    notes TEXT,
    recorded_by VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS product_lots (
    id SERIAL PRIMARY KEY,
    lot_code VARCHAR(30),
    business_id VARCHAR(30),
    production_batch_id INTEGER REFERENCES production_batches(id),
    product_type VARCHAR(50) NOT NULL DEFAULT 'dried_larvae',
    processing_date DATE NOT NULL DEFAULT CURRENT_DATE,
    quantity_kg NUMERIC(14,3) NOT NULL DEFAULT 0,
    available_quantity_kg NUMERIC(14,3),
    status VARCHAR(20) NOT NULL DEFAULT 'available',
    recorded_by VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS waste_collection_items (
    id SERIAL PRIMARY KEY,
    lot_code VARCHAR(30),
    business_id VARCHAR(30),
    collection_time TIME,
    waste_type VARCHAR(50),
    weight_kg NUMERIC(14,3),
    recorded_by VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS inventory_movements (
    id SERIAL PRIMARY KEY,
    business_id VARCHAR(30),
    product_lot_id INTEGER REFERENCES product_lots(id),
    movement_type VARCHAR(30) NOT NULL,
    quantity_kg NUMERIC(14,3) NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    notes TEXT,
    recorded_by VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Operational tables currently used by the Flask routes.
ALTER TABLE waste_sourcing ADD COLUMN IF NOT EXISTS business_id VARCHAR(30);
ALTER TABLE substrate_preparation ADD COLUMN IF NOT EXISTS business_id VARCHAR(30);
ALTER TABLE harvest_yield ADD COLUMN IF NOT EXISTS business_id VARCHAR(30);
ALTER TABLE drying_batches ADD COLUMN IF NOT EXISTS business_id VARCHAR(30);

-- Canonical/ERP tables, whether they were created by ERP v2 or above.
ALTER TABLE production_batches ADD COLUMN IF NOT EXISTS business_id VARCHAR(30);
ALTER TABLE substrate_batches ADD COLUMN IF NOT EXISTS business_id VARCHAR(30);
ALTER TABLE product_lots ADD COLUMN IF NOT EXISTS business_id VARCHAR(30);
ALTER TABLE waste_collection_items ADD COLUMN IF NOT EXISTS business_id VARCHAR(30);
ALTER TABLE inventory_movements ADD COLUMN IF NOT EXISTS business_id VARCHAR(30);

ALTER TABLE waste_sourcing
    ALTER COLUMN business_id SET DEFAULT ('WL-' || to_char(CURRENT_DATE, 'YYYY') || '-' ||
                                          lpad(nextval('phase_one_waste_lot_seq')::text, 5, '0'));
ALTER TABLE substrate_preparation
    ALTER COLUMN business_id SET DEFAULT ('SUB-' || to_char(CURRENT_DATE, 'YYYY') || '-' ||
                                          lpad(nextval('phase_one_substrate_batch_seq')::text, 5, '0'));
ALTER TABLE harvest_yield
    ALTER COLUMN business_id SET DEFAULT ('HRV-' || to_char(CURRENT_DATE, 'YYYY') || '-' ||
                                          lpad(nextval('phase_one_harvest_seq')::text, 5, '0'));
ALTER TABLE drying_batches
    ALTER COLUMN business_id SET DEFAULT ('DRY-' || to_char(CURRENT_DATE, 'YYYY') || '-' ||
                                          lpad(nextval('phase_one_drying_batch_seq')::text, 5, '0'));
ALTER TABLE production_batches
    ALTER COLUMN business_id SET DEFAULT ('BSF-' || to_char(CURRENT_DATE, 'YYYY') || '-' ||
                                          lpad(nextval('phase_one_production_batch_seq')::text, 5, '0'));
ALTER TABLE substrate_batches
    ALTER COLUMN business_id SET DEFAULT ('SUB-' || to_char(CURRENT_DATE, 'YYYY') || '-' ||
                                          lpad(nextval('phase_one_substrate_batch_seq')::text, 5, '0'));
ALTER TABLE product_lots
    ALTER COLUMN business_id SET DEFAULT ('LOT-' || to_char(CURRENT_DATE, 'YYYY') || '-' ||
                                          lpad(nextval('phase_one_product_lot_seq')::text, 5, '0'));
ALTER TABLE waste_collection_items
    ALTER COLUMN business_id SET DEFAULT ('WL-' || to_char(CURRENT_DATE, 'YYYY') || '-' ||
                                          lpad(nextval('phase_one_waste_lot_seq')::text, 5, '0'));
ALTER TABLE inventory_movements
    ALTER COLUMN business_id SET DEFAULT ('MOV-' || to_char(CURRENT_DATE, 'YYYY') || '-' ||
                                          lpad(nextval('phase_one_inventory_movement_seq')::text, 5, '0'));

-- Backfill only missing values.  The legacy primary key makes this deterministic
-- and preserves access to every existing record without changing references.
UPDATE waste_sourcing
SET business_id = 'WL-' || to_char(COALESCE(collection_date, CURRENT_DATE), 'YYYY') || '-' ||
                  lpad(id::text, 5, '0')
WHERE business_id IS NULL;
UPDATE substrate_preparation
SET business_id = 'SUB-' || to_char(COALESCE(prep_date, CURRENT_DATE), 'YYYY') || '-' ||
                  lpad(id::text, 5, '0')
WHERE business_id IS NULL;
UPDATE harvest_yield
SET business_id = 'HRV-' || to_char(COALESCE(harvest_date, CURRENT_DATE), 'YYYY') || '-' ||
                  lpad(id::text, 5, '0')
WHERE business_id IS NULL;
UPDATE drying_batches
SET business_id = 'DRY-' || to_char(COALESCE(drying_date, CURRENT_DATE), 'YYYY') || '-' ||
                  lpad(id::text, 5, '0')
WHERE business_id IS NULL;
UPDATE production_batches
SET business_id = 'BSF-' || to_char(COALESCE(start_date, CURRENT_DATE), 'YYYY') || '-' ||
                  lpad(id::text, 5, '0')
WHERE business_id IS NULL;
UPDATE substrate_batches
SET business_id = 'SUB-' || to_char(COALESCE(preparation_date, CURRENT_DATE), 'YYYY') || '-' ||
                  lpad(id::text, 5, '0')
WHERE business_id IS NULL;
UPDATE product_lots
SET business_id = 'LOT-' || to_char(COALESCE(processing_date, CURRENT_DATE), 'YYYY') || '-' ||
                  lpad(id::text, 5, '0')
WHERE business_id IS NULL;
UPDATE waste_collection_items
SET business_id = 'WL-' || to_char(COALESCE(created_at::date, CURRENT_DATE), 'YYYY') || '-' ||
                  lpad(id::text, 5, '0')
WHERE business_id IS NULL;
UPDATE inventory_movements
SET business_id = 'MOV-' || to_char(COALESCE(occurred_at::date, CURRENT_DATE), 'YYYY') || '-' ||
                  lpad(id::text, 5, '0')
WHERE business_id IS NULL;

-- Ensure the next sequence value is above all legacy integer keys.  This is a
-- one-time migration alignment, not runtime ID generation.
SELECT setval(
    'phase_one_waste_lot_seq',
    GREATEST((SELECT last_value FROM phase_one_waste_lot_seq),
             COALESCE((SELECT MAX(id) FROM waste_collection_items), 0),
             COALESCE((SELECT MAX(id) FROM waste_sourcing), 0), 1),
    (SELECT is_called FROM phase_one_waste_lot_seq) OR
        GREATEST(COALESCE((SELECT MAX(id) FROM waste_collection_items), 0),
                 COALESCE((SELECT MAX(id) FROM waste_sourcing), 0)) > 0
);
SELECT setval(
    'phase_one_substrate_batch_seq',
    GREATEST((SELECT last_value FROM phase_one_substrate_batch_seq),
             COALESCE((SELECT MAX(id) FROM substrate_preparation), 0),
             COALESCE((SELECT MAX(id) FROM substrate_batches), 0), 1),
    (SELECT is_called FROM phase_one_substrate_batch_seq) OR
        GREATEST(COALESCE((SELECT MAX(id) FROM substrate_preparation), 0),
                 COALESCE((SELECT MAX(id) FROM substrate_batches), 0)) > 0
);
SELECT setval(
    'phase_one_production_batch_seq',
    GREATEST((SELECT last_value FROM phase_one_production_batch_seq),
             COALESCE((SELECT MAX(id) FROM production_batches), 0), 1),
    (SELECT is_called FROM phase_one_production_batch_seq) OR
        COALESCE((SELECT MAX(id) FROM production_batches), 0) > 0
);
SELECT setval(
    'phase_one_harvest_seq',
    GREATEST((SELECT last_value FROM phase_one_harvest_seq),
             COALESCE((SELECT MAX(id) FROM harvest_yield), 0), 1),
    (SELECT is_called FROM phase_one_harvest_seq) OR
        COALESCE((SELECT MAX(id) FROM harvest_yield), 0) > 0
);
SELECT setval(
    'phase_one_drying_batch_seq',
    GREATEST((SELECT last_value FROM phase_one_drying_batch_seq),
             COALESCE((SELECT MAX(id) FROM drying_batches), 0), 1),
    (SELECT is_called FROM phase_one_drying_batch_seq) OR
        COALESCE((SELECT MAX(id) FROM drying_batches), 0) > 0
);
SELECT setval(
    'phase_one_product_lot_seq',
    GREATEST((SELECT last_value FROM phase_one_product_lot_seq),
             COALESCE((SELECT MAX(id) FROM product_lots), 0), 1),
    (SELECT is_called FROM phase_one_product_lot_seq) OR
        COALESCE((SELECT MAX(id) FROM product_lots), 0) > 0
);
SELECT setval(
    'phase_one_inventory_movement_seq',
    GREATEST((SELECT last_value FROM phase_one_inventory_movement_seq),
             COALESCE((SELECT MAX(id) FROM inventory_movements), 0), 1),
    (SELECT is_called FROM phase_one_inventory_movement_seq) OR
        COALESCE((SELECT MAX(id) FROM inventory_movements), 0) > 0
);

ALTER TABLE waste_sourcing ALTER COLUMN business_id SET NOT NULL;
ALTER TABLE substrate_preparation ALTER COLUMN business_id SET NOT NULL;
ALTER TABLE harvest_yield ALTER COLUMN business_id SET NOT NULL;
ALTER TABLE drying_batches ALTER COLUMN business_id SET NOT NULL;
ALTER TABLE production_batches ALTER COLUMN business_id SET NOT NULL;
ALTER TABLE substrate_batches ALTER COLUMN business_id SET NOT NULL;
ALTER TABLE product_lots ALTER COLUMN business_id SET NOT NULL;
ALTER TABLE waste_collection_items ALTER COLUMN business_id SET NOT NULL;
ALTER TABLE inventory_movements ALTER COLUMN business_id SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_waste_sourcing_business_id ON waste_sourcing(business_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_substrate_preparation_business_id ON substrate_preparation(business_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_harvest_yield_business_id ON harvest_yield(business_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_drying_batches_business_id ON drying_batches(business_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_production_batches_business_id ON production_batches(business_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_substrate_batches_business_id ON substrate_batches(business_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_product_lots_business_id ON product_lots(business_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_waste_collection_items_business_id ON waste_collection_items(business_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_inventory_movements_business_id ON inventory_movements(business_id);

-- Hatchery's old preview endpoint scanned hatchery_feeding, which is unrelated
-- to batch creation.  Keep the existing batch_number field but give it a
-- database-backed allocator for callers that omit it.
ALTER TABLE hatchery_batches
    ALTER COLUMN batch_number SET DEFAULT ('HAT-' || to_char(CURRENT_DATE, 'YYYY') || '-' ||
                                           lpad(nextval('phase_one_hatchery_batch_seq')::text, 5, '0'));
SELECT setval(
    'phase_one_hatchery_batch_seq',
    GREATEST((SELECT last_value FROM phase_one_hatchery_batch_seq),
             COALESCE((SELECT MAX(id) FROM hatchery_batches), 0), 1),
    (SELECT is_called FROM phase_one_hatchery_batch_seq) OR
        COALESCE((SELECT MAX(id) FROM hatchery_batches), 0) > 0
);