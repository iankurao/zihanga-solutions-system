-- Phase One Step 16: operational alerts derived from ERP records.
--
-- Alerts are produced by rules over the transactional tables (see
-- _alert_candidates in app.py).  Each rule/entity pair has at most one active
-- alert, identified by alert_key; when the condition clears the alert is
-- resolved automatically and a later recurrence opens a new row, so history
-- is kept.  People acknowledge or snooze alerts; they never delete them.

CREATE TABLE IF NOT EXISTS operational_alerts (
    id BIGSERIAL PRIMARY KEY,
    alert_key VARCHAR(200) NOT NULL,
    rule VARCHAR(50) NOT NULL,
    severity VARCHAR(10) NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
    title VARCHAR(200) NOT NULL,
    message TEXT NOT NULL,
    entity_type VARCHAR(40) NOT NULL,
    entity_id BIGINT NOT NULL,
    entity_ref VARCHAR(60),
    href VARCHAR(300),
    farm_id INTEGER REFERENCES farms(id) ON DELETE RESTRICT,
    site_id INTEGER,
    facility_id INTEGER,
    status VARCHAR(15) NOT NULL DEFAULT 'OPEN'
        CHECK (status IN ('OPEN', 'ACKNOWLEDGED', 'SNOOZED', 'RESOLVED')),
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    first_detected_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_detected_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    acknowledged_at TIMESTAMPTZ,
    acknowledged_by VARCHAR(100),
    acknowledged_by_user_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    acknowledgement_note TEXT,
    snoozed_until TIMESTAMPTZ,
    resolved_at TIMESTAMPTZ,
    resolved_reason TEXT,
    CHECK (status <> 'SNOOZED' OR snoozed_until IS NOT NULL),
    CHECK (status <> 'RESOLVED' OR resolved_at IS NOT NULL)
);

-- One active alert per condition; resolved rows are history.
CREATE UNIQUE INDEX IF NOT EXISTS uq_operational_alerts_active_key
    ON operational_alerts(alert_key)
    WHERE status <> 'RESOLVED';
CREATE INDEX IF NOT EXISTS idx_operational_alerts_status_severity
    ON operational_alerts(status, severity);
CREATE INDEX IF NOT EXISTS idx_operational_alerts_entity
    ON operational_alerts(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_operational_alerts_farm
    ON operational_alerts(farm_id);

-- Minimum free stock per farm and product type for the low-stock rule.
CREATE TABLE IF NOT EXISTS inventory_alert_thresholds (
    id SERIAL PRIMARY KEY,
    farm_id INTEGER NOT NULL REFERENCES farms(id) ON DELETE RESTRICT,
    product_type VARCHAR(50) NOT NULL CHECK (length(trim(product_type)) > 0),
    minimum_kg NUMERIC(14, 3) NOT NULL CHECK (minimum_kg > 0),
    updated_by VARCHAR(100) NOT NULL,
    updated_by_user_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (farm_id, product_type)
);

-- Rule evaluation is throttled across requests and workers.
CREATE TABLE IF NOT EXISTS operational_alert_sync (
    id SMALLINT PRIMARY KEY CHECK (id = 1),
    last_run_at TIMESTAMPTZ
);
INSERT INTO operational_alert_sync (id, last_run_at) VALUES (1, NULL)
ON CONFLICT (id) DO NOTHING;
