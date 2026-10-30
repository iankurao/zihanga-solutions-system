"""Live operations dashboard."""

from datetime import date, timedelta
from decimal import Decimal
from flask import jsonify, render_template, request
from flask_login import login_required

from backend.core.web import app, db, logger
from backend.core.http import _jsonable, _parse_positive_integer
from backend.core.scope import _farm_visibility_clause
from backend.domains.inventory import (
    ALLOCATION_STATE_CTE,
    INVENTORY_LEDGER_CTE,
    PRODUCT_LOT_RELEASABLE_SQL,
)
from backend.domains.alerts import _alert_visibility_clause, _sync_alerts
from backend.domains.reports import KG_SQL, _ReportQuery


# ---- Operations dashboard ------------------------------------------------------
#
# Live figures from the Phase One tables for the caller's locations.  Same
# scoping as the reports: operations follow facility access; order and
# delivery figures need farm-level access and are omitted (restricted)
# otherwise.  Nothing here is stored or estimated.

DASHBOARD_PERIODS = (7, 30, 90)
ACTIVE_BATCH_STATUSES = ('ACTIVE', 'MONITORING', 'READY_FOR_HARVEST', 'PAUSED', 'HEALTH_ALERT')


def _dashboard_value(cursor, sql, params):
    cursor.execute(sql, params)
    row = cursor.fetchone()
    return row[next(iter(row))] if row else None


def _dashboard_buckets(start, end, weekly):
    buckets = []
    day = start - timedelta(days=start.weekday()) if weekly else start
    step = timedelta(days=7 if weekly else 1)
    while day <= end:
        buckets.append(day)
        day += step
    return buckets


def _dashboard_series(cursor, sql, params, buckets, weekly):
    unit = 'week' if weekly else 'day'
    cursor.execute(sql.format(unit=unit), params)
    values = {row['bucket']: Decimal(str(row['kg'])) for row in cursor.fetchall()}
    return [values.get(bucket, Decimal('0')) for bucket in buckets]


