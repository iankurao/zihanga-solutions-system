-- Step 23: append-only audit log.
-- Repeatable: safe to run on every start.
--
-- Row changes on the tables listed at the bottom are recorded by trigger, so
-- no code path can skip them. The web app tells the database who is acting by
-- setting app.audit_actor (JSON) for each transaction; rows written without it
-- (migrations, scheduled jobs) are attributed to "system".

CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    -- No foreign key: entries must outlive deleted users and records.
    actor_user_id INTEGER,
    actor_username VARCHAR(100),
    actor_role VARCHAR(30),
    action VARCHAR(80) NOT NULL,
    entity_type VARCHAR(60) NOT NULL,
    entity_id VARCHAR(80),
    entity_ref VARCHAR(100),
    farm_id INTEGER,
    facility_id INTEGER,
    old_value JSONB,
    new_value JSONB,
    reason TEXT,
    ip_address VARCHAR(64),
    user_agent VARCHAR(200),
    request_id VARCHAR(40),
    request_path VARCHAR(200)
);

CREATE INDEX IF NOT EXISTS idx_audit_log_time ON audit_log (occurred_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_entity ON audit_log (entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_ref ON audit_log (entity_ref);
CREATE INDEX IF NOT EXISTS idx_audit_log_actor ON audit_log (actor_user_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log (action, occurred_at DESC);

-- Entries cannot be edited, deleted or truncated through normal SQL.
CREATE OR REPLACE FUNCTION audit_log_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_log entries cannot be changed or deleted'
        USING ERRCODE = 'insufficient_privilege';
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_log_no_change ON audit_log;
CREATE TRIGGER audit_log_no_change
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();

DROP TRIGGER IF EXISTS audit_log_no_truncate ON audit_log;
CREATE TRIGGER audit_log_no_truncate
    BEFORE TRUNCATE ON audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION audit_log_immutable();

-- Records one row change. Trigger arguments name columns whose values must
-- never be copied (e.g. password_hash); a change to them shows as "[changed]".
CREATE OR REPLACE FUNCTION audit_row_change() RETURNS trigger AS $$
DECLARE
    actor JSONB := NULLIF(current_setting('app.audit_actor', true), '')::jsonb;
    secret TEXT[] := COALESCE(TG_ARGV, ARRAY[]::TEXT[]);
    -- Bookkeeping columns that change without a meaningful edit.
    noise TEXT[] := ARRAY['updated_at', 'last_login'];
    old_row JSONB;
    new_row JSONB;
    old_diff JSONB := '{}'::jsonb;
    new_diff JSONB := '{}'::jsonb;
    subject JSONB;
    column_name TEXT;
    verb TEXT;
BEGIN
    IF TG_OP <> 'INSERT' THEN old_row := to_jsonb(OLD); END IF;
    IF TG_OP <> 'DELETE' THEN new_row := to_jsonb(NEW); END IF;
    subject := COALESCE(new_row, old_row);

    IF TG_OP = 'UPDATE' THEN
        FOR column_name IN SELECT jsonb_object_keys(new_row) LOOP
            CONTINUE WHEN column_name = ANY(noise);
            IF old_row -> column_name IS DISTINCT FROM new_row -> column_name THEN
                IF column_name = ANY(secret) THEN
                    old_diff := old_diff || jsonb_build_object(column_name, '[hidden]');
                    new_diff := new_diff || jsonb_build_object(column_name, '[changed]');
                ELSE
                    old_diff := old_diff || jsonb_build_object(column_name, old_row -> column_name);
                    new_diff := new_diff || jsonb_build_object(column_name, new_row -> column_name);
                END IF;
            END IF;
        END LOOP;
        IF new_diff = '{}'::jsonb THEN
            RETURN NULL;
        END IF;
        verb := CASE WHEN new_diff ? 'status' THEN 'status_changed' ELSE 'updated' END;
        old_row := old_diff;
        new_row := new_diff;
    ELSE
        verb := CASE TG_OP WHEN 'INSERT' THEN 'created' ELSE 'deleted' END;
        old_row := old_row - secret;
        new_row := new_row - secret;
    END IF;

    INSERT INTO audit_log (
        actor_user_id, actor_username, actor_role, action, entity_type,
        entity_id, entity_ref, farm_id, facility_id, old_value, new_value,
        reason, ip_address, user_agent, request_id, request_path
    ) VALUES (
        (actor ->> 'user_id')::INTEGER,
        COALESCE(actor ->> 'username', CASE WHEN actor IS NULL THEN 'system' ELSE 'anonymous' END),
        actor ->> 'role',
        TG_TABLE_NAME || '.' || verb,
        TG_TABLE_NAME,
        COALESCE(subject ->> 'id', subject ->> 'user_id'),
        LEFT(COALESCE(subject ->> 'business_id', subject ->> 'unit_code', subject ->> 'username',
                      subject ->> 'code', subject ->> 'name'), 100),
        CASE WHEN subject ->> 'farm_id' ~ '^[0-9]+$' THEN (subject ->> 'farm_id')::INTEGER END,
        CASE WHEN subject ->> 'facility_id' ~ '^[0-9]+$' THEN (subject ->> 'facility_id')::INTEGER END,
        old_row,
        new_row,
        COALESCE(subject ->> 'reason', subject ->> 'cancel_reason'),
        actor ->> 'ip',
        actor ->> 'ua',
        actor ->> 'request_id',
        actor ->> 'path'
    );
    RETURN NULL;
END
$$ LANGUAGE plpgsql;

-- Tables whose changes are audited. Missing tables are skipped so this also
-- runs on partially upgraded databases.
DO $$
DECLARE
    audited RECORD;
BEGIN
    FOR audited IN
        SELECT * FROM (VALUES
            ('users', 'password_hash'),
            ('user_organization_access', NULL), ('user_farm_access', NULL),
            ('user_site_access', NULL), ('user_facility_access', NULL),
            ('organizations', NULL), ('farms', NULL), ('sites', NULL), ('facilities', NULL),
            ('production_units', NULL), ('production_batch_units', NULL),
            ('waste_lots', NULL), ('substrate_batches', NULL),
            ('production_batches', NULL), ('harvests', NULL),
            ('drying_batches', NULL), ('drying_outputs', NULL),
            ('quality_checks', NULL), ('quality_approvals', NULL), ('product_lots', NULL),
            ('inventory_locations', NULL), ('inventory_movements', NULL),
            ('inventory_alert_thresholds', NULL),
            ('customers', NULL), ('customer_orders', NULL), ('customer_order_lines', NULL),
            ('order_allocations', NULL), ('customer_deliveries', NULL)
        ) AS t(table_name, secret_column)
    LOOP
        CONTINUE WHEN to_regclass(audited.table_name) IS NULL;
        EXECUTE format('DROP TRIGGER IF EXISTS audit_row_change ON %I', audited.table_name);
        IF audited.secret_column IS NULL THEN
            EXECUTE format(
                'CREATE TRIGGER audit_row_change AFTER INSERT OR UPDATE OR DELETE ON %I '
                'FOR EACH ROW EXECUTE FUNCTION audit_row_change()', audited.table_name);
        ELSE
            EXECUTE format(
                'CREATE TRIGGER audit_row_change AFTER INSERT OR UPDATE OR DELETE ON %I '
                'FOR EACH ROW EXECUTE FUNCTION audit_row_change(%L)',
                audited.table_name, audited.secret_column);
        END IF;
    END LOOP;
END $$;
