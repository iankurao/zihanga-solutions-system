"""Waste sourcing, storage, processing, waste lots and substrate preparation."""

from decimal import Decimal
from flask import jsonify, request
from flask_login import current_user, login_required

from backend.core.web import app, db, logger
from backend.core.http import (
    ProductionEventPermissionError,
    _chain_actor,
    _parse_chain_quantity,
    _production_actor,
    _record_date,
    normalize_keys,
)
from backend.core.security import requires, super_admin_required
from backend.core.scope import (
    _assert_production_location,
    _assert_production_scope_access,
    _location_label,
    _optional_scope_filters,
    _production_scope_values,
    _scope_visibility_clause,
)


@app.route('/api/waste-sourcing', methods=['POST'])
@login_required
@requires('production.write')
def handle_waste_sourcing():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'No data provided'}), 400

    # Normalize keys from camelCase to snake_case
    normalized_data = normalize_keys(data)

    required_fields = [
        'collection_date', 'collection_time', 'source_type',
        'source_name', 'waste_type', 'waste_weight', 'segregation_status',
        'collection_personnel'
    ]
    missing_fields = [field for field in required_fields if field not in normalized_data or not normalized_data.get(field)]
    if missing_fields:
        return jsonify({'success': False, 'message': f'Missing required fields: {", ".join(missing_fields)}'}), 400

    try:
        farm_id, site_id, facility_id = _production_scope_values(
            normalized_data, 'a Waste Lot'
        )
        _record_date(normalized_data['collection_date'], 'collection_date')
        quantity = _parse_chain_quantity(normalized_data['waste_weight'], 'waste_weight')
        contaminants = normalized_data.get('contaminants_found', [])
        if isinstance(contaminants, list):
            contaminants = ','.join(str(item) for item in contaminants)
        elif contaminants:
            contaminants = str(contaminants)

        lot_status = normalized_data.get('lot_status', 'available')
        quality_status = str(normalized_data['segregation_status']).strip().lower()
        if lot_status not in ('available', 'quarantined', 'rejected'):
            raise ValueError('Lot status must be available, quarantined, or rejected')
        if lot_status == 'available' and (
            quality_status != 'organic' or bool(contaminants.strip())
        ):
            raise ValueError(
                'Only uncontaminated organic waste can be marked available'
            )

        actor = _chain_actor(normalized_data)
        with db.transaction() as cursor:
            location = _assert_production_location(cursor, farm_id, site_id, facility_id)
            _assert_production_scope_access(cursor, farm_id, site_id, facility_id)
            cursor.execute(
                """
                INSERT INTO waste_sourcing (
                    collection_date, collection_time, source_type, source_name,
                    waste_type, waste_weight, segregation_status,
                    contaminants_found, collection_notes, collection_personnel,
                    recorded_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, business_id
                """,
                (
                    normalized_data['collection_date'],
                    normalized_data['collection_time'],
                    normalized_data['source_type'],
                    normalized_data['source_name'],
                    normalized_data['waste_type'],
                    quantity,
                    normalized_data['segregation_status'],
                    contaminants or None,
                    normalized_data.get('collection_notes', ''),
                    normalized_data['collection_personnel'],
                    actor,
                ),
            )
            source_record = cursor.fetchone()
            cursor.execute(
                """
                INSERT INTO waste_lots (
                    business_id, waste_sourcing_id, farm_site,
                    farm_id, site_id, facility_id, source_type,
                    source_name, waste_type, collection_date, quantity, unit,
                    quality_status, status, recorded_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'kg', %s, %s, %s)
                RETURNING id, business_id, farm_site, farm_id, site_id,
                          facility_id, source_name,
                          collection_date, quantity, unit, quality_status,
                          status, recorded_by, created_at
                """,
                (
                    source_record['business_id'],
                    source_record['id'],
                    _location_label(location),
                    farm_id,
                    site_id,
                    facility_id,
                    normalized_data['source_type'],
                    normalized_data['source_name'].strip(),
                    normalized_data['waste_type'],
                    normalized_data['collection_date'],
                    quantity,
                    quality_status,
                    lot_status,
                    actor,
                ),
            )
            waste_lot = cursor.fetchone()
        return jsonify({
            'success': True,
            'message': 'Waste collection and lot recorded successfully',
            'record': source_record,
            'waste_lot': waste_lot,
            'id': source_record['id'],
            'business_id': source_record['business_id'],
        }), 201
    except ProductionEventPermissionError as e:
        return jsonify({'success': False, 'message': str(e)}), 403
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        logger.error(f"Error handling waste sourcing: {e}")
        return jsonify({'success': False, 'message': 'An error occurred while saving data.'}), 500

