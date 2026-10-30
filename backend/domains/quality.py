"""Quality checks, approvals and Product Lot release."""

import json

from flask import jsonify, render_template, request
from flask_login import login_required

from backend.core.web import app, db, logger
from backend.core.http import (
    ProductionEventPermissionError,
    _event_decimal,
    _parse_positive_integer,
    normalize_keys,
)
from backend.core.security import requires
from backend.core.scope import _assert_production_scope_access, _scope_visibility_clause
from backend.domains.drying import (
    _drying_actor,
    _drying_batch_row,
    _drying_quantity_kg,
    _drying_timestamp,
    _drying_transition,
)
from backend.domains.inventory import (
    INVENTORY_LEDGER_CTE,
    PRODUCT_LOT_RELEASABLE_SQL,
    _insert_inventory_movement,
    _inventory_location_row,
    _inventory_summary,
)


@app.route('/product-lot')
@login_required
def product_lot_page():
    return render_template('product_lot.html')


@app.route('/api/product-lots', methods=['POST'])
@login_required
@requires('quality.decide')
def create_product_lot():
    """Release one approved Drying Output as an available Product Lot."""
    try:
        data = normalize_keys(request.get_json() or {})
        record = _release_product_lot(data)
        return jsonify({
            'success': True,
            'message': 'Approved Drying Output released as a Product Lot',
            'data': record,
            'record': record,
            'id': record['id'],
            'business_id': record['business_id'],
        }), 201
    except ProductionEventPermissionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 403
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception as exc:
        if getattr(exc, 'pgcode', None) == '23505':
            return jsonify({
                'success': False,
                'message': 'This Drying Output or lot number has already been released',
            }), 409
        logger.exception('Error releasing approved Drying Output as Product Lot')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/api/product-lots/<string:lot_ref>', methods=['GET'])
@login_required
def get_product_lot(lot_ref):
    try:
        with db.transaction() as cursor:
            record = _product_lot_detail(cursor, lot_ref)
        return jsonify({'success': True, 'data': record}), 200
    except ProductionEventPermissionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 403
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 404
    except Exception:
        logger.exception('Error fetching Product Lot detail')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/api/product-lots', methods=['GET'])
@login_required
def list_product_lots():
    try:
        visibility, visibility_params = _scope_visibility_clause('batch')
        filters = []
        filter_params = []
        if request.args.get('farm_id') not in (None, ''):
            filters.append('pl.farm_id = %s')
            filter_params.append(_parse_positive_integer(request.args['farm_id'], 'farm_id'))
        rows = db.fetch_all(
            f"""
            WITH {INVENTORY_LEDGER_CTE}
            SELECT pl.id, pl.business_id, pl.lot_code, pl.product_type,
                   pl.quantity_kg, pl.unit, pl.production_date,
                   pl.farm_id, f.name AS farm_name,
                   batch.business_id AS drying_batch_business_id,
                   batch.source_type,
                   CASE WHEN {PRODUCT_LOT_RELEASABLE_SQL}
                        THEN 'AVAILABLE' ELSE 'BLOCKED' END AS status,
                   COALESCE((
                       SELECT SUM(ledger.delta) FROM ledger
                       WHERE ledger.product_lot_id = pl.id
                   ), 0) AS on_hand_kg
            FROM product_lots AS pl
            JOIN product_lot_origins AS batch ON batch.product_lot_id = pl.id
            JOIN farms AS f ON f.id = pl.farm_id
            WHERE {' AND '.join([visibility, *filters])}
            ORDER BY pl.production_date DESC, pl.id DESC
            LIMIT 500
            """,
            (*visibility_params, *filter_params),
        )
        return jsonify({'success': True, 'data': rows}), 200
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception:
        logger.exception('Error listing Product Lots')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


