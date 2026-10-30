"""Frass sold as fertiliser: the frass lot a harvest separates (FRS-), its
curing checks, the weight once cured, a quality check and decision (FQC-),
and release into stock as a product lot of type ``frass_fertilizer``, which
customer orders then reserve and dispatch like dried larvae.

Each step needs the one before it: checks only while curing, a quality
check only once cured, release only after the latest check passed and was
approved (the database enforces that too)."""

from flask import jsonify, request
from flask_login import login_required

from backend.core.web import app, db, logger
from backend.core.http import (
    ProductionEventPermissionError,
    _event_decimal,
    _parse_positive_integer,
    _production_actor,
    normalize_keys,
)
from backend.core.security import requires
from backend.core.scope import (
    _assert_production_scope_access,
    _optional_scope_filters,
    _scope_visibility_clause,
)
from backend.domains.drying import _drying_timestamp
from backend.domains.inventory import _insert_inventory_movement, _inventory_location_row

FRASS_PRODUCT = 'frass_fertilizer'
CONTAMINANTS = ('plastic', 'metal', 'glass', 'stones', 'larvae', 'other')


def _frass_lot(cursor, lot_ref):
    """Lock a frass lot the caller may act on."""
    lookup_id = int(lot_ref) if str(lot_ref).isdigit() else -1
    cursor.execute(
        """
        SELECT fl.*, pb.business_id AS production_batch, h.harvest_code
        FROM frass_lots AS fl
        JOIN production_batches AS pb ON pb.id = fl.production_batch_id
        JOIN harvests AS h ON h.id = fl.harvest_id
        WHERE fl.id = %s OR fl.business_id = %s
        FOR UPDATE OF fl
        """,
        (lookup_id, str(lot_ref)),
    )
    lot = cursor.fetchone()
    if not lot:
        raise LookupError('Frass lot not found')
    _assert_production_scope_access(cursor, lot['farm_id'], lot['site_id'], lot['facility_id'])
    return lot


def _respond(work, success_status=200):
    try:
        return jsonify({'success': True, **work()}), success_status
    except ProductionEventPermissionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 403
    except LookupError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 404
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception:
        logger.exception('Frass request failed')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


def _text(data, name, maximum, required=False):
    value = str(data.get(name) or '').strip()
    if required and not value:
        raise ValueError(f'{name} is required')
    if len(value) > maximum:
        raise ValueError(f'{name} must be at most {maximum} characters')
    return value or None


@app.route('/api/frass/lots', methods=['GET'])
@login_required
def list_frass_lots():
    def work():
        visibility, params = _scope_visibility_clause('fl')
        filters, filter_params = _optional_scope_filters('fl')
        status = str(request.args.get('status') or '').strip().upper()
        if status:
            filters.append('fl.status = %s')
            filter_params.append(status)
        lots = db.fetch_all(
            f"""
            SELECT fl.id, fl.business_id, fl.status, fl.quantity_kg, fl.cured_kg,
                   fl.curing_started_at, fl.cured_at, fl.farm_id, fl.site_id, fl.facility_id,
                   fa.name AS facility_name, pb.business_id AS production_batch, h.harvest_code,
                   (SELECT COUNT(*) FROM frass_curing_checks AS c WHERE c.frass_lot_id = fl.id) AS curing_checks,
                   (SELECT json_build_object('id', q.id, 'check_code', q.check_code, 'status', q.status,
                                             'maturity', q.maturity, 'decision', q.decision)
                      FROM frass_quality_checks AS q WHERE q.frass_lot_id = fl.id
                      ORDER BY q.id DESC LIMIT 1) AS latest_check,
                   (SELECT pl.business_id FROM product_lots AS pl WHERE pl.frass_lot_id = fl.id) AS product_lot
            FROM frass_lots AS fl
            JOIN production_batches AS pb ON pb.id = fl.production_batch_id
            JOIN harvests AS h ON h.id = fl.harvest_id
            JOIN facilities AS fa ON fa.id = fl.facility_id
            WHERE {' AND '.join([visibility, *filters])}
            ORDER BY fl.id DESC
            LIMIT 200
            """,
            (*params, *filter_params),
        )
        return {'data': lots}
    return _respond(work)


