"""Batch 360: one production batch end to end."""

from datetime import date
from decimal import Decimal
from flask import jsonify, render_template
from flask_login import login_required

from backend.core.web import app, db, logger
from backend.core.http import (
    ProductionEventPermissionError,
    RecordNotFoundError,
    _jsonable,
    _kg_text,
    _ratio_percent,
    _to_kg,
)
from backend.core.scope import _assert_production_scope_access, _farm_access_allowed
from backend.domains.inventory import PRODUCT_LOT_RELEASABLE_SQL, _inventory_summary
from backend.domains.alerts import _sync_alerts


def _batch_alerts(cursor, batch_id, drying_ids, lot_ids):
    """Active production, QC and stock alerts that concern this batch."""
    cursor.execute(
        """
        SELECT id, rule, severity, title, message, status, href, first_detected_at
        FROM operational_alerts
        WHERE status <> 'RESOLVED' AND (
            (entity_type = 'production_batch' AND entity_id = %s)
            OR (entity_type = 'production_event' AND details->>'production_batch_id' = %s)
            OR (entity_type = 'drying_batch' AND entity_id = ANY(%s))
            OR (entity_type = 'product_lot' AND entity_id = ANY(%s))
        )
        ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, id
        """,
        (batch_id, str(batch_id), drying_ids, lot_ids),
    )
    return [dict(row) for row in cursor.fetchall()]


def _batch_commercial(cursor, farm_id, product_lots):
    """Orders and deliveries that drew on these lots, if the caller may see them."""
    if not _farm_access_allowed(cursor, farm_id):
        return {'restricted': True, 'orders': [], 'deliveries': []}
    lot_ids = [lot['id'] for lot in product_lots]
    if not lot_ids:
        return {'restricted': False, 'orders': [], 'deliveries': []}
    cursor.execute(
        """
        SELECT o.business_id, o.status, c.name AS customer_name,
               SUM(a.quantity_kg - a.released_kg) AS committed_kg
        FROM order_allocations AS a
        JOIN customer_order_lines AS l ON l.id = a.order_line_id
        JOIN customer_orders AS o ON o.id = l.order_id
        JOIN customers AS c ON c.id = o.customer_id
        WHERE a.product_lot_id = ANY(%s)
        GROUP BY o.id, c.name
        HAVING SUM(a.quantity_kg - a.released_kg) > 0
        ORDER BY o.id
        """,
        (lot_ids,),
    )
    orders = [dict(row) for row in cursor.fetchall()]
    cursor.execute(
        """
        SELECT d.business_id, d.status, o.business_id AS order_business_id,
               c.name AS customer_name, SUM(dl.quantity_kg) AS quantity_kg
        FROM customer_delivery_lines AS dl
        JOIN order_allocations AS a ON a.id = dl.allocation_id
        JOIN customer_deliveries AS d ON d.id = dl.delivery_id
        JOIN customer_orders AS o ON o.id = d.order_id
        JOIN customers AS c ON c.id = o.customer_id
        WHERE a.product_lot_id = ANY(%s)
        GROUP BY d.id, o.business_id, c.name
        ORDER BY d.id
        """,
        (lot_ids,),
    )
    return {
        'restricted': False,
        'orders': orders,
        'deliveries': [dict(row) for row in cursor.fetchall()],
    }