def _operations_dashboard(cursor, days, farm_id, facility_id):
    today = date.today()
    start = today - timedelta(days=days - 1)
    filters = {
        'date_from': start, 'date_to': today, 'farm_id': farm_id, 'facility_id': facility_id,
        'status': None, 'product_type': None,
    }

    def scoped(alias, date_column=None, commercial=False):
        q = _ReportQuery(filters, scope_alias=alias, commercial=commercial)
        if date_column:
            q.dates(date_column)
        return q

    # Production pipeline (current state, not period bound).
    q = scoped('pb')
    q.add("UPPER(pb.status) NOT IN ('COMPLETED', 'CANCELLED')")
    cursor.execute(
        f"SELECT UPPER(pb.status) AS status, COUNT(*) AS n FROM production_batches AS pb {q.where} GROUP BY 1",
        q.params,
    )
    pipeline = {row['status']: row['n'] for row in cursor.fetchall()}

    q = scoped('sb')
    available_sql = (
        "COALESCE(sb.output_weight_kg, sb.total_input_weight_kg, 0) - COALESCE(("
        "SELECT SUM(quantity_issued) FROM production_batch_inputs WHERE substrate_batch_id = sb.id), 0)"
    )
    cursor.execute(
        f"""
        SELECT COALESCE(SUM(GREATEST({available_sql}, 0)), 0) AS kg,
               COUNT(*) FILTER (WHERE {available_sql} > 0) AS batches
        FROM substrate_batches AS sb {q.where}
        """,
        q.params,
    )
    substrate = cursor.fetchone()

    q = scoped('db')
    cursor.execute(
        f"""
        SELECT COUNT(*) FILTER (WHERE UPPER(db.status) IN ('DRAFT', 'RECEIVED', 'DRYING')) AS drying,
               COUNT(*) FILTER (WHERE UPPER(db.status) = 'QC_PENDING') AS qc_pending
        FROM drying_batches AS db {q.where} AND db.farm_id IS NOT NULL
        """,
        q.params,
    )
    drying_now = cursor.fetchone()

    # Stock (current): free = QC-released on hand minus outstanding reservations.
    q = scoped('il')
    cursor.execute(
        f"""
        WITH {INVENTORY_LEDGER_CTE}, {ALLOCATION_STATE_CTE},
        balances AS (SELECT product_lot_id, location_id, SUM(delta) AS kg FROM ledger GROUP BY 1, 2)
        SELECT COALESCE(SUM(b.kg), 0) AS on_hand,
               COALESCE(SUM(b.kg) FILTER (WHERE NOT {PRODUCT_LOT_RELEASABLE_SQL}), 0) AS blocked,
               COALESCE(SUM((SELECT COALESCE(SUM(s.quantity_kg - s.released_kg - s.dispatched_kg), 0)
                             FROM allocation_state AS s
                             WHERE s.product_lot_id = b.product_lot_id AND s.location_id = b.location_id)), 0)
                   AS reserved
        FROM balances AS b
        JOIN product_lots AS pl ON pl.id = b.product_lot_id
        JOIN inventory_locations AS il ON il.id = b.location_id
        {q.where}
        """,
        q.params,
    )
    stock = cursor.fetchone()
    on_hand, blocked, reserved = (Decimal(str(stock[k])) for k in ('on_hand', 'blocked', 'reserved'))

    # Material flow over the period, in kg.
    flow = []
    for label, sql, alias, column in (
        ('Waste received', 'SELECT COALESCE(SUM(wl.quantity), 0) FROM waste_lots AS wl {w}', 'wl', 'wl.collection_date'),
        ('Substrate prepared', 'SELECT COALESCE(SUM(sb.total_input_weight_kg), 0) FROM substrate_batches AS sb {w}',
         'sb', 'sb.preparation_date'),
        ('Harvested (wet)', "SELECT COALESCE(SUM(pe.quantity), 0) FROM production_events AS pe {w} "
                            "AND pe.event_type = 'harvest' AND pe.status = 'recorded'", 'pe', 'pe.occurred_at'),
        ('Dried', f"SELECT COALESCE(SUM({KG_SQL.format(unit='o.unit', qty='o.quantity')}), 0) "
                  "FROM drying_outputs AS o JOIN drying_batches AS db ON db.id = o.drying_batch_id {w}",
         'db', 'o.output_date'),
        ('Released to stock', 'SELECT COALESCE(SUM(pl.quantity_kg), 0) FROM product_lots AS pl '
                              'JOIN product_lot_origins AS batch ON batch.product_lot_id = pl.id {w}',
         'batch', 'pl.production_date'),
        ('Dispatched', "SELECT COALESCE(SUM(im.quantity_kg), 0) FROM inventory_movements AS im "
                       "JOIN inventory_locations AS il ON il.id = im.from_location_id {w} "
                       "AND im.movement_type = 'DISPATCH' AND im.status = 'posted'", 'il', 'im.occurred_at'),
    ):
        q = scoped(alias, column)
        flow.append({'stage': label, 'kg': Decimal(str(_dashboard_value(cursor, sql.format(w=q.where), q.params)))})

    # Output trend: daily up to a month, weekly beyond.
    weekly = days > 31
    buckets = _dashboard_buckets(start, today, weekly)
    trend = {'buckets': buckets, 'weekly': weekly, 'series': []}
    for label, sql, alias, column in (
        ('Harvested (wet)', "SELECT date_trunc('{unit}', pe.occurred_at)::date AS bucket, SUM(pe.quantity) AS kg "
                            "FROM production_events AS pe {w} AND pe.event_type = 'harvest' "
                            "AND pe.status = 'recorded' GROUP BY 1", 'pe', 'pe.occurred_at'),
        ('Dried', f"SELECT date_trunc('{{unit}}', o.output_date)::date AS bucket, "
                  f"SUM({KG_SQL.format(unit='o.unit', qty='o.quantity')}) AS kg "
                  "FROM drying_outputs AS o JOIN drying_batches AS db ON db.id = o.drying_batch_id {w} "
                  "GROUP BY 1", 'db', 'o.output_date'),
        ('Dispatched', "SELECT date_trunc('{unit}', im.occurred_at)::date AS bucket, SUM(im.quantity_kg) AS kg "
                       "FROM inventory_movements AS im JOIN inventory_locations AS il ON il.id = im.from_location_id "
                       "{w} AND im.movement_type = 'DISPATCH' AND im.status = 'posted' GROUP BY 1",
         'il', 'im.occurred_at'),
    ):
        q = scoped(alias, column)
        sql = sql.replace('{w}', q.where)
        trend['series'].append({
            'name': label,
            'values': _dashboard_series(cursor, sql, q.params, buckets, weekly),
        })

    # Commercial figures only for farm-level users.
    farms_visible, farms_params = _farm_visibility_clause('fm')
    cursor.execute(
        f"SELECT EXISTS (SELECT 1 FROM (SELECT id AS farm_id FROM farms) AS fm WHERE {farms_visible}) AS ok",
        farms_params,
    )
    commercial = None
    if cursor.fetchone()['ok']:
        q = scoped('o', commercial=True)
        cursor.execute(
            f"""
            WITH {ALLOCATION_STATE_CTE}
            SELECT COUNT(*) FILTER (WHERE o.status = 'OPEN') AS open_orders,
                   COUNT(*) FILTER (WHERE o.status = 'OPEN' AND o.requested_delivery_date < CURRENT_DATE)
                       AS overdue_orders,
                   COALESCE(SUM(CASE WHEN o.status = 'OPEN' THEN
                       (SELECT SUM(l.quantity_kg) FROM customer_order_lines AS l WHERE l.order_id = o.id)
                       - COALESCE((SELECT SUM(s.dispatched_kg) FROM allocation_state AS s
                                   JOIN customer_order_lines AS l ON l.id = s.order_line_id
                                   WHERE l.order_id = o.id), 0) END), 0) AS outstanding_kg
            FROM customer_orders AS o {q.where}
            """,
            q.params,
        )
        commercial = dict(cursor.fetchone())
        commercial['in_transit'] = _dashboard_value(
            cursor,
            f"""
            SELECT COUNT(*) FROM customer_deliveries AS d
            JOIN customer_orders AS o ON o.id = d.order_id
            {q.where} AND d.status = 'DISPATCHED'
            """,
            q.params,
        )
        q = scoped('o', 'd.delivered_at', commercial=True)
        commercial['delivered_kg'] = _dashboard_value(
            cursor,
            f"""
            SELECT COALESCE(SUM(dl.quantity_kg), 0) FROM customer_delivery_lines AS dl
            JOIN customer_deliveries AS d ON d.id = dl.delivery_id
            JOIN customer_orders AS o ON o.id = d.order_id
            {q.where} AND d.status = 'DELIVERED'
            """,
            q.params,
        )

    # Alerts needing attention (visible to this user).
    visibility, params = _alert_visibility_clause()
    alert_filters = [visibility, "a.status = 'OPEN'"]
    alert_params = list(params)
    if farm_id:
        alert_filters.append('a.farm_id = %s')
        alert_params.append(farm_id)
    if facility_id:
        alert_filters.append('(a.facility_id = %s OR a.facility_id IS NULL)')
        alert_params.append(facility_id)
    cursor.execute(
        f"""
        SELECT a.id, a.severity, a.title, a.message, a.href, a.first_detected_at
        FROM operational_alerts AS a
        WHERE {' AND '.join(alert_filters)}
        ORDER BY CASE a.severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
                 a.first_detected_at DESC
        """,
        alert_params,
    )
    open_alerts = [dict(row) for row in cursor.fetchall()]

    harvested = next(item['kg'] for item in flow if item['stage'] == 'Harvested (wet)')
    dried = next(item['kg'] for item in flow if item['stage'] == 'Dried')
    return _jsonable({
        'period': {'days': days, 'from': start, 'to': today},
        'kpis': {
            'active_batches': sum(pipeline.get(s, 0) for s in ACTIVE_BATCH_STATUSES),
            'planned_batches': pipeline.get('PLANNED', 0),
            'ready_for_harvest': pipeline.get('READY_FOR_HARVEST', 0),
            'health_alert_batches': pipeline.get('HEALTH_ALERT', 0),
            'substrate_available_kg': substrate['kg'],
            'substrate_batches_available': substrate['batches'],
            'harvested_kg': harvested,
            'dried_kg': dried,
            'drying_in_progress': drying_now['drying'],
            'qc_pending': drying_now['qc_pending'],
            'released_kg': next(item['kg'] for item in flow if item['stage'] == 'Released to stock'),
            'stock_on_hand_kg': on_hand,
            'stock_available_kg': on_hand - blocked - reserved,
            'stock_reserved_kg': reserved,
            'stock_blocked_kg': blocked,
        },
        'pipeline': [
            {'status': status, 'count': pipeline.get(status, 0)}
            for status in ('PLANNED', 'ACTIVE', 'MONITORING', 'READY_FOR_HARVEST', 'HARVESTED',
                           'PAUSED', 'HEALTH_ALERT')
        ],
        'flow': flow,
        'trend': trend,
        'commercial': commercial,
        'alerts': {
            'critical': sum(1 for a in open_alerts if a['severity'] == 'critical'),
            'warning': sum(1 for a in open_alerts if a['severity'] == 'warning'),
            'info': sum(1 for a in open_alerts if a['severity'] == 'info'),
            'top': open_alerts[:6],
        },
    })


@app.route('/api/dashboard', methods=['GET'])
@login_required
def operations_dashboard_data():
    try:
        days = int(request.args.get('days', 30))
    except ValueError:
        days = 0
    if days not in DASHBOARD_PERIODS:
        return jsonify({'success': False, 'message': 'days must be 7, 30 or 90'}), 400
    try:
        farm_id = _parse_positive_integer(request.args['farm_id'], 'farm_id') \
            if request.args.get('farm_id') else None
        facility_id = _parse_positive_integer(request.args['facility_id'], 'facility_id') \
            if request.args.get('facility_id') else None
        try:
            _sync_alerts()
        except Exception:
            logger.exception('Alert sync failed while loading the dashboard')
        with db.transaction() as cursor:
            data = _operations_dashboard(cursor, days, farm_id, facility_id)
        return jsonify({'success': True, 'data': data}), 200
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception:
        logger.exception('Error building operations dashboard')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/operations')
@login_required
def operations_page():
    return render_template('operations.html')
