"""Customers, customer orders, stock allocations and deliveries."""

from datetime import date
from decimal import Decimal, InvalidOperation
from flask import jsonify, render_template, request
from flask_login import login_required

from backend.config import CURRENCY
from backend.core.web import app, db, logger
from backend.core.http import (
    InventoryConflictError,
    ProductionEventPermissionError,
    RecordNotFoundError,
    _event_occurred_at,
    _jsonable,
    _optional_text,
    _parse_chain_quantity,
    _parse_positive_integer,
    _production_actor,
    normalize_keys,
)
from backend.core.security import requires
from backend.core.scope import (
    _assert_farm_access,
    _farm_visibility_clause,
    _scope_visibility_clause,
)
from backend.domains.inventory import (
    ALLOCATION_STATE_CTE,
    INVENTORY_LEDGER_CTE,
    PRODUCT_LOT_RELEASABLE_SQL,
    _insert_inventory_movement,
    _inventory_location_row,
    _inventory_lot_row,
    _location_balance,
    _reserved_kg,
)


def _order_row(cursor, order_ref, *, for_update=False):
    lookup_id = int(order_ref) if str(order_ref).isdigit() else -1
    cursor.execute(
        f"""
        SELECT o.*, c.name AS customer_name, c.contact AS customer_contact,
               f.name AS farm_name
        FROM customer_orders AS o
        JOIN customers AS c ON c.id = o.customer_id
        JOIN farms AS f ON f.id = o.farm_id
        WHERE o.id = %s OR UPPER(o.business_id) = UPPER(%s)
        {'FOR UPDATE OF o' if for_update else ''}
        """,
        (lookup_id, str(order_ref)),
    )
    order = cursor.fetchone()
    if not order:
        raise RecordNotFoundError('Customer order not found')
    _assert_farm_access(cursor, order['farm_id'])
    return dict(order)