def _drying_create_quality_check(data):
    batch_ref = data.get('drying_batch_id') or data.get('batch_id') or data.get('batch_code')
    output_ref = data.get('drying_output_id') or data.get('output_id')
    if batch_ref in (None, '') and output_ref in (None, ''):
        raise ValueError('drying_batch_id or batch_code is required')
    inspector = str(data.get('inspector') or data.get('qc_personnel') or '').strip()
    if not inspector:
        raise ValueError('inspector is required')
    status = str(data.get('status') or data.get('check_status') or 'submitted').strip().lower()
    if status not in {'draft', 'submitted', 'passed', 'failed', 'superseded'}:
        raise ValueError('quality check status is invalid')
    moisture = _event_decimal(
        data.get('moisture_percent', data.get('moisture')),
        'moisture_percent',
        minimum=0,
        maximum=100,
    )
    sampled_at = _drying_timestamp(data.get('sampled_at'), 'sampled_at')
    checked_at = _drying_timestamp(data.get('checked_at'), 'checked_at')
    parameters = data.get('parameters') or {}
    if not isinstance(parameters, dict):
        raise ValueError('parameters must be an object')
    with db.transaction() as cursor:
        output = None
        if output_ref not in (None, ''):
            output_id = _parse_positive_integer(output_ref, 'drying_output_id')
            cursor.execute(
                """
                SELECT id, drying_batch_id
                FROM drying_outputs
                WHERE id = %s
                FOR UPDATE
                """,
                (output_id,),
            )
            output = cursor.fetchone()
            if not output:
                raise ValueError('Drying Output not found')
            if batch_ref in (None, ''):
                batch_ref = output['drying_batch_id']
        batch = _drying_batch_row(cursor, batch_ref, for_update=True)
        if output and output['drying_batch_id'] != batch['id']:
            raise ValueError('Drying Output does not belong to this Drying Batch')
        if batch['status'] != 'QC_PENDING':
            raise ValueError('Quality checks can only be recorded while a Drying Batch is QC_PENDING')
        actor, actor_user_id = _drying_actor(data)
        cursor.execute(
            """
            INSERT INTO quality_checks (
                drying_batch_id, drying_output_id, status, moisture_percent, parameters,
                sampled_at, checked_at, inspector, inspector_user_id, notes
            ) VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s)
            RETURNING id, check_code, drying_batch_id, status, moisture_percent,
                      drying_output_id, parameters, sampled_at, checked_at,
                      inspector, notes, created_at
            """,
            (
                batch['id'], output['id'] if output else None, status, moisture,
                json.dumps(parameters),
                sampled_at, checked_at, inspector, actor_user_id, data.get('notes'),
            ),
        )
        return dict(cursor.fetchone())


def _drying_create_quality_approval(data):
    check_id = data.get('quality_check_id') or data.get('check_id')
    if check_id in (None, ''):
        raise ValueError('quality_check_id is required')
    check_id = _parse_positive_integer(check_id, 'quality_check_id')
    decision = str(data.get('decision') or data.get('approval_status') or '').strip().lower()
    if decision not in {'approved', 'rejected', 'conditional', 'revoked'}:
        raise ValueError('decision must be approved, rejected, conditional, or revoked')
    approver = str(data.get('approver') or data.get('reviewed_by') or '').strip()
    if not approver:
        raise ValueError('approver is required')
    with db.transaction() as cursor:
        cursor.execute(
            """
            SELECT qc.id, qc.check_code, qc.drying_batch_id, qc.status,
                   db.status AS batch_status
            FROM quality_checks AS qc
            JOIN drying_batches AS db ON db.id = qc.drying_batch_id
            WHERE qc.id = %s
            FOR UPDATE OF qc, db
            """,
            (check_id,),
        )
        check = cursor.fetchone()
        if not check:
            raise ValueError('Quality check not found')
        batch = _drying_batch_row(cursor, check['drying_batch_id'], for_update=True)
        if batch['status'] != 'QC_PENDING':
            raise ValueError('Quality approval can only be recorded while a Drying Batch is QC_PENDING')
        if decision == 'approved' and check['status'] != 'passed':
            raise ValueError('An approved Drying Batch requires a passed quality check')
        actor, actor_user_id = _drying_actor(data)
        cursor.execute(
            """
            INSERT INTO quality_approvals (
                quality_check_id, decision, rationale, approver, approver_user_id
            ) VALUES (%s, %s, %s, %s, %s)
            RETURNING id, approval_code, quality_check_id, decision,
                      rationale, decided_at, approver, created_at
            """,
            (check_id, decision, data.get('rationale') or data.get('comments'),
             approver, actor_user_id),
        )
        approval = dict(cursor.fetchone())
        if decision == 'approved':
            _drying_transition(cursor, batch, 'COMPLETED', data)
        return approval


