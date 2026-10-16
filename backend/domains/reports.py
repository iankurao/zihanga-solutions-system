"""Operational reports and CSV export."""

import csv
import io

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from flask import Response, jsonify, request
from flask_login import login_required

from backend.config import CURRENCY
from backend.core.web import app, db, logger
from backend.core.http import _jsonable, _parse_positive_integer, _ratio_percent
from backend.core.security import _can
from backend.core.scope import _farm_visibility_clause, _scope_visibility_clause
from backend.domains.production import PRODUCTION_BATCH_STATUSES
from backend.domains.drying import DRYING_BATCH_STATUSES
from backend.domains.farm_operations import KINDS as FARM_LOG_KINDS
from backend.domains.inventory import (
    ALLOCATION_STATE_CTE,
    INVENTORY_LEDGER_CTE,
    PRODUCT_LOT_RELEASABLE_SQL,
)


# ---- Operational reports ------------------------------------------------------
#
# Each report reads the Phase One tables, is limited to the caller's
# locations (facility access for operations, farm access for commercial and
# farm-level figures) and returns typed columns so the browser can show it
# and export it to Excel/PDF; CSV is produced here.

REPORT_ROW_LIMIT = 5000
KG_SQL = "CASE WHEN {unit} = 'g' THEN {qty} / 1000 ELSE {qty} END"


class _ReportQuery:
    """Collects WHERE clauses and parameters for one report."""

    def __init__(self, filters, *, scope_alias, commercial=False):
        self.filters = filters
        self.clauses = []
        self.params = []
        visibility, params = (
            _farm_visibility_clause(scope_alias) if commercial
            else _scope_visibility_clause(scope_alias)
        )
        self.add(visibility, *params)
        if filters['farm_id']:
            self.add(f'{scope_alias}.farm_id = %s', filters['farm_id'])
        if filters['facility_id'] and not commercial:
            self.add(f'{scope_alias}.facility_id = %s', filters['facility_id'])

    def add(self, clause, *params):
        self.clauses.append(clause)
        self.params.extend(params)

    def dates(self, column):
        if self.filters['date_from']:
            self.add(f'({column})::date >= %s', self.filters['date_from'])
        if self.filters['date_to']:
            self.add(f'({column})::date <= %s', self.filters['date_to'])

    @property
    def where(self):
        return 'WHERE ' + ' AND '.join(self.clauses)


def _report_waste(cursor, f):
    q = _ReportQuery(f, scope_alias='wl')
    q.dates('wl.collection_date')
    if f['status']:
        q.add('UPPER(wl.status) = %s', f['status'])
    cursor.execute(
        f"""
        SELECT wl.collection_date AS date, wl.business_id AS waste_lot,
               wl.source_type, wl.source_name, wl.waste_type,
               wl.quantity AS received_kg, COALESCE(u.used, 0) AS used_kg,
               wl.quantity - COALESCE(u.used, 0) AS remaining_kg,
               wl.quality_status, UPPER(wl.status) AS status,
               f.name AS farm, fa.name AS facility
        FROM waste_lots AS wl
        LEFT JOIN (SELECT waste_lot_id, SUM(quantity_used) AS used
                   FROM substrate_batch_inputs GROUP BY waste_lot_id) AS u ON u.waste_lot_id = wl.id
        LEFT JOIN farms AS f ON f.id = wl.farm_id
        LEFT JOIN facilities AS fa ON fa.id = wl.facility_id
        {q.where}
        ORDER BY wl.collection_date DESC, wl.id DESC
        """,
        q.params,
    )
    return cursor.fetchall()


def _report_substrate(cursor, f):
    q = _ReportQuery(f, scope_alias='sb')
    q.dates('sb.preparation_date')
    cursor.execute(
        f"""
        SELECT sb.preparation_date AS date, sb.business_id AS substrate_batch,
               fa.name AS facility,
               (SELECT COUNT(*) FROM substrate_batch_inputs WHERE substrate_batch_id = sb.id) AS waste_lots,
               sb.total_input_weight_kg AS input_kg,
               COALESCE((SELECT SUM(quantity_issued) FROM production_batch_inputs
                         WHERE substrate_batch_id = sb.id), 0) AS issued_kg,
               COALESCE(sb.output_weight_kg, sb.total_input_weight_kg, 0) - COALESCE((
                   SELECT SUM(quantity_issued) FROM production_batch_inputs
                   WHERE substrate_batch_id = sb.id), 0) AS available_kg,
               sb.particle_size, sb.recorded_by
        FROM substrate_batches AS sb
        LEFT JOIN facilities AS fa ON fa.id = sb.facility_id
        {q.where}
        ORDER BY sb.preparation_date DESC, sb.id DESC
        """,
        q.params,
    )
    return cursor.fetchall()