@app.route('/api/substrate-preparation', methods=['POST'])
@login_required
@requires('production.write')
def handle_substrate_preparation():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'No data provided'}), 400

    normalized_data = normalize_keys(data)
    
    required_fields = [
        'prep_date', 'moisture_consistency',
        'waste_particle_size', 'foreign_matter', 'handler_operator'
    ]
    missing_fields = [field for field in required_fields if field not in normalized_data or not normalized_data.get(field)]
    if missing_fields:
        return jsonify({'success': False, 'message': f'Missing required fields: {", ".join(missing_fields)}'}), 400

    try:
        _record_date(normalized_data['prep_date'], 'prep_date')
        input_rows = normalized_data.get('inputs')
        if not isinstance(input_rows, list) or not input_rows:
            raise ValueError('Select at least one available Waste Lot')

        requested_inputs = []
        seen_lot_ids = set()
        for row in input_rows:
            try:
                lot_id = int(row.get('waste_lot_id'))
            except (AttributeError, TypeError, ValueError):
                raise ValueError('Each substrate input must select a Waste Lot')
            if lot_id <= 0 or lot_id in seen_lot_ids:
                raise ValueError('Each Waste Lot can be selected only once per batch')
            seen_lot_ids.add(lot_id)
            requested_inputs.append({
                'waste_lot_id': lot_id,
                'quantity_used': _parse_chain_quantity(
                    row.get('quantity_used'), 'quantity_used'
                ),
            })

        # Lock in a consistent order so concurrent substrate preparations
        # serialize on each lot without deadlocking one another.
        requested_inputs.sort(key=lambda item: item['waste_lot_id'])
        actor = _chain_actor(normalized_data)
        substrate_scope = _production_scope_values(normalized_data, 'a Substrate Batch')
        total_input = Decimal('0')
        validated_inputs = []

        with db.transaction() as cursor:
            location = _assert_production_location(cursor, *substrate_scope)
            _assert_production_scope_access(cursor, *substrate_scope)
            batch_site = _location_label(location)
            for requested in requested_inputs:
                cursor.execute(
                    """
                    SELECT id, business_id, farm_site, farm_id, site_id,
                           quantity, unit, status, source_name
                    FROM waste_lots
                    WHERE id = %s
                    FOR UPDATE
                    """,
                    (requested['waste_lot_id'],),
                )
                lot = cursor.fetchone()
                if not lot:
                    raise ValueError('A selected Waste Lot does not exist')
                if lot['status'] != 'available':
                    raise ValueError(f"Waste Lot {lot['business_id']} is not available")
                if lot['farm_id'] is None:
                    raise ValueError(
                        f"Waste Lot {lot['business_id']} has no assigned farm/site/facility; "
                        'an administrator must assign it before use'
                    )
                # Waste may be received at a different facility on the same
                # site, but it never crosses farm or site boundaries.
                if (lot['farm_id'], lot['site_id']) != substrate_scope[:2]:
                    raise ValueError(
                        f"Waste Lot {lot['business_id']} belongs to a different farm/site"
                    )
                if lot['unit'] != 'kg':
                    raise ValueError(
                        f"Waste Lot {lot['business_id']} does not use kilograms"
                    )

                cursor.execute(
                    """
                    SELECT COALESCE(SUM(quantity_used), 0) AS quantity_consumed
                    FROM substrate_batch_inputs
                    WHERE waste_lot_id = %s
                    """,
                    (lot['id'],),
                )
                consumed = Decimal(str(cursor.fetchone()['quantity_consumed']))
                available = Decimal(str(lot['quantity'])) - consumed
                if requested['quantity_used'] > available:
                    raise ValueError(
                        f"Waste Lot {lot['business_id']} has only "
                        f"{available:.3f} kg available"
                    )
                total_input += requested['quantity_used']
                validated_inputs.append({
                    **lot,
                    'quantity_used': requested['quantity_used'],
                    'remaining_quantity': available - requested['quantity_used'],
                })

            cursor.execute(
                """
                WITH generated AS (
                    SELECT 'SUB-' || to_char(CURRENT_DATE, 'YYYY') || '-' ||
                           lpad(nextval('phase_one_substrate_batch_seq')::text, 5, '0')
                           AS business_id
                )
                INSERT INTO substrate_batches (
                    batch_code, business_id, preparation_date, farm_site,
                    farm_id, site_id, facility_id,
                    total_input_weight_kg, particle_size, notes, recorded_by
                )
                SELECT COALESCE(NULLIF(%s, ''), generated.business_id),
                       generated.business_id, %s, %s, %s, %s, %s, %s, %s, %s, %s
                FROM generated
                RETURNING id, business_id, batch_code
                """,
                (
                    normalized_data.get('batch_no', ''),
                    normalized_data['prep_date'],
                    batch_site,
                    substrate_scope[0],
                    substrate_scope[1],
                    substrate_scope[2],
                    total_input,
                    normalized_data['waste_particle_size'],
                    normalized_data.get('notes', ''),
                    actor,
                ),
            )
            batch = cursor.fetchone()

            source_summary = ', '.join(
                f"{item['business_id']} ({item['quantity_used']} kg)"
                for item in validated_inputs
            )[:100]
            cursor.execute(
                """
                INSERT INTO substrate_preparation (
                    batch_no, business_id, prep_date, organic_waste_source,
                    moisture_consistency, waste_particle_size, foreign_matter,
                    substrate_introduced_kg, handler_operator, notes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    normalized_data.get('batch_no') or batch['batch_code'],
                    batch['business_id'],
                    normalized_data['prep_date'],
                    source_summary,
                    normalized_data['moisture_consistency'],
                    normalized_data['waste_particle_size'],
                    normalized_data['foreign_matter'],
                    total_input,
                    normalized_data['handler_operator'],
                    normalized_data.get('notes', ''),
                ),
            )
            preparation_record = cursor.fetchone()

            for item in validated_inputs:
                cursor.execute(
                    """
                    INSERT INTO substrate_batch_inputs (
                        substrate_batch_id, waste_lot_id, quantity_used, unit, actor
                    ) VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        batch['id'],
                        item['id'],
                        item['quantity_used'],
                        item['unit'],
                        actor,
                    ),
                )
                if item['remaining_quantity'] == 0:
                    cursor.execute(
                        "UPDATE waste_lots SET status = 'consumed' WHERE id = %s",
                        (item['id'],),
                    )

            input_details = [
                {
                    'waste_lot_id': item['id'],
                    'business_id': item['business_id'],
                    'source_name': item['source_name'],
                    'quantity_used': item['quantity_used'],
                    'unit': item['unit'],
                    'remaining_quantity': item['remaining_quantity'],
                    'actor': actor,
                }
                for item in validated_inputs
            ]
        return jsonify({
            'success': True,
            'message': 'Substrate Batch created and Waste Lots consumed successfully',
            'record': {
                **batch,
                'farm_site': batch_site,
                'farm_id': substrate_scope[0],
                'site_id': substrate_scope[1],
                'facility_id': substrate_scope[2],
                'preparation_date': normalized_data['prep_date'],
                'total_input_weight_kg': total_input,
                'inputs': input_details,
                'preparation_record_id': preparation_record['id'],
            },
            'id': batch['id'],
            'business_id': batch['business_id'],
        }), 201
    except ProductionEventPermissionError as e:
        return jsonify({'success': False, 'message': str(e)}), 403
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        logger.error(f"Error saving substrate preparation record: {e}")
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500

