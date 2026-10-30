"""Product Lot inventory ledger, stock locations and balances."""

from decimal import Decimal
from flask import jsonify, request
from flask_login import login_required

from backend.core.web import app, db, logger
from backend.core.http import (
    InventoryConflictError,
    ProductionEventPermissionError,
    RecordNotFoundError,
    _event_occurred_at,
    _optional_text,
    _parse_chain_quantity,
    _parse_positive_integer,
    _production_actor,
    normalize_keys,
)
from backend.core.security import _can, requires, super_admin_required
from backend.core.scope import (
    _assert_production_location,
    _assert_production_scope_access,
    _optional_scope_filters,
    _production_scope_values,
    _scope_visibility_clause,
)


INVENTORY_MOVEMENT_TYPES = {
    'RECEIPT', 'TRANSFER', 'ADJUSTMENT_IN', 'ADJUSTMENT_OUT', 'WASTAGE',
}
# Adjustments and write-offs change stock without a physical receipt, so they
# need an administrator and a written reason.  This is the interim rule until
# Phase One RBAC introduces dedicated inventory roles.
INVENTORY_PRIVILEGED_TYPES = {'ADJUSTMENT_IN', 'ADJUSTMENT_OUT', 'WASTAGE'}
INVENTORY_INBOUND_TYPES = {'RECEIPT', 'ADJUSTMENT_IN'}
INVENTORY_OUTBOUND_TYPES = {'ADJUSTMENT_OUT', 'WASTAGE'}

# True when the lot's release is still backed by the latest approved decision
# on a passing check: the QC approval for dried larvae, or the frass quality
# check for frass fertiliser.  ``pl`` must alias product_lots.
PRODUCT_LOT_RELEASABLE_SQL = """
    (EXISTS (
        SELECT 1
        FROM quality_approvals AS rel_qa
        JOIN quality_checks AS rel_qc ON rel_qc.id = rel_qa.quality_check_id
        WHERE rel_qa.id = pl.release_approval_id
          AND rel_qc.status = 'passed'
          AND (
              SELECT latest.decision
              FROM quality_approvals AS latest
              WHERE latest.quality_check_id = rel_qc.id
              ORDER BY latest.id DESC
              LIMIT 1
          ) = 'approved'
    ) OR EXISTS (
        SELECT 1
        FROM frass_quality_checks AS rel_fq
        WHERE rel_fq.id = pl.frass_quality_check_id
          AND rel_fq.status = 'passed'
          AND rel_fq.decision = 'approved'
          AND rel_fq.id = (SELECT MAX(latest_fq.id) FROM frass_quality_checks AS latest_fq
                           WHERE latest_fq.frass_lot_id = rel_fq.frass_lot_id)
    ))
"""

# One signed row per ledger leg: a transfer contributes -qty to its source
# and +qty to its destination.
INVENTORY_LEDGER_CTE = """
    ledger AS (
        SELECT product_lot_id, to_location_id AS location_id,
               quantity_kg AS delta, occurred_at, id
        FROM inventory_movements
        WHERE status = 'posted' AND to_location_id IS NOT NULL
        UNION ALL
        SELECT product_lot_id, from_location_id AS location_id,
               -quantity_kg AS delta, occurred_at, id
        FROM inventory_movements
        WHERE status = 'posted' AND from_location_id IS NOT NULL
    )
"""


# Outstanding (still reserved) quantity per allocation: allocated minus what
# has been dispatched and what was released back to stock.
ALLOCATION_STATE_CTE = """
    allocation_state AS (
        SELECT a.id, a.order_line_id, a.product_lot_id, a.location_id,
               a.quantity_kg, a.released_kg,
               COALESCE((
                   SELECT SUM(dl.quantity_kg) FROM customer_delivery_lines AS dl
                   WHERE dl.allocation_id = a.id
               ), 0) AS dispatched_kg
        FROM order_allocations AS a
    )
"""