@app.route('/api/frass/lots/<string:lot_ref>/curing-checks', methods=['POST'])
@login_required
@requires('production.write')
def record_frass_curing_check(lot_ref):
    data = normalize_keys(request.get_json() or {})

    def work():
        checked_at = _drying_timestamp(data.get('checked_at'), 'checked_at') or None
        temperature = _event_decimal(data.get('temperature_c'), 'temperature_c', minimum='-10', maximum='90')
        moisture = _event_decimal(data.get('moisture_percent'), 'moisture_percent', minimum=0, maximum=100)
        if temperature is None and moisture is None:
            raise ValueError('Record the temperature, the moisture, or both')
        actor, actor_user_id = _production_actor(data)
        with db.transaction() as cursor:
            lot = _frass_lot(cursor, lot_ref)
            if lot['status'] != 'CURING':
                raise ValueError(f"{lot['business_id']} is no longer curing")
            cursor.execute(
                """
                INSERT INTO frass_curing_checks (
                    frass_lot_id, checked_at, temperature_c, moisture_percent, notes,
                    recorded_by, recorded_by_user_id
                ) VALUES (%s, COALESCE(%s, now()), %s, %s, %s, %s, %s)
                RETURNING id, checked_at, temperature_c, moisture_percent
                """,
                (lot['id'], checked_at, temperature, moisture, _text(data, 'notes', 1000), actor, actor_user_id),
            )
            check = cursor.fetchone()
        return {'message': f"Curing check recorded for {lot['business_id']}", 'business_id': lot['business_id'],
                'data': check}
    return _respond(work, 201)


@app.route('/api/frass/lots/<string:lot_ref>/cured', methods=['POST'])
@login_required
@requires('production.write')
def finish_frass_curing(lot_ref):
    data = normalize_keys(request.get_json() or {})

    def work():
        cured_kg = _event_decimal(data.get('cured_kg'), 'cured_kg', minimum='0.001', required=True)
        cured_at = _drying_timestamp(data.get('cured_at'), 'cured_at') or None
        with db.transaction() as cursor:
            lot = _frass_lot(cursor, lot_ref)
            if lot['status'] != 'CURING':
                raise ValueError(f"{lot['business_id']} has already finished curing")
            cursor.execute("SELECT COUNT(*) AS n FROM frass_curing_checks WHERE frass_lot_id = %s", (lot['id'],))
            if not cursor.fetchone()['n']:
                raise ValueError('Record at least one curing check before finishing curing')
            if cured_kg > lot['quantity_kg']:
                raise ValueError(
                    f"The cured weight cannot be more than the {lot['quantity_kg']} kg separated at harvest")
            cursor.execute(
                """
                UPDATE frass_lots
                SET status = 'QC_PENDING', cured_kg = %s, cured_at = COALESCE(%s, now()), updated_at = now()
                WHERE id = %s
                RETURNING business_id, status, quantity_kg, cured_kg, cured_at
                """,
                (cured_kg, cured_at, lot['id']),
            )
            updated = cursor.fetchone()
        return {'message': f"{lot['business_id']} cured: {cured_kg} kg, waiting for a quality check",
                'business_id': lot['business_id'], 'data': updated}
    return _respond(work)


