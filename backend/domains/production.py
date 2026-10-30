"""Production batches, status changes and production events (feeding, monitoring, health, harvest)."""

from decimal import Decimal
from flask import jsonify, request
from flask_login import current_user, login_required

from backend.core.web import app, db, logger
from backend.core.http import (
    ProductionEventPermissionError,
    _chain_actor,
    _event_decimal,
    _event_occurred_at,
    _event_unit,
    _parse_chain_quantity,
    _parse_positive_integer,
    _production_actor,
    normalize_keys,
)
from backend.core.security import requires
from backend.core.scope import (
    _assert_production_location,
    _assert_production_scope_access,
    _optional_scope_filters,
    _production_scope_values,
    _scope_visibility_clause,
)
from backend.domains.units import PRODUCTION_UNIT_RELEASE_STATUSES, _assign_units, _batch_units


PRODUCTION_BATCH_STATUSES = {
    'PLANNED',
    'ACTIVE',
    'MONITORING',
    'READY_FOR_HARVEST',
    'HARVESTED',
    'COMPLETED',
    'PAUSED',
    'HEALTH_ALERT',
    'CANCELLED',
}

PRODUCTION_BATCH_TRANSITIONS = {
    'PLANNED': {'ACTIVE', 'PAUSED', 'CANCELLED'},
    'ACTIVE': {'MONITORING', 'PAUSED', 'HEALTH_ALERT', 'CANCELLED'},
    'MONITORING': {'READY_FOR_HARVEST', 'PAUSED', 'HEALTH_ALERT', 'CANCELLED'},
    'READY_FOR_HARVEST': {'HARVESTED', 'PAUSED', 'CANCELLED'},
    'HARVESTED': {'COMPLETED'},
    'PAUSED': {'ACTIVE', 'MONITORING', 'HEALTH_ALERT', 'CANCELLED'},
    'HEALTH_ALERT': {'PAUSED', 'ACTIVE', 'MONITORING', 'CANCELLED'},
    'CANCELLED': set(),
    'COMPLETED': set(),
}


PRODUCTION_BATCH_STATUS_ORDER = (
    'ACTIVE', 'MONITORING', 'READY_FOR_HARVEST', 'HARVESTED', 'COMPLETED',
    'PAUSED', 'HEALTH_ALERT', 'CANCELLED',
)
# Statuses that need a reason (checked by change_production_batch_status).
PRODUCTION_BATCH_REASON_STATUSES = {'PAUSED', 'HEALTH_ALERT', 'CANCELLED'}

EVENT_BATCH_CLOSED_STATUSES = {'COMPLETED', 'CANCELLED'}


def _event_bool(value):
    return value is True or str(value).strip().lower() in {'1', 'true', 'yes'}


def _production_event_batch(cursor, batch_ref, data):
    lookup_id = int(batch_ref) if str(batch_ref).isdigit() else -1
    cursor.execute(
        """
        SELECT id, business_id, batch_code, farm_id, site_id, facility_id,
               harvest_limit_kg, UPPER(status) AS status
        FROM production_batches
        WHERE id = %s OR business_id = %s OR batch_code = %s
        FOR UPDATE
        """,
        (lookup_id, str(batch_ref), str(batch_ref)),
    )
    batch = cursor.fetchone()
    if not batch:
        raise ValueError('Production Batch not found')
    _assert_production_scope_access(
        cursor, batch['farm_id'], batch['site_id'], batch['facility_id']
    )
    provided_facility = data.get('facility_id')
    if provided_facility not in (None, ''):
        if _parse_positive_integer(provided_facility, 'facility_id') != batch['facility_id']:
            raise ValueError('The event facility must match the Production Batch facility')
    allow_closed = _event_bool(data.get('allow_closed_batch'))
    if batch['status'] in EVENT_BATCH_CLOSED_STATUSES and not (
        allow_closed
        and getattr(current_user, 'is_authenticated', False)
        and current_user.role == 'super_admin'
    ):
        raise ValueError(
            f'Events cannot be recorded against a {batch["status"].lower()} Production Batch'
        )
    return batch


def _insert_production_event(
    cursor, batch_ref, event_type, data, occurred_at, *, quantity=None, unit=None, notes=None
):
    batch = _production_event_batch(cursor, batch_ref, data)
    cursor.execute(
        """
        INSERT INTO production_events (
            production_batch_id, farm_id, site_id, facility_id, event_type,
            occurred_at, created_by_user_id, actor, quantity, unit, notes
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id, event_code, production_batch_id, farm_id, site_id,
                  facility_id, event_type, occurred_at, actor, status,
                  quantity, unit, notes, created_at
        """,
        (
            batch['id'], batch['farm_id'], batch['site_id'], batch['facility_id'],
            event_type, occurred_at,
            getattr(current_user, 'id', None) if getattr(current_user, 'is_authenticated', False) else None,
            _chain_actor(data), quantity, unit, notes,
        ),
    )
    return batch, cursor.fetchone()


def _event_batch_ref(data):
    value = data.get('production_batch_id')
    if value in (None, ''):
        raise ValueError('production_batch_id is required')
    return value


def _event_response(event):
    return {'event': dict(event)}