def _release_product_lot(data):
    output_ref = data.get('drying_output_id') or data.get('output_id')
    if output_ref in (None, ''):
        raise ValueError('drying_output_id is required')
    output_id = _parse_positive_integer(output_ref, 'drying_output_id')
    product_type = str(data.get('product_type') or '').strip()
    if not product_type:
        raise ValueError('product_type is required')
    if len(product_type) > 50:
        raise ValueError('product_type must be at most 50 characters')

    lot_code = str(data.get('lot_number') or data.get('lot_code') or '').strip() or None
    if lot_code and len(lot_code) > 30:
        raise ValueError('lot_number must be at most 30 characters')
    storage_location = str(data.get('storage_location') or '').strip() or None
    if storage_location and len(storage_location) > 100:
        raise ValueError('storage_location must be at most 100 characters')

    with db.transaction() as cursor:
        cursor.execute(
            """
            SELECT id, drying_batch_id, quantity, unit,
                   (output_date AT TIME ZONE 'UTC')::date AS production_date
            FROM drying_outputs
            WHERE id = %s
            FOR UPDATE
            """,
            (output_id,),
        )
        output = cursor.fetchone()
        if not output:
            raise ValueError('Drying Output not found')

        batch = _drying_batch_row(cursor, output['drying_batch_id'], for_update=True)

        cursor.execute(
            """
            SELECT id, business_id
            FROM product_lots
            WHERE drying_output_id = %s
            """,
            (output_id,),
        )
        if cursor.fetchone():
            raise ValueError('A Product Lot has already been released from this Drying Output')

        cursor.execute(
            """
            SELECT id, check_code, status
            FROM quality_checks
            WHERE drying_output_id = %s
            ORDER BY id DESC
            LIMIT 1
            FOR UPDATE
            """,
            (output_id,),
        )
        check = cursor.fetchone()
        if not check:
            raise ValueError('This Drying Output has no output-specific QC check')

        cursor.execute(
            """
            SELECT id, approval_code, decision, approver, decided_at
            FROM quality_approvals
            WHERE quality_check_id = %s
            ORDER BY id DESC
            LIMIT 1
            FOR UPDATE
            """,
            (check['id'],),
        )
        approval = cursor.fetchone()
        if check['status'] != 'passed' or not approval or approval['decision'] != 'approved':
            raise ValueError(
                'Only a Drying Output with a passed QC check and latest approved decision can become an available Product Lot'
            )

        if batch['status'] != 'COMPLETED':
            raise ValueError('A Product Lot can only be released from a completed Drying Batch')

        # A released lot is received into stock in the same transaction, so
        # every available canonical lot has exactly one RECEIPT in the ledger.
        if data.get('inventory_location_id') in (None, ''):
            raise ValueError('inventory_location_id is required to receive the lot into stock')
        receipt_location = _inventory_location_row(
            cursor, data['inventory_location_id'], 'to'
        )
        if receipt_location['farm_id'] != batch['farm_id']:
            raise ValueError(
                f"Inventory location {receipt_location['location_code']} belongs to a "
                'different farm than the Drying Batch'
            )
        storage_location = storage_location or receipt_location['name']

        if lot_code:
            cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM product_lots WHERE lot_code = %s) AS exists",
                (lot_code,),
            )
            if cursor.fetchone()['exists']:
                raise ValueError('lot_number is already in use')

        quantity_kg = _drying_quantity_kg(output['quantity'], output['unit'])
        actor, _actor_user_id = _drying_actor(data)
        cursor.execute(
            """
            WITH generated AS (
                SELECT 'LOT-' || to_char(%s::date, 'YYYY') || '-' ||
                       lpad(nextval('phase_one_product_lot_seq')::text, 5, '0') AS business_id
            )
            INSERT INTO product_lots (
                lot_code, business_id, drying_output_id, release_approval_id,
                farm_id, product_type, processing_date, production_date,
                quantity_kg, unit, storage_location, status, recorded_by
            )
            SELECT COALESCE(%s, generated.business_id), generated.business_id,
                   %s, %s, %s, %s, %s, %s, %s, 'kg', %s, 'available', %s
            FROM generated
            RETURNING id
            """,
            (
                output['production_date'], lot_code, output['id'], approval['id'],
                batch['farm_id'], product_type, output['production_date'],
                output['production_date'], quantity_kg, storage_location, actor,
            ),
        )
        created = cursor.fetchone()
        _insert_inventory_movement(
            cursor,
            {'id': created['id'], 'farm_id': batch['farm_id']},
            'RECEIPT',
            quantity_kg,
            data,
            to_location=receipt_location,
            occurred_at=None,
            notes='Received on Product Lot release',
            reference_type='quality_approval',
            reference_id=approval['id'],
        )
        return _product_lot_detail(cursor, created['id'])


