"""Super-admin portal API: user management and farm-network overview."""

from flask import jsonify, redirect, request, send_from_directory, url_for
from flask_login import current_user, login_required
from werkzeug.security import generate_password_hash

from backend.passwords import password_problem
from backend.roles import ASSIGNABLE_ROLES, PERMISSION_LABELS, ROLE_LABELS
from backend.config import CURRENCY
from backend.core.web import app, db, logger
from backend.core.security import _permissions_for, super_admin_required
from backend.core.accounts import _account_field_problem, create_user, get_user_by_email


@app.route('/zehunger')
@login_required
def zehunger_portal():
    """Serve the Zehunger Solutions super admin portal"""
    if current_user.role != 'super_admin':
        return redirect(url_for('dashboard'))
    return send_from_directory(app.static_folder, 'zehunger_portal.html')

# --- Zehunger Super Admin API ---

# ---- Figures from the production chain ---------------------------------------------
#
# Everything below counts the records the system writes today (waste lots,
# harvests, drying outputs, feeding events, customer deliveries), attributed
# to the person who recorded them. "Last activity" is the person's latest
# entry in the audit log, which covers every kind of record.

KG = "CASE WHEN {unit} = 'g' THEN {qty} / 1000.0 ELSE {qty} END"

# Per-user totals; the caller filters on u.user_id / u.username.
USER_CHAIN_STATS = f"""
    SELECT u.user_id,
           (SELECT COUNT(*) FROM waste_lots w WHERE w.recorded_by = u.username) AS waste_records,
           (SELECT COALESCE(SUM({KG.format(unit='w.unit', qty='w.quantity')}), 0)
              FROM waste_lots w WHERE w.recorded_by = u.username) AS total_waste_kg,
           (SELECT COUNT(*) FROM production_events e
              WHERE e.event_type = 'harvest' AND e.status = 'recorded' AND e.created_by_user_id = u.user_id
           ) AS harvest_records,
           (SELECT COALESCE(SUM({KG.format(unit='h.unit', qty='h.wet_weight')}), 0)
              FROM harvests h JOIN production_events e ON e.id = h.production_event_id
              WHERE e.status = 'recorded' AND e.created_by_user_id = u.user_id) AS total_harvest_kg,
           (SELECT COUNT(*) FROM drying_outputs o WHERE o.recorded_by_user_id = u.user_id) AS dried_records,
           (SELECT COALESCE(SUM({KG.format(unit='o.unit', qty='o.quantity')}), 0)
              FROM drying_outputs o WHERE o.recorded_by_user_id = u.user_id) AS total_dried_kg,
           (SELECT MAX(a.occurred_at) FROM audit_log a
              WHERE a.actor_user_id = u.user_id
                AND (a.action LIKE '%%.created' OR a.action LIKE '%%.updated')) AS last_activity
    FROM users u
"""


@app.route('/api/admin/overview', methods=['GET'])
@login_required
@super_admin_required
def admin_overview():
    try:
        days = max(0, int(request.args.get('days', '0') or 0))
    except ValueError:
        days = 0
    since = f"CURRENT_DATE - make_interval(days => {days})" if days else "'-infinity'::date"
    row = db.fetch_one(f"""
        SELECT
            (SELECT COUNT(*) FROM users WHERE role != 'super_admin') AS total_farmers,
            (SELECT COUNT(*) FROM users WHERE role != 'super_admin' AND is_active) AS active_farmers,
            (SELECT COALESCE(SUM({KG.format(unit='unit', qty='quantity')}), 0)
               FROM waste_lots WHERE collection_date >= {since}) AS total_waste_kg,
            (SELECT COALESCE(SUM({KG.format(unit='h.unit', qty='h.wet_weight')}), 0)
               FROM harvests h JOIN production_events e ON e.id = h.production_event_id
               WHERE e.status = 'recorded' AND e.occurred_at::date >= {since}) AS total_harvest_kg,
            (SELECT COALESCE(SUM({KG.format(unit='unit', qty='quantity')}), 0)
               FROM drying_outputs WHERE output_date >= {since}) AS total_dried_kg,
            (SELECT COALESCE(SUM(l.quantity_kg), 0)
               FROM customer_delivery_lines l JOIN customer_deliveries d ON d.id = l.delivery_id
               WHERE d.status = 'DELIVERED' AND d.delivered_at::date >= {since}) AS total_delivered_kg,
            (SELECT COALESCE(SUM(dl.quantity_kg * ol.unit_price), 0)
               FROM customer_delivery_lines dl
               JOIN customer_deliveries d ON d.id = dl.delivery_id
               JOIN order_allocations a ON a.id = dl.allocation_id
               JOIN customer_order_lines ol ON ol.id = a.order_line_id
               WHERE d.status = 'DELIVERED' AND d.delivered_at::date >= {since}) AS total_revenue,
            (SELECT COALESCE(SUM(dl.quantity_kg), 0)
               FROM customer_delivery_lines dl
               JOIN customer_deliveries d ON d.id = dl.delivery_id
               JOIN order_allocations a ON a.id = dl.allocation_id
               JOIN customer_order_lines ol ON ol.id = a.order_line_id
               WHERE d.status = 'DELIVERED' AND ol.unit_price IS NULL
                 AND d.delivered_at::date >= {since}) AS total_unpriced_delivered_kg
    """)
    data = {key: float(value) if key.startswith('total_') and 'farmers' not in key else value
            for key, value in row.items()}
    data['currency'] = CURRENCY
    return jsonify({'success': True, 'data': data})


