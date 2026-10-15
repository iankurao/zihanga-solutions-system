"""Traceability graph from waste lot to delivery."""

from flask import jsonify, render_template, request
from flask_login import login_required

from backend.core.web import app, db, logger
from backend.core.http import (
    InventoryConflictError,
    ProductionEventPermissionError,
    RecordNotFoundError,
    _jsonable,
)
from backend.core.scope import (
    _assert_production_scope_access,
    _farm_access_allowed,
    _farm_visibility_clause,
    _scope_visibility_clause,
)
from backend.core.security import _can
from backend.domains.inventory import INVENTORY_LEDGER_CTE, PRODUCT_LOT_RELEASABLE_SQL


# ---- Traceability --------------------------------------------------------
#
# Lineage is walked over the stored foreign keys of the Phase One chain:
#   waste_lot -> substrate_batch -> production_batch -> harvest
#   -> drying_batch -> product_lot -> inventory_location (current stock)
# Upstream walks only follow edges backwards and downstream only forwards,
# so a production batch never pulls in its sibling batches' unrelated data.

TRACE_STAGES = (
    'waste_lot', 'substrate_batch', 'production_batch', 'harvest',
    'drying_batch', 'product_lot', 'inventory_location', 'customer_order',
    'delivery',
)
TRACE_LABELS = {
    'waste_lot': 'Waste Lot',
    'substrate_batch': 'Substrate Batch',
    'production_batch': 'Production Batch',
    'harvest': 'Harvest',
    'drying_batch': 'Drying Batch',
    'product_lot': 'Product Lot',
    'inventory_location': 'Inventory Location',
    'customer_order': 'Customer Order',
    'delivery': 'Delivery',
}
TRACE_ROOT_TYPES = tuple(kind for kind in TRACE_STAGES if kind != 'inventory_location')
# Commercial records need farm-level access; walks stop at these node types
# unless the trace starts from one, so an order never pulls in other lots.
TRACE_COMMERCIAL = {'customer_order', 'delivery'}
TRACE_TERMINAL = {'inventory_location'} | TRACE_COMMERCIAL
# Lookup by numeric database ID (only when the caller names the type).
TRACE_ID_SQL = {
    'waste_lot': "SELECT id FROM waste_lots WHERE id = %s",
    'substrate_batch': "SELECT id FROM substrate_batches WHERE id = %s",
    'production_batch': "SELECT id FROM production_batches WHERE id = %s",
    'harvest': "SELECT id FROM harvests WHERE id = %s",
    'drying_batch': "SELECT id FROM drying_batches WHERE id = %s",
    'product_lot': "SELECT id FROM product_lots WHERE id = %s AND drying_output_id IS NOT NULL",
    'customer_order': "SELECT id FROM customer_orders WHERE id = %s",
    'delivery': "SELECT id FROM customer_deliveries WHERE id = %s",
}
TRACE_NODE_LIMIT = 300

# How each searchable record type is matched by its human-readable IDs.
TRACE_REF_SQL = {
    'waste_lot': (
        "SELECT id FROM waste_lots WHERE UPPER(business_id) = UPPER(%s)", 1,
    ),
    'substrate_batch': (
        "SELECT id FROM substrate_batches "
        "WHERE UPPER(business_id) = UPPER(%s) OR UPPER(batch_code) = UPPER(%s)", 2,
    ),
    'production_batch': (
        "SELECT id FROM production_batches "
        "WHERE UPPER(business_id) = UPPER(%s) OR UPPER(batch_code) = UPPER(%s)", 2,
    ),
    'harvest': (
        "SELECT id FROM harvests WHERE UPPER(harvest_code) = UPPER(%s)", 1,
    ),
    'drying_batch': (
        "SELECT id FROM drying_batches WHERE UPPER(business_id) = UPPER(%s) "
        "OR UPPER(batch_code) = UPPER(%s) OR UPPER(batch_id) = UPPER(%s)", 3,
    ),
    'product_lot': (
        "SELECT id FROM product_lots WHERE drying_output_id IS NOT NULL "
        "AND (UPPER(business_id) = UPPER(%s) OR UPPER(lot_code) = UPPER(%s))", 2,
    ),
    'customer_order': (
        "SELECT id FROM customer_orders WHERE UPPER(business_id) = UPPER(%s)", 1,
    ),
    'delivery': (
        "SELECT id FROM customer_deliveries WHERE UPPER(business_id) = UPPER(%s)", 1,
    ),
}

