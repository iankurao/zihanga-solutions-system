"""Production units (bio-pods, trays) and their batch allocations."""

from flask import request
from flask_login import login_required

from backend.core.web import app, db
from backend.core.http import (
    InventoryConflictError,
    RecordNotFoundError,
    _alert_response,
    _jsonable,
    _optional_text,
    _parse_chain_quantity,
    _parse_positive_integer,
    _production_actor,
    normalize_keys,
)
from backend.core.security import requires, super_admin_required
from backend.core.scope import (
    _assert_production_location,
    _assert_production_scope_access,
    _optional_scope_filters,
    _production_scope_values,
    _scope_visibility_clause,
)


# ---- Production units (bio-pods, trays) ---------------------------------------

PRODUCTION_UNIT_TYPES = ('bio_pod', 'tray', 'bed', 'rack', 'other')
PRODUCTION_UNIT_STATUSES = ('active', 'maintenance', 'retired')
PRODUCTION_UNIT_RELEASE_STATUSES = {'HARVESTED', 'COMPLETED', 'CANCELLED'}


def _units_query(where, params):
    return db.fetch_all(
        f"""
        SELECT u.id, u.unit_code, u.name, u.unit_type, u.capacity_kg, u.status,
               u.farm_id, u.site_id, u.facility_id, fa.name AS facility_name,
               pb.id AS batch_id, pb.business_id AS batch_business_id,
               UPPER(pb.status) AS batch_status, bu.allocated_at
        FROM production_units AS u
        JOIN facilities AS fa ON fa.id = u.facility_id
        LEFT JOIN production_batch_units AS bu
          ON bu.production_unit_id = u.id AND bu.released_at IS NULL
        LEFT JOIN production_batches AS pb ON pb.id = bu.production_batch_id
        WHERE {where}
        ORDER BY fa.name, u.unit_code
        """,
        params,
    )


def _assign_units(cursor, batch, unit_ids, actor, actor_user_id):
    """Put a batch into free, active units of its own facility."""
    ids = []
    for value in unit_ids:
        unit_id = _parse_positive_integer(value, 'unit_id')
        if unit_id in ids:
            raise ValueError('Each unit can be listed only once')
        ids.append(unit_id)
    if not ids:
        raise ValueError('Select at least one unit')
    if str(batch['status']).upper() in PRODUCTION_UNIT_RELEASE_STATUSES:
        raise ValueError('Units cannot be assigned to a harvested, completed or cancelled batch')
    cursor.execute(
        """
        SELECT u.id, u.unit_code, u.status, u.facility_id,
               EXISTS (SELECT 1 FROM production_batch_units AS bu
                       WHERE bu.production_unit_id = u.id AND bu.released_at IS NULL) AS occupied
        FROM production_units AS u WHERE u.id = ANY(%s)
        ORDER BY u.id
        FOR UPDATE OF u
        """,
        (ids,),
    )
    units = cursor.fetchall()
    if len(units) != len(ids):
        raise RecordNotFoundError('One or more units do not exist')
    for unit in units:
        if unit['facility_id'] != batch['facility_id']:
            raise ValueError(f"Unit {unit['unit_code']} is in a different facility from the batch")
        if unit['status'] != 'active':
            raise ValueError(f"Unit {unit['unit_code']} is {unit['status']} and cannot take a batch")
        if unit['occupied']:
            raise InventoryConflictError(f"Unit {unit['unit_code']} already holds a batch")
    for unit in units:
        cursor.execute(
            """
            INSERT INTO production_batch_units
                (production_batch_id, production_unit_id, allocated_by, allocated_by_user_id)
            VALUES (%s, %s, %s, %s)
            """,
            (batch['id'], unit['id'], actor, actor_user_id),
        )


def _batch_for_units(cursor, batch_ref):
    lookup_id = int(batch_ref) if str(batch_ref).isdigit() else -1
    cursor.execute(
        """
        SELECT id, business_id, UPPER(status) AS status, farm_id, site_id, facility_id
        FROM production_batches
        WHERE id = %s OR business_id = %s OR batch_code = %s
        FOR UPDATE
        """,
        (lookup_id, str(batch_ref), str(batch_ref)),
    )
    batch = cursor.fetchone()
    if not batch:
        raise RecordNotFoundError('Production Batch not found')
    _assert_production_scope_access(cursor, batch['farm_id'], batch['site_id'], batch['facility_id'])
    return batch


def _batch_units(cursor, batch_id):
    cursor.execute(
        """
        SELECT u.id, u.unit_code, u.name, u.unit_type, bu.allocated_at, bu.released_at,
               bu.allocated_by, bu.release_reason
        FROM production_batch_units AS bu
        JOIN production_units AS u ON u.id = bu.production_unit_id
        WHERE bu.production_batch_id = %s
        ORDER BY bu.released_at IS NOT NULL, u.unit_code
        """,
        (batch_id,),
    )
    return [dict(row) for row in cursor.fetchall()]


