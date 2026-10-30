"""Operational alerts, thresholds and the in-app notification API."""

import json

from datetime import datetime, timedelta, timezone
from flask import render_template, request
from flask_login import current_user, login_required

from backend import notifications
from backend.roles import COMMERCIAL_ALERT_ENTITIES
from backend.core.web import app, db, logger
from backend.core.http import (
    InventoryConflictError,
    ProductionEventPermissionError,
    RecordNotFoundError,
    _alert_response,
    _jsonable,
    _kg_text,
    _optional_text,
    _parse_chain_quantity,
    _parse_positive_integer,
    _production_actor,
    normalize_keys,
)
from backend.core.security import _can, requires, super_admin_required
from backend.core.scope import _farm_visibility_clause, _scope_visibility_clause
from backend.domains.inventory import (
    ALLOCATION_STATE_CTE,
    INVENTORY_LEDGER_CTE,
    PRODUCT_LOT_RELEASABLE_SQL,
)


# ---- Operational alerts ----------------------------------------------------
#
# Every alert is derived from transactional records by a rule below.  Rules
# only read data; _sync_alerts turns their candidates into stored alerts so
# people can acknowledge or snooze them, and resolves alerts whose condition
# no longer holds.  Thresholds are deliberately few and documented here.

ALERT_SEVERITY_RANK = {'info': 0, 'warning': 1, 'critical': 2}
ALERT_SYNC_INTERVAL = timedelta(seconds=60)
ALERT_FORCE_INTERVAL = timedelta(seconds=10)
HARVEST_DUE_SOON = timedelta(days=3)       # info before the expected harvest
LATE_ESCALATION_DAYS = 3                    # warning becomes critical after this
QC_PENDING_LIMIT = timedelta(hours=24)      # QC should be decided within a day
DELIVERY_CONFIRM_LIMIT = timedelta(hours=48)
ALERT_MAX_SNOOZE_HOURS = 14 * 24


def _alert(rule, severity, title, message, entity_type, entity_id, *, ref=None,
           href=None, farm_id=None, site_id=None, facility_id=None, details=None):
    return {
        'alert_key': f'{rule}:{entity_type}:{entity_id}',
        'rule': rule, 'severity': severity, 'title': title, 'message': message,
        'entity_type': entity_type, 'entity_id': entity_id, 'entity_ref': ref,
        'href': href, 'farm_id': farm_id, 'site_id': site_id,
        'facility_id': facility_id, 'details': details or {},
    }


def _days(value):
    return f"{value} day{'s' if value != 1 else ''}"