def _report_production(cursor, f):
    q = _ReportQuery(f, scope_alias='pb')
    q.dates('pb.start_date')
    if f['status']:
        q.add('UPPER(pb.status) = %s', f['status'])
    cursor.execute(
        f"""
        SELECT pb.business_id AS production_batch, fa.name AS facility,
               pb.start_date, UPPER(pb.status) AS status, pb.current_stage AS stage,
               pb.expected_harvest_at::date AS expected_harvest,
               GREATEST(CURRENT_DATE - pb.start_date, 0) AS age_days,
               COALESCE(i.issued, 0) AS substrate_kg, COALESCE(h.harvested, 0) AS harvested_kg,
               CASE WHEN COALESCE(i.issued, 0) > 0 AND h.harvested IS NOT NULL
                    THEN ROUND(h.harvested / i.issued * 100, 1) END AS harvest_per_substrate_pct
        FROM production_batches AS pb
        LEFT JOIN facilities AS fa ON fa.id = pb.facility_id
        LEFT JOIN (SELECT production_batch_id, SUM(quantity_issued) AS issued
                   FROM production_batch_inputs GROUP BY 1) AS i ON i.production_batch_id = pb.id
        LEFT JOIN (SELECT production_batch_id, SUM(quantity) AS harvested
                   FROM production_events WHERE event_type = 'harvest' AND status = 'recorded'
                   GROUP BY 1) AS h ON h.production_batch_id = pb.id
        {q.where}
        ORDER BY pb.start_date DESC, pb.id DESC
        """,
        q.params,
    )
    return cursor.fetchall()


def _report_feeding(cursor, f):
    q = _ReportQuery(f, scope_alias='pe')
    q.add("pe.event_type = 'feeding' AND pe.status = 'recorded'")
    q.dates('pe.occurred_at')
    cursor.execute(
        f"""
        SELECT pe.occurred_at::date AS date, pb.business_id AS production_batch,
               fe.feed_type,
               {KG_SQL.format(unit='fe.offered_unit', qty='fe.quantity_offered')} AS offered_kg,
               {KG_SQL.format(unit='fe.consumed_unit', qty='fe.quantity_consumed')} AS consumed_kg,
               {KG_SQL.format(unit='fe.biomass_unit', qty='fe.larvae_biomass')} AS larvae_biomass_kg,
               fe.larvae_age_days, pe.actor AS recorded_by, fa.name AS facility
        FROM production_events AS pe
        JOIN feeding_events AS fe ON fe.production_event_id = pe.id
        JOIN production_batches AS pb ON pb.id = pe.production_batch_id
        LEFT JOIN facilities AS fa ON fa.id = pe.facility_id
        {q.where}
        ORDER BY pe.occurred_at DESC, pe.id DESC
        """,
        q.params,
    )
    return cursor.fetchall()


def _report_harvest(cursor, f):
    q = _ReportQuery(f, scope_alias='pe')
    q.add("pe.event_type = 'harvest' AND pe.status = 'recorded'")
    q.dates('pe.occurred_at')
    cursor.execute(
        f"""
        SELECT pe.occurred_at::date AS date, h.harvest_code AS harvest,
               pb.business_id AS production_batch, pe.quantity AS wet_kg,
               h.harvest_stage AS stage, h.operator, h.location, fa.name AS facility,
               COALESCE((SELECT SUM({KG_SQL.format(unit='di.unit', qty='di.quantity')})
                         FROM drying_inputs AS di WHERE di.harvest_id = h.id), 0) AS sent_to_drying_kg
        FROM harvests AS h
        JOIN production_events AS pe ON pe.id = h.production_event_id
        JOIN production_batches AS pb ON pb.id = pe.production_batch_id
        LEFT JOIN facilities AS fa ON fa.id = pe.facility_id
        {q.where}
        ORDER BY pe.occurred_at DESC, h.id DESC
        """,
        q.params,
    )
    return cursor.fetchall()


def _report_drying(cursor, f):
    q = _ReportQuery(f, scope_alias='db')
    q.add('db.farm_id IS NOT NULL')
    q.dates('db.drying_date')
    if f['status']:
        q.add('UPPER(db.status) = %s', f['status'])
    cursor.execute(
        f"""
        SELECT COALESCE(db.business_id, db.batch_code) AS drying_batch, db.drying_date AS date,
               db.drying_method AS method, UPPER(db.status) AS status, fa.name AS facility,
               COALESCE(i.wet, 0) AS wet_in_kg, COALESCE(o.dry, 0) AS dry_out_kg,
               CASE WHEN COALESCE(i.wet, 0) > 0 AND o.dry IS NOT NULL
                    THEN ROUND(o.dry / i.wet * 100, 1) END AS yield_pct,
               o.moisture AS moisture_pct,
               (SELECT string_agg(DISTINCT pb.business_id, ', ')
                FROM drying_inputs AS di
                JOIN harvests AS h ON h.id = di.harvest_id
                JOIN production_events AS pe ON pe.id = h.production_event_id
                JOIN production_batches AS pb ON pb.id = pe.production_batch_id
                WHERE di.drying_batch_id = db.id) AS production_batches
        FROM drying_batches AS db
        LEFT JOIN facilities AS fa ON fa.id = db.facility_id
        LEFT JOIN (SELECT drying_batch_id,
                          SUM({KG_SQL.format(unit='unit', qty='quantity')}) AS wet
                   FROM drying_inputs GROUP BY 1) AS i ON i.drying_batch_id = db.id
        LEFT JOIN (SELECT drying_batch_id,
                          SUM({KG_SQL.format(unit='unit', qty='quantity')}) AS dry,
                          (array_agg(moisture_percent ORDER BY line_no DESC))[1] AS moisture
                   FROM drying_outputs GROUP BY 1) AS o ON o.drying_batch_id = db.id
        {q.where}
        ORDER BY db.drying_date DESC, db.id DESC
        """,
        q.params,
    )
    return cursor.fetchall()