def _order_detail(cursor, order):
    order_id = order['id']
    cursor.execute(
        """
        SELECT id, line_no, product_type, quantity_kg, unit, unit_price, notes
        FROM customer_order_lines WHERE order_id = %s ORDER BY line_no
        """,
        (order_id,),
    )
    lines = [dict(row) for row in cursor.fetchall()]
    cursor.execute(
        f"""
        WITH {ALLOCATION_STATE_CTE}
        SELECT s.id, s.order_line_id, s.product_lot_id, s.location_id,
               s.quantity_kg, s.released_kg, s.dispatched_kg,
               s.quantity_kg - s.released_kg - s.dispatched_kg AS outstanding_kg,
               a.created_at, a.created_by, a.released_at, a.release_reason,
               pl.business_id AS product_lot_business_id, pl.product_type,
               il.location_code, il.name AS location_name
        FROM allocation_state AS s
        JOIN order_allocations AS a ON a.id = s.id
        JOIN customer_order_lines AS l ON l.id = s.order_line_id
        JOIN product_lots AS pl ON pl.id = s.product_lot_id
        JOIN inventory_locations AS il ON il.id = s.location_id
        WHERE l.order_id = %s
        ORDER BY s.id
        """,
        (order_id,),
    )
    allocations = [dict(row) for row in cursor.fetchall()]
    cursor.execute(
        """
        SELECT d.id, d.business_id, d.status, d.dispatched_at, d.delivered_at,
               d.received_by, d.vehicle, d.driver, d.notes, d.created_by
        FROM customer_deliveries AS d WHERE d.order_id = %s ORDER BY d.id
        """,
        (order_id,),
    )
    deliveries = [dict(row) for row in cursor.fetchall()]
    if deliveries:
        cursor.execute(
            """
            SELECT dl.delivery_id, dl.allocation_id, dl.quantity_kg, a.order_line_id,
                   im.business_id AS movement_business_id,
                   pl.business_id AS product_lot_business_id,
                   il.location_code
            FROM customer_delivery_lines AS dl
            JOIN order_allocations AS a ON a.id = dl.allocation_id
            JOIN product_lots AS pl ON pl.id = a.product_lot_id
            JOIN inventory_locations AS il ON il.id = a.location_id
            JOIN inventory_movements AS im ON im.id = dl.inventory_movement_id
            WHERE dl.delivery_id = ANY(%s)
            ORDER BY dl.id
            """,
            ([d['id'] for d in deliveries],),
        )
        delivery_lines = {}
        for row in cursor.fetchall():
            delivery_lines.setdefault(row['delivery_id'], []).append(dict(row))
        for delivery in deliveries:
            delivery['lines'] = delivery_lines.get(delivery['id'], [])
            delivery['quantity_kg'] = sum(
                (Decimal(str(line['quantity_kg'])) for line in delivery['lines']), Decimal('0')
            )

    zero = Decimal('0')
    delivered_by_line = {}
    for delivery in deliveries:
        if delivery['status'] == 'DELIVERED':
            for delivery_line in delivery['lines']:
                delivered_by_line[delivery_line['order_line_id']] = (
                    delivered_by_line.get(delivery_line['order_line_id'], zero)
                    + Decimal(str(delivery_line['quantity_kg'])))
    for line in lines:
        price = line['unit_price']
        line['delivered_kg'] = delivered_by_line.get(line['id'], zero)
        line['line_value'] = _money(Decimal(str(line['quantity_kg'])) * price) if price is not None else None
        line['delivered_value'] = _money(line['delivered_kg'] * price) if price is not None else None
        mine = [a for a in allocations if a['order_line_id'] == line['id']]
        line['allocations'] = mine
        line['outstanding_allocated_kg'] = sum((Decimal(str(a['outstanding_kg'])) for a in mine), zero)
        line['dispatched_kg'] = sum((Decimal(str(a['dispatched_kg'])) for a in mine), zero)
        line['remaining_to_allocate_kg'] = max(
            Decimal(str(line['quantity_kg'])) - line['dispatched_kg'] - line['outstanding_allocated_kg'],
            zero,
        )
    totals = {
        'ordered_kg': sum((Decimal(str(line['quantity_kg'])) for line in lines), zero),
        'allocated_kg': sum((line['outstanding_allocated_kg'] for line in lines), zero),
        'dispatched_kg': sum((line['dispatched_kg'] for line in lines), zero),
        'delivered_kg': sum(
            (d['quantity_kg'] for d in deliveries if d['status'] == 'DELIVERED'), zero
        ),
        # Lines without a price (from before prices) are left out of the values.
        'order_value': sum((line['line_value'] for line in lines if line['line_value'] is not None), zero),
        'delivered_value': sum((line['delivered_value'] for line in lines
                                if line['delivered_value'] is not None), zero),
        'unpriced_lines': sum(1 for line in lines if line['unit_price'] is None),
        'currency': CURRENCY,
    }
    return _jsonable({
        **order,
        'lines': lines,
        'allocations': allocations,
        'deliveries': deliveries,
        'totals': totals,
    })


def _order_line(cursor, order_id, line_ref):
    line_id = _parse_positive_integer(line_ref, 'order_line_id')
    cursor.execute(
        "SELECT * FROM customer_order_lines WHERE id = %s AND order_id = %s",
        (line_id, order_id),
    )
    line = cursor.fetchone()
    if not line:
        raise ValueError('The order line does not belong to this order')
    return dict(line)


def _line_commitments(cursor, line_id):
    """Dispatched plus still-reserved quantity for one order line."""
    cursor.execute(
        f"""
        WITH {ALLOCATION_STATE_CTE}
        SELECT COALESCE(SUM(quantity_kg - released_kg), 0) AS committed
        FROM allocation_state WHERE order_line_id = %s
        """,
        (line_id,),
    )
    return Decimal(str(cursor.fetchone()['committed']))


def _refresh_order_status(cursor, order_id):
    cursor.execute(
        f"""
        WITH {ALLOCATION_STATE_CTE}
        SELECT bool_and(
            COALESCE((SELECT SUM(s.dispatched_kg) FROM allocation_state AS s
                      WHERE s.order_line_id = l.id), 0) >= l.quantity_kg
        ) AS fulfilled
        FROM customer_order_lines AS l WHERE l.order_id = %s
        """,
        (order_id,),
    )
    if cursor.fetchone()['fulfilled']:
        cursor.execute(
            """
            UPDATE customer_orders SET status = 'FULFILLED', updated_at = CURRENT_TIMESTAMP
            WHERE id = %s AND status = 'OPEN'
            """,
            (order_id,),
        )