@app.route('/api/admin/farmers', methods=['GET'])
@login_required
@super_admin_required
def admin_farmers():
    farmers = db.fetch_all(f"""
        SELECT u.user_id, u.username, u.full_name, u.email, u.role, u.is_active, u.last_login, u.created_at,
               s.waste_records, s.total_waste_kg, s.harvest_records, s.total_harvest_kg,
               s.dried_records, s.total_dried_kg, s.last_activity
        FROM users u JOIN ({USER_CHAIN_STATS}) s ON s.user_id = u.user_id
        WHERE u.role != 'super_admin'
        ORDER BY u.username
    """)
    return jsonify({'success': True, 'data': farmers})


@app.route('/api/admin/farmer/<string:username>/stats', methods=['GET'])
@login_required
@super_admin_required
def admin_farmer_stats(username):
    farmer = db.fetch_one(
        "SELECT user_id, username, full_name, email, role, is_active, last_login, created_at FROM users WHERE username = %s",
        (username,)
    )
    if not farmer:
        return jsonify({'success': False, 'message': 'Farmer not found'}), 404
    user_id = farmer['user_id']
    totals = db.fetch_one(f"""
        SELECT total_waste_kg AS total_waste, total_harvest_kg AS total_harvest, total_dried_kg AS total_dried,
               waste_records AS waste_count, harvest_records AS harvest_count, dried_records AS drying_count
        FROM ({USER_CHAIN_STATS}) s WHERE s.user_id = %s
    """, (user_id,))
    waste = db.fetch_all(f"""
        SELECT collection_date, waste_type, {KG.format(unit='unit', qty='quantity')} AS waste_weight, source_type
        FROM waste_lots WHERE recorded_by = %s ORDER BY collection_date DESC, id DESC LIMIT 8
    """, (username,))
    harvest = db.fetch_all(f"""
        SELECT e.occurred_at::date AS harvest_date, b.business_id AS production_batch,
               {KG.format(unit='h.unit', qty='h.wet_weight')} AS wet_weight_kg, h.harvest_stage
        FROM harvests h
        JOIN production_events e ON e.id = h.production_event_id
        JOIN production_batches b ON b.id = e.production_batch_id
        WHERE e.status = 'recorded' AND e.created_by_user_id = %s
        ORDER BY e.occurred_at DESC LIMIT 8
    """, (user_id,))
    drying = db.fetch_all(f"""
        SELECT o.output_date AS created_at, d.business_id AS batch_id,
               {KG.format(unit='o.unit', qty='o.quantity')} AS dried_produced_kg, o.yield_percentage
        FROM drying_outputs o JOIN drying_batches d ON d.id = o.drying_batch_id
        WHERE o.recorded_by_user_id = %s
        ORDER BY o.output_date DESC, o.id DESC LIMIT 8
    """, (user_id,))
    feeding = db.fetch_all("""
        SELECT e.occurred_at::date AS feeding_date, b.business_id AS production_batch, f.feed_type,
               f.quantity_offered || ' ' || f.offered_unit AS feed_quantity
        FROM feeding_events f
        JOIN production_events e ON e.id = f.production_event_id
        JOIN production_batches b ON b.id = e.production_batch_id
        WHERE e.status = 'recorded' AND e.created_by_user_id = %s
        ORDER BY e.occurred_at DESC LIMIT 8
    """, (user_id,))
    return jsonify({
        'success': True,
        'data': {
            'farmer': farmer,
            'totals': totals,
            'recent_waste': waste,
            'recent_harvest': harvest,
            'recent_drying': drying,
            'recent_feeding': feeding
        }
    })