def _reserved_kg(cursor, lot_id, location_id):
    cursor.execute(
        f"""
        WITH {ALLOCATION_STATE_CTE}
        SELECT COALESCE(SUM(quantity_kg - released_kg - dispatched_kg), 0) AS reserved
        FROM allocation_state
        WHERE product_lot_id = %s AND location_id = %s
        """,
        (lot_id, location_id),
    )
    return Decimal(str(cursor.fetchone()['reserved']))


def _is_inventory_administrator():
    return _can('inventory.adjust')


def _inventory_location_row(cursor, location_ref, label):
    location_id = _parse_positive_integer(location_ref, f'{label}_location_id')
    cursor.execute(
        """
        SELECT il.id, il.location_code, il.name, il.farm_id, il.site_id,
               il.facility_id, il.status, fa.name AS facility_name
        FROM inventory_locations AS il
        JOIN facilities AS fa ON fa.id = il.facility_id
        WHERE il.id = %s
        """,
        (location_id,),
    )
    location = cursor.fetchone()
    if not location:
        raise ValueError(f'The {label} inventory location does not exist')
    if location['status'] != 'active':
        raise ValueError(f"Inventory location {location['location_code']} is inactive")
    _assert_production_scope_access(
        cursor, location['farm_id'], location['site_id'], location['facility_id']
    )
    return location


def _inventory_lot_row(cursor, lot_ref):
    """Lock a canonical Product Lot and check the caller may act on it."""
    lookup_id = int(lot_ref) if str(lot_ref).isdigit() else -1
    cursor.execute(
        f"""
        SELECT pl.id, pl.business_id, pl.lot_code, pl.product_type,
               pl.quantity_kg, pl.farm_id, pl.release_approval_id,
               batch.site_id, batch.facility_id,
               {PRODUCT_LOT_RELEASABLE_SQL} AS releasable
        FROM product_lots AS pl
        JOIN product_lot_origins AS batch ON batch.product_lot_id = pl.id
        WHERE (pl.id = %s OR pl.business_id = %s OR pl.lot_code = %s)
        FOR UPDATE OF pl
        """,
        (lookup_id, str(lot_ref), str(lot_ref)),
    )
    lot = cursor.fetchone()
    if not lot:
        raise RecordNotFoundError('Canonical Product Lot not found')
    _assert_production_scope_access(
        cursor, lot['farm_id'], lot['site_id'], lot['facility_id']
    )
    return lot


def _inventory_balances(cursor, lot_id):
    cursor.execute(
        f"""
        WITH {INVENTORY_LEDGER_CTE}, {ALLOCATION_STATE_CTE}
        SELECT il.id AS location_id, il.location_code, il.name AS location_name,
               fa.name AS facility_name, SUM(ledger.delta) AS quantity_kg,
               MAX(ledger.occurred_at) AS last_movement_at,
               COALESCE((
                   SELECT SUM(s.quantity_kg - s.released_kg - s.dispatched_kg)
                   FROM allocation_state AS s
                   WHERE s.product_lot_id = %s AND s.location_id = il.id
               ), 0) AS reserved_kg
        FROM ledger
        JOIN inventory_locations AS il ON il.id = ledger.location_id
        JOIN facilities AS fa ON fa.id = il.facility_id
        WHERE ledger.product_lot_id = %s
        GROUP BY il.id, fa.name
        HAVING SUM(ledger.delta) <> 0
        ORDER BY il.name, il.id
        """,
        (lot_id, lot_id),
    )
    rows = [dict(row) for row in cursor.fetchall()]
    for row in rows:
        row['free_kg'] = Decimal(str(row['quantity_kg'])) - Decimal(str(row['reserved_kg']))
    return rows