def _harvest_report_rows():
    user_id = getattr(current_user, 'id', None)
    can_view_all = app.config.get('LOGIN_DISABLED') or (
        getattr(current_user, 'is_authenticated', False)
        and getattr(current_user, 'role', None) == 'super_admin'
    )
    return db.fetch_all(
        """
        SELECT *
        FROM (
            SELECT
                h.id,
                h.harvest_code AS business_id,
                pe.occurred_at::date AS harvest_date,
                COALESCE(pb.business_id, pb.batch_code) AS production_batch,
                h.harvest_stage,
                pe.quantity AS quantity_kg,
                pe.notes,
                h.operator AS recorded_by,
                pe.production_batch_id,
                h.unit,
                h.wet_weight
            FROM harvests AS h
            JOIN production_events AS pe ON pe.id = h.production_event_id
            JOIN production_batches AS pb ON pb.id = pe.production_batch_id
            WHERE pe.event_type = 'harvest'
              AND pe.status = 'recorded'
              AND (
                  %s OR EXISTS (
                      SELECT 1
                      FROM facilities AS fa
                      JOIN sites AS s
                        ON s.id = fa.site_id AND s.farm_id = pe.farm_id
                      JOIN farms AS f ON f.id = s.farm_id
                      WHERE fa.id = pe.facility_id
                        AND s.id = pe.site_id
                        AND (
                            EXISTS (
                                SELECT 1
                                FROM user_organization_access AS uoa
                                JOIN organizations AS o
                                  ON o.id = uoa.organization_id
                                WHERE uoa.user_id = %s
                                  AND o.id = f.organization_id
                            )
                            OR EXISTS (
                                SELECT 1 FROM user_farm_access AS ufa
                                WHERE ufa.user_id = %s AND ufa.farm_id = f.id
                            )
                            OR EXISTS (
                                SELECT 1 FROM user_site_access AS usa
                                WHERE usa.user_id = %s AND usa.site_id = s.id
                            )
                            OR EXISTS (
                                SELECT 1 FROM user_facility_access AS uca
                                WHERE uca.user_id = %s
                                  AND uca.facility_id = fa.id
                            )
                        )
                  )
              )
        ) AS harvest_records
        ORDER BY harvest_date DESC, id DESC
        """,
        (
            can_view_all,
            user_id,
            user_id,
            user_id,
            user_id,
        ),
    )


def _create_feeding_event(data):
    batch_ref = _event_batch_ref(data)
    occurred_at = _event_occurred_at(data, ('feeding_date',))
    feed_type = str(data.get('feed_type') or '').strip()
    operator = str(data.get('operator') or '').strip()
    if not feed_type or not operator:
        raise ValueError('feed_type and operator are required')
    offered_value = data.get('quantity_offered', data.get('feed_quantity_kg', data.get('feed_quantity')))
    offered_unit = _event_unit(
        data.get('offered_unit', data.get('feed_unit')),
        'offered_unit',
        default='kg',
        allowed={'kg', 'g'},
    )
    offered = _event_decimal(offered_value, 'quantity_offered', minimum='0.001', required=True)
    consumed_key = 'quantity_consumed' if data.get('quantity_consumed') not in (None, '') else 'consumption_g'
    consumed = _event_decimal(data.get(consumed_key), 'quantity_consumed', minimum=0)
    consumed_unit = _event_unit(
        data.get('consumed_unit'),
        'consumed_unit',
        default='g' if consumed is not None and consumed_key == 'consumption_g' else offered_unit,
        allowed={'kg', 'g'},
    ) if consumed is not None else None
    biomass_key = 'larvae_biomass' if data.get('larvae_biomass') not in (None, '') else 'larvae_weight_g'
    biomass = _event_decimal(data.get(biomass_key), 'larvae_biomass', minimum=0)
    biomass_unit = _event_unit(
        data.get('biomass_unit'),
        'biomass_unit',
        default='g' if biomass is not None and biomass_key == 'larvae_weight_g' else offered_unit,
        allowed={'kg', 'g'},
    ) if biomass is not None else None
    larvae_age = data.get('larvae_age_days')
    if larvae_age in (None, ''):
        larvae_age = None  # optional; browser forms send '' for blank fields
    else:
        try:
            larvae_age = int(larvae_age)
        except (TypeError, ValueError):
            raise ValueError('larvae_age_days must be a valid integer')
        if larvae_age < 0:
            raise ValueError('larvae_age_days must be zero or greater')
    tray_reference = str(data.get('tray_reference') or data.get('tray_batch_id') or '').strip() or None
    if tray_reference and len(tray_reference) > 100:
        raise ValueError('tray_reference must be at most 100 characters')
    # Tray weight before and after feeding, in kg (start_weight_g is accepted in grams).
    start_weight = _event_decimal(data.get('start_weight_kg'), 'start_weight_kg', minimum=0)
    if start_weight is None:
        start_grams = _event_decimal(data.get('start_weight_g'), 'start_weight_g', minimum=0)
        start_weight = start_grams / Decimal('1000') if start_grams is not None else None
    end_weight = _event_decimal(data.get('end_weight_kg'), 'end_weight_kg', minimum=0)
    with db.transaction() as cursor:
        batch, event = _insert_production_event(
            cursor, batch_ref, 'feeding', data, occurred_at,
            quantity=offered, unit=offered_unit, notes=data.get('notes'),
        )
        cursor.execute(
            """
            INSERT INTO feeding_events (
                production_event_id, feed_type, quantity_offered, offered_unit,
                quantity_consumed, consumed_unit, larvae_biomass, biomass_unit,
                larvae_age_days, tray_reference, start_weight_kg, end_weight_kg
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                event['id'], feed_type, offered, offered_unit, consumed, consumed_unit,
                biomass, biomass_unit, larvae_age, tray_reference, start_weight, end_weight,
            ),
        )
    return _event_response(event)


def _create_monitoring_event(data):
    batch_ref = _event_batch_ref(data)
    occurred_at = _event_occurred_at(data, ('monitoring_date',))
    asset_reference = str(data.get('asset_reference') or data.get('tray_facility_id') or '').strip()
    if not asset_reference:
        raise ValueError('asset_reference or tray_facility_id is required')
    temperature = _event_decimal(data.get('temperature'), 'temperature', minimum='-50', maximum='100', required=True)
    humidity = _event_decimal(data.get('humidity'), 'humidity', minimum=0, maximum=100, required=True)
    temperature_unit = _event_unit(data.get('temperature_unit'), 'temperature_unit', 'celsius', {'celsius'})
    humidity_unit = _event_unit(data.get('humidity_unit'), 'humidity_unit', 'percent', {'percent'})
    ammonia = _event_decimal(data.get('ammonia'), 'ammonia', minimum=0)
    ammonia_unit = _event_unit(data.get('ammonia_unit'), 'ammonia_unit', 'ppm', {'ppm'}) if ammonia is not None else None
    ammonia_odor = str(data.get('ammonia_odor') or '').strip().lower() or None
    if ammonia_odor not in (None, 'yes', 'no'):
        raise ValueError('ammonia_odor must be yes or no')
    with db.transaction() as cursor:
        batch, event = _insert_production_event(
            cursor, batch_ref, 'monitoring', data, occurred_at, notes=data.get('notes')
        )
        cursor.execute(
            """
            INSERT INTO monitoring_events (
                production_event_id, monitoring_type, asset_reference,
                temperature, temperature_unit, humidity, humidity_unit,
                ammonia, ammonia_unit, ammonia_odor
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                event['id'], data.get('monitoring_type', 'larval_environment'),
                asset_reference, temperature, temperature_unit, humidity, humidity_unit,
                ammonia, ammonia_unit, ammonia_odor,
            ),
        )
    return _event_response(event)


