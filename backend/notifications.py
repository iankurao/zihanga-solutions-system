"""Notifications for operational alerts: recipients, inbox, email outbox.

Notifications are written in the same database transaction that opens or
escalates an alert (``enqueue_alert_notifications``).  Email is only queued
there; ``deliver_pending`` sends it later outside any ERP transaction, so an
SMTP failure can never roll back or slow down operational work.
"""

import logging
import os
import smtplib
import threading
from email.mime.text import MIMEText

from backend import config
from backend.roles import COMMERCIAL_ALERT_ENTITIES, roles_with

logger = logging.getLogger(__name__)

SEVERITY_RANK = {'info': 0, 'warning': 1, 'critical': 2}
PREFERENCE_LEVELS = ('info', 'warning', 'critical', 'off')
DEFAULT_IN_APP_MIN = 'warning'
DEFAULT_EMAIL_MIN = 'critical'
EMAIL_MAX_ATTEMPTS = 5
RETRY_MINUTES = (1, 5, 15, 60)
CLAIM_LEASE_MINUTES = 10

KIND_PREFIX = {
    'alert_opened': 'New alert',
    'alert_escalated': 'Alert escalated',
    'alert_reminder': 'Snooze ended',
}


class EmailChannel:
    """SMTP delivery that raises on failure (unlike the legacy send_email)."""

    def __init__(self, host, port, username, password, sender=None, timeout=20):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.sender = sender or username
        self.timeout = timeout

    @classmethod
    def from_config(cls):
        return cls(
            config.EMAIL_HOST, config.EMAIL_PORT, config.EMAIL_HOST_USER,
            config.EMAIL_HOST_PASSWORD, os.getenv('EMAIL_FROM') or None,
        )

    @property
    def configured(self):
        return bool(self.host and self.username and self.password)

    def send(self, recipient, subject, body):
        message = MIMEText(body, 'plain', 'utf-8')
        message['From'] = self.sender
        message['To'] = recipient
        message['Subject'] = subject
        with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as server:
            server.starttls()
            server.login(self.username, self.password)
            server.sendmail(self.sender, [recipient], message.as_string())


# Replaced in tests; production reads SMTP settings from the environment.
channel_factory = EmailChannel.from_config
background_delivery_enabled = True



def severity_allows(threshold, severity):
    return threshold != 'off' and SEVERITY_RANK[severity] >= SEVERITY_RANK[threshold]


def public_link(href):
    base = (os.getenv('PUBLIC_BASE_URL') or '').rstrip('/')
    if not href:
        return base or ''
    return f'{base}{href}' if base else href


def alert_recipients(cursor, alert):
    """Active users who may see this alert, with their preferences.

    Facility-scoped alerts reach anyone with organization, farm, site or
    facility access to that location; farm-level (commercial and stock
    threshold) alerts need organization or farm access, and order/delivery
    alerts go only to roles that may see sales data.  Super admins always
    receive alerts; records without a farm reach super admins only.
    """
    farm_id, site_id, facility_id = alert.get('farm_id'), alert.get('site_id'), alert.get('facility_id')
    cursor.execute(
        """
        SELECT u.user_id, u.email, u.username,
               COALESCE(p.in_app_min_severity, %s) AS in_app_min,
               COALESCE(p.email_min_severity, %s) AS email_min
        FROM users AS u
        LEFT JOIN notification_preferences AS p ON p.user_id = u.user_id
        WHERE COALESCE(u.is_active, TRUE)
          AND (%s OR u.role = ANY(%s))
          AND (
              u.role = 'super_admin'
              OR (%s::int IS NOT NULL AND (
                  EXISTS (SELECT 1 FROM user_farm_access AS a
                          WHERE a.user_id = u.user_id AND a.farm_id = %s)
                  OR EXISTS (SELECT 1 FROM user_organization_access AS a
                             JOIN farms AS f ON f.organization_id = a.organization_id
                             WHERE a.user_id = u.user_id AND f.id = %s)
                  OR (%s::int IS NOT NULL AND EXISTS (
                          SELECT 1 FROM user_site_access AS a
                          WHERE a.user_id = u.user_id AND a.site_id = %s))
                  OR (%s::int IS NOT NULL AND EXISTS (
                          SELECT 1 FROM user_facility_access AS a
                          WHERE a.user_id = u.user_id AND a.facility_id = %s))
              ))
          )
        """,
        (DEFAULT_IN_APP_MIN, DEFAULT_EMAIL_MIN,
         alert.get('entity_type') not in COMMERCIAL_ALERT_ENTITIES, roles_with('sales.read'),
         farm_id, farm_id, farm_id,
         facility_id, site_id, facility_id, facility_id),
    )
    return cursor.fetchall()


