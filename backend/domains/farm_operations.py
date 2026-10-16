"""Farm operation logs: waste handling, hatchery and fly facility records.

These are the day-to-day logs that sit beside the production chain (waste
storage and processing, hatchery batches, cage checks, egg collection, ...).
Each record belongs to a farm, site and facility like every other record:

    GET  /api/farm-operations                 the kinds of log, with their fields
    POST /api/farm-operations/<kind>          record one (production.write + access
                                              to the chosen farm/site/facility)
    GET  /api/farm-operations/<kind>          records at locations the caller may see

Rows recorded before logs carried a location stay as history: only super
admins see them, and nothing can add new rows without a location (the
database refuses them too, see migrations/farm_operation_logs.sql).
"""
from dataclasses import dataclass
from datetime import date, time, timedelta
from decimal import Decimal, InvalidOperation

from flask import jsonify, request
from flask_login import current_user, login_required

from backend.core.http import ProductionEventPermissionError, _jsonable, normalize_keys
from backend.core.scope import (
    _assert_production_location,
    _assert_production_scope_access,
    _optional_scope_filters,
    _production_scope_values,
    _scope_visibility_clause,
)
from backend.core.security import requires
from backend.core.web import app, db, logger


@dataclass(frozen=True)
class Field:
    column: str
    kind: str                    # date | time | text | note | number | integer
    label: str
    required: bool = False
    aliases: tuple = ()          # other input names the existing forms send
    minimum: float = None
    maximum: float = None
    planned: bool = False        # a date that may lie in the future


def _f(column, kind, label, required=False, *aliases, minimum=None, maximum=None, planned=False):
    return Field(column, kind, label, required, aliases, minimum, maximum, planned)