def _report_quality(cursor, f):
    q = _ReportQuery(f, scope_alias='db')
    q.dates('COALESCE(qc.checked_at, qc.created_at)')
    if f['status']:
        q.add('UPPER(qc.status) = %s', f['status'])
    cursor.execute(
        f"""
        SELECT COALESCE(qc.checked_at, qc.created_at)::date AS date, qc.check_code AS quality_check,
               COALESCE(db.business_id, db.batch_code) AS drying_batch,
               UPPER(qc.status) AS result, qc.moisture_percent AS moisture_pct, qc.inspector,
               UPPER(a.decision) AS decision, a.approver, a.decided_at::date AS decided_on,
               fa.name AS facility
        FROM quality_checks AS qc
        JOIN drying_batches AS db ON db.id = qc.drying_batch_id
        LEFT JOIN facilities AS fa ON fa.id = db.facility_id
        LEFT JOIN LATERAL (
            SELECT decision, approver, decided_at FROM quality_approvals
            WHERE quality_check_id = qc.id ORDER BY id DESC LIMIT 1
        ) AS a ON TRUE
        {q.where}
        ORDER BY qc.id DESC
        """,
        q.params,
    )
    return cursor.fetchall()


def _report_inventory(cursor, f):
    q = _ReportQuery(f, scope_alias='il')
    if f['product_type']:
        q.add('LOWER(pl.product_type) = LOWER(%s)', f['product_type'])
    cursor.execute(
        f"""
        WITH {INVENTORY_LEDGER_CTE}, {ALLOCATION_STATE_CTE},
        balances AS (
            SELECT product_lot_id, location_id, SUM(delta) AS on_hand
            FROM ledger GROUP BY 1, 2 HAVING SUM(delta) <> 0
        )
        SELECT pl.product_type AS product, pl.business_id AS product_lot,
               pl.production_date, il.name || ' (' || il.location_code || ')' AS location,
               fa.name AS facility, b.on_hand AS on_hand_kg,
               COALESCE((SELECT SUM(s.quantity_kg - s.released_kg - s.dispatched_kg)
                         FROM allocation_state AS s
                         WHERE s.product_lot_id = pl.id AND s.location_id = il.id), 0) AS reserved_kg,
               CASE WHEN {PRODUCT_LOT_RELEASABLE_SQL} THEN 'AVAILABLE' ELSE 'BLOCKED' END AS lot_status
        FROM balances AS b
        JOIN product_lots AS pl ON pl.id = b.product_lot_id
        JOIN inventory_locations AS il ON il.id = b.location_id
        JOIN facilities AS fa ON fa.id = il.facility_id
        {q.where}
        ORDER BY pl.product_type, pl.production_date, pl.business_id, il.name
        """,
        q.params,
    )
    rows = [dict(row) for row in cursor.fetchall()]
    for row in rows:
        row['free_kg'] = Decimal(str(row['on_hand_kg'])) - Decimal(str(row['reserved_kg']))
    return rows


def _report_sales(cursor, f):
    q = _ReportQuery(f, scope_alias='o', commercial=True)
    q.dates('o.order_date')
    if f['status']:
        q.add('o.status = %s', f['status'])
    if f['product_type']:
        q.add(
            'EXISTS (SELECT 1 FROM customer_order_lines AS l WHERE l.order_id = o.id '
            'AND LOWER(l.product_type) = LOWER(%s))',
            f['product_type'],
        )
    cursor.execute(
        f"""
        WITH {ALLOCATION_STATE_CTE}
        SELECT o.business_id AS order_ref, o.order_date AS date, c.name AS customer,
               o.customer_reference, fm.name AS farm, o.status,
               o.requested_delivery_date AS requested,
               (SELECT string_agg(DISTINCT l.product_type, ', ') FROM customer_order_lines AS l
                 WHERE l.order_id = o.id) AS products,
               (SELECT SUM(l.quantity_kg) FROM customer_order_lines AS l WHERE l.order_id = o.id) AS ordered_kg,
               COALESCE((SELECT SUM(s.dispatched_kg) FROM allocation_state AS s
                         JOIN customer_order_lines AS l ON l.id = s.order_line_id
                         WHERE l.order_id = o.id), 0) AS dispatched_kg,
               COALESCE((SELECT SUM(dl.quantity_kg) FROM customer_delivery_lines AS dl
                         JOIN customer_deliveries AS d ON d.id = dl.delivery_id
                         WHERE d.order_id = o.id AND d.status = 'DELIVERED'), 0) AS delivered_kg,
               -- A cancelled order is no longer worth anything; leave it out of totals.
               CASE WHEN o.status <> 'CANCELLED' THEN
                   (SELECT SUM(l.quantity_kg * l.unit_price) FROM customer_order_lines AS l
                     WHERE l.order_id = o.id) END AS order_value,
               COALESCE((SELECT SUM(dl.quantity_kg * l.unit_price) FROM customer_delivery_lines AS dl
                         JOIN customer_deliveries AS d ON d.id = dl.delivery_id
                         JOIN order_allocations AS a ON a.id = dl.allocation_id
                         JOIN customer_order_lines AS l ON l.id = a.order_line_id
                         WHERE d.order_id = o.id AND d.status = 'DELIVERED'), 0) AS delivered_value
        FROM customer_orders AS o
        JOIN customers AS c ON c.id = o.customer_id
        JOIN farms AS fm ON fm.id = o.farm_id
        {q.where}
        ORDER BY o.order_date DESC, o.id DESC
        """,
        q.params,
    )
    return cursor.fetchall()