@app.route('/api/waste-lots', methods=['GET'])
@login_required
def get_available_waste_lots():
    try:
        visibility, visibility_params = _scope_visibility_clause('wl')
        filters, filter_params = _optional_scope_filters('wl')
        where = ' AND '.join(["wl.status = 'available'", visibility, *filters])
        records = db.fetch_all(
            f"""
            SELECT wl.id, wl.business_id, wl.farm_site, wl.farm_id, wl.site_id,
                   wl.facility_id, f.name AS farm_name, s.name AS site_name,
                   fa.name AS facility_name, wl.source_type,
                   wl.source_name, wl.waste_type, wl.collection_date,
                   wl.quantity, wl.unit, wl.quality_status, wl.status,
                   wl.recorded_by, wl.created_at,
                   wl.quantity - COALESCE(SUM(sbi.quantity_used), 0)
                       AS available_quantity
            FROM waste_lots AS wl
            LEFT JOIN farms AS f ON f.id = wl.farm_id
            LEFT JOIN sites AS s ON s.id = wl.site_id
            LEFT JOIN facilities AS fa ON fa.id = wl.facility_id
            LEFT JOIN substrate_batch_inputs AS sbi ON sbi.waste_lot_id = wl.id
            WHERE {where}
            GROUP BY wl.id, f.name, s.name, fa.name
            HAVING wl.quantity - COALESCE(SUM(sbi.quantity_used), 0) > 0
            ORDER BY wl.collection_date DESC, wl.id DESC
            """,
            (*visibility_params, *filter_params),
        )
        return jsonify({'success': True, 'data': records}), 200
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        logger.error(f"Error fetching available Waste Lots: {e}")
        return jsonify({'success': False, 'message': 'Could not load Waste Lots'}), 500


