"""Audit log viewer (super admins)."""

from datetime import date
from flask import jsonify, render_template, request
from flask_login import login_required

from backend.core.web import app, db
from backend.core.http import _jsonable, _parse_positive_integer
from backend.core.security import requires, super_admin_required


AUDIT_PAGE_SIZE = 100


def _like_prefix(value):
    """``value`` as a LIKE prefix pattern with its wildcards taken literally."""
    return value.replace('\\', '\\\\').replace('%', r'\%').replace('_', r'\_') + '%'


@app.route('/api/audit', methods=['GET'])
@login_required
@requires('audit.read')
def audit_log_entries():
    """Newest audit entries first, filtered; page with ?before=<id>."""
    filters, params = [], []
    args = request.args
    if args.get('entity_type'):
        filters.append('entity_type = %s')
        params.append(args['entity_type'][:60])
    if args.get('record'):
        filters.append('(entity_ref ILIKE %s OR entity_id = %s)')
        params += [_like_prefix(args['record'][:100]), args['record'][:80]]
    if args.get('actor'):
        filters.append('actor_username ILIKE %s')
        params.append(_like_prefix(args['actor'][:100]))
    if args.get('action'):
        filters.append('action LIKE %s')
        params.append(_like_prefix(args['action'][:80]))
    try:
        if args.get('from'):
            filters.append('occurred_at >= %s::date')
            params.append(date.fromisoformat(args['from']))
        if args.get('to'):
            filters.append("occurred_at < %s::date + INTERVAL '1 day'")
            params.append(date.fromisoformat(args['to']))
        if args.get('before'):
            filters.append('id < %s')
            params.append(_parse_positive_integer(args['before'], 'before'))
    except ValueError:
        return jsonify({'success': False, 'message': 'Dates must be YYYY-MM-DD'}), 400
    where = ' AND '.join(filters) or 'TRUE'
    rows = db.fetch_all(
        f"""
        SELECT id, occurred_at, actor_user_id, actor_username, actor_role, action,
               entity_type, entity_id, entity_ref, farm_id, facility_id, old_value,
               new_value, reason, ip_address, user_agent, request_id, request_path
        FROM audit_log
        WHERE {where}
        ORDER BY id DESC
        LIMIT %s
        """,
        (*params, AUDIT_PAGE_SIZE + 1),
    )
    more = len(rows) > AUDIT_PAGE_SIZE
    rows = rows[:AUDIT_PAGE_SIZE]
    types = db.fetch_all('SELECT DISTINCT entity_type FROM audit_log ORDER BY entity_type')
    return jsonify({
        'success': True,
        'data': _jsonable(rows),
        'next_before': rows[-1]['id'] if more else None,
        'entity_types': [row['entity_type'] for row in types],
    })


@app.route('/audit')
@login_required
@super_admin_required
def audit_page():
    return render_template('audit.html')