_SOURCE_CHAIN_FROM_HARVEST = """
        SELECT harvest.id AS harvest_id, harvest.harvest_code,
               harvest.wet_weight, harvest.unit AS harvest_unit,
               production.id AS production_batch_id,
               production.business_id AS production_batch_business_id,
               production.batch_code AS production_batch_code,
               production_input.quantity_issued AS substrate_issued_quantity,
               production_input.unit AS substrate_issued_unit,
               substrate.id AS substrate_batch_id,
               substrate.business_id AS substrate_batch_business_id,
               substrate.batch_code AS substrate_batch_code,
               substrate_input.quantity_used AS waste_input_quantity,
               substrate_input.unit AS waste_input_unit,
               waste.id AS waste_lot_id,
               waste.business_id AS waste_lot_business_id,
               waste.waste_type, waste.source_name,
               waste.quantity AS waste_lot_quantity,
               waste.unit AS waste_lot_unit
        FROM harvests AS harvest
        JOIN production_events AS event ON event.id = harvest.production_event_id
        JOIN production_batches AS production ON production.id = event.production_batch_id
        LEFT JOIN production_batch_inputs AS production_input
          ON production_input.production_batch_id = production.id
        LEFT JOIN substrate_batches AS substrate ON substrate.id = production_input.substrate_batch_id
        LEFT JOIN substrate_batch_inputs AS substrate_input
          ON substrate_input.substrate_batch_id = substrate.id
        LEFT JOIN waste_lots AS waste ON waste.id = substrate_input.waste_lot_id
        WHERE harvest.id = %s
        ORDER BY production.id, substrate.id, waste.id
"""


def _frass_product_lot_detail(cursor, lot_id):
    """A frass fertiliser lot, in the shape the product lot page reads; the
    frass lot stands where a dried larvae lot shows its drying batch."""
    cursor.execute(
        f"""
        SELECT pl.id, pl.business_id, pl.lot_code, pl.product_type,
               pl.quantity_kg AS quantity, pl.quantity_kg, pl.unit,
               pl.production_date, pl.storage_location,
               UPPER(pl.status) AS stored_status, pl.farm_id,
               NULL::bigint AS drying_output_id,
               fl.id AS frass_lot_id, fl.business_id AS drying_batch_business_id,
               'frass lot' AS drying_batch_code, fl.quantity_kg AS frass_separated_kg,
               fl.cured_kg, fl.harvest_id, fl.site_id, fl.facility_id,
               farm.name AS farm_name,
               fq.check_code, fq.status AS qc_status, fq.decision AS approval_status,
               fq.approver AS released_by, fq.decided_at AS released_at,
               CASE WHEN {PRODUCT_LOT_RELEASABLE_SQL} THEN UPPER(pl.status) ELSE 'BLOCKED' END AS status
        FROM product_lots AS pl
        JOIN frass_lots AS fl ON fl.id = pl.frass_lot_id
        JOIN farms AS farm ON farm.id = pl.farm_id
        JOIN frass_quality_checks AS fq ON fq.id = pl.frass_quality_check_id
        WHERE pl.id = %s
        """,
        (lot_id,),
    )
    lot = cursor.fetchone()
    _assert_production_scope_access(cursor, lot['farm_id'], lot['site_id'], lot['facility_id'])
    cursor.execute(_SOURCE_CHAIN_FROM_HARVEST, (lot['harvest_id'],))
    chain = []
    for row in cursor.fetchall():
        row = dict(row)
        row['drying_input_quantity'] = lot['frass_separated_kg']
        row['drying_input_unit'] = 'kg frass'
        chain.append(row)
    result = dict(lot)
    if hasattr(result.get('production_date'), 'isoformat'):
        result['production_date'] = result['production_date'].isoformat()
    result['source_chain'] = chain
    result['source_frass_lot'] = {'id': lot['frass_lot_id'], 'business_id': lot['drying_batch_business_id']}
    result['inventory'] = _inventory_summary(cursor, lot['id'])
    return result