TRACE_NODE_SQL = {
    'waste_lot': """
        SELECT wl.id, wl.business_id AS ref, wl.source_name || ' · ' || wl.waste_type AS title,
               UPPER(wl.status) AS status, wl.collection_date AS occurred,
               wl.quantity, wl.unit, wl.recorded_by AS actor,
               wl.farm_id, wl.site_id, wl.facility_id,
               json_build_object('source_type', wl.source_type,
                                 'quality_status', wl.quality_status) AS details
        FROM waste_lots AS wl WHERE wl.id = ANY(%s)
    """,
    'substrate_batch': """
        SELECT sb.id, sb.business_id AS ref, NULL AS title,
               NULL AS status, sb.preparation_date AS occurred,
               sb.total_input_weight_kg AS quantity, 'kg' AS unit,
               sb.recorded_by AS actor, sb.farm_id, sb.site_id, sb.facility_id,
               json_build_object('particle_size', sb.particle_size) AS details
        FROM substrate_batches AS sb WHERE sb.id = ANY(%s)
    """,
    'production_batch': """
        SELECT pb.id, pb.business_id AS ref,
               CASE WHEN UPPER(pb.current_stage) = UPPER(pb.status) THEN NULL
                    ELSE 'Stage: ' || pb.current_stage END AS title,
               UPPER(pb.status) AS status, pb.start_date AS occurred,
               (SELECT SUM(quantity_issued) FROM production_batch_inputs
                 WHERE production_batch_id = pb.id) AS quantity,
               'kg' AS unit, pb.recorded_by AS actor,
               pb.farm_id, pb.site_id, pb.facility_id,
               json_build_object('harvest_limit_kg', pb.harvest_limit_kg) AS details
        FROM production_batches AS pb WHERE pb.id = ANY(%s)
    """,
    'harvest': """
        SELECT h.id, h.harvest_code AS ref, h.harvest_stage AS title,
               NULL AS status, pe.occurred_at AS occurred,
               pe.quantity, 'kg' AS unit, h.operator AS actor,
               pe.farm_id, pe.site_id, pe.facility_id,
               json_build_object('location', h.location) AS details
        FROM harvests AS h
        JOIN production_events AS pe ON pe.id = h.production_event_id
        WHERE h.id = ANY(%s)
    """,
    'drying_batch': """
        SELECT db.id, COALESCE(db.business_id, db.batch_code, db.batch_id) AS ref,
               db.drying_method AS title, UPPER(db.status) AS status,
               db.drying_date AS occurred,
               (SELECT SUM(CASE WHEN o.unit = 'g' THEN o.quantity / 1000 ELSE o.quantity END)
                  FROM drying_outputs AS o WHERE o.drying_batch_id = db.id) AS quantity,
               'kg' AS unit, db.personnel AS actor,
               db.farm_id, db.site_id, db.facility_id,
               json_build_object(
                   'qc', (SELECT qc.status FROM quality_checks AS qc
                           WHERE qc.drying_batch_id = db.id ORDER BY qc.id DESC LIMIT 1)
               ) AS details
        FROM drying_batches AS db WHERE db.id = ANY(%s)
    """,
    'product_lot': f"""
        SELECT pl.id, pl.business_id AS ref, pl.product_type AS title,
               CASE WHEN {PRODUCT_LOT_RELEASABLE_SQL}
                    THEN 'AVAILABLE' ELSE 'BLOCKED' END AS status,
               pl.production_date AS occurred, pl.quantity_kg AS quantity,
               pl.unit, pl.recorded_by AS actor,
               pl.farm_id, batch.site_id, batch.facility_id,
               json_build_object('lot_code', pl.lot_code,
                                 'qc_status', qc.status,
                                 'approval', qa.decision) AS details
        FROM product_lots AS pl
        JOIN drying_outputs AS output ON output.id = pl.drying_output_id
        JOIN drying_batches AS batch ON batch.id = output.drying_batch_id
        LEFT JOIN quality_approvals AS qa ON qa.id = pl.release_approval_id
        LEFT JOIN quality_checks AS qc ON qc.id = qa.quality_check_id
        WHERE pl.id = ANY(%s)
    """,
    'inventory_location': """
        SELECT il.id, il.location_code AS ref, il.name AS title,
               UPPER(il.status) AS status, NULL::date AS occurred,
               NULL::numeric AS quantity, 'kg' AS unit, NULL AS actor,
               il.farm_id, il.site_id, il.facility_id,
               '{}'::json AS details
        FROM inventory_locations AS il WHERE il.id = ANY(%s)
    """,
    'customer_order': """
        SELECT o.id, o.business_id AS ref, c.name AS title, o.status,
               o.order_date AS occurred,
               (SELECT SUM(quantity_kg) FROM customer_order_lines
                 WHERE order_id = o.id) AS quantity,
               'kg' AS unit, o.created_by AS actor,
               o.farm_id, NULL::int AS site_id, NULL::int AS facility_id,
               json_build_object('farm_name', f.name,
                                 'requested_delivery_date', o.requested_delivery_date) AS details
        FROM customer_orders AS o
        JOIN customers AS c ON c.id = o.customer_id
        JOIN farms AS f ON f.id = o.farm_id
        WHERE o.id = ANY(%s)
    """,
    'delivery': """
        SELECT d.id, d.business_id AS ref, c.name AS title, d.status,
               d.dispatched_at AS occurred,
               (SELECT SUM(quantity_kg) FROM customer_delivery_lines
                 WHERE delivery_id = d.id) AS quantity,
               'kg' AS unit, d.created_by AS actor,
               o.farm_id, NULL::int AS site_id, NULL::int AS facility_id,
               json_build_object('farm_name', f.name, 'order_ref', o.business_id,
                                 'received_by', d.received_by,
                                 'delivered_at', d.delivered_at) AS details
        FROM customer_deliveries AS d
        JOIN customer_orders AS o ON o.id = d.order_id
        JOIN customers AS c ON c.id = o.customer_id
        JOIN farms AS f ON f.id = o.farm_id
        WHERE d.id = ANY(%s)
    """,
}