def _inventory_movement_history(cursor, lot_id):
    cursor.execute(
        """
        SELECT im.id, im.business_id, im.movement_type, im.quantity_kg,
               im.unit, im.status, im.occurred_at, im.posted_at, im.reason,
               im.notes, im.reference_type, im.reference_id, im.recorded_by,
               src.location_code AS from_location_code,
               src.name AS from_location_name,
               dst.location_code AS to_location_code,
               dst.name AS to_location_name
        FROM inventory_movements AS im
        LEFT JOIN inventory_locations AS src ON src.id = im.from_location_id
        LEFT JOIN inventory_locations AS dst ON dst.id = im.to_location_id
        WHERE im.product_lot_id = %s
          AND (im.from_location_id IS NOT NULL OR im.to_location_id IS NOT NULL)
        ORDER BY im.occurred_at, im.id
        """,
        (lot_id,),
    )
    return [dict(row) for row in cursor.fetchall()]


def _inventory_summary(cursor, lot_id):
    balances = _inventory_balances(cursor, lot_id)
    return {
        'on_hand_kg': sum(
            (Decimal(str(row['quantity_kg'])) for row in balances), Decimal('0')
        ),
        'unit': 'kg',
        'balances': balances,
        'movements': _inventory_movement_history(cursor, lot_id),
    }


def _insert_inventory_movement(
    cursor, lot, movement_type, quantity_kg, data, *, from_location=None,
    to_location=None, occurred_at=None, reason=None, notes=None,
    reference_type=None, reference_id=None,
):
    actor, actor_user_id = _production_actor(data)
    cursor.execute(
        """
        INSERT INTO inventory_movements (
            product_lot_id, farm_id, movement_type, quantity_kg, unit,
            from_location_id, to_location_id, status, occurred_at, posted_at,
            reason, notes, reference_type, reference_id, recorded_by,
            actor_user_id
        ) VALUES (
            %s, %s, %s, %s, 'kg', %s, %s, 'posted',
            COALESCE(%s, CURRENT_TIMESTAMP), CURRENT_TIMESTAMP,
            %s, %s, %s, %s, %s, %s
        )
        RETURNING id, business_id, product_lot_id, farm_id, movement_type,
                  quantity_kg, unit, from_location_id, to_location_id, status,
                  occurred_at, posted_at, reason, notes, reference_type,
                  reference_id, recorded_by
        """,
        (
            lot['id'], lot['farm_id'], movement_type, quantity_kg,
            from_location['id'] if from_location else None,
            to_location['id'] if to_location else None,
            occurred_at, reason, notes, reference_type, reference_id,
            actor, actor_user_id,
        ),
    )
    return dict(cursor.fetchone())


def _location_balance(cursor, lot_id, location_id):
    cursor.execute(
        """
        SELECT
            COALESCE(SUM(quantity_kg) FILTER (WHERE to_location_id = %s), 0)
          - COALESCE(SUM(quantity_kg) FILTER (WHERE from_location_id = %s), 0)
            AS balance
        FROM inventory_movements
        WHERE product_lot_id = %s AND status = 'posted'
        """,
        (location_id, location_id, lot_id),
    )
    return Decimal(str(cursor.fetchone()['balance']))


