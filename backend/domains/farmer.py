"""Mobile farmer portal."""

from datetime import date
from decimal import Decimal
from flask import render_template
from flask_login import login_required

from backend.core.web import app, db
from backend.core.http import _alert_response, _jsonable
from backend.core.scope import _scope_visibility_clause
from backend.domains.units import _units_query


# ---- Farmer portal ------------------------------------------------------------

FARMER_ACTIVE_STATUSES = ('PLANNED', 'ACTIVE', 'MONITORING', 'READY_FOR_HARVEST', 'PAUSED', 'HEALTH_ALERT')


def _farmer_overview(cursor):
    visibility, params = _scope_visibility_clause('pb')
    cursor.execute(
        f"""
        SELECT pb.id, pb.business_id, UPPER(pb.status) AS status, pb.current_stage,
               pb.start_date, pb.expected_harvest_at, pb.harvest_limit_kg,
               GREATEST(CURRENT_DATE - pb.start_date, 0) AS age_days,
               fa.name AS facility_name, pb.facility_id,
               (SELECT MAX(pe.occurred_at) FROM production_events AS pe
                 WHERE pe.production_batch_id = pb.id AND pe.event_type = 'feeding'
                   AND pe.status = 'recorded') AS last_fed_at,
               (SELECT json_build_object('at', pe.occurred_at, 'temperature', me.temperature,
                                         'humidity', me.humidity)
                  FROM production_events AS pe
                  JOIN monitoring_events AS me ON me.production_event_id = pe.id
                 WHERE pe.production_batch_id = pb.id AND pe.status = 'recorded'
                 ORDER BY pe.occurred_at DESC LIMIT 1) AS last_check,
               (SELECT COUNT(*) FROM health_events AS he
                  JOIN production_events AS pe ON pe.id = he.production_event_id
                 WHERE pe.production_batch_id = pb.id AND pe.status = 'recorded'
                   AND he.status IN ('open', 'follow_up')) AS open_health,
               (SELECT MIN(he.follow_up_date) FROM health_events AS he
                  JOIN production_events AS pe ON pe.id = he.production_event_id
                 WHERE pe.production_batch_id = pb.id AND pe.status = 'recorded'
                   AND he.status IN ('open', 'follow_up')) AS next_follow_up,
               COALESCE((SELECT SUM(pe.quantity) FROM production_events AS pe
                 WHERE pe.production_batch_id = pb.id AND pe.event_type = 'harvest'
                   AND pe.status = 'recorded'), 0) AS harvested_kg,
               COALESCE((SELECT json_agg(u.unit_code ORDER BY u.unit_code)
                  FROM production_batch_units AS bu
                  JOIN production_units AS u ON u.id = bu.production_unit_id
                 WHERE bu.production_batch_id = pb.id AND bu.released_at IS NULL), '[]'::json) AS units
        FROM production_batches AS pb
        JOIN facilities AS fa ON fa.id = pb.facility_id
        WHERE {visibility} AND UPPER(pb.status) = ANY(%s)
        ORDER BY pb.start_date, pb.id
        """,
        (*params, list(FARMER_ACTIVE_STATUSES)),
    )
    batches = [dict(row) for row in cursor.fetchall()]

    today = date.today()
    tasks = []
    for b in batches:
        ref = b['business_id']
        if b['status'] in ('ACTIVE', 'MONITORING', 'HEALTH_ALERT') and (
            b['last_fed_at'] is None or b['last_fed_at'].date() < today
        ):
            tasks.append({'kind': 'feed', 'priority': 2, 'batch': ref,
                          'text': f'Feed {ref} — not fed today'})
        if b['status'] == 'READY_FOR_HARVEST':
            tasks.append({'kind': 'harvest', 'priority': 1, 'batch': ref,
                          'text': f'{ref} is ready to harvest'})
        expected = b['expected_harvest_at']
        if expected and expected.date() < today and Decimal(str(b['harvested_kg'])) == 0:
            tasks.append({'kind': 'overdue', 'priority': 0, 'batch': ref,
                          'text': f'Harvest of {ref} was expected {expected:%d %b}'})
        if b['next_follow_up'] and b['next_follow_up'] <= today:
            tasks.append({'kind': 'health', 'priority': 0, 'batch': ref,
                          'text': f'Health follow-up due for {ref}'})
        if b['status'] == 'HEALTH_ALERT':
            tasks.append({'kind': 'health', 'priority': 0, 'batch': ref,
                          'text': f'{ref} is in health alert'})
    tasks.sort(key=lambda t: (t['priority'], t['batch']))

    unit_visibility, unit_params = _scope_visibility_clause('u')
    units = _units_query(f"{unit_visibility} AND u.status <> 'retired'", unit_params)
    return _jsonable({'batches': batches, 'tasks': tasks, 'units': units})


@app.route('/api/farmer/overview', methods=['GET'])
@login_required
def farmer_overview():
    def handler():
        with db.transaction() as cursor:
            return {'data': _farmer_overview(cursor)}
    return _alert_response(handler)


@app.route('/farmer')
@login_required
def farmer_page():
    return render_template('farmer.html')