def _product_lot_detail(cursor, lot_ref):
    lookup_id = int(lot_ref) if str(lot_ref).isdigit() else -1
    cursor.execute(
        "SELECT id FROM product_lots WHERE frass_lot_id IS NOT NULL AND (id = %s OR business_id = %s OR lot_code = %s)",
        (lookup_id, str(lot_ref), str(lot_ref)),
    )
    frass = cursor.fetchone()
    if frass:
        return _frass_product_lot_detail(cursor, frass['id'])
    cursor.execute(
        """
        SELECT pl.id, pl.business_id, pl.lot_code, pl.product_type,
               pl.quantity_kg AS quantity, pl.quantity_kg, pl.unit,
               pl.production_date, pl.storage_location,
               UPPER(pl.status) AS stored_status,
               pl.drying_output_id, pl.release_approval_id, pl.farm_id,
               output.quantity AS output_quantity, output.unit AS output_unit,
               output.moisture_percent AS output_moisture_percent,
               output.output_date, batch.id AS drying_batch_id,
               batch.batch_code AS drying_batch_code,
               batch.business_id AS drying_batch_business_id,
               UPPER(batch.status) AS drying_batch_status,
               batch.site_id, batch.facility_id,
               farm.name AS farm_name,
               check_row.id AS quality_check_id,
               check_row.check_code, check_row.status AS qc_status,
               release_approval.approval_code AS release_approval_code,
               release_approval.decision AS release_decision,
               release_approval.approver AS released_by,
               release_approval.decided_at AS released_at,
               latest_approval.decision AS approval_status,
               CASE
                   WHEN check_row.status = 'passed'
                    AND latest_approval.decision = 'approved'
                   THEN UPPER(pl.status)
                   ELSE 'BLOCKED'
               END AS status
        FROM product_lots AS pl
        JOIN drying_outputs AS output ON output.id = pl.drying_output_id
        JOIN drying_batches AS batch ON batch.id = output.drying_batch_id
        JOIN farms AS farm ON farm.id = pl.farm_id
        JOIN quality_approvals AS release_approval
          ON release_approval.id = pl.release_approval_id
        JOIN quality_checks AS check_row
          ON check_row.id = release_approval.quality_check_id
        LEFT JOIN LATERAL (
            SELECT decision
            FROM quality_approvals
            WHERE quality_check_id = check_row.id
            ORDER BY id DESC
            LIMIT 1
        ) AS latest_approval ON TRUE
        WHERE pl.drying_output_id IS NOT NULL
          AND (pl.id = %s OR pl.business_id = %s OR pl.lot_code = %s)
        """,
        (lookup_id, str(lot_ref), str(lot_ref)),
    )
    lot = cursor.fetchone()
    if not lot:
        raise ValueError('Canonical Product Lot not found')
    _assert_production_scope_access(
        cursor, lot['farm_id'], lot['site_id'], lot['facility_id']
    )

    cursor.execute(
        """
        SELECT di.id AS drying_input_id, di.quantity AS drying_input_quantity,
               di.unit AS drying_input_unit,
               harvest.id AS harvest_id, harvest.harvest_code,
               harvest.wet_weight, harvest.unit AS harvest_unit,
               production.id AS production_batch_id,
               production.business_id AS production_batch_business_id,
               production.batch_code AS production_batch_code,
               production_input.quantity_issued AS substrate_issued_quantity,
               production_input.unit AS substrate_issued_unit,
               substrate.id AS substrate_batch_id,
               substrate.business_id AS substrate_batch_business_id,
               substrate.batch_code AS substrate_batch_code,
               substrate_input.quantity_used AS waste_input_quantity,
               substrate_input.unit AS waste_input_unit,
               waste.id AS waste_lot_id,
               waste.business_id AS waste_lot_business_id,
               waste.waste_type, waste.source_name,
               waste.quantity AS waste_lot_quantity,
               waste.unit AS waste_lot_unit
        FROM drying_inputs AS di
        JOIN harvests AS harvest ON harvest.id = di.harvest_id
        JOIN production_events AS event
          ON event.id = harvest.production_event_id
        JOIN production_batches AS production
          ON production.id = event.production_batch_id
        LEFT JOIN production_batch_inputs AS production_input
          ON production_input.production_batch_id = production.id
        LEFT JOIN substrate_batches AS substrate
          ON substrate.id = production_input.substrate_batch_id
        LEFT JOIN substrate_batch_inputs AS substrate_input
          ON substrate_input.substrate_batch_id = substrate.id
        LEFT JOIN waste_lots AS waste
          ON waste.id = substrate_input.waste_lot_id
        WHERE di.drying_batch_id = %s
        ORDER BY harvest.id, production.id, substrate.id, waste.id
        """,
        (lot['drying_batch_id'],),
    )
    result = dict(lot)
    production_date = result.get('production_date')
    if production_date is not None and hasattr(production_date, 'isoformat'):
        result['production_date'] = production_date.isoformat()
    result['source_chain'] = [dict(row) for row in cursor.fetchall()]
    result['source_drying_batch'] = {
        'id': lot['drying_batch_id'],
        'business_id': lot['drying_batch_business_id'],
        'batch_code': lot['drying_batch_code'],
        'status': lot['drying_batch_status'],
    }
    result['inventory'] = _inventory_summary(cursor, lot['id'])
    return result