@app.route('/api/waste-lots/<string:lot_ref>/location', methods=['POST'])
@login_required
@super_admin_required
def assign_waste_lot_location(lot_ref):
    """Assign canonical scope to an unscoped (older) Waste Lot exactly once.

    Older lots carry only free-text farm_site, which cannot prove ownership,
    so a super admin records the location explicitly.  Lots that already have
    canonical scope cannot be moved because substrate lineage depends on it.
    """
    data = normalize_keys(request.get_json() or {})
    try:
        farm_id, site_id, facility_id = _production_scope_values(data, 'a Waste Lot')
        lookup_id = int(lot_ref) if str(lot_ref).isdigit() else -1
        with db.transaction() as cursor:
            _assert_production_location(cursor, farm_id, site_id, facility_id)
            cursor.execute(
                """
                SELECT id, business_id, farm_id
                FROM waste_lots
                WHERE id = %s OR business_id = %s
                FOR UPDATE
                """,
                (lookup_id, str(lot_ref)),
            )
            lot = cursor.fetchone()
            if not lot:
                return jsonify({'success': False, 'message': 'Waste Lot not found'}), 404
            if lot['farm_id'] is not None:
                return jsonify({
                    'success': False,
                    'message': f"Waste Lot {lot['business_id']} already has an assigned location",
                }), 409
            cursor.execute(
                """
                UPDATE waste_lots
                SET farm_id = %s, site_id = %s, facility_id = %s,
                    location_assigned_by_user_id = %s,
                    location_assigned_at = CURRENT_TIMESTAMP
                WHERE id = %s
                RETURNING id, business_id, farm_site, farm_id, site_id,
                          facility_id, location_assigned_by_user_id,
                          location_assigned_at
                """,
                (farm_id, site_id, facility_id, _production_actor(data)[1], lot['id']),
            )
            record = cursor.fetchone()
        return jsonify({'success': True, 'data': record}), 200
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception:
        logger.exception('Error assigning Waste Lot location')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


def _substrate_batch_detail_query(where_clause='', order_clause=''):
    return f"""
        SELECT sb.id, sb.batch_code, sb.business_id, sb.preparation_date,
               sb.farm_site, sb.farm_id, sb.site_id, sb.facility_id,
               f.name AS farm_name, s.name AS site_name,
               fa.name AS facility_name,
               sb.total_input_weight_kg, sb.particle_size,
               sb.notes, sb.recorded_by, sb.created_at,
               -- Same availability rule as Production Batch creation.
               COALESCE(sb.output_weight_kg, sb.total_input_weight_kg, 0) - COALESCE((
                   SELECT SUM(pbi.quantity_issued) FROM production_batch_inputs AS pbi
                   WHERE pbi.substrate_batch_id = sb.id
               ), 0) AS available_kg,
               COALESCE(
                   json_agg(
                       json_build_object(
                           'waste_lot_id', wl.id,
                           'business_id', wl.business_id,
                           'source_name', wl.source_name,
                           'quantity_used', sbi.quantity_used,
                           'unit', sbi.unit,
                           'created_at', sbi.created_at,
                           'actor', sbi.actor
                       ) ORDER BY sbi.id
                   ) FILTER (WHERE sbi.id IS NOT NULL),
                   '[]'::json
               ) AS inputs
        FROM substrate_batches AS sb
        LEFT JOIN farms AS f ON f.id = sb.farm_id
        LEFT JOIN sites AS s ON s.id = sb.site_id
        LEFT JOIN facilities AS fa ON fa.id = sb.facility_id
        LEFT JOIN substrate_batch_inputs AS sbi
            ON sbi.substrate_batch_id = sb.id
        LEFT JOIN waste_lots AS wl ON wl.id = sbi.waste_lot_id
        {where_clause}
        GROUP BY sb.id, f.name, s.name, fa.name
        {order_clause}
    """


@app.route('/api/substrate-batches', methods=['GET'])
@login_required
def get_substrate_batches():
    try:
        visibility, visibility_params = _scope_visibility_clause('sb')
        filters, filter_params = _optional_scope_filters('sb')
        records = db.fetch_all(
            _substrate_batch_detail_query(
                where_clause='WHERE ' + ' AND '.join([visibility, *filters]),
                order_clause="ORDER BY sb.preparation_date DESC, sb.id DESC",
            ),
            (*visibility_params, *filter_params),
        )
        return jsonify({'success': True, 'data': records}), 200
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        logger.error(f"Error fetching Substrate Batches: {e}")
        return jsonify({'success': False, 'message': 'Could not load Substrate Batches'}), 500


@app.route('/api/substrate/batches/<string:batch_no>', methods=['GET'])
@login_required
def get_substrate_batch(batch_no):
    try:
        visibility, visibility_params = _scope_visibility_clause('sb')
        # Out-of-scope batches are reported as missing so their existence is
        # not disclosed to other farms.
        record = db.fetch_one(
            _substrate_batch_detail_query(
                "WHERE (sb.batch_code = %s OR sb.business_id = %s) AND " + visibility
            ),
            (batch_no, batch_no, *visibility_params),
        )
        if not record:
            return jsonify({'success': False, 'message': 'Substrate batch not found'}), 404
        return jsonify({'success': True, 'data': record})
    except Exception as e:
        logger.error(f"Error fetching substrate batch {batch_no}: {e}")
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500