# (from_type, to_type, SQL returning from_id, to_id, quantity, unit)
TRACE_EDGE_SQL = [
    ('waste_lot', 'substrate_batch', """
        SELECT waste_lot_id AS from_id, substrate_batch_id AS to_id,
               quantity_used AS quantity, unit
        FROM substrate_batch_inputs WHERE {side} = ANY(%s)
    """, ('waste_lot_id', 'substrate_batch_id')),
    ('substrate_batch', 'production_batch', """
        SELECT substrate_batch_id AS from_id, production_batch_id AS to_id,
               quantity_issued AS quantity, unit
        FROM production_batch_inputs WHERE {side} = ANY(%s)
    """, ('substrate_batch_id', 'production_batch_id')),
    ('production_batch', 'harvest', """
        SELECT pe.production_batch_id AS from_id, h.id AS to_id,
               pe.quantity, 'kg' AS unit
        FROM harvests AS h
        JOIN production_events AS pe ON pe.id = h.production_event_id
        WHERE pe.status = 'recorded' AND {side} = ANY(%s)
    """, ('pe.production_batch_id', 'h.id')),
    ('harvest', 'drying_batch', """
        SELECT harvest_id AS from_id, drying_batch_id AS to_id,
               CASE WHEN unit = 'g' THEN quantity / 1000 ELSE quantity END AS quantity,
               'kg' AS unit
        FROM drying_inputs WHERE {side} = ANY(%s)
    """, ('harvest_id', 'drying_batch_id')),
    ('drying_batch', 'product_lot', """
        SELECT output.drying_batch_id AS from_id, pl.id AS to_id,
               pl.quantity_kg AS quantity, 'kg' AS unit
        FROM product_lots AS pl
        JOIN drying_outputs AS output ON output.id = pl.drying_output_id
        WHERE {side} = ANY(%s)
    """, ('output.drying_batch_id', 'pl.id')),
    # Current stock only: a location is a terminal node, never traversed
    # onwards to the other lots it happens to hold.
    ('product_lot', 'inventory_location', f"""
        WITH {INVENTORY_LEDGER_CTE}
        SELECT ledger.product_lot_id AS from_id, ledger.location_id AS to_id,
               SUM(ledger.delta) AS quantity, 'kg' AS unit
        FROM ledger WHERE {{side}} = ANY(%s)
        GROUP BY ledger.product_lot_id, ledger.location_id
        HAVING SUM(ledger.delta) <> 0
    """, ('ledger.product_lot_id', None)),
    # Quantity still committed to the order (allocated minus released).
    ('product_lot', 'customer_order', """
        SELECT a.product_lot_id AS from_id, l.order_id AS to_id,
               SUM(a.quantity_kg - a.released_kg) AS quantity, 'kg' AS unit
        FROM order_allocations AS a
        JOIN customer_order_lines AS l ON l.id = a.order_line_id
        WHERE {side} = ANY(%s)
        GROUP BY a.product_lot_id, l.order_id
        HAVING SUM(a.quantity_kg - a.released_kg) > 0
    """, ('a.product_lot_id', 'l.order_id')),
    ('product_lot', 'delivery', """
        SELECT a.product_lot_id AS from_id, dl.delivery_id AS to_id,
               SUM(dl.quantity_kg) AS quantity, 'kg' AS unit
        FROM customer_delivery_lines AS dl
        JOIN order_allocations AS a ON a.id = dl.allocation_id
        WHERE {side} = ANY(%s)
        GROUP BY a.product_lot_id, dl.delivery_id
    """, ('a.product_lot_id', 'dl.delivery_id')),
    ('customer_order', 'delivery', """
        SELECT d.order_id AS from_id, d.id AS to_id,
               (SELECT SUM(quantity_kg) FROM customer_delivery_lines
                 WHERE delivery_id = d.id) AS quantity, 'kg' AS unit
        FROM customer_deliveries AS d
        WHERE {side} = ANY(%s)
    """, ('d.order_id', 'd.id')),
]