@app.route('/api/admin/activity', methods=['GET'])
@login_required
@super_admin_required
def admin_activity_feed():
    activities = db.fetch_all(f"""
        SELECT * FROM (
            (SELECT 'Waste Sourcing' AS type, recorded_by, business_id || ' · ' || waste_type AS detail,
                    ROUND({KG.format(unit='unit', qty='quantity')}::numeric, 1) || ' kg' AS amount,
                    created_at
             FROM waste_lots ORDER BY created_at DESC LIMIT 20)
            UNION ALL
            (SELECT 'Harvest', u.username, b.business_id || ' · ' || h.harvest_code,
                    ROUND({KG.format(unit='h.unit', qty='h.wet_weight')}::numeric, 1) || ' kg', h.created_at
             FROM harvests h
             JOIN production_events e ON e.id = h.production_event_id
             JOIN production_batches b ON b.id = e.production_batch_id
             LEFT JOIN users u ON u.user_id = e.created_by_user_id
             WHERE e.status = 'recorded'
             ORDER BY h.created_at DESC LIMIT 20)
            UNION ALL
            (SELECT 'Drying Output', u.username, d.business_id || ' · output ' || o.line_no,
                    ROUND({KG.format(unit='o.unit', qty='o.quantity')}::numeric, 1) || ' kg', o.created_at
             FROM drying_outputs o
             JOIN drying_batches d ON d.id = o.drying_batch_id
             LEFT JOIN users u ON u.user_id = o.recorded_by_user_id
             ORDER BY o.created_at DESC LIMIT 20)
        ) AS recent
        ORDER BY created_at DESC
        LIMIT 20
    """)
    return jsonify({'success': True, 'data': activities})


@app.route('/api/admin/users/<int:user_id>/toggle', methods=['POST'])
@login_required
@super_admin_required
def admin_toggle_user(user_id):
    user = db.fetch_one("SELECT is_active FROM users WHERE user_id = %s AND role != 'super_admin'", (user_id,))
    if not user:
        return jsonify({'success': False, 'message': 'User not found'}), 404
    new_status = not user['is_active']
    db.execute_query(
        "UPDATE users SET is_active = %s, auth_version = auth_version + 1 WHERE user_id = %s",
        (new_status, user_id),
    )
    return jsonify({'success': True, 'is_active': new_status, 'message': f"Farmer {'activated' if new_status else 'deactivated'} successfully"})

@app.route('/api/admin/users', methods=['POST'])
@login_required
@super_admin_required
def admin_create_farmer():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'No data provided'}), 400
    username = str(data.get('username') or '').strip()
    full_name = str(data.get('full_name') or '').strip()
    email = str(data.get('email') or '').lower().strip()
    password = str(data.get('password') or '')
    role = str(data.get('role') or 'operator')
    if not all([username, full_name, email, password]):
        return jsonify({'success': False, 'message': 'All fields are required'}), 400
    if role not in ASSIGNABLE_ROLES:
        return jsonify({'success': False, 'message': 'Choose a valid role'}), 400
    problem = _account_field_problem(username, full_name, email) or password_problem(
        password, email=email, username=username
    )
    if problem:
        return jsonify({'success': False, 'message': problem}), 400
    if get_user_by_email(email):
        return jsonify({'success': False, 'message': 'Email already registered'}), 409
    if db.fetch_one("SELECT 1 FROM users WHERE LOWER(username) = LOWER(%s)", (username,)):
        return jsonify({'success': False, 'message': 'Username is already taken'}), 409
    try:
        create_user(username, full_name, email, password, role)
        return jsonify({'success': True, 'message': f"Farmer account for {full_name} created successfully"}), 201
    except Exception as e:
        logger.error(f"Admin create farmer error: {e}")
        return jsonify({'success': False, 'message': 'Failed to create farmer account'}), 500

@app.route('/api/admin/roles', methods=['GET'])
@login_required
@super_admin_required
def admin_roles():
    return jsonify({'success': True, 'data': [
        {
            'key': role,
            'label': ROLE_LABELS[role],
            'permissions': [PERMISSION_LABELS[p] for p in _permissions_for(role)],
        }
        for role in ASSIGNABLE_ROLES
    ]})


@app.route('/api/admin/me', methods=['GET'])
@login_required
@super_admin_required
def admin_me():
    return jsonify({
        'success': True,
        'data': {
            'username': current_user.username,
            'full_name': current_user.full_name,
            'email': current_user.email,
            'role': current_user.role
        }
    })

@app.route('/api/admin/users/<int:user_id>/reset-password', methods=['POST'])
@login_required
@super_admin_required
def admin_reset_password(user_id):
    data = request.get_json() or {}
    new_password = str(data.get('password') or '')
    user = db.fetch_one(
        "SELECT user_id, username, email FROM users WHERE user_id = %s AND role != 'super_admin'",
        (user_id,),
    )
    if not user:
        return jsonify({'success': False, 'message': 'User not found'}), 404
    problem = password_problem(new_password, email=user['email'], username=user['username'])
    if problem:
        return jsonify({'success': False, 'message': problem}), 400
    pw_hash = generate_password_hash(new_password)
    # Signs the user out everywhere.
    db.execute_query(
        "UPDATE users SET password_hash = %s, auth_version = auth_version + 1 WHERE user_id = %s",
        (pw_hash, user_id),
    )
    return jsonify({'success': True, 'message': 'Password reset successfully'})