def _create_health_event(data):
    batch_ref = _event_batch_ref(data)
    occurred_at = _event_occurred_at(data, ('health_date',))
    issue = str(data.get('observed_issue') or '').strip()
    action = str(data.get('action_taken') or '').strip()
    severity = str(data.get('severity') or '').strip().lower()
    if not issue or not action:
        raise ValueError('observed_issue and action_taken are required')
    if severity not in {'low', 'medium', 'high', 'critical'}:
        raise ValueError('severity must be low, medium, high, or critical')
    tray_reference = str(data.get('tray_reference') or data.get('tray_batch_id') or '').strip() or None
    if tray_reference and len(tray_reference) > 100:
        raise ValueError('tray_reference must be at most 100 characters')
    resolved = str(data.get('resolved') or '').strip().lower()
    health_status = str(data.get('status') or '').strip().lower()
    if health_status not in {'open', 'follow_up', 'resolved', 'closed'}:
        health_status = 'resolved' if resolved == 'yes' else 'follow_up' if data.get('follow_up_date') else 'open'
    if health_status in {'resolved', 'closed'} and not data.get('resolved_at'):
        resolved_at = occurred_at
    else:
        resolved_at = data.get('resolved_at')
    with db.transaction() as cursor:
        batch, event = _insert_production_event(
            cursor, batch_ref, 'health', data, occurred_at, notes=data.get('comments')
        )
        cursor.execute(
            """
            INSERT INTO health_events (
                production_event_id, status, observed_issue, severity,
                action_taken, follow_up_date, resolved_at, tray_reference
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                event['id'], health_status, issue, severity, action,
                data.get('follow_up_date') or None, resolved_at, tray_reference,
            ),
        )
    return _event_response(event)


def _create_harvest_event(data):
    batch_ref = _event_batch_ref(data)
    occurred_at = _event_occurred_at(data, ('harvest_date',))
    wet_weight = _event_decimal(
        data.get('wet_weight', data.get('wet_weight_kg')),
        'wet_weight',
        minimum='0.001',
        required=True,
    )
    unit = _event_unit(data.get('unit'), 'unit', default='kg', allowed={'kg', 'g'})
    weight_kg = wet_weight if unit == 'kg' else wet_weight / Decimal('1000')
    harvest_stage = str(data.get('harvest_stage') or '').strip()
    operator = str(data.get('operator') or '').strip()
    location = str(data.get('location') or '').strip()
    if not harvest_stage:
        raise ValueError('harvest_stage is required')
    if len(harvest_stage) > 80:
        raise ValueError('harvest_stage must be at most 80 characters')
    if not operator:
        raise ValueError('operator is required')
    if len(operator) > 100:
        raise ValueError('operator must be at most 100 characters')
    if not location:
        raise ValueError('location is required')
    if len(location) > 200:
        raise ValueError('location must be at most 200 characters')
    # Frass sieved off at harvest becomes a frass lot (fertiliser) to cure.
    frass_kg = _event_decimal(data.get('frass_kg'), 'frass_kg', minimum='0.001')

    with db.transaction() as cursor:
        batch = _production_event_batch(cursor, batch_ref, data)
        if batch['status'] != 'READY_FOR_HARVEST':
            raise ValueError(
                'Harvests can only be recorded for a READY_FOR_HARVEST Production Batch'
            )
        if batch['harvest_limit_kg'] is None:
            raise ValueError(
                'Configure harvest_limit_kg for this Production Batch before harvesting'
            )
        harvest_limit = Decimal(str(batch['harvest_limit_kg']))
        cursor.execute(
            """
            SELECT COALESCE(SUM(pe.quantity), 0) AS harvested_kg
            FROM production_events AS pe
            JOIN harvests AS h ON h.production_event_id = pe.id
            WHERE pe.production_batch_id = %s
              AND pe.event_type = 'harvest'
              AND pe.status = 'recorded'
            """,
            (batch['id'],),
        )
        harvested_kg = Decimal(str(cursor.fetchone()['harvested_kg']))
        if harvested_kg + weight_kg > harvest_limit:
            available_kg = harvest_limit - harvested_kg
            raise ValueError(
                f"Harvest exceeds the batch limit; only {available_kg:.3f} kg remains"
            )

        batch, event = _insert_production_event(
            cursor,
            batch_ref,
            'harvest',
            data,
            occurred_at,
            quantity=weight_kg,
            unit='kg',
            notes=data.get('notes'),
        )
        cursor.execute(
            """
            INSERT INTO harvests (
                harvest_code, production_event_id, wet_weight, unit,
                harvest_stage, operator, location
            ) VALUES (
                'HRV-' || to_char(%s::timestamptz, 'YYYY') || '-' ||
                    lpad(nextval('phase_one_harvest_seq')::text, 5, '0'),
                %s, %s, %s, %s, %s, %s
            )
            RETURNING id, harvest_code, production_event_id, wet_weight, unit,
                      harvest_stage, operator, location, created_at
            """,
            (
                occurred_at,
                event['id'],
                wet_weight,
                unit,
                harvest_stage,
                operator,
                location,
            ),
        )
        harvest = cursor.fetchone()
        frass_lot = None
        if frass_kg is not None:
            cursor.execute(
                """
                INSERT INTO frass_lots (
                    business_id, harvest_id, production_batch_id, farm_id, site_id,
                    facility_id, quantity_kg, curing_started_at, recorded_by, recorded_by_user_id
                ) VALUES (
                    'FRS-' || to_char(%s::timestamptz, 'YYYY') || '-' ||
                        lpad(nextval('phase_one_frass_lot_seq')::text, 5, '0'),
                    %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                RETURNING id, business_id, quantity_kg, status
                """,
                (
                    occurred_at, harvest['id'], batch['id'], event['farm_id'], event['site_id'],
                    event['facility_id'], frass_kg, occurred_at, operator,
                    getattr(current_user, 'id', None) if getattr(current_user, 'is_authenticated', False) else None,
                ),
            )
            frass_lot = dict(cursor.fetchone())

    result = _event_response(event)
    result['frass_lot'] = frass_lot
    result['harvest'] = dict(harvest)
    result['harvest']['production_batch_id'] = batch['id']
    result['harvest']['occurred_at'] = event['occurred_at']
    result['harvest']['notes'] = event['notes']
    return result


def _production_input_rows(data):
    rows = data.get('inputs')
    if rows is None and data.get('substrate_batch_id') is not None:
        rows = [{
            'substrate_batch_id': data.get('substrate_batch_id'),
            'quantity_issued': data.get(
                'quantity_issued',
                data.get('quantity_used', data.get('substrate_quantity_kg')),
            ),
        }]
    if not isinstance(rows, list) or not rows:
        raise ValueError('At least one substrate input is required')

    normalized = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Each substrate input must be an object')
        substrate_batch_id = _parse_positive_integer(
            row.get('substrate_batch_id', row.get('id')),
            'substrate_batch_id',
        )
        if substrate_batch_id in seen:
            raise ValueError('Each Substrate Batch can be selected only once per Production Batch')
        seen.add(substrate_batch_id)
        quantity = _parse_chain_quantity(
            row.get(
                'quantity_issued',
                row.get('quantity_used', row.get('quantity')),
            ),
            'quantity_issued',
        )
        normalized.append({
            'substrate_batch_id': substrate_batch_id,
            'quantity_issued': quantity,
        })
    return sorted(normalized, key=lambda item: item['substrate_batch_id'])


def _production_batch_detail_query():
    return """
        SELECT
            pb.id,
            pb.business_id,
            pb.batch_code,
            pb.start_date,
            pb.started_at,
            pb.expected_harvest_at,
            pb.harvest_limit_kg,
            pb.current_stage,
            UPPER(pb.status) AS status,
            pb.notes,
            pb.recorded_by,
            pb.created_at,
            pb.updated_at,
            pb.farm_id,
            pb.site_id,
            pb.facility_id,
            f.name AS farm_name,
            s.name AS site_name,
            fa.name AS facility_name,
            GREATEST(CURRENT_DATE - pb.start_date, 0) AS age_days,
            COALESCE(
                json_agg(
                    json_build_object(
                        'id', pbi.id,
                        'substrate_batch_id', sb.id,
                        'business_id', sb.business_id,
                        'batch_code', sb.batch_code,
                        'quantity_issued', pbi.quantity_issued,
                        'unit', pbi.unit,
                        'issued_at', pbi.issued_at,
                        'actor', pbi.actor
                    ) ORDER BY pbi.id
                ) FILTER (WHERE pbi.id IS NOT NULL),
                '[]'::json
            ) AS inputs
        FROM production_batches AS pb
        LEFT JOIN farms AS f ON f.id = pb.farm_id
        LEFT JOIN sites AS s ON s.id = pb.site_id
        LEFT JOIN facilities AS fa ON fa.id = pb.facility_id
        LEFT JOIN production_batch_inputs AS pbi
            ON pbi.production_batch_id = pb.id
        LEFT JOIN substrate_batches AS sb
            ON sb.id = pbi.substrate_batch_id
        WHERE pb.id = %s OR pb.business_id = %s OR pb.batch_code = %s
        GROUP BY pb.id, f.name, s.name, fa.name
    """


def _production_event_rows(batch_id):
    return db.fetch_all(
        """
        SELECT
            pe.id AS production_event_id,
            pe.event_code,
            pe.production_batch_id,
            pe.event_type,
            pe.occurred_at,
            pe.actor,
            pe.status AS event_status,
            pe.quantity,
            pe.unit,
            pe.notes,
            pe.farm_id,
            pe.site_id,
            pe.facility_id,
            fe.feed_type,
            fe.quantity_offered,
            fe.offered_unit,
            fe.quantity_consumed,
            fe.consumed_unit,
            fe.larvae_biomass,
            fe.biomass_unit,
            fe.larvae_age_days,
            COALESCE(fe.tray_reference, he.tray_reference) AS tray_reference,
            fe.start_weight_kg,
            fe.end_weight_kg,
            me.monitoring_type,
            me.asset_reference,
            me.temperature,
            me.temperature_unit,
            me.humidity,
            me.humidity_unit,
            me.ammonia,
            me.ammonia_unit,
            me.ammonia_odor,
            he.status AS health_status,
            he.observed_issue,
            he.severity,
            he.action_taken,
            he.follow_up_date,
            he.resolved_at,
            hs.id AS harvest_id,
            hs.harvest_code,
            hs.wet_weight,
            hs.unit AS harvest_unit,
            hs.harvest_stage,
            hs.operator AS harvest_operator,
            hs.location AS harvest_location
        FROM production_events AS pe
        LEFT JOIN feeding_events AS fe ON fe.production_event_id = pe.id
        LEFT JOIN monitoring_events AS me ON me.production_event_id = pe.id
        LEFT JOIN health_events AS he ON he.production_event_id = pe.id
        LEFT JOIN harvests AS hs ON hs.production_event_id = pe.id
        WHERE pe.production_batch_id = %s
        ORDER BY pe.occurred_at ASC, pe.id ASC
        """,
        (batch_id,),
    )


@app.route('/api/production/batches', methods=['POST'])
@login_required
@requires('production.write')
def create_production_batch():
    """Create a PLANNED production batch and issue measured substrate inputs."""
    data = normalize_keys(request.get_json() or {})
    try:
        if not data.get('start_date'):
            raise ValueError('start_date is required')
        inputs = _production_input_rows(data)
        farm_id, site_id, facility_id = _production_scope_values(data)
        harvest_limit_kg = _event_decimal(
            data.get('harvest_limit_kg'),
            'harvest_limit_kg',
            minimum='0.001',
        )
        requested_status = str(data.get('status', 'PLANNED')).upper()
        if requested_status != 'PLANNED':
            raise ValueError('A new Production Batch must start in PLANNED status')
        actor, actor_user_id = _production_actor(data)

        with db.transaction() as cursor:
            _assert_production_location(cursor, farm_id, site_id, facility_id)
            _assert_production_scope_access(cursor, farm_id, site_id, facility_id)
            validated_inputs = []
            for requested in inputs:
                cursor.execute(
                    """
                    SELECT
                        sb.id,
                        sb.business_id,
                        sb.batch_code,
                        sb.farm_id,
                        sb.site_id,
                        sb.facility_id,
                        sb.farm_site,
                        CASE
                            WHEN sb.output_weight_kg IS NOT NULL
                                THEN sb.output_weight_kg
                            ELSE COALESCE(sb.total_input_weight_kg, 0)
                        END AS substrate_quantity
                    FROM substrate_batches AS sb
                    WHERE sb.id = %s
                    FOR UPDATE
                    """,
                    (requested['substrate_batch_id'],),
                )
                substrate = cursor.fetchone()
                if not substrate:
                    raise ValueError(
                        f"Substrate Batch {requested['substrate_batch_id']} does not exist"
                    )
                if (
                    substrate['farm_id'] != farm_id
                    or substrate['site_id'] != site_id
                    or substrate['facility_id'] != facility_id
                ):
                    raise ValueError(
                        f"Substrate Batch {substrate['business_id'] or substrate['id']} "
                        'does not belong to the selected farm/site/facility'
                    )

                cursor.execute(
                    """
                    SELECT COALESCE(SUM(quantity_issued), 0) AS quantity_issued
                    FROM production_batch_inputs
                    WHERE substrate_batch_id = %s
                    """,
                    (substrate['id'],),
                )
                already_issued = Decimal(
                    str(cursor.fetchone()['quantity_issued'])
                )
                available = Decimal(str(substrate['substrate_quantity'])) - already_issued
                if requested['quantity_issued'] > available:
                    raise ValueError(
                        f"Substrate Batch {substrate['business_id'] or substrate['id']} "
                        f"has only {available:.3f} kg available"
                    )
                validated_inputs.append({
                    **substrate,
                    'quantity_issued': requested['quantity_issued'],
                    'remaining_quantity': available - requested['quantity_issued'],
                })

            primary_substrate_id = validated_inputs[0]['id']
            cursor.execute(
                """
                WITH generated AS (
                    SELECT 'BSF-' || to_char(CURRENT_DATE, 'YYYY') || '-' ||
                           lpad(nextval('phase_one_production_batch_seq')::text, 5, '0')
                           AS business_id
                )
                INSERT INTO production_batches (
                    batch_code, business_id, substrate_batch_id, farm_id, site_id,
                    facility_id, start_date, started_at, expected_harvest_at,
                    harvest_limit_kg,
                    current_stage, status, notes, recorded_by
                )
                SELECT
                    COALESCE(NULLIF(%s, ''), generated.business_id),
                    generated.business_id, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, 'PLANNED', %s, %s
                FROM generated
                RETURNING id, business_id, batch_code, harvest_limit_kg
                """,
                (
                    data.get('batch_code', ''),
                    primary_substrate_id,
                    farm_id,
                    site_id,
                    facility_id,
                    data['start_date'],
                    data.get('started_at'),
                    data.get('expected_harvest_at'),
                    harvest_limit_kg,
                    data.get('current_stage', 'STARTING'),
                    data.get('notes'),
                    actor,
                ),
            )
            batch = cursor.fetchone()
            for item in validated_inputs:
                cursor.execute(
                    """
                    INSERT INTO production_batch_inputs (
                        production_batch_id, substrate_batch_id, quantity_issued,
                        unit, actor_user_id, actor
                    ) VALUES (%s, %s, %s, 'kg', %s, %s)
                    """,
                    (
                        batch['id'],
                        item['id'],
                        item['quantity_issued'],
                        actor_user_id,
                        actor,
                    ),
                )
            cursor.execute(
                """
                INSERT INTO production_batch_status_history (
                    production_batch_id, previous_status, new_status,
                    actor_user_id, actor, reason
                ) VALUES (%s, NULL, 'PLANNED', %s, %s, %s)
                """,
                (batch['id'], actor_user_id, actor, data.get('reason')),
            )
            if data.get('unit_ids'):
                if not isinstance(data['unit_ids'], list):
                    raise ValueError('unit_ids must be a list')
                _assign_units(
                    cursor,
                    {'id': batch['id'], 'status': 'PLANNED', 'facility_id': facility_id},
                    data['unit_ids'], actor, actor_user_id,
                )

            record = dict(batch)
            record.update({
                'farm_id': farm_id,
                'site_id': site_id,
                'facility_id': facility_id,
                'start_date': data['start_date'],
                'current_stage': data.get('current_stage', 'STARTING'),
                'status': 'PLANNED',
                'harvest_limit_kg': harvest_limit_kg,
                'inputs': [
                    {
                        'substrate_batch_id': item['id'],
                        'business_id': item['business_id'],
                        'batch_code': item['batch_code'],
                        'quantity_issued': item['quantity_issued'],
                        'unit': 'kg',
                        'remaining_quantity': item['remaining_quantity'],
                    }
                    for item in validated_inputs
                ],
            })
        return jsonify({
            'success': True,
            'message': 'Production Batch created with substrate inputs',
            'record': record,
            'id': record['id'],
            'business_id': record['business_id'],
        }), 201
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        logger.error(f"Error creating production batch: {e}")
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/api/production/batches', methods=['GET'])
@login_required
def list_production_batches():
    try:
        visibility, visibility_params = _scope_visibility_clause('pb')
        filters, filter_params = _optional_scope_filters('pb')
        status = str(request.args.get('status') or '').strip().upper()
        if status:
            if status not in PRODUCTION_BATCH_STATUSES:
                raise ValueError('Unknown Production Batch status')
            filters.append('UPPER(pb.status) = %s')
            filter_params.append(status)
        rows = db.fetch_all(
            f"""
            SELECT pb.id, pb.business_id, pb.batch_code, UPPER(pb.status) AS status,
                   pb.current_stage, pb.start_date, pb.expected_harvest_at,
                   GREATEST(CURRENT_DATE - pb.start_date, 0) AS age_days,
                   pb.farm_id, pb.site_id, pb.facility_id,
                   f.name AS farm_name, s.name AS site_name,
                   fa.name AS facility_name,
                   COALESCE((
                       SELECT SUM(pe.quantity)
                       FROM production_events AS pe
                       WHERE pe.production_batch_id = pb.id
                         AND pe.event_type = 'harvest'
                         AND pe.status = 'recorded'
                   ), 0) AS total_harvested_kg
            FROM production_batches AS pb
            LEFT JOIN farms AS f ON f.id = pb.farm_id
            LEFT JOIN sites AS s ON s.id = pb.site_id
            LEFT JOIN facilities AS fa ON fa.id = pb.facility_id
            WHERE {' AND '.join([visibility, *filters])}
            ORDER BY pb.start_date DESC, pb.id DESC
            LIMIT 500
            """,
            (*visibility_params, *filter_params),
        )
        return jsonify({'success': True, 'data': rows}), 200
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception:
        logger.exception('Error listing Production Batches')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/api/production/batches/<string:batch_ref>', methods=['GET'])
@login_required
def get_production_batch(batch_ref):
    try:
        lookup_id = int(batch_ref) if batch_ref.isdigit() else -1
        record = db.fetch_one(
            _production_batch_detail_query(),
            (lookup_id, batch_ref, batch_ref),
        )
        if not record:
            return jsonify({'success': False, 'message': 'Production Batch not found'}), 404
        scope = db.fetch_one(
            """
            SELECT farm_id, site_id, facility_id
            FROM production_batches
            WHERE id = %s
            """,
            (record['id'],),
        )
        with db.transaction() as cursor:
            _assert_production_scope_access(
                cursor, scope['farm_id'], scope['site_id'], scope['facility_id']
            )
            record['units'] = _batch_units(cursor, record['id'])
        event_rows = _production_event_rows(record['id'])
        record['events'] = event_rows
        record['harvests'] = [
            row for row in event_rows if row['event_type'] == 'harvest'
        ]
        record['total_harvested_kg'] = sum(
            (Decimal(str(row['quantity'] or 0)) for row in record['harvests']),
            Decimal('0'),
        )
        if record['harvest_limit_kg'] is not None:
            record['remaining_harvest_kg'] = max(
                Decimal(str(record['harvest_limit_kg'])) - record['total_harvested_kg'],
                Decimal('0'),
            )
        record['feeding_events'] = [
            row for row in event_rows if row['event_type'] == 'feeding'
        ]
        record['monitoring_events'] = [
            row for row in event_rows if row['event_type'] == 'monitoring'
        ]
        record['health_events'] = [
            row for row in event_rows if row['event_type'] == 'health'
        ]
        record['timeline'] = event_rows
        record['batch_number'] = record['business_id'] or record['batch_code']
        record['substrate_source'] = record['inputs']
        # Where the batch can go next, in lifecycle order (the status control).
        allowed = PRODUCTION_BATCH_TRANSITIONS.get(str(record['status'] or '').upper(), set())
        record['next_statuses'] = [status for status in PRODUCTION_BATCH_STATUS_ORDER if status in allowed]
        return jsonify({'success': True, 'data': record}), 200
    except ProductionEventPermissionError as e:
        return jsonify({'success': False, 'message': str(e)}), 403
    except Exception as e:
        logger.error(f"Error fetching production batch {batch_ref}: {e}")
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route(
    '/api/production/batches/<string:batch_ref>/harvest-limit',
    methods=['PUT', 'PATCH'],
)
@login_required
@requires('production.write')
def set_production_batch_harvest_limit(batch_ref):
    data = normalize_keys(request.get_json() or {})
    try:
        harvest_limit_kg = _event_decimal(
            data.get('harvest_limit_kg'),
            'harvest_limit_kg',
            minimum='0.001',
            required=True,
        )
        lookup_id = int(batch_ref) if batch_ref.isdigit() else -1
        with db.transaction() as cursor:
            cursor.execute(
                """
                SELECT id, UPPER(status) AS status, farm_id, site_id, facility_id
                FROM production_batches
                WHERE id = %s OR business_id = %s OR batch_code = %s
                FOR UPDATE
                """,
                (lookup_id, batch_ref, batch_ref),
            )
            batch = cursor.fetchone()
            if not batch:
                return jsonify({
                    'success': False,
                    'message': 'Production Batch not found',
                }), 404
            _assert_production_scope_access(
                cursor, batch['farm_id'], batch['site_id'], batch['facility_id']
            )
            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM production_events AS pe
                    JOIN harvests AS h ON h.production_event_id = pe.id
                    WHERE pe.production_batch_id = %s
                      AND pe.event_type = 'harvest'
                ) AS has_harvest
                """,
                (batch['id'],),
            )
            if cursor.fetchone()['has_harvest']:
                raise ValueError(
                    'The harvest limit cannot be changed after the first harvest'
                )
            if batch['status'] in {'HARVESTED', 'COMPLETED', 'CANCELLED'}:
                raise ValueError(
                    f"The harvest limit cannot be changed for a {batch['status']} Production Batch"
                )
            cursor.execute(
                """
                UPDATE production_batches
                SET harvest_limit_kg = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                RETURNING id, business_id, batch_code, harvest_limit_kg, updated_at
                """,
                (harvest_limit_kg, batch['id']),
            )
            record = cursor.fetchone()
        return jsonify({
            'success': True,
            'message': 'Production Batch harvest limit saved',
            'record': record,
        }), 200
    except ProductionEventPermissionError as e:
        return jsonify({'success': False, 'message': str(e)}), 403
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        logger.error(f"Error setting harvest limit for Production Batch {batch_ref}: {e}")
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/api/production/batches/<string:batch_ref>/status', methods=['POST', 'PATCH'])
@login_required
@requires('production.write')
def change_production_batch_status(batch_ref):
    data = normalize_keys(request.get_json() or {})
    target_status = str(data.get('status', '')).strip().upper()
    if target_status not in PRODUCTION_BATCH_STATUSES:
        return jsonify({
            'success': False,
            'message': f'Invalid Production Batch status: {target_status or "missing"}',
        }), 400
    reason = str(data.get('reason', '')).strip() or None
    if target_status in PRODUCTION_BATCH_REASON_STATUSES and not reason:
        return jsonify({
            'success': False,
            'message': f'A reason is required when changing status to {target_status}',
        }), 400
    actor, actor_user_id = _production_actor(data)

    try:
        with db.transaction() as cursor:
            lookup_id = int(batch_ref) if batch_ref.isdigit() else -1
            cursor.execute(
                """
                SELECT id, UPPER(status) AS status, farm_id, site_id, facility_id
                FROM production_batches
                WHERE id = %s OR business_id = %s OR batch_code = %s
                FOR UPDATE
                """,
                (lookup_id, batch_ref, batch_ref),
            )
            batch = cursor.fetchone()
            if not batch:
                return jsonify({
                    'success': False,
                    'message': 'Production Batch not found',
                }), 404
            _assert_production_scope_access(
                cursor, batch['farm_id'], batch['site_id'], batch['facility_id']
            )
            previous_status = batch['status']
            if target_status not in PRODUCTION_BATCH_TRANSITIONS.get(previous_status, set()):
                return jsonify({
                    'success': False,
                    'message': (
                        f'Invalid status transition from {previous_status} '
                        f'to {target_status}'
                    ),
                }), 400
            if target_status == 'HARVESTED':
                cursor.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM production_events AS pe
                        JOIN harvests AS h ON h.production_event_id = pe.id
                        WHERE pe.production_batch_id = %s
                          AND pe.event_type = 'harvest'
                          AND pe.status = 'recorded'
                    ) AS has_valid_harvest
                    """,
                    (batch['id'],),
                )
                if not cursor.fetchone()['has_valid_harvest']:
                    raise ValueError(
                        'A valid harvest must be recorded before marking the batch HARVESTED'
                    )
            cursor.execute(
                """
                UPDATE production_batches
                SET status = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                RETURNING id, business_id, batch_code, status, current_stage, updated_at
                """,
                (target_status, batch["id"]),
            )
            updated = cursor.fetchone()
            cursor.execute(
                """
                INSERT INTO production_batch_status_history (
                    production_batch_id, previous_status, new_status,
                    actor_user_id, actor, reason
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    batch['id'],
                    previous_status,
                    target_status,
                    actor_user_id,
                    actor,
                    reason,
                ),
            )
            if target_status in PRODUCTION_UNIT_RELEASE_STATUSES:
                # Harvested, finished or cancelled batches free their units.
                cursor.execute(
                    """
                    UPDATE production_batch_units
                    SET released_at = now(), release_reason = %s
                    WHERE production_batch_id = %s AND released_at IS NULL
                    """,
                    (f'Batch {target_status}', batch['id']),
                )
        return jsonify({
            'success': True,
            'message': 'Production Batch status updated',
            'record': {
                **updated,
                'previous_status': previous_status,
                'reason': reason,
            },
        }), 200
    except ProductionEventPermissionError as e:
        return jsonify({'success': False, 'message': str(e)}), 403
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        logger.error(f"Error changing production batch status {batch_ref}: {e}")
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


