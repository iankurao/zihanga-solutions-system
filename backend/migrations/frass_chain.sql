-- Frass (larvae droppings and spent substrate) sold as fertiliser.
--
-- harvest --(frass separated, kg)--> frass lot (FRS-) --curing checks-->
-- cured weight --> quality check (FQC-) + decision --> product lot
-- (product_type 'frass_fertilizer') received into stock --> customer orders.
--
-- A frass product lot needs the latest quality check of its frass lot to
-- have passed and been approved, enforced here like the larvae release.
-- Repeatable: safe to run on every start.

CREATE SEQUENCE IF NOT EXISTS phase_one_frass_lot_seq;
CREATE SEQUENCE IF NOT EXISTS phase_one_frass_check_seq;

CREATE TABLE IF NOT EXISTS frass_lots (
    id BIGSERIAL PRIMARY KEY,
    business_id VARCHAR(30) NOT NULL UNIQUE,
    harvest_id BIGINT NOT NULL UNIQUE REFERENCES harvests(id) ON DELETE RESTRICT,
    production_batch_id BIGINT NOT NULL REFERENCES production_batches(id) ON DELETE RESTRICT,
    farm_id INTEGER NOT NULL REFERENCES farms(id) ON DELETE RESTRICT,
    site_id INTEGER NOT NULL REFERENCES sites(id) ON DELETE RESTRICT,
    facility_id INTEGER NOT NULL REFERENCES facilities(id) ON DELETE RESTRICT,
    quantity_kg NUMERIC(14, 3) NOT NULL CHECK (quantity_kg > 0),
    cured_kg NUMERIC(14, 3) CHECK (cured_kg > 0 AND cured_kg <= quantity_kg),
    status VARCHAR(20) NOT NULL DEFAULT 'CURING'
        CHECK (status IN ('CURING', 'QC_PENDING', 'APPROVED', 'REJECTED', 'RELEASED')),
    curing_started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    cured_at TIMESTAMPTZ,
    notes TEXT,
    recorded_by VARCHAR(100),
    recorded_by_user_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ((status = 'CURING') = (cured_kg IS NULL))
);
CREATE INDEX IF NOT EXISTS idx_frass_lots_scope ON frass_lots(farm_id, site_id, facility_id);
CREATE INDEX IF NOT EXISTS idx_frass_lots_batch ON frass_lots(production_batch_id);

CREATE TABLE IF NOT EXISTS frass_curing_checks (
    id BIGSERIAL PRIMARY KEY,
    frass_lot_id BIGINT NOT NULL REFERENCES frass_lots(id) ON DELETE RESTRICT,
    checked_at TIMESTAMPTZ NOT NULL,
    temperature_c NUMERIC(5, 2) CHECK (temperature_c BETWEEN -10 AND 90),
    moisture_percent NUMERIC(5, 2) CHECK (moisture_percent BETWEEN 0 AND 100),
    notes TEXT,
    recorded_by VARCHAR(100),
    recorded_by_user_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (temperature_c IS NOT NULL OR moisture_percent IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_frass_curing_checks_lot ON frass_curing_checks(frass_lot_id);

CREATE TABLE IF NOT EXISTS frass_quality_checks (
    id BIGSERIAL PRIMARY KEY,
    check_code VARCHAR(30) NOT NULL UNIQUE,
    frass_lot_id BIGINT NOT NULL REFERENCES frass_lots(id) ON DELETE RESTRICT,
    status VARCHAR(10) NOT NULL CHECK (status IN ('passed', 'failed')),
    moisture_percent NUMERIC(5, 2) CHECK (moisture_percent BETWEEN 0 AND 100),
    maturity VARCHAR(20) NOT NULL CHECK (maturity IN ('mature', 'immature')),
    contaminants TEXT,
    notes TEXT,
    inspector VARCHAR(100) NOT NULL,
    inspector_user_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    decision VARCHAR(10) CHECK (decision IN ('approved', 'rejected')),
    rationale TEXT,
    approver VARCHAR(100),
    approver_user_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    decided_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (decision IS DISTINCT FROM 'approved' OR status = 'passed'),
    CHECK ((decision IS NULL) = (decided_at IS NULL))
);
CREATE INDEX IF NOT EXISTS idx_frass_quality_checks_lot ON frass_quality_checks(frass_lot_id);

-- Product lots made from frass.
ALTER TABLE product_lots
    ADD COLUMN IF NOT EXISTS frass_lot_id BIGINT,
    ADD COLUMN IF NOT EXISTS frass_quality_check_id BIGINT;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'product_lots_frass_lot_fk') THEN
        ALTER TABLE product_lots ADD CONSTRAINT product_lots_frass_lot_fk
            FOREIGN KEY (frass_lot_id) REFERENCES frass_lots(id) ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'product_lots_frass_check_fk') THEN
        ALTER TABLE product_lots ADD CONSTRAINT product_lots_frass_check_fk
            FOREIGN KEY (frass_quality_check_id) REFERENCES frass_quality_checks(id) ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'product_lots_one_source') THEN
        ALTER TABLE product_lots ADD CONSTRAINT product_lots_one_source
            CHECK (drying_output_id IS NULL OR frass_lot_id IS NULL);
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_product_lots_frass_lot
    ON product_lots(frass_lot_id) WHERE frass_lot_id IS NOT NULL;