@app.route('/api/drying/batches/<string:batch_ref>/quality-checks', methods=['POST'])
@login_required
@requires('quality.decide')
def create_canonical_drying_quality_check(batch_ref):
    data = normalize_keys(request.get_json() or {})
    data['drying_batch_id'] = batch_ref
    return _canonical_quality_check_response(data)


@app.route('/api/drying/outputs/<int:output_id>/quality-checks', methods=['POST'])
@login_required
@requires('quality.decide')
def create_canonical_drying_output_quality_check(output_id):
    data = normalize_keys(request.get_json() or {})
    data['drying_output_id'] = output_id
    return _canonical_quality_check_response(data)


def _canonical_quality_check_response(data):
    try:
        record = _drying_create_quality_check(data)
        return jsonify({'success': True, 'message': 'Drying quality check recorded', 'data': record}), 201
    except ProductionEventPermissionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 403
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception:
        logger.exception('Error recording canonical Drying quality check')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/api/drying/quality-approvals', methods=['POST'])
@login_required
@requires('quality.decide')
def create_canonical_drying_quality_approval():
    try:
        data = normalize_keys(request.get_json() or {})
        record = _drying_create_quality_approval(data)
        return jsonify({'success': True, 'message': 'Drying quality approval recorded', 'data': record}), 201
    except ProductionEventPermissionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 403
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception:
        logger.exception('Error recording canonical Drying quality approval')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/api/drying/batches/<string:batch_ref>/quality-approvals', methods=['POST'])
@login_required
@requires('quality.decide')
def create_canonical_drying_batch_quality_approval(batch_ref):
    data = normalize_keys(request.get_json() or {})
    data['drying_batch_id'] = batch_ref
    try:
        check_id = data.get('quality_check_id') or data.get('check_id')
        if check_id in (None, ''):
            raise ValueError('quality_check_id is required')
        check_id = _parse_positive_integer(check_id, 'quality_check_id')
        with db.transaction() as cursor:
            cursor.execute(
                """
                SELECT qc.drying_batch_id
                FROM quality_checks AS qc
                WHERE qc.id = %s
                """,
                (check_id,),
            )
            check = cursor.fetchone()
            if not check:
                raise ValueError('Quality check not found')
            batch = _drying_batch_row(cursor, batch_ref)
            if check['drying_batch_id'] != batch['id']:
                raise ValueError('Quality check does not belong to this Drying Batch')
        return create_canonical_drying_quality_approval()
    except ProductionEventPermissionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 403
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
