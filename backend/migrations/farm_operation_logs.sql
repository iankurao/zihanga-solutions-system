-- Farm operation logs: hatchery, fly facility and waste-handling records get
-- the same organization > farm > site > facility ownership as the production
-- chain (backend/domains/farm_operations.py).
--
-- * New rows must name a farm, site and facility (CHECK ... NOT VALID: rows
--   recorded before this change stay valid as history without a location).
-- * Locations an administrator already mapped through
--   operational_location_links are copied onto the rows.
-- * Every change is written to the audit log.
-- Repeatable: safe to run on every start.

DO $$
DECLARE
    log_table TEXT;
BEGIN
    FOREACH log_table IN ARRAY ARRAY[
        'storage_records', 'processing_records', 'waste_monitoring',
        'hatchery_batches', 'hatchery_feeding', 'hatchery_monitoring',
        'hatchery_cleaning', 'hatchery_problems',
        'cage_monitoring', 'facility_maintenance', 'pupae_transition',
        'egg_collection', 'bait_preparation'
    ]
    LOOP
        CONTINUE WHEN to_regclass(log_table) IS NULL;

        EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS farm_id INTEGER REFERENCES farms(id) ON DELETE RESTRICT', log_table);
        EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS site_id INTEGER REFERENCES sites(id) ON DELETE RESTRICT', log_table);
        EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS facility_id INTEGER REFERENCES facilities(id) ON DELETE RESTRICT', log_table);
        EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS recorded_by_user_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL', log_table);
        EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON %I (facility_id)', log_table || '_facility_idx', log_table);
        EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON %I (farm_id)', log_table || '_farm_idx', log_table);

        -- Copy administrator mappings made before records carried a location.
        IF to_regclass('operational_location_links') IS NOT NULL THEN
            EXECUTE format(
                'UPDATE %I AS t SET farm_id = l.farm_id, site_id = l.site_id, facility_id = l.facility_id '
                'FROM operational_location_links AS l '
                'WHERE l.entity_table = %L AND l.entity_id = t.id AND t.facility_id IS NULL',
                log_table, log_table);
        END IF;

        -- A location is all three levels or none (history rows).
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = log_table || '_scope_complete') THEN
            EXECUTE format(
                'ALTER TABLE %I ADD CONSTRAINT %I CHECK ('
                '(farm_id IS NULL AND site_id IS NULL AND facility_id IS NULL) OR '
                '(farm_id IS NOT NULL AND site_id IS NOT NULL AND facility_id IS NOT NULL))',
                log_table, log_table || '_scope_complete');
        END IF;
        -- New records must have one; existing history rows are not re-checked.
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = log_table || '_scope_required') THEN
            EXECUTE format(
                'ALTER TABLE %I ADD CONSTRAINT %I CHECK (facility_id IS NOT NULL) NOT VALID',
                log_table, log_table || '_scope_required');
        END IF;

        IF to_regprocedure('audit_row_change()') IS NOT NULL THEN
            EXECUTE format('DROP TRIGGER IF EXISTS audit_row_change ON %I', log_table);
            EXECUTE format(
                'CREATE TRIGGER audit_row_change AFTER INSERT OR UPDATE OR DELETE ON %I '
                'FOR EACH ROW EXECUTE FUNCTION audit_row_change()', log_table);
        END IF;
    END LOOP;
END $$;

-- Hatchery batch numbers are assigned when the batch is saved (HAT-YYYY-00001).
CREATE SEQUENCE IF NOT EXISTS phase_one_hatchery_batch_seq;