def _report_deliveries(cursor, f):
    q = _ReportQuery(f, scope_alias='o', commercial=True)
    q.dates('d.dispatched_at')
    if f['status']:
        q.add('d.status = %s', f['status'])
    cursor.execute(
        f"""
        SELECT d.business_id AS delivery, o.business_id AS order_ref, c.name AS customer,
               d.status, d.dispatched_at, d.delivered_at, d.received_by, d.vehicle, d.driver,
               (SELECT SUM(quantity_kg) FROM customer_delivery_lines WHERE delivery_id = d.id) AS quantity_kg,
               (SELECT SUM(dl.quantity_kg * l.unit_price)
                FROM customer_delivery_lines AS dl
                JOIN order_allocations AS a ON a.id = dl.allocation_id
                JOIN customer_order_lines AS l ON l.id = a.order_line_id
                WHERE dl.delivery_id = d.id) AS value,
               (SELECT string_agg(pl.business_id, ', ' ORDER BY pl.business_id)
                FROM customer_delivery_lines AS dl
                JOIN order_allocations AS a ON a.id = dl.allocation_id
                JOIN product_lots AS pl ON pl.id = a.product_lot_id
                WHERE dl.delivery_id = d.id) AS product_lots
        FROM customer_deliveries AS d
        JOIN customer_orders AS o ON o.id = d.order_id
        JOIN customers AS c ON c.id = o.customer_id
        {q.where}
        ORDER BY d.dispatched_at DESC, d.id DESC
        """,
        q.params,
    )
    return cursor.fetchall()


def _report_traceability(cursor, f):
    q = _ReportQuery(f, scope_alias='batch')
    q.dates('pl.production_date')
    if f['product_type']:
        q.add('LOWER(pl.product_type) = LOWER(%s)', f['product_type'])
    commercial_visible = _farm_visibility_clause('pl')
    cursor.execute(
        f"""
        WITH chain AS (
            SELECT di.drying_batch_id, h.harvest_code, pb.business_id AS production_batch,
                   sb.business_id AS substrate_batch, wl.business_id AS waste_lot,
                   wl.source_name
            FROM drying_inputs AS di
            JOIN harvests AS h ON h.id = di.harvest_id
            JOIN production_events AS pe ON pe.id = h.production_event_id
            JOIN production_batches AS pb ON pb.id = pe.production_batch_id
            LEFT JOIN production_batch_inputs AS pbi ON pbi.production_batch_id = pb.id
            LEFT JOIN substrate_batches AS sb ON sb.id = pbi.substrate_batch_id
            LEFT JOIN substrate_batch_inputs AS sbi ON sbi.substrate_batch_id = sb.id
            LEFT JOIN waste_lots AS wl ON wl.id = sbi.waste_lot_id
        )
        SELECT pl.business_id AS product_lot, pl.product_type AS product, pl.production_date,
               pl.quantity_kg, COALESCE(batch.business_id, batch.batch_code) AS drying_batch,
               (SELECT string_agg(DISTINCT harvest_code, ', ') FROM chain
                 WHERE drying_batch_id = batch.id) AS harvests,
               (SELECT string_agg(DISTINCT production_batch, ', ') FROM chain
                 WHERE drying_batch_id = batch.id) AS production_batches,
               (SELECT string_agg(DISTINCT substrate_batch, ', ') FROM chain
                 WHERE drying_batch_id = batch.id) AS substrate_batches,
               (SELECT string_agg(DISTINCT waste_lot, ', ') FROM chain
                 WHERE drying_batch_id = batch.id) AS waste_lots,
               (SELECT string_agg(DISTINCT source_name, ', ') FROM chain
                 WHERE drying_batch_id = batch.id) AS waste_sources,
               CASE WHEN {commercial_visible[0]} THEN (
                   SELECT string_agg(DISTINCT c.name, ', ')
                   FROM order_allocations AS a
                   JOIN customer_order_lines AS l ON l.id = a.order_line_id
                   JOIN customer_orders AS o ON o.id = l.order_id
                   JOIN customers AS c ON c.id = o.customer_id
                   WHERE a.product_lot_id = pl.id
               ) ELSE 'restricted' END AS customers
        FROM product_lots AS pl
        JOIN drying_outputs AS output ON output.id = pl.drying_output_id
        JOIN drying_batches AS batch ON batch.id = output.drying_batch_id
        {q.where}
        ORDER BY pl.production_date DESC, pl.id DESC
        """,
        (*commercial_visible[1], *q.params),
    )
    return cursor.fetchall()


