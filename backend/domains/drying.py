"""Drying batches: inputs, outputs and status."""

from datetime import datetime, timezone
from decimal import Decimal
from flask import jsonify, request
from flask_login import login_required

from backend.core.web import app, db, logger
from backend.core.http import (
    ProductionEventPermissionError,
    _jsonable,
    _event_decimal,
    _event_unit,
    _parse_positive_integer,
    _production_actor,
    normalize_keys,
)
from backend.core.security import requires
from backend.core.scope import (
    _assert_production_location,
    _assert_production_scope_access,
    _scope_visibility_clause,
)


DRYING_BATCH_STATUSES = {'DRAFT', 'RECEIVED', 'DRYING', 'QC_PENDING', 'COMPLETED'}
DRYING_BATCH_TRANSITIONS = {
    'DRAFT': {'RECEIVED'},
    'RECEIVED': {'DRYING'},
    'DRYING': {'QC_PENDING'},
    'QC_PENDING': {'COMPLETED'},
    'COMPLETED': set(),
}


def _drying_actor(data):
    actor, actor_user_id = _production_actor(data)
    return actor, actor_user_id


def _drying_scope_values(data):
    values = [data.get(field) for field in ('farm_id', 'site_id', 'facility_id')]
    if any(value in (None, '') for value in values):
        raise ValueError('farm_id, site_id, and facility_id are required for a Drying Batch')
    return tuple(
        _parse_positive_integer(value, field)
        for value, field in zip(values, ('farm_id', 'site_id', 'facility_id'))
    )