def _event_request_data(batch_ref=None):
    data = normalize_keys(request.get_json() or {})
    if batch_ref is not None:
        data['production_batch_id'] = batch_ref
    return data


@app.route('/api/production/batches/<string:batch_ref>/events/feeding', methods=['POST'])
@login_required
@requires('production.write')
def create_production_feeding_event(batch_ref):
    try:
        result = _create_feeding_event(_event_request_data(batch_ref))
        return jsonify({
            'success': True,
            'message': 'Feeding event recorded',
            **result,
        }), 201
    except ProductionEventPermissionError as e:
        return jsonify({'success': False, 'message': str(e)}), 403
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        logger.error(f"Error saving Production Batch feeding event: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/api/production/batches/<string:batch_ref>/events/monitoring', methods=['POST'])
@login_required
@requires('production.write')
def create_production_monitoring_event(batch_ref):
    try:
        result = _create_monitoring_event(_event_request_data(batch_ref))
        return jsonify({
            'success': True,
            'message': 'Monitoring event recorded',
            **result,
        }), 201
    except ProductionEventPermissionError as e:
        return jsonify({'success': False, 'message': str(e)}), 403
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        logger.error(f"Error saving Production Batch monitoring event: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/api/production/batches/<string:batch_ref>/events/health', methods=['POST'])
@login_required
@requires('production.write')
def create_production_health_event(batch_ref):
    try:
        result = _create_health_event(_event_request_data(batch_ref))
        return jsonify({
            'success': True,
            'message': 'Health event recorded',
            **result,
        }), 201
    except ProductionEventPermissionError as e:
        return jsonify({'success': False, 'message': str(e)}), 403
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        logger.error(f"Error saving Production Batch health event: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/api/production/batches/<string:batch_ref>/events/harvest', methods=['POST'])
@login_required
@requires('production.write')
def create_production_harvest_event(batch_ref):
    try:
        result = _create_harvest_event(_event_request_data(batch_ref))
        frass = result.get('frass_lot')
        message = 'Harvest recorded' + (
            f"; frass lot {frass['business_id']} ({frass['quantity_kg']} kg) started curing" if frass else '')
        return jsonify({
            'success': True,
            'message': message,
            **result,
        }), 201
    except ProductionEventPermissionError as e:
        return jsonify({'success': False, 'message': str(e)}), 403
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        logger.error(f"Error saving Production Batch harvest: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500