@app.route('/api/frass/lots/<string:lot_ref>/quality-checks', methods=['POST'])
@login_required
@requires('quality.decide')
def record_frass_quality_check(lot_ref):
    data = normalize_keys(request.get_json() or {})

    def work():
        status = str(data.get('status') or '').strip().lower()
        if status not in ('passed', 'failed'):
            raise ValueError('status must be passed or failed')
        maturity = str(data.get('maturity') or '').strip().lower()
        if maturity not in ('mature', 'immature'):
            raise ValueError('maturity must be mature or immature')
        moisture = _event_decimal(data.get('moisture_percent'), 'moisture_percent', minimum=0, maximum=100)
        contaminants = data.get('contaminants') or []
        if isinstance(contaminants, str):
            contaminants = [contaminants]
        contaminants = [str(c).strip().lower() for c in contaminants if str(c).strip()]
        unknown = [c for c in contaminants if c not in CONTAMINANTS]
        if unknown:
            raise ValueError('Unknown contaminant: ' + ', '.join(unknown))
        if status == 'passed' and (maturity != 'mature' or contaminants):
            raise ValueError('Frass with contaminants or not yet mature cannot pass')
        actor, actor_user_id = _production_actor(data)
        inspector = _text(data, 'inspector', 100) or actor
        checked_at = _drying_timestamp(data.get('checked_at'), 'checked_at') or None
        with db.transaction() as cursor:
            lot = _frass_lot(cursor, lot_ref)
            if lot['status'] not in ('QC_PENDING', 'REJECTED'):
                raise ValueError(f"{lot['business_id']} is not waiting for a quality check ({lot['status'].lower()})")
            cursor.execute(
                """
                INSERT INTO frass_quality_checks (
                    check_code, frass_lot_id, status, moisture_percent, maturity, contaminants,
                    notes, inspector, inspector_user_id, checked_at
                ) VALUES (
                    'FQC-' || to_char(COALESCE(%s::timestamptz, now()), 'YYYY') || '-' ||
                        lpad(nextval('phase_one_frass_check_seq')::text, 5, '0'),
                    %s, %s, %s, %s, %s, %s, %s, %s, COALESCE(%s, now())
                )
                RETURNING id, check_code, status, maturity
                """,
                (checked_at, lot['id'], status, moisture, maturity, ','.join(contaminants) or None,
                 _text(data, 'notes', 1000), inspector, actor_user_id, checked_at),
            )
            check = cursor.fetchone()
            cursor.execute("UPDATE frass_lots SET status = 'QC_PENDING', updated_at = now() WHERE id = %s",
                           (lot['id'],))
        return {'message': f"Quality check {check['check_code']} recorded for {lot['business_id']}: {status}",
                'data': check}
    return _respond(work, 201)


@app.route('/api/frass/quality-checks/<int:check_id>/decision', methods=['POST'])
@login_required
@requires('quality.decide')
def decide_frass_quality_check(check_id):
    data = normalize_keys(request.get_json() or {})

    def work():
        decision = str(data.get('decision') or '').strip().lower()
        if decision not in ('approved', 'rejected'):
            raise ValueError('decision must be approved or rejected')
        rationale = _text(data, 'rationale', 1000)
        if decision == 'rejected' and not rationale:
            raise ValueError('Give a reason for rejecting')
        actor, actor_user_id = _production_actor(data)
        with db.transaction() as cursor:
            cursor.execute("SELECT * FROM frass_quality_checks WHERE id = %s FOR UPDATE", (check_id,))
            check = cursor.fetchone()
            if not check:
                raise LookupError('Frass quality check not found')
            lot = _frass_lot(cursor, check['frass_lot_id'])
            cursor.execute("SELECT MAX(id) AS latest FROM frass_quality_checks WHERE frass_lot_id = %s", (lot['id'],))
            if cursor.fetchone()['latest'] != check['id']:
                raise ValueError('A newer quality check exists for this lot; decide on that one')
            if check['decision']:
                raise ValueError(f"{check['check_code']} was already {check['decision']}")
            if decision == 'approved' and check['status'] != 'passed':
                raise ValueError('Only a passed quality check can be approved')
            if lot['status'] != 'QC_PENDING':
                raise ValueError(f"{lot['business_id']} is not waiting for a decision")
            approver = _text(data, 'approver', 100) or actor
            cursor.execute(
                """
                UPDATE frass_quality_checks
                SET decision = %s, rationale = %s, approver = %s, approver_user_id = %s, decided_at = now()
                WHERE id = %s
                """,
                (decision, rationale, approver, actor_user_id, check['id']),
            )
            new_status = 'APPROVED' if decision == 'approved' else 'REJECTED'
            cursor.execute("UPDATE frass_lots SET status = %s, updated_at = now() WHERE id = %s",
                           (new_status, lot['id']))
        return {'message': f"{lot['business_id']} {decision}", 'business_id': lot['business_id'],
                'data': {'check_code': check['check_code'], 'decision': decision}}
    return _respond(work)