def _trace_resolve(cursor, ref, record_type=None):
    ref = str(ref or '').strip()
    if not ref:
        raise ValueError('Enter a record ID to trace')
    if record_type:
        if record_type not in TRACE_ROOT_TYPES:
            raise ValueError('Unknown record type')
        types = [record_type]
    else:
        types = list(TRACE_ROOT_TYPES)
    matches = []
    for kind in types:
        if ref.isdigit() and record_type:
            cursor.execute(TRACE_ID_SQL[kind], (int(ref),))
        else:
            sql, count = TRACE_REF_SQL[kind]
            cursor.execute(sql, (ref,) * count)
        matches.extend((kind, row['id']) for row in cursor.fetchall())
    if not matches:
        if ref.isdigit() and not record_type:
            raise ValueError('Choose a record type to trace a numeric database ID')
        raise RecordNotFoundError(f'No traceable record matches {ref}')
    if len(matches) > 1:
        raise InventoryConflictError(
            'This ID matches more than one record; choose a record type: '
            + ', '.join(sorted({TRACE_LABELS[kind] for kind, _ in matches}))
        )
    return matches[0]


def _trace_walk(cursor, root, direction):
    """Breadth-first walk from ``root`` in one direction over stored edges."""
    seen = {root}
    frontier = {root}
    edges = []
    truncated = False
    while frontier:
        next_frontier = set()
        for from_type, to_type, sql, (from_col, to_col) in TRACE_EDGE_SQL:
            source_type = from_type if direction == 'down' else to_type
            ids = [node_id for kind, node_id in frontier if kind == source_type]
            side = from_col if direction == 'down' else to_col
            if not ids or side is None:
                continue
            cursor.execute(sql.format(side=side), (ids,))
            for row in cursor.fetchall():
                edges.append({
                    'from': f"{from_type}:{row['from_id']}",
                    'to': f"{to_type}:{row['to_id']}",
                    'quantity': row['quantity'],
                    'unit': row['unit'],
                })
                neighbour = (
                    (to_type, row['to_id']) if direction == 'down' else (from_type, row['from_id'])
                )
                if neighbour not in seen:
                    if len(seen) >= TRACE_NODE_LIMIT:
                        truncated = True
                        continue
                    seen.add(neighbour)
                    if neighbour[0] not in TRACE_TERMINAL:
                        next_frontier.add(neighbour)
        frontier = next_frontier
    return seen - {root}, edges, truncated