def _drying_timestamp(value, field_name, *, required=False):
    if value in (None, ''):
        if required:
            raise ValueError(f'{field_name} is required')
        return None
    raw = str(value)
    if len(raw) == 10:
        raw = f'{raw}T00:00:00+00:00'
    try:
        parsed = datetime.fromisoformat(raw.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError(f'{field_name} must be a valid ISO date or timestamp')
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _drying_batch_row(cursor, batch_ref, *, for_update=False):
    lookup_id = int(batch_ref) if str(batch_ref).isdigit() else -1
    cursor.execute(
        f"""
        SELECT db.id, db.batch_id, db.batch_code, db.business_id,
               db.drying_date, db.drying_method, db.personnel,
               UPPER(db.status) AS status, db.farm_id, db.site_id, db.facility_id,
               db.started_at, db.ended_at, db.created_at, db.updated_at
        FROM drying_batches AS db
        WHERE db.id = %s
           OR db.batch_id = %s
           OR db.batch_code = %s
           OR db.business_id = %s
        {'FOR UPDATE' if for_update else ''}
        """,
        (lookup_id, str(batch_ref), str(batch_ref), str(batch_ref)),
    )
    row = cursor.fetchone()
    if not row:
        raise ValueError('Drying Batch not found')
    if row['farm_id'] is None or row['site_id'] is None or row['facility_id'] is None:
        raise ValueError(
            'Drying Batch has no canonical farm, site, and facility scope'
        )
    _assert_production_location(
        cursor, row['farm_id'], row['site_id'], row['facility_id']
    )
    _assert_production_scope_access(
        cursor, row['farm_id'], row['site_id'], row['facility_id']
    )
    return row


def _drying_harvest_row(cursor, harvest_ref):
    lookup_id = int(harvest_ref) if str(harvest_ref).isdigit() else -1
    cursor.execute(
        """
        SELECT h.id, h.harvest_code, h.wet_weight, h.unit,
               pe.production_batch_id, pe.farm_id, pe.site_id, pe.facility_id,
               pe.occurred_at
        FROM harvests AS h
        JOIN production_events AS pe ON pe.id = h.production_event_id
        WHERE (h.id = %s OR h.harvest_code = %s)
          AND pe.event_type = 'harvest'
          AND pe.status = 'recorded'
        FOR UPDATE OF h
        """,
        (lookup_id, str(harvest_ref)),
    )
    row = cursor.fetchone()
    if not row:
        raise ValueError('Harvest not found or it is not an active harvest event')
    return row


def _drying_input_rows(data):
    rows = data.get('inputs')
    if rows is None:
        rows = data.get('harvest_inputs')
    if rows is None:
        rows = data.get('harvests')
    if rows is None:
        source_ids = data.get('source_harvest_ids')
        if source_ids is None:
            source_ids = data.get('source_harvests')
        if source_ids is not None:
            if not isinstance(source_ids, list) or not source_ids:
                raise ValueError('source_harvest_ids must be a non-empty list')
            rows = [
                item if isinstance(item, dict) else {'harvest_id': item}
                for item in source_ids
            ]
    if rows is None and any(
        data.get(key) not in (None, '')
        for key in ('harvest_id', 'harvest_code')
    ):
        rows = [data]
    if not isinstance(rows, list) or not rows:
        raise ValueError('At least one harvest input is required')

    normalized = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Each drying input must be an object')
        harvest_ref = row.get('harvest_id', row.get('harvest_code'))
        if harvest_ref in (None, ''):
            raise ValueError('harvest_id or harvest_code is required for each input')
        ref_key = str(harvest_ref)
        if ref_key in seen:
            raise ValueError('Each Harvest can be selected only once per Drying Batch')
        seen.add(ref_key)
        quantity = _event_decimal(
            row.get(
                'quantity',
                row.get('input_quantity', row.get('quantity_kg')),
            ),
            'quantity',
            minimum='0.001',
            required=True,
        )
        unit = _event_unit(row.get('unit'), 'unit', 'kg', {'kg', 'g'})
        moisture = _event_decimal(
            row.get(
                'incoming_moisture_percent',
                row.get('moisture_percent', row.get('moisture')),
            ),
            'incoming_moisture_percent',
            minimum=0,
            maximum=100,
        )
        normalized.append({
            'harvest_ref': harvest_ref,
            'quantity': quantity,
            'unit': unit,
            'incoming_moisture_percent': moisture,
            'notes': row.get('notes'),
        })
    return normalized


def _drying_quantity_kg(quantity, unit):
    return quantity if unit == 'kg' else quantity / Decimal('1000')


def _drying_add_inputs(cursor, batch, rows, data):
    if batch['status'] not in {'DRAFT', 'RECEIVED'}:
        raise ValueError('Harvest inputs can only be added while a Drying Batch is DRAFT or RECEIVED')
    actor, actor_user_id = _drying_actor(data)
    for row in rows:
        harvest = _drying_harvest_row(cursor, row['harvest_ref'])
        # Wet larvae may go to a dedicated drying facility, but never leave
        # the farm, and the caller must also be allowed at the harvest site.
        if harvest['farm_id'] != batch['farm_id']:
            raise ValueError('Harvest and Drying Batch must be on the same farm')
        _assert_production_scope_access(
            cursor, harvest['farm_id'], harvest['site_id'], harvest['facility_id']
        )
        quantity_kg = _drying_quantity_kg(row['quantity'], row['unit'])
        available_kg = (
            harvest['wet_weight']
            if harvest['unit'] == 'kg'
            else harvest['wet_weight'] / Decimal('1000')
        )
        cursor.execute(
            """
            SELECT COALESCE(
                SUM(CASE WHEN unit = 'kg' THEN quantity ELSE quantity / 1000 END),
                0
            ) AS consumed_kg
            FROM drying_inputs
            WHERE harvest_id = %s
            """,
            (harvest['id'],),
        )
        consumed_kg = Decimal(str(cursor.fetchone()['consumed_kg']))
        if consumed_kg + quantity_kg > available_kg:
            remaining = max(available_kg - consumed_kg, Decimal('0'))
            raise ValueError(
                f'Input exceeds available Harvest material; only {remaining:.3f} kg remains'
            )
        cursor.execute(
            """
            SELECT COALESCE(MAX(line_no), 0) + 1 AS line_no
            FROM drying_inputs
            WHERE drying_batch_id = %s
            """,
            (batch['id'],),
        )
        line_no = cursor.fetchone()['line_no']
        cursor.execute(
            """
            INSERT INTO drying_inputs (
                drying_batch_id, line_no, harvest_id, quantity, unit,
                incoming_moisture_percent, added_at, recorded_by_user_id,
                recorded_by, notes
            ) VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, %s, %s, %s)
            RETURNING id, line_no, harvest_id, quantity, unit,
                      incoming_moisture_percent, added_at, recorded_by, notes
            """,
            (
                batch['id'], line_no, harvest['id'], row['quantity'], row['unit'],
                row['incoming_moisture_percent'], actor_user_id, actor, row['notes'],
            ),
        )


def _drying_batch_detail(cursor, batch):
    cursor.execute(
        """
        SELECT di.id, di.line_no, di.harvest_id, h.harvest_code,
               di.quantity, di.unit, di.incoming_moisture_percent,
               di.added_at, di.recorded_by, di.notes
        FROM drying_inputs AS di
        JOIN harvests AS h ON h.id = di.harvest_id
        WHERE di.drying_batch_id = %s
        ORDER BY di.line_no
        """,
        (batch['id'],),
    )
    inputs = [dict(row) for row in cursor.fetchall()]
    cursor.execute(
        """
        SELECT id, line_no, quantity, unit, moisture_percent, output_date,
               operator, input_quantity_kg_at_output, yield_ratio,
               yield_percentage, recorded_by, notes
        FROM drying_outputs
        WHERE drying_batch_id = %s
        ORDER BY line_no
        """,
        (batch['id'],),
    )
    outputs = [dict(row) for row in cursor.fetchall()]
    input_kg = sum(
        (_drying_quantity_kg(row['quantity'], row['unit']) for row in inputs),
        Decimal('0'),
    )
    output_kg = sum(
        (_drying_quantity_kg(row['quantity'], row['unit']) for row in outputs),
        Decimal('0'),
    )
    yield_ratio = output_kg / input_kg if input_kg else None
    result = dict(batch)
    result.update({
        'source': inputs,
        'inputs': inputs,
        'outputs': outputs,
        'input_quantity_kg': input_kg,
        'output_quantity_kg': output_kg,
        'yield_ratio': yield_ratio,
        'yield_percentage': yield_ratio * Decimal('100') if yield_ratio is not None else None,
    })
    return result


def _drying_create_batch(data):
    batch_code = str(data.get('batch_code') or data.get('batch_id') or '').strip()
    if not batch_code:
        raise ValueError('batch_code is required for a Drying Batch')
    drying_date = data.get('drying_date') or data.get('batch_date')
    if not drying_date:
        raise ValueError('drying_date is required')
    method = str(data.get('drying_method') or data.get('method') or '').strip()
    personnel = str(data.get('personnel') or data.get('operator') or '').strip()
    if not method:
        raise ValueError('drying_method is required')
    if not personnel:
        raise ValueError('personnel is required')
    farm_id, site_id, facility_id = _drying_scope_values(data)
    started_at = _drying_timestamp(data.get('started_at'), 'started_at')
    rows = _drying_input_rows(data) if any(
        data.get(key) is not None for key in ('inputs', 'harvest_inputs', 'harvests', 'harvest_id', 'harvest_code')
    ) else None
    actor, actor_user_id = _drying_actor(data)
    with db.transaction() as cursor:
        _assert_production_location(cursor, farm_id, site_id, facility_id)
        _assert_production_scope_access(cursor, farm_id, site_id, facility_id)
        cursor.execute(
            """
            INSERT INTO drying_batches (
                batch_id, batch_code, drying_date, drying_method, personnel,
                status, farm_id, site_id, facility_id, started_at,
                created_by_user_id, updated_at
            ) VALUES (%s, %s, %s, %s, %s, 'DRAFT', %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            RETURNING id, batch_id, batch_code, business_id, drying_date,
                      drying_method, personnel, UPPER(status) AS status,
                      farm_id, site_id, facility_id, started_at, ended_at,
                      created_at, updated_at
            """,
            (
                batch_code, batch_code, drying_date, method, personnel,
                farm_id, site_id, facility_id, started_at, actor_user_id,
            ),
        )
        batch = cursor.fetchone()
        if rows:
            _drying_add_inputs(cursor, batch, rows, data)
        cursor.execute(
            """
            INSERT INTO drying_batch_status_history (
                drying_batch_id, previous_status, new_status,
                actor_user_id, actor, reason
            ) VALUES (%s, NULL, 'DRAFT', %s, %s, %s)
            """,
            (batch['id'], actor_user_id, actor, data.get('reason')),
        )
        detail = _drying_batch_detail(cursor, batch)
    return detail


def _drying_transition(cursor, batch, new_status, data):
    current_status = batch['status']
    if new_status not in DRYING_BATCH_STATUSES:
        raise ValueError(f'status must be one of: {", ".join(sorted(DRYING_BATCH_STATUSES))}')
    if new_status not in DRYING_BATCH_TRANSITIONS.get(current_status, set()):
        raise ValueError(f'Invalid Drying Batch transition from {current_status} to {new_status}')
    cursor.execute(
        "SELECT COUNT(*) AS count FROM drying_inputs WHERE drying_batch_id = %s",
        (batch['id'],),
    )
    input_count = cursor.fetchone()['count']
    if new_status == 'RECEIVED' and input_count == 0:
        raise ValueError('A Drying Batch must have at least one Harvest input before RECEIVED')
    if new_status == 'DRYING' and input_count == 0:
        raise ValueError('A Drying Batch must have at least one Harvest input before DRYING')
    cursor.execute(
        "SELECT COUNT(*) AS count FROM drying_outputs WHERE drying_batch_id = %s",
        (batch['id'],),
    )
    output_count = cursor.fetchone()['count']
    if new_status == 'QC_PENDING' and output_count == 0:
        raise ValueError('A Drying Batch must have at least one output before QC_PENDING')
    if new_status == 'COMPLETED':
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM quality_approvals AS qa
                JOIN quality_checks AS qc ON qc.id = qa.quality_check_id
                WHERE qc.drying_batch_id = %s
                  AND qc.status = 'passed'
                  AND qa.decision = 'approved'
            ) AS approved
            """,
            (batch['id'],),
        )
        if not cursor.fetchone()['approved']:
            raise ValueError(
                'A Drying Batch requires an approved passing quality check before COMPLETED'
            )
    actor, actor_user_id = _drying_actor(data)
    started_at = "CURRENT_TIMESTAMP" if new_status == 'DRYING' else "started_at"
    ended_at = "CURRENT_TIMESTAMP" if new_status == 'COMPLETED' else "ended_at"
    cursor.execute(
        f"""
        UPDATE drying_batches
        SET status = %s,
            started_at = {started_at},
            ended_at = {ended_at},
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        RETURNING id, batch_id, batch_code, business_id, drying_date,
                  drying_method, personnel, UPPER(status) AS status,
                  farm_id, site_id, facility_id, started_at, ended_at,
                  created_at, updated_at
        """,
        (new_status, batch['id']),
    )
    updated = cursor.fetchone()
    cursor.execute(
        """
        INSERT INTO drying_batch_status_history (
            drying_batch_id, previous_status, new_status,
            actor_user_id, actor, reason
        ) VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (batch['id'], current_status, new_status, actor_user_id, actor, data.get('reason')),
    )
    return updated