def _record_inventory_movement(data):
    movement_type = str(data.get('movement_type') or '').strip().upper()
    if movement_type not in INVENTORY_MOVEMENT_TYPES:
        raise ValueError(
            'movement_type must be one of: ' + ', '.join(sorted(INVENTORY_MOVEMENT_TYPES))
        )
    lot_ref = data.get('product_lot_id') or data.get('product_lot')
    if lot_ref in (None, ''):
        raise ValueError('product_lot_id is required')
    quantity = _parse_chain_quantity(
        data.get('quantity_kg', data.get('quantity')), 'quantity_kg'
    )
    if str(data.get('unit') or 'kg').strip().lower() != 'kg':
        raise ValueError('Inventory quantities must be recorded in kg')
    reason = _optional_text(data, 'reason', 500)
    notes = _optional_text(data, 'notes', 2000)
    occurred_at = None
    if data.get('occurred_at') not in (None, ''):
        occurred_at = _event_occurred_at({'occurred_at': data['occurred_at']}, ())
    if movement_type in INVENTORY_PRIVILEGED_TYPES:
        if not _is_inventory_administrator():
            raise ProductionEventPermissionError(
                'Your role does not allow stock adjustments or wastage'
            )
        if not reason:
            raise ValueError(f'A reason is required for {movement_type}')

    needs_source = movement_type in INVENTORY_OUTBOUND_TYPES or movement_type == 'TRANSFER'
    needs_destination = movement_type in INVENTORY_INBOUND_TYPES or movement_type == 'TRANSFER'
    source_ref = data.get('from_location_id')
    destination_ref = data.get('to_location_id')
    if needs_source != (source_ref not in (None, '')):
        raise ValueError(
            f"{movement_type} {'requires' if needs_source else 'must not have'} a from_location_id"
        )
    if needs_destination != (destination_ref not in (None, '')):
        raise ValueError(
            f"{movement_type} {'requires' if needs_destination else 'must not have'} a to_location_id"
        )

    with db.transaction() as cursor:
        # Locking the lot serializes every movement for it, so balance checks
        # below cannot race with a concurrent withdrawal.
        lot = _inventory_lot_row(cursor, lot_ref)
        source = _inventory_location_row(cursor, source_ref, 'from') if needs_source else None
        destination = (
            _inventory_location_row(cursor, destination_ref, 'to') if needs_destination else None
        )
        for location in (source, destination):
            if location and location['farm_id'] != lot['farm_id']:
                raise ValueError(
                    f"Inventory location {location['location_code']} belongs to a different farm "
                    f"than Product Lot {lot['business_id']}"
                )
        if source and destination and source['id'] == destination['id']:
            raise ValueError('A transfer needs two different inventory locations')
        if (movement_type in INVENTORY_INBOUND_TYPES or movement_type == 'TRANSFER') \
                and not lot['releasable']:
            raise ValueError(
                f"Product Lot {lot['business_id']} is blocked by QC and cannot be received or moved"
            )

        released = Decimal(str(lot['quantity_kg']))
        if movement_type == 'RECEIPT':
            cursor.execute(
                """
                SELECT 1 FROM inventory_movements
                WHERE product_lot_id = %s AND movement_type = 'RECEIPT'
                  AND status = 'posted'
                """,
                (lot['id'],),
            )
            if cursor.fetchone():
                raise InventoryConflictError(
                    f"Product Lot {lot['business_id']} has already been received into inventory"
                )
            if quantity != released:
                raise ValueError(
                    f'A RECEIPT must receive the full released quantity of {released:.3f} kg'
                )
        if movement_type == 'ADJUSTMENT_IN':
            cursor.execute(
                """
                SELECT
                    COALESCE(SUM(quantity_kg) FILTER (WHERE to_location_id IS NOT NULL), 0)
                  - COALESCE(SUM(quantity_kg) FILTER (WHERE from_location_id IS NOT NULL), 0)
                    AS on_hand
                FROM inventory_movements
                WHERE product_lot_id = %s AND status = 'posted'
                """,
                (lot['id'],),
            )
            on_hand = Decimal(str(cursor.fetchone()['on_hand']))
            if on_hand + quantity > released:
                raise ValueError(
                    f'Stock cannot exceed the released quantity of {released:.3f} kg; '
                    f'{on_hand:.3f} kg is already on hand'
                )
        if source:
            on_hand = _location_balance(cursor, lot['id'], source['id'])
            # Stock allocated to customer orders can only leave by dispatch.
            reserved = _reserved_kg(cursor, lot['id'], source['id'])
            available = on_hand - reserved
            if quantity > available:
                if reserved:
                    raise ValueError(
                        f"Only {available:.3f} kg of {lot['business_id']} at "
                        f"{source['location_code']} is free; {reserved:.3f} kg is "
                        'reserved for customer orders'
                    )
                raise ValueError(
                    f"Only {available:.3f} kg of {lot['business_id']} is at "
                    f"{source['location_code']}"
                )

        movement = _insert_inventory_movement(
            cursor, lot, movement_type, quantity, data,
            from_location=source, to_location=destination,
            occurred_at=occurred_at, reason=reason, notes=notes,
        )
        movement['product_lot_business_id'] = lot['business_id']
        movement['inventory'] = _inventory_summary(cursor, lot['id'])
        return movement


