-- Phase One Step 12: Product Lot -> Inventory ledger.
--
-- Stock is never stored as an editable quantity.  It is the sum of posted
-- inventory_movements per product lot and inventory location:
--   balance(lot, location) = SUM(quantity WHERE to_location = location)
--                          - SUM(quantity WHERE from_location = location)
-- A transfer is a single row with both locations, so it can never be half
-- posted.  Additive and safe to run at every application startup.
--
-- Rows written by the earlier unvalidated endpoint have no locations.  They
-- stay readable for audit but contribute to no location balance, and the new
-- CHECK constraints are NOT VALID so they do not block startup.

CREATE TABLE IF NOT EXISTS inventory_locations (
    id SERIAL PRIMARY KEY,
    location_code VARCHAR(30) NOT NULL CHECK (length(trim(location_code)) > 0),
    name VARCHAR(100) NOT NULL CHECK (length(trim(name)) > 0),
    farm_id INTEGER NOT NULL REFERENCES farms(id) ON DELETE RESTRICT,
    site_id INTEGER NOT NULL,
    facility_id INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'inactive')),
    created_by_user_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (facility_id, location_code),
    FOREIGN KEY (site_id, farm_id) REFERENCES sites(id, farm_id) ON DELETE RESTRICT,
    FOREIGN KEY (facility_id, site_id) REFERENCES facilities(id, site_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_inventory_locations_scope
    ON inventory_locations(farm_id, site_id, facility_id);

ALTER TABLE inventory_movements
    ADD COLUMN IF NOT EXISTS farm_id INTEGER,
    ADD COLUMN IF NOT EXISTS from_location_id INTEGER,
    ADD COLUMN IF NOT EXISTS to_location_id INTEGER,
    ADD COLUMN IF NOT EXISTS unit VARCHAR(16),
    ADD COLUMN IF NOT EXISTS status VARCHAR(20),
    ADD COLUMN IF NOT EXISTS reason TEXT,
    ADD COLUMN IF NOT EXISTS reference_type VARCHAR(40),
    ADD COLUMN IF NOT EXISTS reference_id BIGINT,
    ADD COLUMN IF NOT EXISTS actor_user_id INTEGER,
    ADD COLUMN IF NOT EXISTS posted_at TIMESTAMPTZ;

ALTER TABLE inventory_movements
    ALTER COLUMN status SET DEFAULT 'posted';

DO $$
BEGIN
    BEGIN
        ALTER TABLE inventory_movements
            ADD CONSTRAINT inventory_movements_farm_fk
            FOREIGN KEY (farm_id) REFERENCES farms(id) ON DELETE RESTRICT;
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
    BEGIN
        ALTER TABLE inventory_movements
            ADD CONSTRAINT inventory_movements_from_location_fk
            FOREIGN KEY (from_location_id) REFERENCES inventory_locations(id)
            ON DELETE RESTRICT;
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
    BEGIN
        ALTER TABLE inventory_movements
            ADD CONSTRAINT inventory_movements_to_location_fk
            FOREIGN KEY (to_location_id) REFERENCES inventory_locations(id)
            ON DELETE RESTRICT;
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
    BEGIN
        ALTER TABLE inventory_movements
            ADD CONSTRAINT inventory_movements_actor_fk
            FOREIGN KEY (actor_user_id) REFERENCES users(user_id)
            ON DELETE SET NULL;
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
    BEGIN
        ALTER TABLE inventory_movements
            ADD CONSTRAINT inventory_movements_quantity_positive_check
            CHECK (quantity_kg > 0) NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
    BEGIN
        ALTER TABLE inventory_movements
            ADD CONSTRAINT inventory_movements_unit_check
            CHECK (unit IS NULL OR unit = 'kg') NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
    BEGIN
        ALTER TABLE inventory_movements
            ADD CONSTRAINT inventory_movements_status_check
            CHECK (status IS NULL OR status IN ('posted', 'void')) NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
    -- Every located (ledger) movement must use a known type with the
    -- matching source/destination combination.  Unlocated legacy rows are
    -- outside the ledger and exempt.
    BEGIN
        ALTER TABLE inventory_movements
            ADD CONSTRAINT inventory_movements_type_locations_check
            CHECK (
                (from_location_id IS NULL AND to_location_id IS NULL)
                OR (movement_type IN ('RECEIPT', 'ADJUSTMENT_IN')
                    AND from_location_id IS NULL AND to_location_id IS NOT NULL)
                OR (movement_type IN ('ADJUSTMENT_OUT', 'WASTAGE')
                    AND from_location_id IS NOT NULL AND to_location_id IS NULL)
                OR (movement_type = 'TRANSFER'
                    AND from_location_id IS NOT NULL AND to_location_id IS NOT NULL
                    AND from_location_id <> to_location_id)
            ) NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
    BEGIN
        ALTER TABLE inventory_movements
            ADD CONSTRAINT inventory_movements_ledger_fields_check
            CHECK (
                (from_location_id IS NULL AND to_location_id IS NULL)
                OR (farm_id IS NOT NULL AND unit = 'kg' AND status IS NOT NULL
                    AND product_lot_id IS NOT NULL)
            ) NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
END $$;

-- A Product Lot is received into stock exactly once.
CREATE UNIQUE INDEX IF NOT EXISTS uq_inventory_movements_one_receipt_per_lot
    ON inventory_movements(product_lot_id)
    WHERE movement_type = 'RECEIPT' AND status = 'posted';

CREATE INDEX IF NOT EXISTS idx_inventory_movements_lot_time
    ON inventory_movements(product_lot_id, occurred_at, id);
CREATE INDEX IF NOT EXISTS idx_inventory_movements_from_location
    ON inventory_movements(from_location_id) WHERE from_location_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_inventory_movements_to_location
    ON inventory_movements(to_location_id) WHERE to_location_id IS NOT NULL;