def _canonical_drying_batch_request(data):
    return any(
        data.get(key) not in (None, '')
        for key in ('farm_id', 'site_id', 'facility_id', 'inputs', 'harvest_inputs',
                    'harvests', 'source_harvest_ids', 'source_harvests',
                    'harvest_id', 'harvest_code')
    )


@app.route('/api/drying/batches', methods=['POST'])
@login_required
@requires('production.write')
def create_canonical_drying_batch():
    try:
        data = normalize_keys(request.get_json() or {})
        record = _drying_create_batch(data)
        return jsonify({'success': True, 'message': 'Drying Batch created', 'data': record}), 201
    except ProductionEventPermissionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 403
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception:
        logger.exception('Error creating canonical Drying Batch')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


DRYING_STATUSES = ('DRAFT', 'RECEIVED', 'DRYING', 'QC_PENDING', 'COMPLETED', 'CANCELLED')


@app.route('/api/drying/batches', methods=['GET'])
@login_required
def list_canonical_drying_batches():
    """Drying batches at locations the caller may see, newest first, with
    their outputs, the quality checks on each output, the decision on each
    check and the Product Lot released from it (for the data-entry forms)."""
    statuses = [s.strip().upper() for s in (request.args.get('status') or '').split(',') if s.strip()]
    if any(s not in DRYING_STATUSES for s in statuses):
        return jsonify({'success': False, 'message': 'Unknown drying status'}), 400
    visibility, params = _scope_visibility_clause('b')
    clauses, values = ['b.facility_id IS NOT NULL', visibility], list(params)
    if statuses:
        clauses.append('UPPER(b.status) = ANY(%s)')
        values.append(statuses)
    batches = db.fetch_all(
        f"""
        SELECT b.id, b.business_id, b.batch_code, UPPER(b.status) AS status, b.drying_date,
               b.farm_id, b.site_id, b.facility_id, f.name AS farm_name, fa.name AS facility_name,
               COALESCE((SELECT SUM(CASE WHEN di.unit = 'kg' THEN di.quantity ELSE di.quantity / 1000 END)
                         FROM drying_inputs AS di WHERE di.drying_batch_id = b.id), 0) AS input_kg
        FROM drying_batches AS b
        JOIN farms AS f ON f.id = b.farm_id
        JOIN facilities AS fa ON fa.id = b.facility_id
        WHERE {' AND '.join(clauses)}
        ORDER BY b.drying_date DESC, b.id DESC
        LIMIT 200
        """,
        tuple(values),
    )
    ids = [b['id'] for b in batches]
    outputs = db.fetch_all(
        """
        SELECT o.id, o.drying_batch_id, o.line_no, o.quantity, o.unit, o.moisture_percent, o.output_date,
               (SELECT pl.business_id FROM product_lots AS pl WHERE pl.drying_output_id = o.id LIMIT 1) AS product_lot
        FROM drying_outputs AS o WHERE o.drying_batch_id = ANY(%s) ORDER BY o.line_no
        """,
        (ids,),
    ) if ids else []
    checks = db.fetch_all(
        """
        SELECT q.id, q.check_code, q.drying_output_id, LOWER(q.status) AS status, q.checked_at,
               (SELECT LOWER(a.decision) FROM quality_approvals AS a
                WHERE a.quality_check_id = q.id ORDER BY a.id DESC LIMIT 1) AS decision
        FROM quality_checks AS q WHERE q.drying_batch_id = ANY(%s) ORDER BY q.id
        """,
        (ids,),
    ) if ids else []
    by_output = {}
    for check in checks:
        by_output.setdefault(check['drying_output_id'], []).append(dict(check))
    by_batch = {}
    for output in outputs:
        row = dict(output)
        row['checks'] = by_output.get(output['id'], [])
        by_batch.setdefault(output['drying_batch_id'], []).append(row)
    data = []
    for batch in batches:
        row = dict(batch)
        row['outputs'] = by_batch.get(batch['id'], [])
        data.append(row)
    return jsonify({'success': True, 'data': _jsonable(data)})