def _report_farm_performance(cursor, f):
    q = _ReportQuery(f, scope_alias='fm', commercial=True)
    period = []
    period_params = []
    for column, op, value in (('{c}', '>=', f['date_from']), ('{c}', '<=', f['date_to'])):
        if value:
            period.append(f"({column})::date {op} %s")
            period_params.append(value)

    def within(column):
        if not period:
            return 'TRUE', []
        return ' AND '.join(p.format(c=column) for p in period), list(period_params)

    parts = []
    params = []
    for name, sql, column in (
        ('waste_received_kg', 'SELECT COALESCE(SUM(quantity), 0) FROM waste_lots WHERE farm_id = fm.farm_id AND {w}', 'collection_date'),
        ('substrate_kg', 'SELECT COALESCE(SUM(total_input_weight_kg), 0) FROM substrate_batches WHERE farm_id = fm.farm_id AND {w}', 'preparation_date'),
        ('batches_started', 'SELECT COUNT(*) FROM production_batches WHERE farm_id = fm.farm_id AND {w}', 'start_date'),
        ('harvested_kg', "SELECT COALESCE(SUM(quantity), 0) FROM production_events WHERE farm_id = fm.farm_id AND event_type = 'harvest' AND status = 'recorded' AND {w}", 'occurred_at'),
        ('dried_in_kg', f"SELECT COALESCE(SUM({KG_SQL.format(unit='di.unit', qty='di.quantity')}), 0) FROM drying_inputs AS di JOIN drying_batches AS db ON db.id = di.drying_batch_id WHERE db.farm_id = fm.farm_id AND {{w}}", 'db.drying_date'),
        ('dried_out_kg', f"SELECT COALESCE(SUM({KG_SQL.format(unit='o.unit', qty='o.quantity')}), 0) FROM drying_outputs AS o JOIN drying_batches AS db ON db.id = o.drying_batch_id WHERE db.farm_id = fm.farm_id AND {{w}}", 'db.drying_date'),
        ('released_kg', 'SELECT COALESCE(SUM(quantity_kg), 0) FROM product_lots WHERE farm_id = fm.farm_id AND drying_output_id IS NOT NULL AND {w}', 'production_date'),
        ('dispatched_kg', "SELECT COALESCE(SUM(quantity_kg), 0) FROM inventory_movements WHERE farm_id = fm.farm_id AND movement_type = 'DISPATCH' AND status = 'posted' AND {w}", 'occurred_at'),
        ('revenue', "SELECT COALESCE(SUM(dl.quantity_kg * l.unit_price), 0) FROM customer_delivery_lines AS dl JOIN customer_deliveries AS d ON d.id = dl.delivery_id JOIN customer_orders AS ro ON ro.id = d.order_id JOIN order_allocations AS a ON a.id = dl.allocation_id JOIN customer_order_lines AS l ON l.id = a.order_line_id WHERE ro.farm_id = fm.farm_id AND d.status = 'DELIVERED' AND {w}", 'd.delivered_at'),
    ):
        clause, clause_params = within(column)
        parts.append(f"({sql.format(w=clause)}) AS {name}")
        params.extend(clause_params)
    cursor.execute(
        f"""
        SELECT fm.name AS farm, {', '.join(parts)},
               (SELECT COUNT(*) FROM operational_alerts AS a
                 WHERE a.farm_id = fm.farm_id AND a.status = 'OPEN') AS open_alerts
        FROM (SELECT id AS farm_id, name FROM farms WHERE status = 'active') AS fm
        {q.where}
        ORDER BY fm.name
        """,
        (*params, *q.params),
    )
    rows = [dict(row) for row in cursor.fetchall()]
    for row in rows:
        substrate, harvested = Decimal(str(row['substrate_kg'])), Decimal(str(row['harvested_kg']))
        dried_in, dried_out = Decimal(str(row['dried_in_kg'])), Decimal(str(row['dried_out_kg']))
        row['harvest_per_substrate_pct'] = _ratio_percent(harvested, substrate) if harvested else None
        row['drying_yield_pct'] = _ratio_percent(dried_out, dried_in) if dried_out else None
    return rows



FARM_LOG_GROUPS = {'WASTE_HANDLING': 'Waste handling', 'HATCHERY': 'Hatchery', 'FLY_FACILITY': 'Fly facility'}