def _alert_candidates(cursor):
    """Evaluate every rule against current data; returns {alert_key: alert}."""
    found = []
    now = datetime.now(timezone.utc)

    # Production batches: harvest overdue / due soon (no harvest recorded yet).
    cursor.execute(
        """
        SELECT pb.id, pb.business_id, UPPER(pb.status) AS status,
               pb.farm_id, pb.site_id, pb.facility_id, pb.expected_harvest_at
        FROM production_batches AS pb
        WHERE pb.expected_harvest_at IS NOT NULL
          AND UPPER(pb.status) NOT IN ('HARVESTED', 'COMPLETED', 'CANCELLED')
          AND pb.expected_harvest_at < now() + %s
          AND NOT EXISTS (
              SELECT 1 FROM production_events AS pe
              WHERE pe.production_batch_id = pb.id
                AND pe.event_type = 'harvest' AND pe.status = 'recorded'
          )
        """,
        (HARVEST_DUE_SOON,),
    )
    for row in cursor.fetchall():
        scope = dict(farm_id=row['farm_id'], site_id=row['site_id'], facility_id=row['facility_id'])
        href = f"/batch-360?ref={row['business_id']}"
        expected = row['expected_harvest_at']
        if expected < now:
            late = (now - expected).days
            found.append(_alert(
                'harvest_overdue', 'critical' if late >= LATE_ESCALATION_DAYS else 'warning',
                f"Harvest overdue · {row['business_id']}",
                f"Expected {expected:%d %b %Y}; no harvest recorded"
                + (f" ({_days(late)} late)" if late else '') + f". Status {row['status']}.",
                'production_batch', row['id'], ref=row['business_id'], href=href,
                details={'expected_harvest_at': expected.isoformat()}, **scope,
            ))
        else:
            found.append(_alert(
                'harvest_due', 'info', f"Harvest due soon · {row['business_id']}",
                f"Expected harvest {expected:%d %b %Y}. Status {row['status']}.",
                'production_batch', row['id'], ref=row['business_id'], href=href,
                details={'expected_harvest_at': expected.isoformat()}, **scope,
            ))

    # Production batches flagged HEALTH_ALERT.
    cursor.execute(
        """
        SELECT id, business_id, farm_id, site_id, facility_id
        FROM production_batches WHERE UPPER(status) = 'HEALTH_ALERT'
        """
    )
    for row in cursor.fetchall():
        found.append(_alert(
            'batch_health_alert', 'critical', f"Batch in health alert · {row['business_id']}",
            'The batch status is HEALTH_ALERT. Record the intervention and return it to production.',
            'production_batch', row['id'], ref=row['business_id'],
            href=f"/batch-360?ref={row['business_id']}",
            farm_id=row['farm_id'], site_id=row['site_id'], facility_id=row['facility_id'],
        ))

    # Open health issues that are severe or past their follow-up date.
    cursor.execute(
        """
        SELECT pe.id, pe.event_code, pb.id AS batch_id, pb.business_id,
               pe.farm_id, pe.site_id, pe.facility_id,
               he.severity, he.status, he.observed_issue, he.follow_up_date
        FROM health_events AS he
        JOIN production_events AS pe ON pe.id = he.production_event_id
        JOIN production_batches AS pb ON pb.id = pe.production_batch_id
        WHERE pe.status = 'recorded' AND he.status IN ('open', 'follow_up')
          AND UPPER(pb.status) NOT IN ('COMPLETED', 'CANCELLED')
          AND (he.severity IN ('high', 'critical')
               OR (he.follow_up_date IS NOT NULL AND he.follow_up_date < CURRENT_DATE))
        """
    )
    for row in cursor.fetchall():
        overdue = row['follow_up_date'] is not None and row['follow_up_date'] < now.date()
        found.append(_alert(
            'health_issue_open', 'critical' if row['severity'] == 'critical' else 'warning',
            f"Health issue open · {row['business_id']}",
            f"{row['severity'].title()} severity: {row['observed_issue']}"
            + (f". Follow-up was due {row['follow_up_date']:%d %b %Y}." if overdue else '.'),
            'production_event', row['id'], ref=row['event_code'],
            href=f"/batch-360?ref={row['business_id']}",
            farm_id=row['farm_id'], site_id=row['site_id'], facility_id=row['facility_id'],
            details={'production_batch_id': row['batch_id']},
        ))

    # Drying batches awaiting QC: failed/rejected, or pending too long.
    cursor.execute(
        """
        SELECT db.id, COALESCE(db.business_id, db.batch_code, db.batch_id) AS ref,
               db.farm_id, db.site_id, db.facility_id,
               COALESCE((
                   SELECT MAX(h.changed_at) FROM drying_batch_status_history AS h
                   WHERE h.drying_batch_id = db.id AND h.new_status = 'QC_PENDING'
               ), db.updated_at) AS pending_since,
               EXISTS (
                   SELECT 1 FROM drying_outputs AS o
                   WHERE o.drying_batch_id = db.id AND (
                       (SELECT qc.status FROM quality_checks AS qc
                         WHERE qc.drying_output_id = o.id ORDER BY qc.id DESC LIMIT 1) = 'failed'
                       OR (SELECT qa.decision FROM quality_approvals AS qa
                           JOIN quality_checks AS qc ON qc.id = qa.quality_check_id
                           WHERE qc.drying_output_id = o.id ORDER BY qa.id DESC LIMIT 1) = 'rejected'
                   )
               ) OR (
                   SELECT qc.status FROM quality_checks AS qc
                   WHERE qc.drying_batch_id = db.id AND qc.drying_output_id IS NULL
                   ORDER BY qc.id DESC LIMIT 1
               ) = 'failed' AS failed
        FROM drying_batches AS db
        WHERE UPPER(db.status) = 'QC_PENDING'
        """
    )
    for row in cursor.fetchall():
        scope = dict(farm_id=row['farm_id'], site_id=row['site_id'], facility_id=row['facility_id'])
        href = f"/traceability?ref={row['ref']}&type=drying_batch"
        if row['failed']:
            found.append(_alert(
                'qc_failed', 'critical', f"QC failed · {row['ref']}",
                'The latest quality check failed or was rejected. Decide whether to rework or dispose of the output.',
                'drying_batch', row['id'], ref=row['ref'], href=href, **scope,
            ))
        elif row['pending_since'] and now - row['pending_since'] > QC_PENDING_LIMIT:
            hours = int((now - row['pending_since']).total_seconds() // 3600)
            found.append(_alert(
                'qc_pending', 'warning', f"QC decision pending · {row['ref']}",
                f'Waiting for a QC decision for {hours} hours.',
                'drying_batch', row['id'], ref=row['ref'], href=href, **scope,
            ))

    # Stock on hand from lots whose QC release is no longer valid.
    cursor.execute(
        f"""
        WITH {INVENTORY_LEDGER_CTE}
        SELECT pl.id, pl.business_id, pl.farm_id, batch.site_id, batch.facility_id,
               SUM(ledger.delta) AS on_hand_kg
        FROM ledger
        JOIN product_lots AS pl ON pl.id = ledger.product_lot_id
        JOIN product_lot_origins AS batch ON batch.product_lot_id = pl.id
        WHERE NOT {PRODUCT_LOT_RELEASABLE_SQL}
        GROUP BY pl.id, batch.site_id, batch.facility_id
        HAVING SUM(ledger.delta) > 0
        """
    )
    for row in cursor.fetchall():
        found.append(_alert(
            'quarantined_stock', 'critical', f"Blocked stock on hand · {row['business_id']}",
            f"{_kg_text(row['on_hand_kg'])} is in stock but its QC release was revoked. "
            'It cannot be moved or dispatched; write it off or re-approve it.',
            'product_lot', row['id'], ref=row['business_id'],
            href=f"/product-lot?ref={row['business_id']}",
            farm_id=row['farm_id'], site_id=row['site_id'], facility_id=row['facility_id'],
        ))

    # Free QC-released stock below the farm's configured minimum.
    cursor.execute(
        f"""
        WITH {INVENTORY_LEDGER_CTE}, {ALLOCATION_STATE_CTE},
        on_hand AS (
            SELECT pl.farm_id, LOWER(pl.product_type) AS product, SUM(ledger.delta) AS kg
            FROM ledger JOIN product_lots AS pl ON pl.id = ledger.product_lot_id
            WHERE {PRODUCT_LOT_RELEASABLE_SQL}
            GROUP BY 1, 2
        ),
        reserved AS (
            SELECT pl.farm_id, LOWER(pl.product_type) AS product,
                   SUM(s.quantity_kg - s.released_kg - s.dispatched_kg) AS kg
            FROM allocation_state AS s JOIN product_lots AS pl ON pl.id = s.product_lot_id
            WHERE {PRODUCT_LOT_RELEASABLE_SQL}
            GROUP BY 1, 2
        )
        SELECT t.id, t.farm_id, t.product_type, t.minimum_kg, f.name AS farm_name,
               COALESCE(o.kg, 0) - COALESCE(r.kg, 0) AS free_kg
        FROM inventory_alert_thresholds AS t
        JOIN farms AS f ON f.id = t.farm_id
        LEFT JOIN on_hand AS o ON o.farm_id = t.farm_id AND o.product = LOWER(t.product_type)
        LEFT JOIN reserved AS r ON r.farm_id = t.farm_id AND r.product = LOWER(t.product_type)
        WHERE COALESCE(o.kg, 0) - COALESCE(r.kg, 0) < t.minimum_kg
        """
    )
    for row in cursor.fetchall():
        found.append(_alert(
            'low_stock', 'critical' if row['free_kg'] <= 0 else 'warning',
            f"Low stock · {row['product_type']} at {row['farm_name']}",
            f"{_kg_text(max(row['free_kg'], 0))} free against a minimum of {_kg_text(row['minimum_kg'])}.",
            'inventory_threshold', row['id'], ref=row['product_type'], href='/product-lot',
            farm_id=row['farm_id'],
            details={'free_kg': str(row['free_kg']), 'minimum_kg': str(row['minimum_kg'])},
        ))

    # Customer orders past their requested delivery date.
    cursor.execute(
        """
        SELECT o.id, o.business_id, o.farm_id, o.requested_delivery_date,
               c.name AS customer_name, CURRENT_DATE - o.requested_delivery_date AS days_late
        FROM customer_orders AS o
        JOIN customers AS c ON c.id = o.customer_id
        WHERE o.status = 'OPEN' AND o.requested_delivery_date < CURRENT_DATE
        """
    )
    for row in cursor.fetchall():
        found.append(_alert(
            'order_overdue', 'critical' if row['days_late'] >= LATE_ESCALATION_DAYS else 'warning',
            f"Order overdue · {row['business_id']}",
            f"{row['customer_name']} requested delivery by {row['requested_delivery_date']:%d %b %Y} "
            f"({_days(row['days_late'])} ago) and the order is not fully dispatched.",
            'customer_order', row['id'], ref=row['business_id'],
            href=f"/orders?ref={row['business_id']}", farm_id=row['farm_id'],
        ))

    # Dispatched deliveries never confirmed as received.
    cursor.execute(
        """
        SELECT d.id, d.business_id, d.dispatched_at, o.business_id AS order_ref,
               o.farm_id, c.name AS customer_name
        FROM customer_deliveries AS d
        JOIN customer_orders AS o ON o.id = d.order_id
        JOIN customers AS c ON c.id = o.customer_id
        WHERE d.status = 'DISPATCHED' AND d.dispatched_at < now() - %s
        """,
        (DELIVERY_CONFIRM_LIMIT,),
    )
    for row in cursor.fetchall():
        found.append(_alert(
            'delivery_unconfirmed', 'warning', f"Delivery not confirmed · {row['business_id']}",
            f"Dispatched to {row['customer_name']} on {row['dispatched_at']:%d %b %Y} "
            'and not yet confirmed as received.',
            'customer_delivery', row['id'], ref=row['business_id'],
            href=f"/orders?ref={row['order_ref']}", farm_id=row['farm_id'],
        ))

    return {item['alert_key']: item for item in found}


def _sync_alerts(*, force=False):
    """Reconcile stored alerts with the rules and notify people.

    Returns True if the rules ran.  Notifications are written in the same
    transaction as the alert changes; queued email is sent afterwards.
    """
    ran = _sync_alerts_transaction(force=force)
    if ran:
        notifications.kick_background_delivery(db)
    return ran


def _sync_alerts_transaction(*, force=False):
    email_configured = notifications.channel_factory().configured
    with db.transaction() as cursor:
        cursor.execute(
            "SELECT pg_try_advisory_xact_lock(hashtext('operational_alert_sync')) AS locked"
        )
        if not cursor.fetchone()['locked']:
            return False  # another request is already syncing
        cursor.execute(
            "SELECT last_run_at, now() AS now FROM operational_alert_sync WHERE id = 1"
        )
        state = cursor.fetchone()
        if state['last_run_at'] is not None:
            elapsed = state['now'] - state['last_run_at']
            if elapsed < (ALERT_FORCE_INTERVAL if force else ALERT_SYNC_INTERVAL):
                return False
        candidates = _alert_candidates(cursor)
        cursor.execute(
            "SELECT * FROM operational_alerts WHERE status <> 'RESOLVED' FOR UPDATE"
        )
        active = {row['alert_key']: dict(row) for row in cursor.fetchall()}
        for key, alert in candidates.items():
            existing = active.pop(key, None)
            payload = (
                alert['severity'], alert['title'], alert['message'], alert['entity_ref'],
                alert['href'], alert['farm_id'], alert['site_id'], alert['facility_id'],
                json.dumps(alert['details'], default=str),
            )
            if existing is None:
                cursor.execute(
                    """
                    INSERT INTO operational_alerts (
                        severity, title, message, entity_ref, href, farm_id, site_id,
                        facility_id, details, alert_key, rule, entity_type, entity_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    payload + (key, alert['rule'], alert['entity_type'], alert['entity_id']),
                )
                notifications.enqueue_alert_notifications(
                    cursor, dict(cursor.fetchone()), 'alert_opened',
                    email_configured=email_configured,
                )
                continue
            status = existing['status']
            snoozed_until = existing['snoozed_until']
            snooze_ended = status == 'SNOOZED' and snoozed_until <= state['now']
            if snooze_ended:
                status = 'OPEN'
            escalated = ALERT_SEVERITY_RANK[alert['severity']] > ALERT_SEVERITY_RANK[existing['severity']]
            if escalated and status in ('ACKNOWLEDGED', 'SNOOZED'):
                status = 'OPEN'  # a worse condition needs fresh attention
            if status == 'OPEN':
                snoozed_until = None
            cursor.execute(
                """
                UPDATE operational_alerts
                SET severity = %s, title = %s, message = %s, entity_ref = %s, href = %s,
                    farm_id = %s, site_id = %s, facility_id = %s, details = %s::jsonb,
                    status = %s, snoozed_until = %s, last_detected_at = now()
                WHERE id = %s
                """,
                payload + (status, snoozed_until, existing['id']),
            )
            if escalated or snooze_ended:
                notifications.enqueue_alert_notifications(
                    cursor, {**existing, **alert, 'id': existing['id'], 'status': status},
                    'alert_escalated' if escalated else 'alert_reminder',
                    email_configured=email_configured,
                )
        for existing in active.values():
            cursor.execute(
                """
                UPDATE operational_alerts
                SET status = 'RESOLVED', resolved_at = now(),
                    resolved_reason = 'Condition cleared', snoozed_until = NULL
                WHERE id = %s
                """,
                (existing['id'],),
            )
        cursor.execute("UPDATE operational_alert_sync SET last_run_at = now() WHERE id = 1")
        return True


def _alert_visibility_clause():
    """Facility-scoped alerts follow location access; farm-level ones need farm
    access, and alerts about orders or deliveries also need sales access."""
    scope_sql, scope_params = _scope_visibility_clause('a')
    farm_sql, farm_params = _farm_visibility_clause('a', permission=None)
    commercial_ok = _can('sales.read')
    return (
        f"""((a.facility_id IS NOT NULL AND {scope_sql})
             OR (a.facility_id IS NULL AND {farm_sql}))
            AND (%s OR a.entity_type <> ALL(%s))""",
        (*scope_params, *farm_params, commercial_ok, list(COMMERCIAL_ALERT_ENTITIES)),
    )


def _alert_counts(visibility, params):
    row = db.fetch_one(
        f"""
        SELECT COUNT(*) FILTER (WHERE a.status = 'OPEN') AS open,
               COUNT(*) FILTER (WHERE a.status = 'OPEN' AND a.severity = 'critical') AS critical,
               COUNT(*) FILTER (WHERE a.status = 'OPEN' AND a.severity = 'warning') AS warning,
               COUNT(*) FILTER (WHERE a.status = 'OPEN' AND a.severity = 'info') AS info,
               COUNT(*) FILTER (WHERE a.status = 'ACKNOWLEDGED') AS acknowledged,
               COUNT(*) FILTER (WHERE a.status = 'SNOOZED') AS snoozed
        FROM operational_alerts AS a
        WHERE a.status <> 'RESOLVED' AND {visibility}
        """,
        params,
    )
    return {key: int(value or 0) for key, value in row.items()}


@app.route('/api/alerts', methods=['GET'])
@login_required
def list_alerts():
    def handler():
        _sync_alerts()
        visibility, params = _alert_visibility_clause()
        filters = [visibility]
        filter_params = list(params)
        view = str(request.args.get('status') or 'active').lower()
        if view == 'active':
            filters.append("a.status <> 'RESOLVED'")
        elif view == 'resolved':
            filters.append("a.status = 'RESOLVED'")
        elif view != 'all':
            raise ValueError('status must be active, resolved or all')
        severity = str(request.args.get('severity') or '').lower()
        if severity:
            if severity not in ALERT_SEVERITY_RANK:
                raise ValueError('severity must be info, warning or critical')
            filters.append('a.severity = %s')
            filter_params.append(severity)
        for field in ('farm_id', 'entity_id'):
            if request.args.get(field) not in (None, ''):
                filters.append(f'a.{field} = %s')
                filter_params.append(_parse_positive_integer(request.args[field], field))
        if request.args.get('entity_type'):
            filters.append('a.entity_type = %s')
            filter_params.append(str(request.args['entity_type'])[:40])
        rows = db.fetch_all(
            f"""
            SELECT a.id, a.rule, a.severity, a.title, a.message, a.entity_type,
                   a.entity_id, a.entity_ref, a.href, a.farm_id, a.status, a.details,
                   a.first_detected_at, a.last_detected_at, a.acknowledged_at,
                   a.acknowledged_by, a.acknowledgement_note, a.snoozed_until,
                   a.resolved_at, a.resolved_reason, f.name AS farm_name,
                   fa.name AS facility_name
            FROM operational_alerts AS a
            LEFT JOIN farms AS f ON f.id = a.farm_id
            LEFT JOIN facilities AS fa ON fa.id = a.facility_id
            WHERE {' AND '.join(filters)}
            ORDER BY (a.status = 'OPEN') DESC,
                     CASE a.severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
                     a.first_detected_at DESC
            LIMIT 500
            """,
            tuple(filter_params),
        )
        return {'data': _jsonable(rows), 'counts': _alert_counts(visibility, params)}
    return _alert_response(handler)


@app.route('/api/alerts/summary', methods=['GET'])
@login_required
def alert_summary():
    def handler():
        _sync_alerts()
        visibility, params = _alert_visibility_clause()
        return {'counts': _alert_counts(visibility, params)}
    return _alert_response(handler)


@app.route('/api/alerts/refresh', methods=['POST'])
@login_required
def refresh_alerts():
    def handler():
        ran = _sync_alerts(force=True)
        visibility, params = _alert_visibility_clause()
        return {'refreshed': ran, 'counts': _alert_counts(visibility, params)}
    return _alert_response(handler)


def _visible_alert(cursor, alert_id):
    visibility, params = _alert_visibility_clause()
    cursor.execute(
        f"SELECT a.* FROM operational_alerts AS a WHERE a.id = %s AND {visibility} FOR UPDATE",
        (alert_id, *params),
    )
    alert = cursor.fetchone()
    if not alert:
        raise RecordNotFoundError('Alert not found')
    return dict(alert)


def _acknowledge_alert(alert_id, data):
    note = _optional_text(data, 'note', 500)
    actor, actor_user_id = _production_actor(data)
    with db.transaction() as cursor:
        alert = _visible_alert(cursor, alert_id)
        if alert['status'] not in ('OPEN', 'SNOOZED'):
            raise InventoryConflictError(f"This alert is already {alert['status'].lower()}")
        cursor.execute(
            """
            UPDATE operational_alerts
            SET status = 'ACKNOWLEDGED', acknowledged_at = now(), acknowledged_by = %s,
                acknowledged_by_user_id = %s, acknowledgement_note = %s, snoozed_until = NULL
            WHERE id = %s
            RETURNING id, status, acknowledged_at, acknowledged_by, acknowledgement_note
            """,
            (actor, actor_user_id, note, alert_id),
        )
        return {'data': _jsonable(dict(cursor.fetchone()))}


def _snooze_alert(alert_id, data):
    try:
        hours = int(data.get('hours'))
    except (TypeError, ValueError):
        raise ValueError('hours must be a whole number')
    if not 1 <= hours <= ALERT_MAX_SNOOZE_HOURS:
        raise ValueError(f'hours must be between 1 and {ALERT_MAX_SNOOZE_HOURS}')
    with db.transaction() as cursor:
        alert = _visible_alert(cursor, alert_id)
        if alert['status'] == 'RESOLVED':
            raise InventoryConflictError('This alert is already resolved')
        cursor.execute(
            """
            UPDATE operational_alerts
            SET status = 'SNOOZED', snoozed_until = now() + make_interval(hours => %s)
            WHERE id = %s
            RETURNING id, status, snoozed_until
            """,
            (hours, alert_id),
        )
        return {'data': _jsonable(dict(cursor.fetchone()))}


@app.route('/api/alerts/<int:alert_id>/acknowledge', methods=['POST'])
@login_required
@requires('alerts.manage')
def acknowledge_alert(alert_id):
    return _alert_response(_acknowledge_alert, alert_id, normalize_keys(request.get_json() or {}))


@app.route('/api/alerts/<int:alert_id>/snooze', methods=['POST'])
@login_required
@requires('alerts.manage')
def snooze_alert(alert_id):
    return _alert_response(_snooze_alert, alert_id, normalize_keys(request.get_json() or {}))


@app.route('/api/alerts/thresholds', methods=['GET'])
@login_required
def list_alert_thresholds():
    def handler():
        visibility, params = _farm_visibility_clause('t', permission=None)
        rows = db.fetch_all(
            f"""
            SELECT t.id, t.farm_id, f.name AS farm_name, t.product_type, t.minimum_kg,
                   t.updated_by, t.updated_at
            FROM inventory_alert_thresholds AS t
            JOIN farms AS f ON f.id = t.farm_id
            WHERE {visibility}
            ORDER BY f.name, t.product_type
            """,
            params,
        )
        return {'data': _jsonable(rows)}
    return _alert_response(handler)


@app.route('/api/alerts/thresholds', methods=['PUT'])
@login_required
@super_admin_required
def set_alert_threshold():
    def handler(data):
        farm_id = _parse_positive_integer(data.get('farm_id'), 'farm_id')
        product_type = _optional_text(data, 'product_type', 50)
        if not product_type:
            raise ValueError('product_type is required')
        minimum = _parse_chain_quantity(data.get('minimum_kg'), 'minimum_kg')
        actor, actor_user_id = _production_actor(data)
        with db.transaction() as cursor:
            cursor.execute("SELECT 1 FROM farms WHERE id = %s", (farm_id,))
            if not cursor.fetchone():
                raise ValueError('Farm not found')
            cursor.execute(
                """
                INSERT INTO inventory_alert_thresholds
                    (farm_id, product_type, minimum_kg, updated_by, updated_by_user_id)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (farm_id, product_type) DO UPDATE SET
                    minimum_kg = EXCLUDED.minimum_kg, updated_by = EXCLUDED.updated_by,
                    updated_by_user_id = EXCLUDED.updated_by_user_id,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id, farm_id, product_type, minimum_kg
                """,
                (farm_id, product_type, minimum, actor, actor_user_id),
            )
            return {'data': _jsonable(dict(cursor.fetchone()))}
    return _alert_response(handler, normalize_keys(request.get_json() or {}))


@app.route('/api/alerts/thresholds/<int:threshold_id>', methods=['DELETE'])
@login_required
@super_admin_required
def delete_alert_threshold(threshold_id):
    def handler():
        with db.transaction() as cursor:
            cursor.execute(
                "DELETE FROM inventory_alert_thresholds WHERE id = %s RETURNING id", (threshold_id,)
            )
            if not cursor.fetchone():
                raise RecordNotFoundError('Threshold not found')
        return {'data': {'id': threshold_id}}
    return _alert_response(handler)


def _notification_user_id():
    if not getattr(current_user, 'is_authenticated', False):
        raise ProductionEventPermissionError('Sign in to see your notifications')
    return int(current_user.id)


@app.route('/api/notifications', methods=['GET'])
@login_required
def list_notifications():
    def handler():
        user_id = _notification_user_id()
        try:
            limit = min(max(int(request.args.get('limit', 20)), 1), 100)
        except ValueError:
            raise ValueError('limit must be a number')
        unread_only = request.args.get('unread') in ('1', 'true')
        rows = db.fetch_all(
            f"""
            SELECT n.id, n.kind, n.severity, n.title, n.body, n.href, n.created_at,
                   n.read_at, n.alert_id, a.status AS alert_status
            FROM notifications AS n
            LEFT JOIN operational_alerts AS a ON a.id = n.alert_id
            WHERE n.user_id = %s {'AND n.read_at IS NULL' if unread_only else ''}
            ORDER BY n.created_at DESC, n.id DESC
            LIMIT %s
            """,
            (user_id, limit),
        )
        unread = db.fetch_one(
            "SELECT COUNT(*) AS n FROM notifications WHERE user_id = %s AND read_at IS NULL",
            (user_id,),
        )['n']
        return {'data': _jsonable(rows), 'unread': unread}
    return _alert_response(handler)


@app.route('/api/notifications/unread-count', methods=['GET'])
@login_required
def unread_notification_count():
    def handler():
        user_id = _notification_user_id()
        try:
            _sync_alerts()  # throttled; keeps the bell current without a scheduler
        except Exception:
            logger.exception('Alert sync failed while counting notifications')
        row = db.fetch_one(
            """
            SELECT COUNT(*) AS unread,
                   COUNT(*) FILTER (WHERE severity = 'critical') AS critical
            FROM notifications WHERE user_id = %s AND read_at IS NULL
            """,
            (user_id,),
        )
        return {'unread': row['unread'], 'critical': row['critical']}
    return _alert_response(handler)


@app.route('/api/notifications/<int:notification_id>/read', methods=['POST'])
@login_required
def mark_notification_read(notification_id):
    def handler():
        row = db.execute_returning(
            """
            UPDATE notifications SET read_at = COALESCE(read_at, now())
            WHERE id = %s AND user_id = %s
            RETURNING id, read_at
            """,
            (notification_id, _notification_user_id()),
        )
        if not row:
            raise RecordNotFoundError('Notification not found')
        return {'data': _jsonable(dict(row))}
    return _alert_response(handler)


@app.route('/api/notifications/read-all', methods=['POST'])
@login_required
def mark_all_notifications_read():
    def handler():
        with db.transaction() as cursor:
            cursor.execute(
                "UPDATE notifications SET read_at = now() WHERE user_id = %s AND read_at IS NULL",
                (_notification_user_id(),),
            )
            return {'updated': cursor.rowcount}
    return _alert_response(handler)


@app.route('/api/notifications/preferences', methods=['GET'])
@login_required
def get_notification_preferences():
    def handler():
        user_id = _notification_user_id()
        row = db.fetch_one(
            "SELECT in_app_min_severity, email_min_severity FROM notification_preferences WHERE user_id = %s",
            (user_id,),
        ) or {}
        return {'data': {
            'in_app_min_severity': row.get('in_app_min_severity', notifications.DEFAULT_IN_APP_MIN),
            'email_min_severity': row.get('email_min_severity', notifications.DEFAULT_EMAIL_MIN),
            'email': getattr(current_user, 'email', None),
            'email_configured': notifications.channel_factory().configured,
        }}
    return _alert_response(handler)


@app.route('/api/notifications/preferences', methods=['PUT'])
@login_required
def set_notification_preferences():
    def handler(data):
        user_id = _notification_user_id()
        values = {}
        for field in ('in_app_min_severity', 'email_min_severity'):
            value = str(data.get(field) or '').strip().lower()
            if value not in notifications.PREFERENCE_LEVELS:
                raise ValueError(f"{field} must be one of: {', '.join(notifications.PREFERENCE_LEVELS)}")
            values[field] = value
        row = db.execute_returning(
            """
            INSERT INTO notification_preferences (user_id, in_app_min_severity, email_min_severity)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                in_app_min_severity = EXCLUDED.in_app_min_severity,
                email_min_severity = EXCLUDED.email_min_severity,
                updated_at = now()
            RETURNING in_app_min_severity, email_min_severity
            """,
            (user_id, values['in_app_min_severity'], values['email_min_severity']),
        )
        return {'data': dict(row)}
    return _alert_response(handler, normalize_keys(request.get_json() or {}))


@app.route('/api/notifications/email-status', methods=['GET'])
@login_required
@super_admin_required
def notification_email_status():
    def handler():
        counts = db.fetch_one(
            """
            SELECT COUNT(*) FILTER (WHERE status = 'PENDING') AS pending,
                   COUNT(*) FILTER (WHERE status = 'SENT') AS sent,
                   COUNT(*) FILTER (WHERE status = 'FAILED') AS failed,
                   MAX(sent_at) AS last_sent_at
            FROM notification_outbox
            """
        )
        failures = db.fetch_all(
            """
            SELECT id, recipient, subject, attempts, last_error, status, next_attempt_at
            FROM notification_outbox
            WHERE last_error IS NOT NULL AND status <> 'SENT'
            ORDER BY id DESC LIMIT 10
            """
        )
        return {'data': _jsonable({
            'configured': notifications.channel_factory().configured,
            **dict(counts),
            'recent_failures': failures,
        })}
    return _alert_response(handler)


@app.route('/api/notifications/test-email', methods=['POST'])
@login_required
@super_admin_required
def send_test_notification():
    def handler():
        user_id = _notification_user_id()
        if not notifications.channel_factory().configured:
            raise ValueError('Email is not configured: set EMAIL_HOST_USER and EMAIL_HOST_PASSWORD')
        with db.transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO notifications (user_id, kind, severity, title, body, href)
                VALUES (%s, 'test', 'info', 'Test notification',
                        'Email notifications are working for this account.', '/alerts')
                RETURNING id
                """,
                (user_id,),
            )
            notification_id = cursor.fetchone()['id']
            cursor.execute(
                """
                INSERT INTO notification_outbox (notification_id, user_id, recipient, subject, body)
                SELECT %s, user_id, email, '[Zehunger] Test notification',
                       'Email notifications are working for this account.'
                FROM users WHERE user_id = %s
                RETURNING id
                """,
                (notification_id, user_id),
            )
            outbox_id = cursor.fetchone()['id']
        notifications.kick_background_delivery(db)
        return {'data': {'outbox_id': outbox_id}}
    return _alert_response(handler)


@app.route('/alerts')
@login_required
def alerts_page():
    return render_template('alerts.html')