@app.route('/api/production/units', methods=['GET'])
@login_required
def list_production_units():
    def handler():
        visibility, params = _scope_visibility_clause('u')
        filters, filter_params = _optional_scope_filters('u')
        if request.args.get('include_inactive') not in ('1', 'true'):
            filters.append("u.status = 'active'")
        if request.args.get('free') in ('1', 'true'):
            filters.append('bu.id IS NULL')
        rows = _units_query(' AND '.join([visibility, *filters]), (*params, *filter_params))
        return {'data': _jsonable(rows)}
    return _alert_response(handler)


@app.route('/api/production/units', methods=['POST'])
@login_required
@super_admin_required
def create_production_unit():
    def handler(data):
        farm_id, site_id, facility_id = _production_scope_values(data, 'a production unit')
        code = _optional_text(data, 'unit_code', 30)
        name = _optional_text(data, 'name', 100)
        unit_type = str(data.get('unit_type') or 'bio_pod').strip().lower()
        if not code or not name:
            raise ValueError('unit_code and name are required')
        if unit_type not in PRODUCTION_UNIT_TYPES:
            raise ValueError('unit_type must be one of: ' + ', '.join(PRODUCTION_UNIT_TYPES))
        capacity = None
        if data.get('capacity_kg') not in (None, ''):
            capacity = _parse_chain_quantity(data['capacity_kg'], 'capacity_kg')
        actor, actor_user_id = _production_actor(data)
        try:
            with db.transaction() as cursor:
                _assert_production_location(cursor, farm_id, site_id, facility_id)
                cursor.execute(
                    """
                    INSERT INTO production_units (unit_code, name, unit_type, capacity_kg, farm_id,
                        site_id, facility_id, created_by, created_by_user_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, unit_code, name, unit_type, capacity_kg, status, facility_id
                    """,
                    (code, name, unit_type, capacity, farm_id, site_id, facility_id, actor, actor_user_id),
                )
                return {'data': _jsonable(dict(cursor.fetchone()))}
        except Exception as exc:
            if getattr(exc, 'pgcode', None) == '23505':
                raise InventoryConflictError('This unit code already exists in the facility')
            raise
    return _alert_response(handler, normalize_keys(request.get_json() or {}), status=201)


@app.route('/api/production/units/<int:unit_id>/status', methods=['POST'])
@login_required
@super_admin_required
def set_production_unit_status(unit_id):
    def handler(data):
        status = str(data.get('status') or '').strip().lower()
        if status not in PRODUCTION_UNIT_STATUSES:
            raise ValueError('status must be one of: ' + ', '.join(PRODUCTION_UNIT_STATUSES))
        with db.transaction() as cursor:
            cursor.execute(
                """
                SELECT u.id, EXISTS (SELECT 1 FROM production_batch_units AS bu
                       WHERE bu.production_unit_id = u.id AND bu.released_at IS NULL) AS occupied
                FROM production_units AS u WHERE u.id = %s FOR UPDATE
                """,
                (unit_id,),
            )
            unit = cursor.fetchone()
            if not unit:
                raise RecordNotFoundError('Production unit not found')
            if status != 'active' and unit['occupied']:
                raise ValueError('Release the batch from this unit before taking it out of service')
            cursor.execute(
                "UPDATE production_units SET status = %s, updated_at = now() WHERE id = %s RETURNING id, status",
                (status, unit_id),
            )
            return {'data': dict(cursor.fetchone())}
    return _alert_response(handler, normalize_keys(request.get_json() or {}))


@app.route('/api/production/batches/<string:batch_ref>/units', methods=['POST'])
@login_required
@requires('production.write')
def assign_production_units(batch_ref):
    def handler(data):
        unit_ids = data.get('unit_ids')
        if not isinstance(unit_ids, list):
            raise ValueError('unit_ids must be a list')
        actor, actor_user_id = _production_actor(data)
        try:
            with db.transaction() as cursor:
                batch = _batch_for_units(cursor, batch_ref)
                _assign_units(cursor, batch, unit_ids, actor, actor_user_id)
                return {'data': _jsonable(_batch_units(cursor, batch['id']))}
        except Exception as exc:
            if getattr(exc, 'pgcode', None) == '23505':
                raise InventoryConflictError('A selected unit was just taken by another batch')
            raise
    return _alert_response(handler, normalize_keys(request.get_json() or {}), status=201)


@app.route('/api/production/batches/<string:batch_ref>/units/<int:unit_id>/release', methods=['POST'])
@login_required
@requires('production.write')
def release_production_unit(batch_ref, unit_id):
    def handler(data):
        reason = _optional_text(data, 'reason', 300) or 'Released by operator'
        with db.transaction() as cursor:
            batch = _batch_for_units(cursor, batch_ref)
            cursor.execute(
                """
                UPDATE production_batch_units SET released_at = now(), release_reason = %s
                WHERE production_batch_id = %s AND production_unit_id = %s AND released_at IS NULL
                RETURNING id
                """,
                (reason, batch['id'], unit_id),
            )
            if not cursor.fetchone():
                raise RecordNotFoundError('This unit is not holding the batch')
            return {'data': _jsonable(_batch_units(cursor, batch['id']))}
    return _alert_response(handler, normalize_keys(request.get_json() or {}))