KINDS = {
    # ---- Waste handling ----------------------------------------------------------
    'waste-storage': {
        'table': 'storage_records', 'group': 'Waste handling', 'label': 'Waste storage',
        'date': 'storage_date', 'saved': 'Storage record saved',
        'fields': [
            _f('storage_date', 'date', 'Storage date', True),
            _f('storage_method', 'text', 'Storage method', True),
            _f('storage_conditions', 'text', 'Storage conditions', True),
            _f('storage_duration', 'integer', 'Storage duration (days)', True, minimum=0, maximum=3650),
            _f('planned_utilization', 'text', 'Planned use', True),
            _f('storage_observations', 'note', 'Observations'),
        ],
    },
    'waste-processing': {
        'table': 'processing_records', 'group': 'Waste handling', 'label': 'Waste processing',
        'date': 'processing_date', 'saved': 'Processing record saved',
        'fields': [
            _f('processing_date', 'date', 'Processing date', True),
            _f('processing_type', 'text', 'Processing type', True),
            _f('processing_method', 'text', 'Processing method', True),
            _f('waste_processed', 'number', 'Waste processed (kg)', True, minimum=0),
            _f('waste_reduction', 'number', 'Waste reduction', minimum=0),
            _f('processing_remarks', 'note', 'Remarks'),
        ],
    },
    'waste-monitoring': {
        'table': 'waste_monitoring', 'group': 'Waste handling', 'label': 'Waste environment check',
        'date': 'monitoring_date', 'saved': 'Waste monitoring saved',
        'fields': [
            _f('monitoring_date', 'date', 'Date', True),
            _f('monitoring_time', 'time', 'Time', True),
            _f('temperature', 'number', 'Temperature (°C)', True, minimum=-20, maximum=90),
            _f('water_consistency', 'text', 'Water consistency', True),
            _f('odor_level', 'text', 'Odour level', True),
            _f('pest_presence', 'text', 'Pests present', True),
            _f('pest_details', 'note', 'Pest details'),
            _f('mitigation_actions', 'note', 'Actions taken'),
            _f('remarks', 'note', 'Remarks'),
        ],
    },
    # ---- Hatchery ---------------------------------------------------------------------
    'hatchery-batch': {
        'table': 'hatchery_batches', 'group': 'Hatchery', 'label': 'Hatchery batch',
        'date': 'batch_date', 'saved': 'Hatchery batch saved', 'ref': 'batch_number',
        'fields': [
            _f('batch_number', 'text', 'Batch number (assigned when blank)'),
            _f('batch_date', 'date', 'Batch date', True),
            _f('egg_incubation_date', 'date', 'Egg incubation date', True),
            _f('total_eggs_grams', 'number', 'Eggs (g)', True, minimum=0),
            _f('expected_hatch_date', 'date', 'Expected hatch date', True, planned=True),
            _f('actual_hatch_date', 'date', 'Actual hatch date'),
            _f('hatch_days', 'integer', 'Days to hatch', minimum=0, maximum=60),
            _f('supervisor_name', 'text', 'Supervisor', True),
            _f('notes', 'note', 'Notes'),
        ],
    },
    'hatchery-feeding': {
        'table': 'hatchery_feeding', 'group': 'Hatchery', 'label': 'Hatchery feeding',
        'date': 'feeding_date', 'saved': 'Hatchery feeding saved', 'ref': 'batch_id',
        'fields': [
            _f('batch_id', 'text', 'Hatchery batch number', True),
            _f('feeding_date', 'date', 'Feeding date', True),
            _f('feed_per_5g_eggs_grams', 'number', 'Feed per 5 g of eggs (g)', True, minimum=0),
            _f('total_feed_used_grams', 'number', 'Total feed used (g)', True, minimum=0),
            _f('days_to_utilize', 'integer', 'Days to use up', True, minimum=0, maximum=365),
            _f('feed_type', 'text', 'Feed type', True),
            _f('feed_source', 'text', 'Feed source'),
            _f('distribution_method', 'text', 'Distribution method', True),
            _f('notes', 'note', 'Notes'),
        ],
    },
    'hatchery-monitoring': {
        'table': 'hatchery_monitoring', 'group': 'Hatchery', 'label': 'Hatchery environment check',
        'date': 'monitoring_date', 'saved': 'Hatchery monitoring saved',
        'fields': [
            _f('monitoring_date', 'date', 'Date', True),
            _f('temperature_c', 'number', 'Temperature (°C)', True, minimum=-20, maximum=60),
            _f('humidity_percent', 'number', 'Humidity (%)', True, minimum=0, maximum=100),
            _f('adjustments_made', 'note', 'Adjustments made'),
        ],
    },
    'hatchery-cleaning': {
        'table': 'hatchery_cleaning', 'group': 'Hatchery', 'label': 'Hatchery cleaning',
        'date': 'cleaning_date', 'saved': 'Cleaning record saved',
        'fields': [
            _f('cleaning_date', 'date', 'Cleaning date', True),
            _f('areas_cleaned', 'note', 'Areas cleaned', True),
            _f('cleaning_materials', 'note', 'Materials used', True),
            _f('cleaning_personnel', 'text', 'Cleaned by', True),
            _f('remarks', 'note', 'Remarks'),
        ],
    },
    'hatchery-problem': {
        'table': 'hatchery_problems', 'group': 'Hatchery', 'label': 'Hatchery problem',
        'date': 'problem_date', 'saved': 'Problem record saved',
        'fields': [
            _f('problem_date', 'date', 'Date', True),
            _f('problem_identified', 'note', 'Problem', True),
            _f('proposed_solution', 'note', 'Proposed solution', True),
            _f('responsible_person', 'text', 'Responsible person', True),
            _f('days_to_implement', 'integer', 'Days to implement', minimum=0, maximum=365),
            _f('resolution_status', 'text', 'Status'),
            _f('additional_comments', 'note', 'Comments'),
        ],
    },
    # ---- Fly facility -----------------------------------------------------------------
    'cage-monitoring': {
        'table': 'cage_monitoring', 'group': 'Fly facility', 'label': 'Cage check',
        'date': 'monitoring_date', 'saved': 'Cage check saved', 'ref': 'cage_id',
        'fields': [
            _f('monitoring_date', 'date', 'Date', True, 'date'),
            _f('cage_id', 'text', 'Cage', True),
            _f('temperature', 'number', 'Temperature (°C)', True, minimum=-20, maximum=60),
            _f('humidity', 'number', 'Humidity (%)', True, minimum=0, maximum=100),
            _f('lighting_hours', 'text', 'Lighting hours', True),
            _f('ventilation_ok', 'text', 'Ventilation OK', True),
            _f('cage_cleaned', 'text', 'Cage cleaned', True),
            _f('dead_flies_removed', 'text', 'Dead flies removed'),
            _f('cage_damage', 'text', 'Cage damage', True),
            _f('cages_damaged_list', 'note', 'Damaged cages'),
            _f('damage_notes', 'note', 'Damage notes'),
            _f('additional_notes', 'note', 'Notes'),
        ],
    },
    'facility-maintenance': {
        'table': 'facility_maintenance', 'group': 'Fly facility', 'label': 'Facility maintenance',
        'date': 'maintenance_date', 'saved': 'Maintenance record saved',
        'fields': [
            _f('maintenance_date', 'date', 'Date', True, 'date'),
            _f('moat_check', 'text', 'Moat checked', True),
            _f('ants_present', 'text', 'Ants present', True),
            _f('rodents_present', 'text', 'Rodents present', True),
            _f('bird_net_ok', 'text', 'Bird net OK', True),
            _f('trench_refilled', 'text', 'Trench refilled', True),
            _f('maintenance_notes', 'note', 'Notes', True),
        ],
    },
    'pupae-transition': {
        'table': 'pupae_transition', 'group': 'Fly facility', 'label': 'Pupae transition',
        'date': 'transition_date', 'saved': 'Pupae transition saved', 'ref': 'love_cage_id',
        'fields': [
            _f('transition_date', 'date', 'Date', True, 'date'),
            _f('love_cage_id', 'text', 'Love cage', True),
            _f('pupae_weight_added', 'number', 'Pupae added (kg)', True, 'pupae_weight_added_kg', minimum=0),
            _f('old_pupae_removed', 'number', 'Old pupae removed (kg)', True, 'old_pupae_removed_kg', minimum=0),
            _f('dead_flies_removed', 'text', 'Dead flies removed', True),
            _f('water_points_checked', 'text', 'Water points checked', True),
            _f('new_egg_crates_installed', 'text', 'New egg crates installed', True),
            _f('number_of_crates', 'integer', 'Number of crates', minimum=0, maximum=10000),
            _f('notes', 'note', 'Notes'),
        ],
    },
    'egg-collection': {
        'table': 'egg_collection', 'group': 'Fly facility', 'label': 'Egg collection',
        'date': 'collection_date', 'saved': 'Egg collection saved', 'ref': 'cage_id',
        'fields': [
            _f('collection_date', 'date', 'Date', True, 'date'),
            _f('collection_time', 'text', 'Time', True, 'time'),
            _f('cage_id', 'text', 'Cage', True),
            _f('eggs_collected', 'number', 'Eggs collected (g)', True, minimum=0),
            _f('bait_replaced', 'text', 'Bait replaced', True),
            _f('eggs_intact', 'text', 'Eggs intact', True),
            _f('collector_name', 'text', 'Collected by', True),
            _f('collection_method', 'text', 'Method', True),
            _f('notes', 'note', 'Notes'),
        ],
    },
    'bait-preparation': {
        'table': 'bait_preparation', 'group': 'Fly facility', 'label': 'Bait preparation',
        'date': 'start_date', 'saved': 'Bait preparation saved', 'ref': 'barrel_id',
        'fields': [
            _f('barrel_id', 'text', 'Barrel', True),
            _f('bait_type', 'text', 'Bait type', True),
            _f('ingredients_added', 'note', 'Ingredients', True),
            _f('start_date', 'date', 'Start date', True),
            _f('ready_date', 'date', 'Ready date', True, planned=True),
            _f('used_in_cage_ids', 'note', 'Used in cages'),
            _f('notes', 'note', 'Notes'),
        ],
    },
}