@app.route('/api/inventory/movements', methods=['POST'])
@login_required
@requires('inventory.write')
def create_inventory_movement():
    """Post one validated movement to the Product Lot inventory ledger."""
    try:
        movement = _record_inventory_movement(normalize_keys(request.get_json() or {}))
        return jsonify({
            'success': True,
            'message': 'Inventory movement posted',
            'data': movement,
            'record': movement,
            'id': movement['id'],
            'business_id': movement['business_id'],
        }), 201
    except ProductionEventPermissionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 403
    except RecordNotFoundError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 404
    except InventoryConflictError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 409
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception as exc:
        if getattr(exc, 'pgcode', None) == '23505':
            return jsonify({
                'success': False,
                'message': 'This Product Lot has already been received into inventory',
            }), 409
        logger.exception('Error posting inventory movement')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/api/inventory/locations', methods=['GET'])
@login_required
def list_inventory_locations():
    try:
        visibility, visibility_params = _scope_visibility_clause('il')
        filters, filter_params = _optional_scope_filters('il')
        if request.args.get('include_inactive') not in ('1', 'true'):
            filters.append("il.status = 'active'")
        rows = db.fetch_all(
            f"""
            SELECT il.id, il.location_code, il.name, il.status,
                   il.farm_id, il.site_id, il.facility_id,
                   f.name AS farm_name, s.name AS site_name,
                   fa.name AS facility_name
            FROM inventory_locations AS il
            JOIN farms AS f ON f.id = il.farm_id
            JOIN sites AS s ON s.id = il.site_id
            JOIN facilities AS fa ON fa.id = il.facility_id
            WHERE {' AND '.join([visibility, *filters])}
            ORDER BY f.name, s.name, fa.name, il.name
            """,
            (*visibility_params, *filter_params),
        )
        return jsonify({'success': True, 'data': rows}), 200
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception:
        logger.exception('Error listing inventory locations')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/api/inventory/locations', methods=['POST'])
@login_required
@super_admin_required
def create_inventory_location():
    data = normalize_keys(request.get_json() or {})
    try:
        farm_id, site_id, facility_id = _production_scope_values(
            data, 'an inventory location'
        )
        location_code = _optional_text(data, 'location_code', 30)
        name = _optional_text(data, 'name', 100)
        if not location_code or not name:
            raise ValueError('location_code and name are required')
        actor_user_id = _production_actor(data)[1]
        with db.transaction() as cursor:
            _assert_production_location(cursor, farm_id, site_id, facility_id)
            cursor.execute(
                """
                INSERT INTO inventory_locations (
                    location_code, name, farm_id, site_id, facility_id,
                    created_by_user_id
                ) VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, location_code, name, status, farm_id, site_id,
                          facility_id, created_at
                """,
                (location_code, name, farm_id, site_id, facility_id, actor_user_id),
            )
            location = cursor.fetchone()
        return jsonify({'success': True, 'data': location}), 201
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception as exc:
        if getattr(exc, 'pgcode', None) == '23505':
            return jsonify({
                'success': False,
                'message': 'This location code already exists in the facility',
            }), 409
        logger.exception('Error creating inventory location')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/api/inventory/locations/<int:location_id>/status', methods=['POST'])