@app.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
@login_required
@super_admin_required
def admin_delete_farmer(user_id):
    user = db.fetch_one("SELECT username, full_name FROM users WHERE user_id = %s AND role != 'super_admin'", (user_id,))
    if not user:
        return jsonify({'success': False, 'message': 'User not found'}), 404
    db.execute_query("DELETE FROM users WHERE user_id = %s AND role != 'super_admin'", (user_id,))
    return jsonify({'success': True, 'message': f"Farmer account for {user['full_name']} deleted successfully"})

@app.route('/api/admin/users/<int:user_id>', methods=['PUT'])
@login_required
@super_admin_required
def admin_edit_farmer(user_id):
    data = request.get_json() or {}
    full_name = str(data.get('full_name') or '').strip()
    email = str(data.get('email') or '').lower().strip()
    if not full_name or not email:
        return jsonify({'success': False, 'message': 'Full name and email are required'}), 400
    current = db.fetch_one(
        "SELECT username, role FROM users WHERE user_id = %s AND role != 'super_admin'", (user_id,)
    )
    if not current:
        return jsonify({'success': False, 'message': 'User not found'}), 404
    role = str(data.get('role') or current['role'])
    if role not in ASSIGNABLE_ROLES:
        return jsonify({'success': False, 'message': 'Choose a valid role'}), 400
    problem = _account_field_problem(current['username'], full_name, email)
    if problem:
        return jsonify({'success': False, 'message': problem}), 400
    existing = db.fetch_one("SELECT user_id FROM users WHERE email = %s AND user_id != %s", (email, user_id))
    if existing:
        return jsonify({'success': False, 'message': 'Email already registered to another account'}), 409
    # A role change takes effect at once and ends the user's other sessions.
    db.execute_query(
        """
        UPDATE users
        SET full_name = %s, email = %s, role = %s,
            auth_version = auth_version + CASE WHEN role <> %s THEN 1 ELSE 0 END
        WHERE user_id = %s AND role != 'super_admin'
        """,
        (full_name, email, role, role, user_id)
    )
    return jsonify({'success': True, 'message': 'Farmer details updated successfully'})

@app.route('/api/admin/inactive-farmers', methods=['GET'])
@login_required
@super_admin_required
def admin_inactive_farmers():
    """Active accounts with no recorded data for ``days`` days (any kind of
    record, from the audit log)."""
    try:
        days = max(1, int(request.args.get('days', '14') or 14))
    except ValueError:
        days = 14
    rows = db.fetch_all(f"""
        SELECT u.user_id, u.username, u.full_name, u.email, u.is_active, u.last_login,
               COALESCE(s.last_activity, '1970-01-01'::timestamptz) AS last_data_activity
        FROM users u JOIN ({USER_CHAIN_STATS}) s ON s.user_id = u.user_id
        WHERE u.role != 'super_admin' AND u.is_active
          AND COALESCE(s.last_activity, '1970-01-01'::timestamptz) < NOW() - make_interval(days => %s)
        ORDER BY last_data_activity ASC
    """, (days,))
    return jsonify({'success': True, 'data': rows, 'days': days})


@app.route('/api/admin/farmers/export', methods=['GET'])
@login_required
@super_admin_required
def admin_export_farmers():
    import csv, io
    from flask import Response
    farmers = db.fetch_all(f"""
        SELECT u.username, u.full_name, u.email,
               CASE WHEN u.is_active THEN 'Active' ELSE 'Inactive' END AS status,
               TO_CHAR(u.created_at, 'YYYY-MM-DD') AS joined,
               TO_CHAR(u.last_login, 'YYYY-MM-DD HH24:MI') AS last_login,
               s.waste_records, s.total_waste_kg, s.harvest_records, s.total_harvest_kg,
               s.dried_records, s.total_dried_kg
        FROM users u JOIN ({USER_CHAIN_STATS}) s ON s.user_id = u.user_id
        WHERE u.role != 'super_admin'
        ORDER BY u.username
    """)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Username', 'Full Name', 'Email', 'Status', 'Joined', 'Last Login',
                     'Waste Records', 'Waste (kg)', 'Harvest Records', 'Harvest (kg)',
                     'Dried Records', 'Dried (kg)'])
    for f in farmers:
        writer.writerow([
            f['username'], f['full_name'], f['email'], f['status'],
            f['joined'], f['last_login'] or '',
            f['waste_records'], f['total_waste_kg'],
            f['harvest_records'], f['total_harvest_kg'],
            f['dried_records'], f['total_dried_kg']
        ])
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=farmers_export.csv'}
    )
