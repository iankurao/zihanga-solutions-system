-- Phase One Step 17: notifications.
--
-- Notifications are created in the same transaction that opens or escalates
-- an operational alert.  In-app notifications are rows in `notifications`;
-- email is queued in `notification_outbox` and delivered later by a worker,
-- so a mail failure can never roll back or block an ERP transaction.

CREATE TABLE IF NOT EXISTS notification_preferences (
    user_id INTEGER PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    in_app_min_severity VARCHAR(10) NOT NULL DEFAULT 'warning'
        CHECK (in_app_min_severity IN ('info', 'warning', 'critical', 'off')),
    email_min_severity VARCHAR(10) NOT NULL DEFAULT 'critical'
        CHECK (email_min_severity IN ('info', 'warning', 'critical', 'off')),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notifications (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    alert_id BIGINT REFERENCES operational_alerts(id) ON DELETE CASCADE,
    kind VARCHAR(30) NOT NULL
        CHECK (kind IN ('alert_opened', 'alert_escalated', 'alert_reminder', 'test')),
    severity VARCHAR(10) NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
    title VARCHAR(200) NOT NULL,
    body TEXT NOT NULL,
    href VARCHAR(300),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    read_at TIMESTAMPTZ
);

-- A user is told once per alert event (opening, then each escalation level);
-- snooze reminders repeat by design.
CREATE UNIQUE INDEX IF NOT EXISTS uq_notifications_alert_event
    ON notifications(user_id, alert_id, kind, severity)
    WHERE alert_id IS NOT NULL AND kind IN ('alert_opened', 'alert_escalated');
CREATE INDEX IF NOT EXISTS idx_notifications_user_unread
    ON notifications(user_id, created_at DESC) WHERE read_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_notifications_user_time
    ON notifications(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS notification_outbox (
    id BIGSERIAL PRIMARY KEY,
    notification_id BIGINT REFERENCES notifications(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(user_id) ON DELETE CASCADE,
    channel VARCHAR(10) NOT NULL DEFAULT 'email' CHECK (channel = 'email'),
    recipient VARCHAR(200) NOT NULL,
    subject VARCHAR(250) NOT NULL,
    body TEXT NOT NULL,
    status VARCHAR(10) NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'SENT', 'FAILED')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_error VARCHAR(300),
    sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_notification_outbox_due
    ON notification_outbox(next_attempt_at) WHERE status = 'PENDING';