@app.route('/api/drying/available-harvests', methods=['GET'])
@login_required
def list_harvests_available_for_drying():
    """Recorded harvests the caller may see that still have wet larvae left
    to put into a Drying Batch (wet weight minus what drying inputs used)."""
    visibility, params = _scope_visibility_clause('pe')
    clauses, values = [visibility], list(params)
    if request.args.get('farm_id'):
        try:
            values.append(_parse_positive_integer(request.args['farm_id'], 'farm_id'))
        except ValueError as exc:
            return jsonify({'success': False, 'message': str(exc)}), 400
        clauses.append('pe.farm_id = %s')
    rows = db.fetch_all(
        f"""
        SELECT * FROM (
            SELECT h.id, h.harvest_code, pe.occurred_at, pb.business_id AS production_batch,
                   pe.farm_id, pe.site_id, pe.facility_id, fa.name AS facility_name,
                   (CASE WHEN h.unit = 'kg' THEN h.wet_weight ELSE h.wet_weight / 1000 END)
                   - COALESCE((SELECT SUM(CASE WHEN di.unit = 'kg' THEN di.quantity ELSE di.quantity / 1000 END)
                               FROM drying_inputs AS di WHERE di.harvest_id = h.id), 0) AS remaining_kg
            FROM harvests AS h
            JOIN production_events AS pe ON pe.id = h.production_event_id
            JOIN production_batches AS pb ON pb.id = pe.production_batch_id
            JOIN facilities AS fa ON fa.id = pe.facility_id
            WHERE pe.event_type = 'harvest' AND pe.status = 'recorded' AND {' AND '.join(clauses)}
        ) AS available
        WHERE remaining_kg > 0
        ORDER BY occurred_at DESC, id DESC
        LIMIT 200
        """,
        tuple(values),
    )
    return jsonify({'success': True, 'data': _jsonable([dict(r) for r in rows])})