TEXT_MAX = {'text': 100, 'note': 2000}
# The older hatchery tables have no recorded_by text column (recorded_by_user_id
# is on every log table).
_NO_RECORDED_BY = {'hatchery_batches', 'hatchery_feeding', 'hatchery_monitoring',
                   'hatchery_cleaning', 'hatchery_problems'}
# Record dates may be up to a day ahead (time zones); planned dates up to a year.
FUTURE_SLACK = {False: timedelta(days=1), True: timedelta(days=366)}


def _raw(field, data):
    for name in (field.column, *field.aliases):
        value = data.get(name)
        if value not in (None, ''):
            return value.strip() if isinstance(value, str) else value
    return None


def _clean(field, value):
    label = field.label
    if field.kind == 'date':
        try:
            parsed = date.fromisoformat(str(value)[:10])
        except ValueError:
            raise ValueError(f'{label} must be a date (YYYY-MM-DD)')
        if parsed > date.today() + FUTURE_SLACK[field.planned]:
            raise ValueError(f'{label} cannot be that far in the future')
        if parsed.year < 2000:
            raise ValueError(f'{label} is too far in the past')
        return parsed
    if field.kind == 'time':
        try:
            return time.fromisoformat(str(value))
        except ValueError:
            raise ValueError(f'{label} must be a time (HH:MM)')
    if field.kind in ('number', 'integer'):
        try:
            number = Decimal(str(value))
        except InvalidOperation:
            raise ValueError(f'{label} must be a number')
        if not number.is_finite():
            raise ValueError(f'{label} must be a number')
        if field.kind == 'integer':
            if number != number.to_integral_value():
                raise ValueError(f'{label} must be a whole number')
            number = int(number)
        if field.minimum is not None and number < field.minimum:
            raise ValueError(f'{label} must be at least {field.minimum:g}')
        if field.maximum is not None and number > field.maximum:
            raise ValueError(f'{label} must be at most {field.maximum:g}')
        return number
    text = str(value)
    if len(text) > TEXT_MAX[field.kind]:
        raise ValueError(f'{label} must be at most {TEXT_MAX[field.kind]} characters')
    return text