CREATE OR REPLACE FUNCTION enforce_frass_product_lot_release()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.frass_lot_id IS NULL THEN
        RETURN NEW;
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM frass_quality_checks AS fq
        JOIN frass_lots AS fl ON fl.id = fq.frass_lot_id
        WHERE fq.id = NEW.frass_quality_check_id
          AND fq.frass_lot_id = NEW.frass_lot_id
          AND fq.status = 'passed'
          AND fq.decision = 'approved'
          AND fq.id = (SELECT MAX(latest.id) FROM frass_quality_checks AS latest
                       WHERE latest.frass_lot_id = NEW.frass_lot_id)
          AND fl.farm_id = NEW.farm_id
          AND LOWER(COALESCE(NEW.status, '')) = 'available'
    ) THEN
        RAISE EXCEPTION 'A frass Product Lot requires the latest passed and approved frass quality check';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS product_lots_require_approved_frass ON product_lots;
CREATE TRIGGER product_lots_require_approved_frass
    BEFORE INSERT OR UPDATE OF frass_lot_id, frass_quality_check_id, farm_id, status
    ON product_lots
    FOR EACH ROW
    EXECUTE FUNCTION enforce_frass_product_lot_release();

-- Where every product lot comes from, whatever its source: its farm, site
-- and facility, and the source record (drying batch or frass lot).
CREATE OR REPLACE VIEW product_lot_origins AS
SELECT pl.id AS product_lot_id, 'drying_batch'::text AS source_type, db.id AS source_id,
       COALESCE(db.business_id, db.batch_code) AS business_id, db.batch_code,
       db.farm_id, db.site_id, db.facility_id
FROM product_lots AS pl
JOIN drying_outputs AS o ON o.id = pl.drying_output_id
JOIN drying_batches AS db ON db.id = o.drying_batch_id
UNION ALL
SELECT pl.id, 'frass_lot'::text, fl.id, fl.business_id, fl.business_id,
       fl.farm_id, fl.site_id, fl.facility_id
FROM product_lots AS pl
JOIN frass_lots AS fl ON fl.id = pl.frass_lot_id;

-- Every change is in the audit log.
DO $$
DECLARE
    audited TEXT;
BEGIN
    IF to_regprocedure('audit_row_change()') IS NULL THEN
        RETURN;
    END IF;
    FOREACH audited IN ARRAY ARRAY['frass_lots', 'frass_curing_checks', 'frass_quality_checks'] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS audit_row_change ON %I', audited);
        EXECUTE format('CREATE TRIGGER audit_row_change AFTER INSERT OR UPDATE OR DELETE ON %I '
                       'FOR EACH ROW EXECUTE FUNCTION audit_row_change()', audited);
    END LOOP;
END $$;
