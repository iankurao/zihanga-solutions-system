-- Phase One Step 4 remainder: canonical farm/site/facility scope for Waste Lots
-- and Substrate Batches, plus protection of commercial history.
--
-- Additive and safe to run at every application startup.  Existing rows keep
-- NULL scope: the legacy farm_site text cannot prove ownership, so it is never
-- used to backfill these columns.  A super admin assigns legacy lots explicitly.

ALTER TABLE waste_lots
    ADD COLUMN IF NOT EXISTS farm_id INTEGER,
    ADD COLUMN IF NOT EXISTS site_id INTEGER,
    ADD COLUMN IF NOT EXISTS facility_id INTEGER,
    ADD COLUMN IF NOT EXISTS location_assigned_by_user_id INTEGER,
    ADD COLUMN IF NOT EXISTS location_assigned_at TIMESTAMPTZ;

DO $$
BEGIN
    BEGIN
        ALTER TABLE waste_lots
            ADD CONSTRAINT waste_lots_farm_fk
            FOREIGN KEY (farm_id) REFERENCES farms(id) ON DELETE RESTRICT;
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
    BEGIN
        ALTER TABLE waste_lots
            ADD CONSTRAINT waste_lots_site_farm_fk
            FOREIGN KEY (site_id, farm_id) REFERENCES sites(id, farm_id)
            ON DELETE RESTRICT;
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
    BEGIN
        ALTER TABLE waste_lots
            ADD CONSTRAINT waste_lots_facility_site_fk
            FOREIGN KEY (facility_id, site_id) REFERENCES facilities(id, site_id)
            ON DELETE RESTRICT;
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
    BEGIN
        ALTER TABLE waste_lots
            ADD CONSTRAINT waste_lots_location_assigned_by_fk
            FOREIGN KEY (location_assigned_by_user_id) REFERENCES users(user_id)
            ON DELETE SET NULL;
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
    -- Scope is all-or-nothing.  NOT VALID enforces the rule for new and
    -- updated rows without failing startup on unexpected historical data.
    BEGIN
        ALTER TABLE waste_lots
            ADD CONSTRAINT waste_lots_scope_complete_check
            CHECK (
                (farm_id IS NULL AND site_id IS NULL AND facility_id IS NULL)
                OR (farm_id IS NOT NULL AND site_id IS NOT NULL AND facility_id IS NOT NULL)
            ) NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
    BEGIN
        ALTER TABLE substrate_batches
            ADD CONSTRAINT substrate_batches_scope_complete_check
            CHECK (
                (farm_id IS NULL AND site_id IS NULL AND facility_id IS NULL)
                OR (farm_id IS NOT NULL AND site_id IS NOT NULL AND facility_id IS NOT NULL)
            ) NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
END $$;

CREATE INDEX IF NOT EXISTS idx_waste_lots_scope
    ON waste_lots(farm_id, site_id, facility_id);
CREATE INDEX IF NOT EXISTS idx_substrate_batches_scope
    ON substrate_batches(farm_id, site_id, facility_id);