@app.route('/api/drying/batches/<string:batch_ref>', methods=['GET'])
@login_required
def get_canonical_drying_batch(batch_ref):
    try:
        with db.transaction() as cursor:
            batch = _drying_batch_row(cursor, batch_ref)
            record = _drying_batch_detail(cursor, batch)
        return jsonify({'success': True, 'data': record}), 200
    except ProductionEventPermissionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 403
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 404
    except Exception:
        logger.exception('Error fetching canonical Drying Batch')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/api/drying/batches/<string:batch_ref>/inputs', methods=['POST'])
@login_required
@requires('production.write')
def add_canonical_drying_inputs(batch_ref):
    try:
        data = normalize_keys(request.get_json() or {})
        rows = _drying_input_rows(data)
        with db.transaction() as cursor:
            batch = _drying_batch_row(cursor, batch_ref, for_update=True)
            _drying_add_inputs(cursor, batch, rows, data)
            record = _drying_batch_detail(cursor, batch)
        return jsonify({'success': True, 'message': 'Drying inputs recorded', 'data': record}), 201
    except ProductionEventPermissionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 403
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception:
        logger.exception('Error recording canonical Drying inputs')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/api/drying/batches/<string:batch_ref>/outputs', methods=['POST'])
@login_required
@requires('production.write')
def add_canonical_drying_output(batch_ref):
    try:
        data = normalize_keys(request.get_json() or {})
        quantity = _event_decimal(
            data.get('quantity', data.get('dried_quantity', data.get('dried_produced'))),
            'quantity',
            minimum='0.001',
            required=True,
        )
        unit = _event_unit(data.get('unit', data.get('output_unit')), 'unit', 'kg', {'kg', 'g'})
        moisture = _event_decimal(
            data.get('moisture_percent', data.get('moisture')),
            'moisture_percent',
            minimum=0,
            maximum=100,
        )
        output_date = _drying_timestamp(
            data.get('output_date') or data.get('produced_at'),
            'output_date',
            required=True,
        )
        operator = str(data.get('operator') or '').strip()
        if not operator:
            raise ValueError('operator is required')
        with db.transaction() as cursor:
            batch = _drying_batch_row(cursor, batch_ref, for_update=True)
            if batch['status'] != 'DRYING':
                raise ValueError('Outputs can only be recorded while a Drying Batch is DRYING')
            if batch['drying_date'] and output_date[:10] < str(batch['drying_date']):
                raise ValueError('output_date cannot be before the Drying Batch date')
            cursor.execute(
                "SELECT COUNT(*) AS count FROM drying_inputs WHERE drying_batch_id = %s",
                (batch['id'],),
            )
            if cursor.fetchone()['count'] == 0:
                raise ValueError('A Drying Batch must have Harvest inputs before recording output')
            cursor.execute(
                """
                SELECT COALESCE(SUM(CASE WHEN unit = 'kg' THEN quantity ELSE quantity / 1000 END), 0)
                    AS input_kg
                FROM drying_inputs WHERE drying_batch_id = %s
                """,
                (batch['id'],),
            )
            input_kg = Decimal(str(cursor.fetchone()['input_kg']))
            cursor.execute(
                """
                SELECT COALESCE(SUM(CASE WHEN unit = 'kg' THEN quantity ELSE quantity / 1000 END), 0)
                    AS output_kg
                FROM drying_outputs WHERE drying_batch_id = %s
                """,
                (batch['id'],),
            )
            output_kg = Decimal(str(cursor.fetchone()['output_kg']))
            output_quantity_kg = _drying_quantity_kg(quantity, unit)
            if output_kg + output_quantity_kg > input_kg:
                raise ValueError('Dried output cannot exceed the total wet Harvest input')
            total_output_kg = output_kg + output_quantity_kg
            yield_ratio = total_output_kg / input_kg
            yield_percentage = yield_ratio * Decimal('100')
            cursor.execute(
                """
                SELECT COALESCE(MAX(line_no), 0) + 1 AS line_no
                FROM drying_outputs WHERE drying_batch_id = %s
                """,
                (batch['id'],),
            )
            line_no = cursor.fetchone()['line_no']
            actor, actor_user_id = _drying_actor(data)
            cursor.execute(
                """
                INSERT INTO drying_outputs (
                    drying_batch_id, line_no, quantity, unit, moisture_percent,
                    output_date, operator, input_quantity_kg_at_output,
                    yield_ratio, yield_percentage, recorded_by_user_id,
                    recorded_by, notes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, line_no, quantity, unit, moisture_percent,
                          output_date, operator, input_quantity_kg_at_output,
                          yield_ratio, yield_percentage, recorded_by, notes
                """,
                (
                    batch['id'], line_no, quantity, unit, moisture, output_date,
                    operator, input_kg, yield_ratio, yield_percentage,
                    actor_user_id, actor, data.get('notes'),
                ),
            )
            output = dict(cursor.fetchone())
            record = _drying_batch_detail(cursor, batch)
        return jsonify({
            'success': True,
            'message': 'Drying output recorded',
            'output': output,
            'data': record,
        }), 201
    except ProductionEventPermissionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 403
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception:
        logger.exception('Error recording canonical Drying output')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/api/drying/batches/<string:batch_ref>/status', methods=['POST'])
@login_required
@requires('production.write')
def update_canonical_drying_status(batch_ref):
    try:
        data = normalize_keys(request.get_json() or {})
        new_status = str(data.get('status') or '').strip().upper()
        with db.transaction() as cursor:
            batch = _drying_batch_row(cursor, batch_ref, for_update=True)
            updated = _drying_transition(cursor, batch, new_status, data)
            record = _drying_batch_detail(cursor, updated)
        return jsonify({'success': True, 'message': 'Drying Batch status updated', 'data': record}), 200
    except ProductionEventPermissionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 403
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception:
        logger.exception('Error updating canonical Drying Batch status')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500
