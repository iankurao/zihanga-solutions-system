"""The last few records each data-entry form saved, listed under the form so
the person entering data can see at once what went in (GET /api/data-entry/recent).

Rows are limited to the locations the signed-in user may see, like every
other list."""

from decimal import Decimal

from flask import jsonify, request
from flask_login import login_required

from backend.core.web import app, db, logger
from backend.core.scope import _scope_visibility_clause
from backend.domains.farm_operations import KINDS

LIMIT = 5
EVENT_KINDS = ('feeding', 'monitoring', 'health', 'harvest')


def _amount(value, unit='kg'):
    if value is None:
        return ''
    number = Decimal(str(value)).normalize()
    text = format(number, 'f')
    return f'{text} {unit}'.strip()


def _when(value):
    return value.isoformat() if hasattr(value, 'isoformat') else (str(value) if value else None)


def _waste_rows():
    visibility, params = _scope_visibility_clause('wl')
    rows = db.fetch_all(
        f"""
        SELECT wl.business_id, wl.created_at, wl.quantity, wl.unit, wl.waste_type,
               wl.source_name, wl.status, wl.recorded_by
        FROM waste_lots AS wl
        WHERE {visibility}
        ORDER BY wl.created_at DESC, wl.id DESC
        LIMIT {LIMIT}
        """,
        params,
    )
    return [{
        'ref': r['business_id'],
        'href': f"/traceability?ref={r['business_id']}&type=waste_lot",
        'when': _when(r['created_at']),
        'text': f"{_amount(r['quantity'], r['unit'] or 'kg')} {str(r['waste_type'] or '').replace('_', ' ')}"
                f" from {r['source_name']} · {str(r['status'] or '').title()}",
        'by': r['recorded_by'],
    } for r in rows]


def _substrate_rows():
    visibility, params = _scope_visibility_clause('sb')
    rows = db.fetch_all(
        f"""
        SELECT sb.business_id, sb.created_at, sb.total_input_weight_kg, sb.recorded_by,
               fa.name AS facility_name
        FROM substrate_batches AS sb
        LEFT JOIN facilities AS fa ON fa.id = sb.facility_id
        WHERE {visibility}
        ORDER BY sb.created_at DESC, sb.id DESC
        LIMIT {LIMIT}
        """,
        params,
    )
    return [{
        'ref': r['business_id'],
        'href': f"/traceability?ref={r['business_id']}&type=substrate_batch",
        'when': _when(r['created_at']),
        'text': f"{_amount(r['total_input_weight_kg'])} of waste used · {r['facility_name'] or ''}".rstrip(' ·'),
        'by': r['recorded_by'],
    } for r in rows]


def _event_rows(kind):
    visibility, params = _scope_visibility_clause('pe')
    rows = db.fetch_all(
        f"""
        SELECT pb.business_id AS batch, pe.occurred_at, pe.actor,
               fe.feed_type, fe.quantity_offered, fe.offered_unit,
               me.temperature, me.humidity,
               he.observed_issue, he.severity,
               hs.harvest_code, hs.wet_weight, hs.unit AS harvest_unit
        FROM production_events AS pe
        JOIN production_batches AS pb ON pb.id = pe.production_batch_id
        LEFT JOIN feeding_events AS fe ON fe.production_event_id = pe.id
        LEFT JOIN monitoring_events AS me ON me.production_event_id = pe.id
        LEFT JOIN health_events AS he ON he.production_event_id = pe.id
        LEFT JOIN harvests AS hs ON hs.production_event_id = pe.id
        WHERE pe.event_type = %s AND pe.status = 'recorded' AND {visibility}
        ORDER BY pe.created_at DESC, pe.id DESC
        LIMIT {LIMIT}
        """,
        (kind, *params),
    )
    out = []
    for r in rows:
        if kind == 'feeding':
            text = f"{_amount(r['quantity_offered'], r['offered_unit'])} {r['feed_type'] or ''}".strip()
        elif kind == 'monitoring':
            text = f"{_amount(r['temperature'], '°C')} · {_amount(r['humidity'], '%')} humidity"
        elif kind == 'health':
            text = f"{r['observed_issue']} · {str(r['severity'] or '').title()}"
        else:
            text = f"{r['harvest_code']} · {_amount(r['wet_weight'], r['harvest_unit'] or 'kg')} wet"
        out.append({
            'ref': r['batch'],
            'href': f"/production_batch.html?batch={r['batch']}",
            'when': _when(r['occurred_at']),
            'text': text,
            'by': r['actor'],
        })
    return out


def _farm_operation_rows(kind):
    spec = KINDS[kind]
    table, date_column = spec['table'], spec['date']
    # Two of the form's own required answers describe the record best.
    shown = [f.column for f in spec['fields'] if f.required and f.column != date_column][:2]
    labels = {f.column: f.label for f in spec['fields']}
    visibility, params = _scope_visibility_clause('t')
    columns = ', '.join(f't.{c}' for c in shown)
    rows = db.fetch_all(
        f"""
        SELECT t.id, t.{date_column} AS record_date, fa.name AS facility_name,
               u.full_name, u.username{', ' + columns if columns else ''}
        FROM {table} AS t
        LEFT JOIN facilities AS fa ON fa.id = t.facility_id
        LEFT JOIN users AS u ON u.user_id = t.recorded_by_user_id
        WHERE {visibility}
        ORDER BY t.id DESC
        LIMIT {LIMIT}
        """,
        params,
    )
    out = []
    for r in rows:
        details = [f"{labels[c]}: {str(r[c]).replace('_', ' ')}" for c in shown if r[c] not in (None, '')]
        out.append({
            'ref': spec['label'],
            'href': None,
            'when': _when(r['record_date']),
            'text': ' · '.join(filter(None, [r['facility_name'], *details])),
            'by': r['full_name'] or r['username'],
        })
    return out


@app.route('/api/data-entry/recent', methods=['GET'])
@login_required
def recent_data_entries():
    kind = str(request.args.get('kind') or '').strip()
    try:
        if kind == 'waste':
            rows = _waste_rows()
        elif kind == 'substrate':
            rows = _substrate_rows()
        elif kind in EVENT_KINDS:
            rows = _event_rows(kind)
        elif kind in KINDS:
            rows = _farm_operation_rows(kind)
        else:
            return jsonify({'success': False, 'message': 'Unknown form'}), 400
        return jsonify({'success': True, 'data': rows})
    except Exception:
        logger.exception('Could not list recent entries for %s', kind)
        return jsonify({'success': False, 'message': 'Could not load recent entries'}), 500