@app.route('/api/frass/lots/<string:lot_ref>/release', methods=['POST'])
@login_required
@requires('quality.decide')
def release_frass_lot(lot_ref):
    data = normalize_keys(request.get_json() or {})

    def work():
        if data.get('inventory_location_id') in (None, ''):
            raise ValueError('inventory_location_id is required to receive the fertiliser into stock')
        lot_code = _text(data, 'lot_number', 30)
        with db.transaction() as cursor:
            lot = _frass_lot(cursor, lot_ref)
            if lot['status'] != 'APPROVED':
                raise ValueError(f"{lot['business_id']} must be approved before it can be released")
            cursor.execute(
                "SELECT id FROM frass_quality_checks WHERE frass_lot_id = %s ORDER BY id DESC LIMIT 1",
                (lot['id'],),
            )
            check = cursor.fetchone()
            location = _inventory_location_row(cursor, data['inventory_location_id'], 'to')
            if location['farm_id'] != lot['farm_id']:
                raise ValueError(f"Store {location['location_code']} belongs to a different farm than {lot['business_id']}")
            if lot_code:
                cursor.execute("SELECT EXISTS (SELECT 1 FROM product_lots WHERE lot_code = %s) AS taken", (lot_code,))
                if cursor.fetchone()['taken']:
                    raise ValueError('lot_number is already in use')
            actor, _actor_user_id = _production_actor(data)
            produced = lot['cured_at'].date() if lot['cured_at'] else None
            cursor.execute(
                """
                WITH generated AS (
                    SELECT 'LOT-' || to_char(%s::date, 'YYYY') || '-' ||
                           lpad(nextval('phase_one_product_lot_seq')::text, 5, '0') AS business_id
                )
                INSERT INTO product_lots (
                    lot_code, business_id, frass_lot_id, frass_quality_check_id, farm_id,
                    product_type, processing_date, production_date, quantity_kg, unit,
                    storage_location, status, recorded_by
                )
                SELECT COALESCE(%s, generated.business_id), generated.business_id, %s, %s, %s,
                       %s, %s, %s, %s, 'kg', %s, 'available', %s
                FROM generated
                RETURNING id, business_id, quantity_kg
                """,
                (produced, lot_code, lot['id'], check['id'], lot['farm_id'], FRASS_PRODUCT,
                 produced, produced, lot['cured_kg'], location['name'], actor),
            )
            product = cursor.fetchone()
            _insert_inventory_movement(
                cursor, {'id': product['id'], 'farm_id': lot['farm_id']}, 'RECEIPT', lot['cured_kg'], data,
                to_location=location, notes=f"Frass fertiliser released from {lot['business_id']}",
                reference_type='frass_quality_check', reference_id=check['id'],
            )
            cursor.execute("UPDATE frass_lots SET status = 'RELEASED', updated_at = now() WHERE id = %s",
                           (lot['id'],))
        return {'message': f"{lot['business_id']} released as {product['business_id']}: "
                           f"{product['quantity_kg']} kg frass fertiliser in {location['name']}",
                'data': {'business_id': product['business_id'], 'quantity_kg': product['quantity_kg']}}
    return _respond(work, 201)