def _values(spec, data):
    values, missing = {}, []
    for field in spec['fields']:
        raw = _raw(field, data)
        if raw is None:
            if field.required:
                missing.append(field.label)
            continue
        values[field.column] = _clean(field, raw)
    if missing:
        raise ValueError('Missing: ' + ', '.join(missing))
    return values


def _check_rules(cursor, kind, values, farm_id):
    """Rules that span fields or other records."""
    if kind == 'bait-preparation' and values['ready_date'] < values['start_date']:
        raise ValueError('Ready date cannot be before the start date')
    if kind == 'hatchery-batch':
        if values.get('actual_hatch_date') and values['actual_hatch_date'] < values['egg_incubation_date']:
            raise ValueError('Actual hatch date cannot be before the incubation date')
        if values.get('batch_number'):
            cursor.execute(
                "SELECT 1 FROM hatchery_batches WHERE batch_number = %s AND (farm_id = %s OR farm_id IS NULL)",
                (values['batch_number'], farm_id),
            )
            if cursor.fetchone():
                raise ValueError(f"Hatchery batch {values['batch_number']} already exists on this farm")
    if kind == 'hatchery-feeding':
        # The batch must exist on this farm (or be a batch from before
        # locations, so feeding can continue on batches already running).
        cursor.execute(
            "SELECT 1 FROM hatchery_batches WHERE batch_number = %s AND (farm_id = %s OR farm_id IS NULL)",
            (values['batch_id'], farm_id),
        )
        if not cursor.fetchone():
            raise ValueError(f"No hatchery batch {values['batch_id']} on this farm")