def enqueue_alert_notifications(cursor, alert, kind, *, email_configured):
    """Create inbox rows (and queued emails) for one alert event.

    Returns the number of emails queued.  Runs inside the caller's
    transaction so notifications exist exactly when the alert change does.
    """
    severity = alert['severity']
    title = f"{KIND_PREFIX[kind]}: {alert['title']}"
    queued = 0
    for user in alert_recipients(cursor, alert):
        if not severity_allows(user['in_app_min'], severity):
            continue
        conflict = (
            "ON CONFLICT (user_id, alert_id, kind, severity) "
            "WHERE alert_id IS NOT NULL AND kind IN ('alert_opened', 'alert_escalated') "
            "DO NOTHING"
            if kind != 'alert_reminder' else ''
        )
        cursor.execute(
            f"""
            INSERT INTO notifications (user_id, alert_id, kind, severity, title, body, href)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            {conflict}
            RETURNING id
            """,
            (user['user_id'], alert['id'], kind, severity, title[:200], alert['message'], alert.get('href')),
        )
        created = cursor.fetchone()
        if not created:
            continue  # already told about this event
        if email_configured and user['email'] and severity_allows(user['email_min'], severity):
            cursor.execute(
                """
                INSERT INTO notification_outbox (notification_id, user_id, recipient, subject, body)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    created['id'], user['user_id'], user['email'],
                    f"[Zehunger {severity.upper()}] {title}"[:250],
                    _email_body(alert, kind),
                ),
            )
            queued += 1
    return queued


def _email_body(alert, kind):
    link = public_link(alert.get('href'))
    lines = [
        f"{KIND_PREFIX[kind]} ({alert['severity']})",
        '',
        alert['title'],
        alert['message'],
    ]
    if link:
        lines += ['', f'Open: {link}']
    lines += ['', 'You can change which alerts you receive by email on the Alerts page.']
    return '\n'.join(lines)


def _safe_error(exc):
    """Short, credential-free description of a delivery failure."""
    text = f'{type(exc).__name__}: {exc}'.replace('\n', ' ')
    for secret in (config.EMAIL_HOST_PASSWORD,):
        if secret:
            text = text.replace(secret, '***')
    return text[:300]


def deliver_pending(db, *, limit=50, channel=None):
    """Send due emails one at a time; safe to run from several workers."""
    channel = channel or channel_factory()
    stats = {'sent': 0, 'retry': 0, 'failed': 0, 'skipped_unconfigured': False, 'skipped_demo': False}
    from backend.demo import is_demo_database

    if is_demo_database(db):
        # Demo records name invented customers and staff: never email from them.
        stats['skipped_demo'] = True
        return stats
    if not channel.configured:
        stats['skipped_unconfigured'] = True
        return stats
    for _ in range(limit):
        # Claim one message with a lease so no other worker sends it while
        # SMTP runs outside the transaction.
        with db.transaction() as cursor:
            cursor.execute(
                f"""
                UPDATE notification_outbox
                SET attempts = attempts + 1,
                    next_attempt_at = now() + interval '{CLAIM_LEASE_MINUTES} minutes'
                WHERE id = (
                    SELECT id FROM notification_outbox
                    WHERE status = 'PENDING' AND next_attempt_at <= now()
                    ORDER BY next_attempt_at, id
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                RETURNING id, recipient, subject, body, attempts
                """
            )
            message = cursor.fetchone()
        if not message:
            break
        try:
            channel.send(message['recipient'], message['subject'], message['body'])
        except Exception as exc:  # noqa: BLE001 - any delivery failure is retried
            final = message['attempts'] >= EMAIL_MAX_ATTEMPTS
            delay = RETRY_MINUTES[min(message['attempts'] - 1, len(RETRY_MINUTES) - 1)]
            with db.transaction() as cursor:
                cursor.execute(
                    """
                    UPDATE notification_outbox
                    SET status = %s, last_error = %s,
                        next_attempt_at = now() + make_interval(mins => %s)
                    WHERE id = %s
                    """,
                    ('FAILED' if final else 'PENDING', _safe_error(exc), delay, message['id']),
                )
            stats['failed' if final else 'retry'] += 1
            logger.warning('Email notification %s failed (attempt %s)', message['id'], message['attempts'])
            continue
        with db.transaction() as cursor:
            cursor.execute(
                "UPDATE notification_outbox SET status = 'SENT', sent_at = now(), last_error = NULL WHERE id = %s",
                (message['id'],),
            )
        stats['sent'] += 1
    return stats


_delivery_lock = threading.Lock()


def kick_background_delivery(db):
    """Send due emails on a daemon thread unless one is already running."""
    if not background_delivery_enabled or not _delivery_lock.acquire(blocking=False):
        return False

    def run():
        try:
            deliver_pending(db)
        except Exception:  # noqa: BLE001 - never crash the web worker
            logger.exception('Background email delivery failed')
        finally:
            _delivery_lock.release()

    threading.Thread(target=run, name='notification-delivery', daemon=True).start()
    return True