def _trace_can_access(cursor, farm_id, site_id, facility_id):
    try:
        _assert_production_scope_access(cursor, farm_id, site_id, facility_id)
        return True
    except ProductionEventPermissionError:
        return False


def _trace_nodes(cursor, keys, root):
    by_type = {}
    for kind, node_id in keys:
        by_type.setdefault(kind, []).append(node_id)
    nodes = {}
    for kind, ids in by_type.items():
        cursor.execute(TRACE_NODE_SQL[kind], (ids,))
        for row in cursor.fetchall():
            key = f"{kind}:{row['id']}"
            node = {'key': key, 'type': kind, 'type_label': TRACE_LABELS[kind], **dict(row)}
            node['is_root'] = (kind, row['id']) == root
            if kind in TRACE_COMMERCIAL:
                allowed = _farm_access_allowed(cursor, row['farm_id'])
            else:
                allowed = _trace_can_access(cursor, row['farm_id'], row['site_id'], row['facility_id'])
            if not allowed:
                # Show that a link exists without disclosing the record. The
                # reason is the user's own role or access, never the record.
                node = {
                    'key': key, 'type': kind, 'type_label': TRACE_LABELS[kind],
                    'restricted': True, 'is_root': False,
                    'restricted_reason': ('sales' if kind in TRACE_COMMERCIAL and not _can('sales.read')
                                          else 'location'),
                }
            else:
                node['restricted'] = False
                if kind == 'production_batch':
                    node['href'] = f"/batch-360?ref={row['ref']}"
                elif kind == 'product_lot':
                    node['href'] = f"/product-lot?ref={row['ref']}"
                elif kind == 'customer_order':
                    node['href'] = f"/orders?ref={row['ref']}"
                    node['location'] = row['details'].get('farm_name')
                elif kind == 'delivery':
                    node['href'] = f"/orders?ref={row['details'].get('order_ref')}"
                    node['location'] = row['details'].get('farm_name')
            nodes[key] = node
    names = {}
    scope_ids = {
        (n['farm_id'], n['site_id'], n['facility_id'])
        for n in nodes.values() if not n['restricted'] and n.get('facility_id')
    }
    if scope_ids:
        cursor.execute(
            """
            SELECT f.id AS farm_id, s.id AS site_id, fa.id AS facility_id,
                   f.name AS farm_name, s.name AS site_name, fa.name AS facility_name
            FROM facilities AS fa
            JOIN sites AS s ON s.id = fa.site_id
            JOIN farms AS f ON f.id = s.farm_id
            WHERE fa.id = ANY(%s)
            """,
            ([scope[2] for scope in scope_ids],),
        )
        names = {row['facility_id']: dict(row) for row in cursor.fetchall()}
    for node in nodes.values():
        place = names.get(node.get('facility_id'))
        if place and not node['restricted']:
            node['location'] = f"{place['farm_name']} / {place['site_name']} / {place['facility_name']}"
    return nodes