def _batch_360(cursor, batch_ref):
    """Assemble one production batch's full upstream and downstream record.

    Everything comes from stored relationships; nothing is inferred from
    names, labels or timestamps.  Sections with no recorded data are returned
    empty so the page can say so instead of showing placeholders.
    """
    lookup_id = int(batch_ref) if str(batch_ref).isdigit() else -1
    cursor.execute(
        """
        SELECT pb.id, pb.business_id, pb.batch_code, UPPER(pb.status) AS status,
               pb.current_stage, pb.start_date, pb.started_at,
               pb.expected_harvest_at, pb.harvest_limit_kg, pb.notes,
               pb.recorded_by, pb.created_at::timestamptz AS created_at, pb.farm_id, pb.site_id,
               pb.facility_id, f.name AS farm_name, s.name AS site_name,
               fa.name AS facility_name, fa.facility_type,
               GREATEST(CURRENT_DATE - pb.start_date, 0) AS age_days
        FROM production_batches AS pb
        LEFT JOIN farms AS f ON f.id = pb.farm_id
        LEFT JOIN sites AS s ON s.id = pb.site_id
        LEFT JOIN facilities AS fa ON fa.id = pb.facility_id
        WHERE pb.id = %s OR pb.business_id = %s OR pb.batch_code = %s
        """,
        (lookup_id, str(batch_ref), str(batch_ref)),
    )
    batch = cursor.fetchone()
    if not batch:
        raise RecordNotFoundError('Production Batch not found')
    batch = dict(batch)
    _assert_production_scope_access(
        cursor, batch['farm_id'], batch['site_id'], batch['facility_id']
    )
    batch_id = batch['id']

    # 1. Source material: substrate issued to this batch and its waste lots.
    cursor.execute(
        """
        SELECT pbi.substrate_batch_id, pbi.quantity_issued, pbi.unit,
               pbi.issued_at, pbi.actor, sb.business_id, sb.batch_code,
               sb.preparation_date, sb.total_input_weight_kg, sb.particle_size
        FROM production_batch_inputs AS pbi
        JOIN substrate_batches AS sb ON sb.id = pbi.substrate_batch_id
        WHERE pbi.production_batch_id = %s
        ORDER BY pbi.id
        """,
        (batch_id,),
    )
    substrates = [dict(row) for row in cursor.fetchall()]
    substrate_ids = [row['substrate_batch_id'] for row in substrates]
    waste_by_substrate = {}
    if substrate_ids:
        cursor.execute(
            """
            SELECT sbi.substrate_batch_id, sbi.quantity_used, sbi.unit,
                   wl.id AS waste_lot_id, wl.business_id, wl.source_type,
                   wl.source_name, wl.waste_type, wl.collection_date,
                   wl.quantity AS lot_quantity, wl.quality_status
            FROM substrate_batch_inputs AS sbi
            JOIN waste_lots AS wl ON wl.id = sbi.waste_lot_id
            WHERE sbi.substrate_batch_id = ANY(%s)
            ORDER BY sbi.substrate_batch_id, wl.collection_date, wl.id
            """,
            (substrate_ids,),
        )
        for row in cursor.fetchall():
            waste_by_substrate.setdefault(row['substrate_batch_id'], []).append(dict(row))
    for substrate in substrates:
        substrate['waste_lots'] = waste_by_substrate.get(substrate['substrate_batch_id'], [])
    substrate_issued_kg = sum(
        (_to_kg(row['quantity_issued'], row['unit']) for row in substrates), Decimal('0')
    )

    # 2–4. Operations and harvests from the production event envelope.
    cursor.execute(
        """
        SELECT pe.id, pe.event_code, pe.event_type, pe.occurred_at, pe.actor,
               pe.quantity, pe.unit, pe.notes,
               fe.feed_type, fe.quantity_offered, fe.offered_unit,
               fe.quantity_consumed, fe.consumed_unit, fe.larvae_age_days,
               me.temperature, me.humidity, me.ammonia, me.asset_reference,
               he.status AS health_status, he.observed_issue, he.severity,
               he.action_taken, he.follow_up_date,
               hs.id AS harvest_id, hs.harvest_code, hs.wet_weight,
               hs.unit AS harvest_unit, hs.harvest_stage, hs.operator,
               hs.location
        FROM production_events AS pe
        LEFT JOIN feeding_events AS fe ON fe.production_event_id = pe.id
        LEFT JOIN monitoring_events AS me ON me.production_event_id = pe.id
        LEFT JOIN health_events AS he ON he.production_event_id = pe.id
        LEFT JOIN harvests AS hs ON hs.production_event_id = pe.id
        WHERE pe.production_batch_id = %s AND pe.status = 'recorded'
        ORDER BY pe.occurred_at, pe.id
        """,
        (batch_id,),
    )
    events = [dict(row) for row in cursor.fetchall()]
    feeding = [e for e in events if e['event_type'] == 'feeding']
    monitoring = [e for e in events if e['event_type'] == 'monitoring']
    health = [e for e in events if e['event_type'] == 'health']
    harvests = [e for e in events if e['event_type'] == 'harvest']

    temperatures = [e['temperature'] for e in monitoring if e['temperature'] is not None]
    humidities = [e['humidity'] for e in monitoring if e['humidity'] is not None]
    operations = {
        'feeding': {
            'count': len(feeding),
            'total_offered_kg': sum(
                (_to_kg(e['quantity_offered'], e['offered_unit']) or Decimal('0') for e in feeding),
                Decimal('0'),
            ),
            'feed_types': sorted({e['feed_type'] for e in feeding if e['feed_type']}),
            'last_at': feeding[-1]['occurred_at'] if feeding else None,
            'recent': feeding[-5:][::-1],
        },
        'monitoring': {
            'count': len(monitoring),
            'latest': monitoring[-1] if monitoring else None,
            'temperature_min': min(temperatures) if temperatures else None,
            'temperature_max': max(temperatures) if temperatures else None,
            'humidity_min': min(humidities) if humidities else None,
            'humidity_max': max(humidities) if humidities else None,
            'recent': monitoring[-5:][::-1],
        },
        'health': {
            'count': len(health),
            'open_count': sum(1 for e in health if e['health_status'] in ('open', 'follow_up')),
            'items': health[::-1],
        },
    }

    harvested_kg = sum((Decimal(str(e['quantity'] or 0)) for e in harvests), Decimal('0'))
    harvest = {
        'count': len(harvests),
        'total_wet_kg': harvested_kg,
        'first_at': harvests[0]['occurred_at'] if harvests else None,
        'last_at': harvests[-1]['occurred_at'] if harvests else None,
        'items': harvests,
        # Wet larvae harvested per kg of substrate issued to this batch.
        'substrate_conversion_percent': _ratio_percent(
            harvested_kg if harvests else None, substrate_issued_kg
        ),
        'harvest_limit_kg': batch['harvest_limit_kg'],
        'limit_used_percent': _ratio_percent(
            harvested_kg if harvests else None, batch['harvest_limit_kg']
        ),
    }

    # 5. Processing: drying batches that consumed this batch's harvests.
    harvest_ids = [e['harvest_id'] for e in harvests if e['harvest_id']]
    drying_batches = []
    output_ids = []
    if harvest_ids:
        cursor.execute(
            """
            SELECT DISTINCT db.id, db.business_id, db.batch_code,
                   UPPER(db.status) AS status, db.drying_method, db.drying_date,
                   db.started_at, db.ended_at
            FROM drying_inputs AS di
            JOIN drying_batches AS db ON db.id = di.drying_batch_id
            WHERE di.harvest_id = ANY(%s)
            ORDER BY db.id
            """,
            (harvest_ids,),
        )
        drying_batches = [dict(row) for row in cursor.fetchall()]
    for drying in drying_batches:
        cursor.execute(
            """
            SELECT di.quantity, di.unit, di.incoming_moisture_percent,
                   di.harvest_id, hs.harvest_code,
                   pe.production_batch_id
            FROM drying_inputs AS di
            JOIN harvests AS hs ON hs.id = di.harvest_id
            JOIN production_events AS pe ON pe.id = hs.production_event_id
            WHERE di.drying_batch_id = %s
            ORDER BY di.line_no
            """,
            (drying['id'],),
        )
        inputs = [dict(row) for row in cursor.fetchall()]
        own_inputs = [row for row in inputs if row['production_batch_id'] == batch_id]
        drying['inputs_from_this_batch'] = own_inputs
        drying['input_from_this_batch_kg'] = sum(
            (_to_kg(row['quantity'], row['unit']) for row in own_inputs), Decimal('0')
        )
        drying['total_input_kg'] = sum(
            (_to_kg(row['quantity'], row['unit']) for row in inputs), Decimal('0')
        )
        drying['shared_with_other_batches'] = len(
            {row['production_batch_id'] for row in inputs} - {batch_id}
        )
        cursor.execute(
            """
            SELECT id, line_no, quantity, unit, moisture_percent, output_date,
                   operator
            FROM drying_outputs
            WHERE drying_batch_id = %s
            ORDER BY line_no
            """,
            (drying['id'],),
        )
        outputs = [dict(row) for row in cursor.fetchall()]
        drying['outputs'] = outputs
        output_ids.extend(row['id'] for row in outputs)
        drying['total_output_kg'] = sum(
            (_to_kg(row['quantity'], row['unit']) for row in outputs), Decimal('0')
        )
        moistures = [row['moisture_percent'] for row in outputs if row['moisture_percent'] is not None]
        drying['output_moisture_percent'] = moistures[-1] if moistures else None
        drying['yield_percent'] = _ratio_percent(
            drying['total_output_kg'] if outputs else None, drying['total_input_kg']
        )
    processing = {
        'drying_batches': drying_batches,
        'wet_input_kg': sum(
            (row['input_from_this_batch_kg'] for row in drying_batches), Decimal('0')
        ),
        'dry_output_kg': sum((row['total_output_kg'] for row in drying_batches), Decimal('0')),
        'any_shared': any(row['shared_with_other_batches'] for row in drying_batches),
    }

    # 6. Quality: the latest check and decision for each drying output.
    quality = []
    if output_ids:
        cursor.execute(
            """
            SELECT DISTINCT ON (qc.drying_output_id)
                   qc.drying_output_id, qc.id AS quality_check_id, qc.check_code,
                   qc.status AS check_status, qc.moisture_percent, qc.inspector,
                   qc.checked_at, qc.created_at AS check_recorded_at,
                   db.business_id AS drying_batch_business_id,
                   approval.approval_code, approval.decision, approval.approver,
                   approval.decided_at, approval.rationale
            FROM quality_checks AS qc
            JOIN drying_batches AS db ON db.id = qc.drying_batch_id
            LEFT JOIN LATERAL (
                SELECT approval_code, decision, approver, decided_at, rationale
                FROM quality_approvals
                WHERE quality_check_id = qc.id
                ORDER BY id DESC
                LIMIT 1
            ) AS approval ON TRUE
            WHERE qc.drying_output_id = ANY(%s)
            ORDER BY qc.drying_output_id, qc.id DESC
            """,
            (output_ids,),
        )
        quality = [dict(row) for row in cursor.fetchall()]

    # 7–8. Product lots released from those outputs and their stock.
    product_lots = []
    if output_ids:
        cursor.execute(
            f"""
            SELECT pl.id, pl.business_id, pl.lot_code, pl.product_type,
                   pl.quantity_kg, pl.unit, pl.production_date,
                   pl.drying_output_id, pl.storage_location,
                   pl.created_at::timestamptz AS created_at,
                   pl.recorded_by,
                   CASE WHEN {PRODUCT_LOT_RELEASABLE_SQL}
                        THEN 'AVAILABLE' ELSE 'BLOCKED' END AS status
            FROM product_lots AS pl
            WHERE pl.drying_output_id = ANY(%s)
            ORDER BY pl.id
            """,
            (output_ids,),
        )
        product_lots = [dict(row) for row in cursor.fetchall()]
    inventory_balances = []
    inventory_movements = []
    for lot in product_lots:
        summary = _inventory_summary(cursor, lot['id'])
        lot['on_hand_kg'] = summary['on_hand_kg']
        for row in summary['balances']:
            inventory_balances.append({**row, 'product_lot_business_id': lot['business_id']})
        for row in summary['movements']:
            inventory_movements.append({**row, 'product_lot_business_id': lot['business_id']})
    inventory_movements.sort(key=lambda row: (row['occurred_at'], row['id']))
    inventory = {
        'on_hand_kg': sum((lot['on_hand_kg'] for lot in product_lots), Decimal('0')),
        'available_kg': sum(
            (lot['on_hand_kg'] for lot in product_lots if lot['status'] == 'AVAILABLE'),
            Decimal('0'),
        ),
        'balances': inventory_balances,
        'movements': inventory_movements,
    }

    # 10. Audit: lifecycle facts from their authoritative tables.
    audit = []
    cursor.execute(
        """
        SELECT previous_status, new_status, actor, changed_at, reason
        FROM production_batch_status_history
        WHERE production_batch_id = %s
        ORDER BY changed_at, id
        """,
        (batch_id,),
    )
    for row in cursor.fetchall():
        audit.append({
            'at': row['changed_at'], 'kind': 'status',
            'title': (
                f"Status {row['previous_status']} → {row['new_status']}"
                if row['previous_status'] else f"Batch created as {row['new_status']}"
            ),
            'actor': row['actor'], 'detail': row['reason'],
        })
    if not any(entry['title'].startswith('Batch created') for entry in audit):
        # Legacy batches predate status history; fall back to the row itself.
        audit.append({
            'at': batch['created_at'], 'kind': 'status', 'title': 'Batch created',
            'actor': batch['recorded_by'], 'detail': None,
        })
    for event in harvests:
        audit.append({
            'at': event['occurred_at'], 'kind': 'harvest',
            'title': f"Harvest {event['harvest_code']} recorded",
            'actor': event['actor'],
            'detail': f"{_kg_text(event['quantity'])} wet · {event['harvest_stage']}",
        })
    for event in health:
        audit.append({
            'at': event['occurred_at'], 'kind': 'health',
            'title': f"Health event ({event['severity']})",
            'actor': event['actor'], 'detail': event['observed_issue'],
        })
    if drying_batches:
        cursor.execute(
            """
            SELECT h.previous_status, h.new_status, h.actor, h.changed_at, h.reason,
                   db.business_id
            FROM drying_batch_status_history AS h
            JOIN drying_batches AS db ON db.id = h.drying_batch_id
            WHERE h.drying_batch_id = ANY(%s)
            ORDER BY h.changed_at, h.id
            """,
            ([row['id'] for row in drying_batches],),
        )
        for row in cursor.fetchall():
            audit.append({
                'at': row['changed_at'], 'kind': 'drying',
                'title': (
                    f"{row['business_id']} {row['previous_status']} → {row['new_status']}"
                    if row['previous_status']
                    else f"{row['business_id']} created as {row['new_status']}"
                ),
                'actor': row['actor'], 'detail': row['reason'],
            })
    for check in quality:
        audit.append({
            'at': check['check_recorded_at'], 'kind': 'quality',
            'title': f"QC {check['check_code']} {check['check_status']}",
            'actor': check['inspector'], 'detail': check['drying_batch_business_id'],
        })
        if check['decision']:
            audit.append({
                'at': check['decided_at'], 'kind': 'quality',
                'title': f"QC decision {check['approval_code']}: {check['decision']}",
                'actor': check['approver'], 'detail': check['rationale'],
            })
    for lot in product_lots:
        audit.append({
            'at': lot['created_at'], 'kind': 'product',
            'title': f"Product Lot {lot['business_id']} released",
            'actor': lot['recorded_by'],
            'detail': f"{_kg_text(lot['quantity_kg'])} {lot['product_type']}",
        })
    for movement in inventory_movements:
        audit.append({
            'at': movement['occurred_at'], 'kind': 'inventory',
            'title': f"{movement['business_id']} {movement['movement_type']}",
            'actor': movement['recorded_by'],
            'detail': f"{_kg_text(movement['quantity_kg'])} · {movement['product_lot_business_id']}",
        })
    audit = [row for row in audit if row['at'] is not None]
    # Every audit timestamp is timestamptz (naive columns are cast in SQL).
    audit.sort(key=lambda row: row['at'])

    has_approval = any(q['decision'] == 'approved' for q in quality)
    stages = [
        {'key': 'source', 'label': 'Source material', 'done': bool(substrates)},
        {'key': 'production', 'label': 'Production', 'done': batch['status'] not in ('PLANNED', 'CANCELLED')},
        {'key': 'harvest', 'label': 'Harvest', 'done': bool(harvests)},
        {'key': 'processing', 'label': 'Drying', 'done': any(d['outputs'] for d in drying_batches)},
        {'key': 'quality', 'label': 'QC approved', 'done': has_approval},
        {'key': 'product', 'label': 'Product lot', 'done': bool(product_lots)},
        {'key': 'inventory', 'label': 'In stock', 'done': inventory['on_hand_kg'] > 0},
    ]

    traceability = {
        'upstream': {
            'waste_lots': [
                {'business_id': lot['business_id'], 'source_name': lot['source_name'],
                 'quantity_used': lot['quantity_used'], 'unit': lot['unit'],
                 'substrate_business_id': sub['business_id']}
                for sub in substrates for lot in sub['waste_lots']
            ],
            'substrate_batches': [
                {'business_id': sub['business_id'], 'quantity_issued': sub['quantity_issued'],
                 'unit': sub['unit']}
                for sub in substrates
            ],
        },
        'downstream': {
            'harvests': [
                {'harvest_code': e['harvest_code'], 'wet_kg': e['quantity']} for e in harvests
            ],
            'drying_batches': [
                {'business_id': d['business_id'], 'status': d['status'],
                 'output_kg': d['total_output_kg']} for d in drying_batches
            ],
            'product_lots': [
                {'business_id': lot['business_id'], 'status': lot['status'],
                 'on_hand_kg': lot['on_hand_kg']} for lot in product_lots
            ],
            'locations': sorted({
                f"{row['location_name']} ({row['location_code']})" for row in inventory_balances
            }),
            'commercial': _batch_commercial(cursor, batch['farm_id'], product_lots),
        },
    }

    expected = batch['expected_harvest_at']
    production = {
        'status': batch['status'],
        'current_stage': batch['current_stage'],
        'start_date': batch['start_date'],
        'started_at': batch['started_at'],
        'expected_harvest_at': expected,
        'days_to_expected_harvest': (
            (expected.date() - date.today()).days if expected is not None else None
        ),
        'age_days': batch['age_days'],
        'substrate_issued_kg': substrate_issued_kg,
    }

    return _jsonable({
        'batch': batch,
        'stages': stages,
        'source': {'substrate_batches': substrates, 'substrate_issued_kg': substrate_issued_kg},
        'production': production,
        'operations': operations,
        'harvest': harvest,
        'processing': processing,
        'quality': quality,
        'product_lots': product_lots,
        'inventory': inventory,
        'traceability': traceability,
        'audit': audit,
        'alerts': _batch_alerts(
            cursor, batch_id,
            [row['id'] for row in drying_batches],
            [lot['id'] for lot in product_lots],
        ),
    })


@app.route('/api/production/batches/<string:batch_ref>/360', methods=['GET'])
@login_required
def get_production_batch_360(batch_ref):
    # Operational alerts must not stop the executive view from loading.
    try:
        _sync_alerts()
    except Exception:
        logger.exception('Alert sync failed while loading Batch 360')
    try:
        with db.transaction() as cursor:
            record = _batch_360(cursor, batch_ref)
        return jsonify({'success': True, 'data': record}), 200
    except ProductionEventPermissionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 403
    except RecordNotFoundError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 404
    except Exception:
        logger.exception('Error building Batch 360 view')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/batch-360')
@login_required
def batch_360_page():
    return render_template('batch_360.html')