@login_required
@super_admin_required
def set_inventory_location_status(location_id):
    """Deactivate or reactivate a store; history and balances are kept."""
    data = request.get_json() or {}
    status = str(data.get('status') or '').strip().lower()
    if status not in ('active', 'inactive'):
        return jsonify({'success': False, 'message': 'status must be active or inactive'}), 400
    try:
        with db.transaction() as cursor:
            if status == 'inactive':
                cursor.execute(
                    f"""
                    WITH {INVENTORY_LEDGER_CTE}
                    SELECT COALESCE(SUM(delta), 0) AS on_hand
                    FROM ledger WHERE location_id = %s
                    """,
                    (location_id,),
                )
                if Decimal(str(cursor.fetchone()['on_hand'])) > 0:
                    return jsonify({
                        'success': False,
                        'message': 'Move the stock out of this location before deactivating it',
                    }), 400
            cursor.execute(
                """
                UPDATE inventory_locations SET status = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s RETURNING id, status
                """,
                (status, location_id),
            )
            row = cursor.fetchone()
        if not row:
            return jsonify({'success': False, 'message': 'Inventory location not found'}), 404
        return jsonify({'success': True, 'data': dict(row)}), 200
    except Exception:
        logger.exception('Error updating inventory location status')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/api/inventory', methods=['GET'])
@login_required
def get_inventory_stock():
    """Stock on hand by product, lot and location, derived from the ledger."""
    try:
        visibility, visibility_params = _scope_visibility_clause('il')
        filters, filter_params = _optional_scope_filters('il')
        product_type = request.args.get('product_type')
        if product_type:
            filters.append('pl.product_type = %s')
            filter_params.append(product_type)
        rows = db.fetch_all(
            f"""
            WITH {INVENTORY_LEDGER_CTE}, {ALLOCATION_STATE_CTE}
            SELECT pl.product_type, pl.id AS product_lot_id, pl.business_id,
                   pl.lot_code,
                   CASE WHEN {PRODUCT_LOT_RELEASABLE_SQL}
                        THEN 'AVAILABLE' ELSE 'BLOCKED' END AS lot_status,
                   il.id AS location_id, il.location_code,
                   il.name AS location_name, fa.name AS facility_name,
                   f.name AS farm_name, il.farm_id,
                   SUM(ledger.delta) AS quantity_kg, 'kg' AS unit,
                   MAX(ledger.occurred_at) AS last_movement_at,
                   COALESCE((
                       SELECT SUM(s.quantity_kg - s.released_kg - s.dispatched_kg)
                       FROM allocation_state AS s
                       WHERE s.product_lot_id = pl.id AND s.location_id = il.id
                   ), 0) AS reserved_kg
            FROM ledger
            JOIN product_lots AS pl ON pl.id = ledger.product_lot_id
            JOIN inventory_locations AS il ON il.id = ledger.location_id
            JOIN facilities AS fa ON fa.id = il.facility_id
            JOIN farms AS f ON f.id = il.farm_id
            WHERE {' AND '.join([visibility, *filters])}
            GROUP BY pl.id, il.id, fa.name, f.name
            HAVING SUM(ledger.delta) <> 0
            ORDER BY pl.product_type, pl.business_id, il.name
            """,
            (*visibility_params, *filter_params),
        )
        totals = {}
        for row in rows:
            entry = totals.setdefault(row['product_type'], {
                'product_type': row['product_type'],
                'quantity_kg': Decimal('0'),
                'reserved_kg': Decimal('0'),
                'available_kg': Decimal('0'),
            })
            quantity = Decimal(str(row['quantity_kg']))
            reserved = Decimal(str(row['reserved_kg']))
            # Free stock: on hand, not reserved for an order, and QC released.
            row['free_kg'] = quantity - reserved
            entry['quantity_kg'] += quantity
            entry['reserved_kg'] += reserved
            if row['lot_status'] == 'AVAILABLE':
                entry['available_kg'] += quantity - reserved
        return jsonify({
            'success': True,
            'data': rows,
            'totals': sorted(totals.values(), key=lambda item: item['product_type']),
        }), 200
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception:
        logger.exception('Error loading inventory stock')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500