def _traceability(cursor, ref, record_type=None):
    root = _trace_resolve(cursor, ref, record_type)
    root_nodes = _trace_nodes(cursor, [root], root)
    root_node = root_nodes[f'{root[0]}:{root[1]}']
    if root_node['restricted']:
        # Same answer as a missing record, so IDs at other locations cannot be probed.
        raise RecordNotFoundError(f'No traceable record matches {ref}')

    upstream_keys, upstream_edges, up_truncated = _trace_walk(cursor, root, 'up')
    downstream_keys, downstream_edges, down_truncated = _trace_walk(cursor, root, 'down')
    nodes = _trace_nodes(cursor, upstream_keys | downstream_keys, root)
    nodes[root_node['key']] = root_node
    for key in (f'{kind}:{node_id}' for kind, node_id in upstream_keys):
        nodes[key]['direction'] = 'upstream'
    for key in (f'{kind}:{node_id}' for kind, node_id in downstream_keys):
        nodes[key].setdefault('direction', 'downstream')
    root_node['direction'] = 'root'

    def column(kind):
        rows = [node for node in nodes.values() if node['type'] == kind]
        rows.sort(key=lambda node: (not node.get('is_root'), node.get('restricted', False),
                                    str(node.get('ref') or '')))
        return rows

    stages = [
        {'type': kind, 'label': TRACE_LABELS[kind], 'nodes': column(kind)}
        for kind in TRACE_STAGES
    ]
    # Restricted neighbours keep their edge but lose quantities.
    edges = []
    for edge in upstream_edges + downstream_edges:
        hidden = nodes.get(edge['from'], {}).get('restricted') or nodes.get(edge['to'], {}).get('restricted')
        edges.append({**edge, 'quantity': None if hidden else edge['quantity']})

    return _jsonable({
        'root': root_node,
        'stages': stages,
        'edges': edges,
        'counts': {
            'upstream': len(upstream_keys),
            'downstream': len(downstream_keys),
            'restricted': sum(1 for node in nodes.values() if node['restricted']),
        },
        'truncated': up_truncated or down_truncated,
        'commercial': {'linked': True},
    })


@app.route('/api/traceability', methods=['GET'])
@login_required
def get_traceability():
    try:
        with db.transaction() as cursor:
            result = _traceability(
                cursor, request.args.get('ref'), request.args.get('type') or None
            )
        return jsonify({'success': True, 'data': result}), 200
    except ProductionEventPermissionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 403
    except RecordNotFoundError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 404
    except InventoryConflictError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 409
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception:
        logger.exception('Error building traceability graph')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/api/traceability/search', methods=['GET'])
@login_required
def search_traceability():
    """Suggest traceable records whose ID starts with ``q`` (scoped)."""
    query = str(request.args.get('q') or '').strip()
    if len(query) < 2:
        return jsonify({'success': True, 'data': []}), 200
    pattern = query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
    sources = [
        ('waste_lot', 'waste_lots AS t', 't.business_id', 't'),
        ('substrate_batch', 'substrate_batches AS t', 't.business_id', 't'),
        ('production_batch', 'production_batches AS t', 't.business_id', 't'),
        ('harvest', 'harvests AS h JOIN production_events AS t ON t.id = h.production_event_id',
         'h.harvest_code', 't'),
        ('drying_batch', 'drying_batches AS t', 'COALESCE(t.business_id, t.batch_code)', 't'),
        ('product_lot',
         'product_lots AS p JOIN drying_outputs AS o ON o.id = p.drying_output_id '
         'JOIN drying_batches AS t ON t.id = o.drying_batch_id',
         'p.business_id', 't'),
        ('customer_order', 'customer_orders AS t', 't.business_id', 't'),
        ('delivery', 'customer_deliveries AS d JOIN customer_orders AS t ON t.id = d.order_id',
         'd.business_id', 't'),
    ]
    try:
        results = []
        for kind, source, column_sql, alias in sources:
            visibility, params = (
                _farm_visibility_clause(alias) if kind in TRACE_COMMERCIAL
                else _scope_visibility_clause(alias)
            )
            rows = db.fetch_all(
                f"SELECT {column_sql} AS ref FROM {source} "
                f"WHERE {column_sql} ILIKE %s AND {visibility} "
                f"ORDER BY 1 DESC LIMIT 10",
                (pattern, *params),
            )
            results.extend(
                {'type': kind, 'type_label': TRACE_LABELS[kind], 'ref': row['ref']}
                for row in rows if row['ref']
            )
        return jsonify({'success': True, 'data': results[:20]}), 200
    except Exception:
        logger.exception('Error searching traceable records')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/traceability')
@login_required
def traceability_page():
    return render_template('traceability.html')