def _report_farm_operations(cursor, f):
    """Hatchery, fly facility and waste-handling logs, one row per record,
    built from the same registry as the data-entry forms."""
    parts, params = [], []
    for spec in FARM_LOG_KINDS.values():
        if f['status'] and FARM_LOG_GROUPS[f['status']] != spec['group']:
            continue
        q = _ReportQuery(f, scope_alias='t')
        q.dates(f"t.{spec['date']}")
        detail_fields = [fd for fd in spec['fields']
                         if fd.column not in (spec['date'], spec.get('ref')) and fd.kind != 'note'][:4]
        # "Label: value" pairs; labels are parameters (some contain %).
        detail = "concat_ws(' · ', " + ', '.join(
            f"%s || NULLIF(t.{fd.column}::text, '')" for fd in detail_fields) + ")"
        reference = f"t.{spec['ref']}::text" if spec.get('ref') else 'NULL::text'
        parts.append(f"""
            SELECT t.{spec['date']}::date AS date, %s AS log_group, %s AS record, {reference} AS reference,
                   {detail} AS details, fm.name AS farm, fa.name AS facility,
                   COALESCE(u.username, '') AS recorded_by, t.id AS row_id
            FROM {spec['table']} AS t
            LEFT JOIN farms AS fm ON fm.id = t.farm_id
            LEFT JOIN facilities AS fa ON fa.id = t.facility_id
            LEFT JOIN users AS u ON u.user_id = t.recorded_by_user_id
            {q.where}""")
        params += [spec['group'], spec['label'], *[fd.label + ': ' for fd in detail_fields], *q.params]
    if not parts:
        return []
    cursor.execute(
        'SELECT date, log_group, record, reference, details, farm, facility, recorded_by FROM ('
        + ' UNION ALL '.join(parts) + f') AS logs ORDER BY date DESC, record, row_id DESC LIMIT {REPORT_ROW_LIMIT + 1}',
        params,
    )
    return cursor.fetchall()


def _col(key, label, kind='text'):
    return {'key': key, 'label': label, 'type': kind}