def _spec_or_404(kind):
    spec = KINDS.get(kind)
    if spec is None:
        return None, (jsonify({'success': False, 'message': 'Unknown kind of record'}), 404)
    return spec, None


@app.route('/api/farm-operations', methods=['GET'])
@login_required
def farm_operation_kinds():
    return jsonify({'success': True, 'data': [
        {
            'key': key, 'label': spec['label'], 'group': spec['group'],
            'fields': [
                {'name': f.column, 'label': f.label, 'type': f.kind, 'required': f.required,
                 'min': f.minimum, 'max': f.maximum}
                for f in spec['fields']
            ],
        }
        for key, spec in KINDS.items()
    ]})


@app.route('/api/farm-operations/<string:kind>', methods=['POST'])
@login_required
@requires('production.write')
def record_farm_operation(kind):
    spec, missing = _spec_or_404(kind)
    if missing:
        return missing
    data = normalize_keys(request.get_json(silent=True) or {})
    try:
        farm_id, site_id, facility_id = _production_scope_values(data, f"a {spec['label'].lower()}")
        values = _values(spec, data)
        with db.transaction() as cursor:
            _assert_production_location(cursor, farm_id, site_id, facility_id)
            _assert_production_scope_access(cursor, farm_id, site_id, facility_id)
            _check_rules(cursor, kind, values, farm_id)
            values.update(farm_id=farm_id, site_id=site_id, facility_id=facility_id,
                          recorded_by_user_id=current_user.id)
            if spec['table'] not in _NO_RECORDED_BY:
                values['recorded_by'] = current_user.username
            columns = list(values)
            placeholders = ['%s'] * len(columns)
            if kind == 'hatchery-batch' and 'batch_number' not in values:
                columns.append('batch_number')
                placeholders.append(
                    "'HAT-' || to_char(CURRENT_DATE, 'YYYY') || '-' || "
                    "lpad(nextval('phase_one_hatchery_batch_seq')::text, 5, '0')")
            # Table and column names come from KINDS, never from the request.
            cursor.execute(
                f"INSERT INTO {spec['table']} ({', '.join(columns)}) "
                f"VALUES ({', '.join(placeholders)}) RETURNING *",
                list(values.values()),
            )
            row = cursor.fetchone()
    except ProductionEventPermissionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 403
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception:
        logger.exception('Error recording %s', kind)
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500
    return jsonify({'success': True, 'message': spec['saved'], 'data': _jsonable(dict(row))}), 201


@app.route('/api/farm-operations/<string:kind>', methods=['GET'])
@login_required
def list_farm_operations(kind):
    spec, missing = _spec_or_404(kind)
    if missing:
        return missing
    try:
        visibility, params = _scope_visibility_clause('t')
        filters, filter_params = _optional_scope_filters('t')
        clauses, values = [visibility, *filters], [*params, *filter_params]
        for arg, operator in (('date_from', '>='), ('date_to', '<=')):
            if request.args.get(arg):
                try:
                    values.append(date.fromisoformat(request.args[arg]))
                except ValueError:
                    raise ValueError(f'{arg} must be a date (YYYY-MM-DD)')
                clauses.append(f"t.{spec['date']} {operator} %s")
        try:
            limit = min(max(int(request.args.get('limit') or 100), 1), 500)
        except ValueError:
            raise ValueError('limit must be a whole number')
        rows = db.fetch_all(
            f"""
            SELECT t.*, f.name AS farm_name, s.name AS site_name, fa.name AS facility_name
            FROM {spec['table']} AS t
            LEFT JOIN farms AS f ON f.id = t.farm_id
            LEFT JOIN sites AS s ON s.id = t.site_id
            LEFT JOIN facilities AS fa ON fa.id = t.facility_id
            WHERE {' AND '.join(clauses)}
            ORDER BY t.{spec['date']} DESC, t.id DESC
            LIMIT {limit}
            """,
            tuple(values),
        )
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    return jsonify({'success': True, 'data': [_jsonable(dict(r)) for r in rows]})
