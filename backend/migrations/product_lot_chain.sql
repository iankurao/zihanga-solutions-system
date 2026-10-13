-- Phase One Step 9: release a specific approved Drying Output as a Product Lot.
-- Existing unlinked product-lot records remain unchanged and are not assigned
-- invented drying, quality, or farm relationships.

ALTER TABLE quality_checks
    ADD COLUMN IF NOT EXISTS drying_output_id BIGINT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'quality_checks'::regclass
          AND conname = 'quality_checks_drying_output_fk'
    ) THEN
        ALTER TABLE quality_checks
            ADD CONSTRAINT quality_checks_drying_output_fk
            FOREIGN KEY (drying_output_id)
            REFERENCES drying_outputs(id) ON DELETE RESTRICT;
    END IF;
END $$;

ALTER TABLE product_lots
    ADD COLUMN IF NOT EXISTS drying_output_id BIGINT,
    ADD COLUMN IF NOT EXISTS release_approval_id BIGINT,
    ADD COLUMN IF NOT EXISTS farm_id INTEGER,
    ADD COLUMN IF NOT EXISTS production_date DATE,
    ADD COLUMN IF NOT EXISTS unit VARCHAR(16),
    ADD COLUMN IF NOT EXISTS storage_location VARCHAR(100);

-- The legacy quantity column is explicitly in kg and the former processing
-- date is the only safe source for this matching legacy production date.
UPDATE product_lots
SET production_date = processing_date
WHERE production_date IS NULL;

UPDATE product_lots
SET unit = 'kg'
WHERE unit IS NULL;

ALTER TABLE product_lots
    ALTER COLUMN production_date SET DEFAULT CURRENT_DATE,
    ALTER COLUMN unit SET DEFAULT 'kg',
    ALTER COLUMN unit SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'product_lots'::regclass
          AND conname = 'product_lots_drying_output_fk'
    ) THEN
        ALTER TABLE product_lots
            ADD CONSTRAINT product_lots_drying_output_fk
            FOREIGN KEY (drying_output_id)
            REFERENCES drying_outputs(id) ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'product_lots'::regclass
          AND conname = 'product_lots_release_approval_fk'
    ) THEN
        ALTER TABLE product_lots
            ADD CONSTRAINT product_lots_release_approval_fk
            FOREIGN KEY (release_approval_id)
            REFERENCES quality_approvals(id) ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'product_lots'::regclass
          AND conname = 'product_lots_farm_fk'
    ) THEN
        ALTER TABLE product_lots
            ADD CONSTRAINT product_lots_farm_fk
            FOREIGN KEY (farm_id)
            REFERENCES farms(id) ON DELETE RESTRICT;
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_product_lots_drying_output
    ON product_lots(drying_output_id)
    WHERE drying_output_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_product_lots_canonical_lot_code
    ON product_lots(lot_code)
    WHERE drying_output_id IS NOT NULL AND lot_code IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_product_lots_farm
    ON product_lots(farm_id);

CREATE OR REPLACE FUNCTION enforce_product_lot_release()
RETURNS TRIGGER AS $$
DECLARE
    release_is_approved BOOLEAN;
BEGIN
    IF NEW.drying_output_id IS NULL THEN
        RETURN NEW;
    END IF;

    IF NEW.release_approval_id IS NULL OR NEW.farm_id IS NULL
       OR LOWER(COALESCE(NEW.status, '')) <> 'available' THEN
        RAISE EXCEPTION
            'A canonical Product Lot requires an approved QC release and available status';
    END IF;

    SELECT EXISTS (
        SELECT 1
        FROM quality_approvals AS qa
        JOIN quality_checks AS qc ON qc.id = qa.quality_check_id
        JOIN drying_outputs AS output
          ON output.id = qc.drying_output_id
         AND output.id = NEW.drying_output_id
        JOIN drying_batches AS batch
          ON batch.id = output.drying_batch_id
        WHERE qa.id = NEW.release_approval_id
          AND qa.decision = 'approved'
          AND qa.id = (
              SELECT MAX(latest.id)
              FROM quality_approvals AS latest
              WHERE latest.quality_check_id = qa.quality_check_id
          )
          AND qc.status = 'passed'
          AND qc.drying_output_id = NEW.drying_output_id
          AND batch.status = 'COMPLETED'
          AND batch.farm_id = NEW.farm_id
    ) INTO release_is_approved;

    IF NOT release_is_approved THEN
        RAISE EXCEPTION
            'Product Lot release requires the latest approved passing QC for this completed Drying Output';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS product_lots_require_approved_output ON product_lots;
CREATE TRIGGER product_lots_require_approved_output
    BEFORE INSERT OR UPDATE OF drying_output_id, release_approval_id, farm_id, status
    ON product_lots
    FOR EACH ROW
    EXECUTE FUNCTION enforce_product_lot_release();