# Report catalogue: builder, columns, filters it accepts, and totals to sum.
REPORTS = {
    'waste_received': {
        'title': 'Waste received', 'group': 'Production', 'builder': _report_waste,
        'filters': ['dates', 'farm', 'facility', 'status'],
        'statuses': ['AVAILABLE', 'QUARANTINED', 'REJECTED', 'CONSUMED'],
        'columns': [_col('date', 'Date', 'date'), _col('waste_lot', 'Waste lot'), _col('source_type', 'Source type'),
                    _col('source_name', 'Source'), _col('waste_type', 'Waste type'),
                    _col('received_kg', 'Received kg', 'kg'), _col('used_kg', 'Used kg', 'kg'),
                    _col('remaining_kg', 'Remaining kg', 'kg'), _col('quality_status', 'Quality'),
                    _col('status', 'Status'), _col('facility', 'Facility')],
        'totals': ['received_kg', 'used_kg', 'remaining_kg'],
    },
    'substrate': {
        'title': 'Substrate preparation', 'group': 'Production', 'builder': _report_substrate,
        'filters': ['dates', 'farm', 'facility'],
        'columns': [_col('date', 'Date', 'date'), _col('substrate_batch', 'Substrate batch'), _col('facility', 'Facility'),
                    _col('waste_lots', 'Waste lots', 'number'), _col('input_kg', 'Input kg', 'kg'),
                    _col('issued_kg', 'Issued kg', 'kg'), _col('available_kg', 'Available kg', 'kg'),
                    _col('particle_size', 'Particle size'), _col('recorded_by', 'Recorded by')],
        'totals': ['input_kg', 'issued_kg', 'available_kg'],
    },
    'production_batches': {
        'title': 'Production batches', 'group': 'Production', 'builder': _report_production,
        'filters': ['dates', 'farm', 'facility', 'status'],
        'statuses': sorted(PRODUCTION_BATCH_STATUSES),
        'columns': [_col('production_batch', 'Batch'), _col('facility', 'Facility'), _col('start_date', 'Started', 'date'),
                    _col('status', 'Status'), _col('stage', 'Stage'), _col('expected_harvest', 'Expected harvest', 'date'),
                    _col('age_days', 'Age (days)', 'number'), _col('substrate_kg', 'Substrate kg', 'kg'),
                    _col('harvested_kg', 'Harvested kg', 'kg'), _col('harvest_per_substrate_pct', 'Harvest / substrate %', 'percent')],
        'totals': ['substrate_kg', 'harvested_kg'],
    },
    'feeding': {
        'title': 'Feeding activity', 'group': 'Production', 'builder': _report_feeding,
        'filters': ['dates', 'farm', 'facility'],
        'columns': [_col('date', 'Date', 'date'), _col('production_batch', 'Batch'), _col('feed_type', 'Feed'),
                    _col('offered_kg', 'Offered kg', 'kg'), _col('consumed_kg', 'Consumed kg', 'kg'),
                    _col('larvae_biomass_kg', 'Biomass kg', 'kg'), _col('larvae_age_days', 'Larvae age', 'number'),
                    _col('recorded_by', 'Recorded by'), _col('facility', 'Facility')],
        'totals': ['offered_kg', 'consumed_kg'],
    },
    'harvest': {
        'title': 'Harvest', 'group': 'Production', 'builder': _report_harvest,
        'filters': ['dates', 'farm', 'facility'],
        'columns': [_col('date', 'Date', 'date'), _col('harvest', 'Harvest'), _col('production_batch', 'Batch'),
                    _col('wet_kg', 'Wet kg', 'kg'), _col('sent_to_drying_kg', 'Sent to drying kg', 'kg'),
                    _col('stage', 'Stage'), _col('operator', 'Operator'), _col('location', 'Location'),
                    _col('facility', 'Facility')],
        'totals': ['wet_kg', 'sent_to_drying_kg'],
    },
    'drying': {
        'title': 'Drying', 'group': 'Processing', 'builder': _report_drying,
        'filters': ['dates', 'farm', 'facility', 'status'],
        'statuses': sorted(DRYING_BATCH_STATUSES),
        'columns': [_col('drying_batch', 'Drying batch'), _col('date', 'Date', 'date'), _col('method', 'Method'),
                    _col('status', 'Status'), _col('facility', 'Facility'), _col('wet_in_kg', 'Wet in kg', 'kg'),
                    _col('dry_out_kg', 'Dry out kg', 'kg'), _col('yield_pct', 'Yield %', 'percent'),
                    _col('moisture_pct', 'Moisture %', 'percent'), _col('production_batches', 'From batches')],
        'totals': ['wet_in_kg', 'dry_out_kg'],
    },
    'quality': {
        'title': 'Quality control', 'group': 'Processing', 'builder': _report_quality,
        'filters': ['dates', 'farm', 'facility', 'status'],
        'statuses': ['PASSED', 'FAILED', 'SUBMITTED', 'DRAFT', 'SUPERSEDED'],
        'columns': [_col('date', 'Date', 'date'), _col('quality_check', 'Check'), _col('drying_batch', 'Drying batch'),
                    _col('result', 'Result'), _col('moisture_pct', 'Moisture %', 'percent'), _col('inspector', 'Inspector'),
                    _col('decision', 'Decision'), _col('approver', 'Approver'), _col('decided_on', 'Decided', 'date'),
                    _col('facility', 'Facility')],
        'totals': [],
    },
    'inventory': {
        'title': 'Current stock', 'group': 'Stock & sales', 'builder': _report_inventory,
        'filters': ['farm', 'facility', 'product'],
        'columns': [_col('product', 'Product'), _col('product_lot', 'Product lot'),
                    _col('production_date', 'Produced', 'date'), _col('location', 'Location'), _col('facility', 'Facility'),
                    _col('on_hand_kg', 'On hand kg', 'kg'), _col('reserved_kg', 'Reserved kg', 'kg'),
                    _col('free_kg', 'Free kg', 'kg'), _col('lot_status', 'Lot status')],
        'totals': ['on_hand_kg', 'reserved_kg', 'free_kg'],
    },
    'sales': {
        'title': 'Customer orders', 'group': 'Stock & sales', 'builder': _report_sales,
        'filters': ['dates', 'farm', 'status', 'product'], 'commercial': True,
        'statuses': ['OPEN', 'FULFILLED', 'CANCELLED'],
        'columns': [_col('order_ref', 'Order'), _col('date', 'Date', 'date'), _col('customer', 'Customer'),
                    _col('customer_reference', 'Customer ref'), _col('status', 'Status'),
                    _col('requested', 'Requested', 'date'), _col('products', 'Products'),
                    _col('ordered_kg', 'Ordered kg', 'kg'), _col('dispatched_kg', 'Dispatched kg', 'kg'),
                    _col('delivered_kg', 'Delivered kg', 'kg'),
                    _col('order_value', f'Order value ({CURRENCY})', 'money'),
                    _col('delivered_value', f'Delivered value ({CURRENCY})', 'money'), _col('farm', 'Farm')],
        'totals': ['ordered_kg', 'dispatched_kg', 'delivered_kg', 'order_value', 'delivered_value'],
    },
    'deliveries': {
        'title': 'Deliveries', 'group': 'Stock & sales', 'builder': _report_deliveries,
        'filters': ['dates', 'farm', 'status'], 'commercial': True,
        'statuses': ['DISPATCHED', 'DELIVERED'],
        'columns': [_col('delivery', 'Delivery'), _col('order_ref', 'Order'), _col('customer', 'Customer'),
                    _col('status', 'Status'), _col('dispatched_at', 'Dispatched', 'datetime'),
                    _col('delivered_at', 'Delivered', 'datetime'), _col('received_by', 'Received by'),
                    _col('quantity_kg', 'Quantity kg', 'kg'), _col('value', f'Value ({CURRENCY})', 'money'),
                    _col('product_lots', 'Product lots'), _col('vehicle', 'Vehicle'), _col('driver', 'Driver')],
        'totals': ['quantity_kg', 'value'],
    },
    'farm_operations': {
        'title': 'Farm operation logs', 'group': 'Production', 'builder': _report_farm_operations,
        'filters': ['dates', 'farm', 'facility', 'status'],
        'statuses': list(FARM_LOG_GROUPS),
        'columns': [_col('date', 'Date', 'date'), _col('log_group', 'Area'), _col('record', 'Record'),
                    _col('reference', 'Reference'), _col('details', 'Details'), _col('farm', 'Farm'),
                    _col('facility', 'Facility'), _col('recorded_by', 'Recorded by')],
        'totals': [],
    },
    'traceability': {
        'title': 'Product lineage', 'group': 'Traceability', 'builder': _report_traceability,
        'filters': ['dates', 'farm', 'facility', 'product'],
        'columns': [_col('product_lot', 'Product lot'), _col('product', 'Product'),
                    _col('production_date', 'Produced', 'date'), _col('quantity_kg', 'Released kg', 'kg'),
                    _col('drying_batch', 'Drying batch'), _col('harvests', 'Harvests'),
                    _col('production_batches', 'Production batches'), _col('substrate_batches', 'Substrate'),
                    _col('waste_lots', 'Waste lots'), _col('waste_sources', 'Waste sources'),
                    _col('customers', 'Customers')],
        'totals': ['quantity_kg'],
    },
    'farm_performance': {
        'title': 'Farm performance', 'group': 'Overview', 'builder': _report_farm_performance,
        'filters': ['dates', 'farm'], 'commercial': True,
        'columns': [_col('farm', 'Farm'), _col('waste_received_kg', 'Waste received kg', 'kg'),
                    _col('substrate_kg', 'Substrate kg', 'kg'), _col('batches_started', 'Batches started', 'number'),
                    _col('harvested_kg', 'Harvested kg', 'kg'),
                    _col('harvest_per_substrate_pct', 'Harvest / substrate %', 'percent'),
                    _col('dried_in_kg', 'Into drying kg', 'kg'), _col('dried_out_kg', 'Dried kg', 'kg'),
                    _col('drying_yield_pct', 'Drying yield %', 'percent'), _col('released_kg', 'Released kg', 'kg'),
                    _col('dispatched_kg', 'Dispatched kg', 'kg'),
                    _col('revenue', f'Revenue ({CURRENCY})', 'money'), _col('open_alerts', 'Open alerts', 'number')],
        'totals': ['waste_received_kg', 'substrate_kg', 'batches_started', 'harvested_kg',
                   'dried_in_kg', 'dried_out_kg', 'released_kg', 'dispatched_kg', 'revenue', 'open_alerts'],
    },
}