def _optional_date(data, field):
    value = data.get(field)
    if value in (None, ''):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise ValueError(f'{field} must be a valid date (YYYY-MM-DD)')


MAX_UNIT_PRICE = Decimal('100000000')


def _money(value):
    return value.quantize(Decimal('0.01'))


def _parse_price(value, field):
    """Price per kg: required, zero or more, at most two decimals."""
    if value in (None, ''):
        raise ValueError(f'{field} is required (price per kg in {CURRENCY})')
    try:
        price = Decimal(str(value).strip())
    except InvalidOperation:
        raise ValueError(f'{field} must be a number')
    if not price.is_finite() or price < 0:
        raise ValueError(f'{field} must be zero or more')
    if price > MAX_UNIT_PRICE:
        raise ValueError(f'{field} is too large')
    if price != price.quantize(Decimal('0.01')):
        raise ValueError(f'{field} can have at most two decimals')
    return _money(price)


def _set_line_price(order_ref, line_id, data):
    """Price a line, or correct its price, until anything on it is dispatched."""
    unit_price = _parse_price(data.get('unit_price'), 'unit_price')
    with db.transaction() as cursor:
        order = _order_row(cursor, order_ref, for_update=True)
        if order['status'] == 'CANCELLED':
            raise ValueError('A cancelled order cannot be priced')
        cursor.execute(
            "SELECT id FROM customer_order_lines WHERE id = %s AND order_id = %s FOR UPDATE",
            (line_id, order['id']),
        )
        if not cursor.fetchone():
            raise RecordNotFoundError('Order line not found')
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM customer_delivery_lines AS dl
                JOIN order_allocations AS a ON a.id = dl.allocation_id
                WHERE a.order_line_id = %s) AS dispatched
            """,
            (line_id,),
        )
        if cursor.fetchone()['dispatched']:
            raise InventoryConflictError('The price is fixed once the line has been dispatched')
        cursor.execute("UPDATE customer_order_lines SET unit_price = %s WHERE id = %s", (unit_price, line_id))
        return _order_detail(cursor, _order_row(cursor, order['id']))


def _create_order(data):
    customer_id = _parse_positive_integer(data.get('customer_id'), 'customer_id')
    farm_id = _parse_positive_integer(data.get('farm_id'), 'farm_id')
    order_date = _optional_date(data, 'order_date') or date.today()
    requested = _optional_date(data, 'requested_delivery_date')
    if requested and requested < order_date:
        raise ValueError('requested_delivery_date cannot be before the order date')
    lines = data.get('lines')
    if not isinstance(lines, list) or not lines:
        raise ValueError('Add at least one order line')
    if len(lines) > 50:
        raise ValueError('An order can have at most 50 lines')
    parsed_lines = []
    for index, line in enumerate(lines, start=1):
        if not isinstance(line, dict):
            raise ValueError('Each order line must be an object')
        product_type = str(line.get('product_type') or '').strip()
        if not product_type or len(product_type) > 50:
            raise ValueError(f'Line {index}: product_type is required (max 50 characters)')
        if str(line.get('unit') or 'kg').strip().lower() != 'kg':
            raise ValueError(f'Line {index}: quantities must be in kg')
        parsed_lines.append((
            index, product_type,
            _parse_chain_quantity(line.get('quantity_kg'), f'Line {index} quantity_kg'),
            _parse_price(line.get('unit_price'), f'Line {index} unit_price'),
            _optional_text(line, 'notes', 500),
        ))
    customer_reference = _optional_text(data, 'customer_reference', 60)
    notes = _optional_text(data, 'notes', 2000)
    actor, actor_user_id = _production_actor(data)
    with db.transaction() as cursor:
        cursor.execute("SELECT status FROM farms WHERE id = %s", (farm_id,))
        farm = cursor.fetchone()
        if not farm or farm['status'] != 'active':
            raise ValueError('Select an active farm')
        _assert_farm_access(cursor, farm_id)
        cursor.execute("SELECT id FROM customers WHERE id = %s", (customer_id,))
        if not cursor.fetchone():
            raise ValueError('Customer not found')
        cursor.execute(
            """
            INSERT INTO customer_orders (
                customer_id, farm_id, order_date, requested_delivery_date,
                customer_reference, notes, created_by, created_by_user_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (customer_id, farm_id, order_date, requested, customer_reference, notes,
             actor, actor_user_id),
        )
        order_id = cursor.fetchone()['id']
        for line_no, product_type, quantity, unit_price, line_notes in parsed_lines:
            cursor.execute(
                """
                INSERT INTO customer_order_lines (order_id, line_no, product_type, quantity_kg, unit_price, notes)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (order_id, line_no, product_type, quantity, unit_price, line_notes),
            )
        return _order_detail(cursor, _order_row(cursor, order_id))


def _available_stock_for_line(cursor, order, line):
    """Free, QC-released stock of the line's product on the order's farm."""
    visibility, params = _scope_visibility_clause('il')
    cursor.execute(
        f"""
        WITH {INVENTORY_LEDGER_CTE}, {ALLOCATION_STATE_CTE},
        balances AS (
            SELECT ledger.product_lot_id, ledger.location_id,
                   SUM(ledger.delta) AS on_hand_kg
            FROM ledger GROUP BY ledger.product_lot_id, ledger.location_id
        )
        SELECT pl.id AS product_lot_id, pl.business_id AS product_lot_business_id,
               pl.product_type, pl.production_date,
               il.id AS location_id, il.location_code, il.name AS location_name,
               fa.name AS facility_name, b.on_hand_kg,
               COALESCE((
                   SELECT SUM(s.quantity_kg - s.released_kg - s.dispatched_kg)
                   FROM allocation_state AS s
                   WHERE s.product_lot_id = pl.id AND s.location_id = il.id
               ), 0) AS reserved_kg
        FROM balances AS b
        JOIN product_lots AS pl ON pl.id = b.product_lot_id
        JOIN inventory_locations AS il ON il.id = b.location_id
        JOIN facilities AS fa ON fa.id = il.facility_id
        WHERE pl.farm_id = %s AND LOWER(pl.product_type) = LOWER(%s)
          AND il.status = 'active' AND {PRODUCT_LOT_RELEASABLE_SQL}
          AND {visibility}
        ORDER BY pl.production_date, pl.id, il.name
        """,
        (order['farm_id'], line['product_type'], *params),
    )
    rows = []
    for row in cursor.fetchall():
        row = dict(row)
        row['free_kg'] = Decimal(str(row['on_hand_kg'])) - Decimal(str(row['reserved_kg']))
        if row['free_kg'] > 0:
            rows.append(row)
    return rows


def _allocate(order_ref, data):
    quantity = _parse_chain_quantity(data.get('quantity_kg'), 'quantity_kg')
    with db.transaction() as cursor:
        order = _order_row(cursor, order_ref, for_update=True)
        if order['status'] != 'OPEN':
            raise ValueError(f"Order {order['business_id']} is {order['status']} and cannot be allocated")
        line = _order_line(cursor, order['id'], data.get('order_line_id'))
        for field in ('product_lot_id', 'location_id'):
            if data.get(field) in (None, ''):
                raise ValueError(f'{field} is required')
        lot = _inventory_lot_row(cursor, data.get('product_lot_id'))
        location = _inventory_location_row(cursor, data.get('location_id'), 'allocation')
        if lot['farm_id'] != order['farm_id'] or location['farm_id'] != order['farm_id']:
            raise ValueError('Allocated stock must be on the same farm as the order')
        if lot['product_type'].lower() != line['product_type'].lower():
            raise ValueError(
                f"Product Lot {lot['business_id']} is {lot['product_type']}, "
                f"but the order line is for {line['product_type']}"
            )
        if not lot['releasable']:
            raise ValueError(f"Product Lot {lot['business_id']} is blocked by QC and cannot be allocated")
        remaining = Decimal(str(line['quantity_kg'])) - _line_commitments(cursor, line['id'])
        if quantity > remaining:
            raise ValueError(f'Only {max(remaining, Decimal("0")):.3f} kg of this order line is left to allocate')
        free = _location_balance(cursor, lot['id'], location['id']) - _reserved_kg(
            cursor, lot['id'], location['id']
        )
        if quantity > free:
            raise ValueError(
                f"Only {max(free, Decimal('0')):.3f} kg of {lot['business_id']} at "
                f"{location['location_code']} is free to allocate"
            )
        actor, actor_user_id = _production_actor(data)
        cursor.execute(
            """
            INSERT INTO order_allocations (
                order_line_id, product_lot_id, location_id, quantity_kg,
                created_by, created_by_user_id
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (line['id'], lot['id'], location['id'], quantity, actor, actor_user_id),
        )
        cursor.execute(
            "UPDATE customer_orders SET updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (order['id'],),
        )
        return _order_detail(cursor, order)


def _release_outstanding(cursor, allocation_ids, reason):
    if not allocation_ids:
        return
    cursor.execute(
        f"""
        WITH {ALLOCATION_STATE_CTE}
        UPDATE order_allocations AS a
        SET released_kg = a.released_kg + (s.quantity_kg - s.released_kg - s.dispatched_kg),
            released_at = CURRENT_TIMESTAMP,
            release_reason = %s
        FROM allocation_state AS s
        WHERE s.id = a.id AND a.id = ANY(%s)
          AND s.quantity_kg - s.released_kg - s.dispatched_kg > 0
        """,
        (reason, allocation_ids),
    )


def _release_allocation(order_ref, allocation_id, data):
    reason = _optional_text(data, 'reason', 500)
    if not reason:
        raise ValueError('A reason is required to release an allocation')
    with db.transaction() as cursor:
        order = _order_row(cursor, order_ref, for_update=True)
        cursor.execute(
            f"""
            WITH {ALLOCATION_STATE_CTE}
            SELECT s.*, s.quantity_kg - s.released_kg - s.dispatched_kg AS outstanding
            FROM allocation_state AS s
            JOIN customer_order_lines AS l ON l.id = s.order_line_id
            WHERE s.id = %s AND l.order_id = %s
            """,
            (allocation_id, order['id']),
        )
        allocation = cursor.fetchone()
        if not allocation:
            raise RecordNotFoundError('Allocation not found on this order')
        if allocation['outstanding'] <= 0:
            raise ValueError('This allocation has nothing left to release')
        _release_outstanding(cursor, [allocation['id']], reason)
        return _order_detail(cursor, order)


def _cancel_order(order_ref, data):
    reason = _optional_text(data, 'reason', 500)
    if not reason:
        raise ValueError('A reason is required to cancel an order')
    with db.transaction() as cursor:
        order = _order_row(cursor, order_ref, for_update=True)
        if order['status'] != 'OPEN':
            raise ValueError(f"Order {order['business_id']} is already {order['status']}")
        cursor.execute(
            "SELECT 1 FROM customer_deliveries WHERE order_id = %s LIMIT 1", (order['id'],)
        )
        if cursor.fetchone():
            raise ValueError(
                'This order already has dispatched deliveries and cannot be cancelled; '
                'release the remaining allocations instead'
            )
        cursor.execute(
            """
            SELECT a.id FROM order_allocations AS a
            JOIN customer_order_lines AS l ON l.id = a.order_line_id
            WHERE l.order_id = %s
            """,
            (order['id'],),
        )
        _release_outstanding(cursor, [row['id'] for row in cursor.fetchall()], f'Order cancelled: {reason}')
        cursor.execute(
            """
            UPDATE customer_orders
            SET status = 'CANCELLED', cancel_reason = %s, cancelled_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (reason, order['id']),
        )
        return _order_detail(cursor, _order_row(cursor, order['id']))


def _dispatch(order_ref, data):
    requested = data.get('lines')
    if not isinstance(requested, list) or not requested:
        raise ValueError('Choose at least one allocation to dispatch')
    parsed = {}
    for item in requested:
        if not isinstance(item, dict):
            raise ValueError('Each dispatch line must be an object')
        allocation_id = _parse_positive_integer(item.get('allocation_id'), 'allocation_id')
        if allocation_id in parsed:
            raise ValueError('Each allocation can appear only once per delivery')
        parsed[allocation_id] = _parse_chain_quantity(item.get('quantity_kg'), 'quantity_kg')
    vehicle = _optional_text(data, 'vehicle', 60)
    driver = _optional_text(data, 'driver', 100)
    notes = _optional_text(data, 'notes', 2000)
    dispatched_at = None
    if data.get('dispatched_at') not in (None, ''):
        dispatched_at = _event_occurred_at({'occurred_at': data['dispatched_at']}, ())
    actor, actor_user_id = _production_actor(data)

    with db.transaction() as cursor:
        order = _order_row(cursor, order_ref, for_update=True)
        if order['status'] != 'OPEN':
            raise ValueError(f"Order {order['business_id']} is {order['status']} and cannot be dispatched")
        cursor.execute(
            f"""
            WITH {ALLOCATION_STATE_CTE}
            SELECT s.*, s.quantity_kg - s.released_kg - s.dispatched_kg AS outstanding
            FROM allocation_state AS s
            JOIN customer_order_lines AS l ON l.id = s.order_line_id
            WHERE l.order_id = %s AND s.id = ANY(%s)
            ORDER BY s.product_lot_id, s.id
            """,
            (order['id'], list(parsed)),
        )
        allocations = {row['id']: dict(row) for row in cursor.fetchall()}
        missing = set(parsed) - set(allocations)
        if missing:
            raise ValueError('One or more allocations do not belong to this order')

        cursor.execute(
            """
            INSERT INTO customer_deliveries (
                order_id, dispatched_at, vehicle, driver, notes, created_by, created_by_user_id
            ) VALUES (%s, COALESCE(%s, CURRENT_TIMESTAMP), %s, %s, %s, %s, %s)
            RETURNING id, business_id
            """,
            (order['id'], dispatched_at, vehicle, driver, notes, actor, actor_user_id),
        )
        delivery = cursor.fetchone()
        # Lock lots in a stable order so concurrent dispatches cannot deadlock.
        for allocation_id in sorted(allocations, key=lambda key: (allocations[key]['product_lot_id'], key)):
            allocation = allocations[allocation_id]
            quantity = parsed[allocation_id]
            lot = _inventory_lot_row(cursor, allocation['product_lot_id'])
            if not lot['releasable']:
                raise ValueError(f"Product Lot {lot['business_id']} is blocked by QC and cannot be dispatched")
            location = _inventory_location_row(cursor, allocation['location_id'], 'dispatch')
            if quantity > Decimal(str(allocation['outstanding'])):
                raise ValueError(
                    f"Only {Decimal(str(allocation['outstanding'])):.3f} kg of the "
                    f"{lot['business_id']} allocation is left to dispatch"
                )
            on_hand = _location_balance(cursor, lot['id'], location['id'])
            if quantity > on_hand:
                raise ValueError(
                    f"Only {on_hand:.3f} kg of {lot['business_id']} is at {location['location_code']}"
                )
            movement = _insert_inventory_movement(
                cursor, lot, 'DISPATCH', quantity, data,
                from_location=location, occurred_at=dispatched_at,
                notes=f"{delivery['business_id']} for {order['business_id']}",
                reference_type='customer_delivery', reference_id=delivery['id'],
            )
            cursor.execute(
                """
                INSERT INTO customer_delivery_lines (
                    delivery_id, allocation_id, quantity_kg, inventory_movement_id
                ) VALUES (%s, %s, %s, %s)
                """,
                (delivery['id'], allocation_id, quantity, movement['id']),
            )
        _refresh_order_status(cursor, order['id'])
        detail = _order_detail(cursor, _order_row(cursor, order['id']))
        detail['created_delivery'] = delivery['business_id']
        return detail


def _confirm_delivery(delivery_ref, data):
    received_by = _optional_text(data, 'received_by', 100)
    if not received_by:
        raise ValueError('received_by is required to confirm a delivery')
    delivered_at = None
    if data.get('delivered_at') not in (None, ''):
        delivered_at = _event_occurred_at({'occurred_at': data['delivered_at']}, ())
    lookup_id = int(delivery_ref) if str(delivery_ref).isdigit() else -1
    with db.transaction() as cursor:
        cursor.execute(
            """
            SELECT id, order_id, status, dispatched_at FROM customer_deliveries
            WHERE id = %s OR UPPER(business_id) = UPPER(%s)
            FOR UPDATE
            """,
            (lookup_id, str(delivery_ref)),
        )
        delivery = cursor.fetchone()
        if not delivery:
            raise RecordNotFoundError('Delivery not found')
        order = _order_row(cursor, delivery['order_id'])
        if delivery['status'] != 'DISPATCHED':
            raise InventoryConflictError('This delivery has already been confirmed')
        cursor.execute(
            """
            UPDATE customer_deliveries
            SET status = 'DELIVERED', received_by = %s,
                delivered_at = COALESCE(%s, CURRENT_TIMESTAMP)
            WHERE id = %s AND COALESCE(%s, CURRENT_TIMESTAMP) >= dispatched_at
            RETURNING id
            """,
            (received_by, delivered_at, delivery['id'], delivered_at),
        )
        if not cursor.fetchone():
            raise ValueError('delivered_at cannot be before the dispatch time')
        return _order_detail(cursor, order)


def _order_response(handler, *args, status=200):
    try:
        return jsonify({'success': True, 'data': handler(*args)}), status
    except ProductionEventPermissionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 403
    except RecordNotFoundError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 404
    except InventoryConflictError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 409
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception:
        logger.exception('Error processing customer order request')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/api/orders', methods=['POST'])
@login_required
@requires('sales.write')
def create_customer_order():
    return _order_response(_create_order, normalize_keys(request.get_json() or {}), status=201)


@app.route('/api/orders', methods=['GET'])
@login_required
@requires('sales.read')
def list_customer_orders():
    def handler():
        visibility, params = _farm_visibility_clause('o')
        filters = [visibility]
        filter_params = list(params)
        status = str(request.args.get('status') or '').strip().upper()
        if status:
            if status not in {'OPEN', 'FULFILLED', 'CANCELLED'}:
                raise ValueError('Unknown order status')
            filters.append('o.status = %s')
            filter_params.append(status)
        if request.args.get('farm_id') not in (None, ''):
            filters.append('o.farm_id = %s')
            filter_params.append(_parse_positive_integer(request.args['farm_id'], 'farm_id'))
        rows = db.fetch_all(
            f"""
            WITH {ALLOCATION_STATE_CTE}
            SELECT o.id, o.business_id, o.status, o.order_date,
                   o.requested_delivery_date, o.customer_reference,
                   c.name AS customer_name, f.name AS farm_name, o.farm_id,
                   (SELECT SUM(l.quantity_kg) FROM customer_order_lines AS l
                     WHERE l.order_id = o.id) AS ordered_kg,
                   COALESCE((SELECT SUM(s.dispatched_kg) FROM allocation_state AS s
                     JOIN customer_order_lines AS l ON l.id = s.order_line_id
                     WHERE l.order_id = o.id), 0) AS dispatched_kg,
                   COALESCE((SELECT SUM(s.quantity_kg - s.released_kg - s.dispatched_kg)
                     FROM allocation_state AS s
                     JOIN customer_order_lines AS l ON l.id = s.order_line_id
                     WHERE l.order_id = o.id), 0) AS allocated_kg,
                   (SELECT SUM(l.quantity_kg * l.unit_price) FROM customer_order_lines AS l
                     WHERE l.order_id = o.id) AS order_value,
                   %s AS currency
            FROM customer_orders AS o
            JOIN customers AS c ON c.id = o.customer_id
            JOIN farms AS f ON f.id = o.farm_id
            WHERE {' AND '.join(filters)}
            ORDER BY o.order_date DESC, o.id DESC
            LIMIT 500
            """,
            (CURRENCY, *filter_params),
        )
        return _jsonable(rows)
    return _order_response(handler)


@app.route('/api/orders/<string:order_ref>', methods=['GET'])
@login_required
@requires('sales.read')
def get_customer_order(order_ref):
    def handler():
        with db.transaction() as cursor:
            return _order_detail(cursor, _order_row(cursor, order_ref))
    return _order_response(handler)


@app.route('/api/orders/<string:order_ref>/available-stock', methods=['GET'])
@login_required
@requires('sales.read')
def get_order_available_stock(order_ref):
    def handler():
        with db.transaction() as cursor:
            order = _order_row(cursor, order_ref)
            line = _order_line(cursor, order['id'], request.args.get('line_id'))
            return _jsonable(_available_stock_for_line(cursor, order, line))
    return _order_response(handler)


@app.route('/api/orders/<string:order_ref>/allocations', methods=['POST'])
@login_required
@requires('sales.write')
def allocate_customer_order(order_ref):
    return _order_response(_allocate, order_ref, normalize_keys(request.get_json() or {}), status=201)


@app.route('/api/orders/<string:order_ref>/allocations/<int:allocation_id>/release', methods=['POST'])
@login_required
@requires('sales.write')
def release_order_allocation(order_ref, allocation_id):
    return _order_response(
        _release_allocation, order_ref, allocation_id, normalize_keys(request.get_json() or {})
    )


@app.route('/api/orders/<string:order_ref>/lines/<int:line_id>/price', methods=['PUT'])
@login_required
@requires('sales.write')
def price_customer_order_line(order_ref, line_id):
    return _order_response(_set_line_price, order_ref, line_id, normalize_keys(request.get_json() or {}))


@app.route('/api/orders/<string:order_ref>/cancel', methods=['POST'])
@login_required
@requires('sales.write')
def cancel_customer_order(order_ref):
    return _order_response(_cancel_order, order_ref, normalize_keys(request.get_json() or {}))


@app.route('/api/orders/<string:order_ref>/deliveries', methods=['POST'])
@login_required
@requires('sales.write')
def dispatch_customer_order(order_ref):
    return _order_response(_dispatch, order_ref, normalize_keys(request.get_json() or {}), status=201)


@app.route('/api/deliveries/<string:delivery_ref>/confirm', methods=['POST'])
@login_required
@requires('sales.write')
def confirm_customer_delivery(delivery_ref):
    return _order_response(_confirm_delivery, delivery_ref, normalize_keys(request.get_json() or {}))


@app.route('/orders')
@login_required
def orders_page():
    return render_template('orders.html')

# --- Customers CRUD ---
@app.route('/api/customers', methods=['GET'])
@login_required
@requires('sales.read')
def get_customers():
    customers = db.fetch_all("SELECT * FROM customers")
    return jsonify(customers)

def _customer_fields(data):
    """Validated customer fields; raises ValueError with a message for the user."""
    name = _optional_text(data, 'name', 100)
    if not name:
        raise ValueError('Customer name is required')
    return (
        name,
        _optional_text(data, 'contact', 50),
        _optional_text(data, 'email', 100),
        _optional_text(data, 'address', 2000),
    )


@app.route('/api/customers', methods=['POST'])
@login_required
@requires('sales.write')
def add_customer():
    try:
        name, contact, email, address = _customer_fields(request.get_json(silent=True) or {})
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc), 'message': str(exc)}), 400
    existing = db.fetch_one(
        "SELECT id FROM customers WHERE LOWER(name) = LOWER(%s) AND email IS NOT DISTINCT FROM %s",
        (name, email),
    )
    if existing:
        message = 'Customer with this name and email already exists.'
        return jsonify({'success': False, 'error': message, 'message': message}), 409
    row = db.execute_returning(
        "INSERT INTO customers (name, contact, email, address) VALUES (%s, %s, %s, %s) RETURNING id",
        (name, contact, email, address),
    )
    return jsonify({'success': True, 'id': row['id']}), 201

@app.route('/api/customers/<int:customer_id>', methods=['PUT'])
@login_required
@requires('sales.write')
def edit_customer(customer_id):
    try:
        name, contact, email, address = _customer_fields(request.get_json(silent=True) or {})
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc), 'message': str(exc)}), 400
    row = db.execute_returning(
        "UPDATE customers SET name=%s, contact=%s, email=%s, address=%s, updated_at=CURRENT_TIMESTAMP "
        "WHERE id=%s RETURNING id",
        (name, contact, email, address, customer_id),
    )
    if not row:
        return jsonify({'success': False, 'error': 'Customer not found', 'message': 'Customer not found'}), 404
    return jsonify({'success': True})