def _report_filters(spec):
    args = request.args

    def day(name):
        value = args.get(name)
        if value in (None, ''):
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            raise ValueError(f'{name} must be a date (YYYY-MM-DD)')

    filters = {
        'date_from': day('date_from') if 'dates' in spec['filters'] else None,
        'date_to': day('date_to') if 'dates' in spec['filters'] else None,
        'farm_id': None, 'facility_id': None, 'status': None, 'product_type': None,
    }
    if filters['date_from'] and filters['date_to'] and filters['date_from'] > filters['date_to']:
        raise ValueError('date_from must be on or before date_to')
    for name in ('farm_id', 'facility_id'):
        if args.get(name) not in (None, '') and name.split('_')[0] in spec['filters']:
            filters[name] = _parse_positive_integer(args[name], name)
    status = str(args.get('status') or '').strip().upper()
    if status and 'status' in spec['filters']:
        if status not in spec.get('statuses', []):
            raise ValueError('Unknown status for this report')
        filters['status'] = status
    product = str(args.get('product_type') or '').strip()
    if product and 'product' in spec['filters']:
        filters['product_type'] = product[:50]
    return filters


def _csv_cell(value):
    """Plain text for CSV; neutralise spreadsheet formulas from user data."""
    if value is None:
        return ''
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    text = str(value)
    if text and text[0] in ('=', '+', '-', '@', '\t', '\r') and not _looks_numeric(text):
        return "'" + text
    return text


def _looks_numeric(text):
    try:
        Decimal(text)
        return True
    except (InvalidOperation, ValueError):
        return False


@app.route('/api/reports', methods=['GET'])
@login_required
def list_reports():
    return jsonify({'success': True, 'data': [
        {'key': key, 'title': spec['title'], 'group': spec['group'], 'filters': spec['filters'],
         'statuses': spec.get('statuses', []), 'commercial': spec.get('commercial', False),
         'columns': spec['columns']}
        for key, spec in REPORTS.items()
        if not spec.get('commercial') or _can('sales.read')
    ]})


@app.route('/api/reports/<string:report_key>', methods=['GET'])
@login_required
def run_report(report_key):
    spec = REPORTS.get(report_key)
    if not spec:
        return jsonify({'success': False, 'message': 'Unknown report'}), 404
    if spec.get('commercial') and not _can('sales.read'):
        return jsonify({'success': False, 'message': 'Your role does not allow sales reports'}), 403
    try:
        filters = _report_filters(spec)
        with db.transaction() as cursor:
            rows = [dict(row) for row in spec['builder'](cursor, filters)]
        truncated = len(rows) > REPORT_ROW_LIMIT
        rows = rows[:REPORT_ROW_LIMIT]
        totals = {
            key: sum((Decimal(str(row[key])) for row in rows if row.get(key) is not None), Decimal('0'))
            for key in spec['totals']
        }
        if request.args.get('format') == 'csv':
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow([column['label'] for column in spec['columns']])
            for row in rows:
                writer.writerow([_csv_cell(row.get(column['key'])) for column in spec['columns']])
            stamp = date.today().isoformat()
            return Response(
                '﻿' + buffer.getvalue(),  # BOM so Excel opens UTF-8 correctly
                mimetype='text/csv',
                headers={'Content-Disposition': f'attachment; filename=zehunger-{report_key}-{stamp}.csv'},
            )
        return jsonify({
            'success': True,
            'report': {'key': report_key, 'title': spec['title'], 'columns': spec['columns']},
            'filters': _jsonable(filters),
            'data': _jsonable(rows),
            'totals': totals,
            'row_count': len(rows),
            'truncated': truncated,
        }), 200
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception:
        logger.exception('Error running report %s', report_key)
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500
