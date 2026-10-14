"""Super-admin portal API: user management and farm-network overview."""

from flask import jsonify, redirect, request, send_from_directory, url_for
from flask_login import current_user, login_required
from werkzeug.security import generate_password_hash

from backend.passwords import password_problem
from backend.roles import ASSIGNABLE_ROLES, PERMISSION_LABELS, ROLE_LABELS
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

@app.route('/api/admin/overview', methods=['GET'])
@login_required
@super_admin_required
def admin_overview():
    days = request.args.get('days', '0')
    try:
        days = max(0, int(days))
    except Exception:
        days = 0
    if days > 0:
        tf      = f"AND created_at >= NOW() - INTERVAL '{days} days'"
        tf_date = f"AND collection_date >= CURRENT_DATE - INTERVAL '{days} days'"
        tf_harv = f"AND harvest_date >= CURRENT_DATE - INTERVAL '{days} days'"
    else:
        tf = tf_date = tf_harv = ''
    total_farmers  = db.fetch_one("SELECT COUNT(*) as cnt FROM users WHERE role != 'super_admin'")
    active_farmers = db.fetch_one("SELECT COUNT(*) as cnt FROM users WHERE role != 'super_admin' AND is_active = TRUE")
    total_waste    = db.fetch_one(f"SELECT COALESCE(SUM(waste_weight), 0) as total FROM waste_sourcing WHERE 1=1 {tf_date}")
    total_dried    = db.fetch_one(f"SELECT COALESCE(SUM(dried_produced_kg), 0) as total FROM drying_output WHERE 1=1 {tf}")
    total_sales    = db.fetch_one(f"SELECT COALESCE(SUM(amount), 0) as total FROM sales WHERE 1=1 {tf}")
    total_harvest  = db.fetch_one(f"SELECT COALESCE(SUM(larvae_collected), 0) as total FROM harvest_yield WHERE 1=1 {tf_harv}")
    return jsonify({
        'success': True,
        'data': {
            'total_farmers':   total_farmers['cnt'],
            'active_farmers':  active_farmers['cnt'],
            'total_waste_kg':  float(total_waste['total']),
            'total_dried_kg':  float(total_dried['total']),
            'total_revenue':   float(total_sales['total']),
            'total_harvest_kg': float(total_harvest['total'])
        }
    })

@app.route('/api/admin/farmers', methods=['GET'])
@login_required
@super_admin_required
def admin_farmers():
    farmers = db.fetch_all("""
        SELECT
            u.user_id, u.username, u.full_name, u.email, u.role, u.is_active, u.last_login, u.created_at,
            COALESCE(ws.waste_records, 0) AS waste_records,
            COALESCE(ws.total_waste_kg, 0) AS total_waste_kg,
            COALESCE(hy.harvest_records, 0) AS harvest_records,
            COALESCE(hy.total_harvest_kg, 0) AS total_harvest_kg,
            COALESCE(dout.dried_records, 0) AS dried_records,
            COALESCE(dout.total_dried_kg, 0) AS total_dried_kg,
            ws.last_activity
        FROM users u
        LEFT JOIN (
            SELECT recorded_by,
                   COUNT(*) AS waste_records,
                   SUM(waste_weight) AS total_waste_kg,
                   MAX(created_at) AS last_activity
            FROM waste_sourcing GROUP BY recorded_by
        ) ws ON ws.recorded_by = u.username
        LEFT JOIN (
            SELECT recorded_by,
                   COUNT(*) AS harvest_records,
                   SUM(larvae_collected) AS total_harvest_kg
            FROM harvest_yield GROUP BY recorded_by
        ) hy ON hy.recorded_by = u.username
        LEFT JOIN (
            SELECT recorded_by,
                   COUNT(*) AS dried_records,
                   SUM(dried_produced_kg) AS total_dried_kg
            FROM drying_output GROUP BY recorded_by
        ) dout ON dout.recorded_by = u.username
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
    waste = db.fetch_all(
        "SELECT collection_date, waste_type, waste_weight, source_type FROM waste_sourcing WHERE recorded_by = %s ORDER BY created_at DESC LIMIT 8",
        (username,)
    )
    harvest = db.fetch_all(
        "SELECT harvest_date, tray_batch_id, larvae_collected, processing_method FROM harvest_yield WHERE recorded_by = %s ORDER BY harvest_date DESC LIMIT 8",
        (username,)
    )
    drying = db.fetch_all(
        "SELECT created_at, batch_id, dried_produced_kg, yield_percentage FROM drying_output WHERE recorded_by = %s ORDER BY created_at DESC LIMIT 8",
        (username,)
    )
    feeding = db.fetch_all(
        "SELECT feeding_date, tray_batch_id, feed_type, feed_quantity FROM feeding_schedule WHERE recorded_by = %s ORDER BY feeding_date DESC LIMIT 8",
        (username,)
    )
    totals = db.fetch_one("""
        SELECT
            COALESCE((SELECT SUM(waste_weight) FROM waste_sourcing WHERE recorded_by = %s), 0) AS total_waste,
            COALESCE((SELECT SUM(larvae_collected) FROM harvest_yield WHERE recorded_by = %s), 0) AS total_harvest,
            COALESCE((SELECT SUM(dried_produced_kg) FROM drying_output WHERE recorded_by = %s), 0) AS total_dried,
            COALESCE((SELECT COUNT(*) FROM waste_sourcing WHERE recorded_by = %s), 0) AS waste_count,
            COALESCE((SELECT COUNT(*) FROM harvest_yield WHERE recorded_by = %s), 0) AS harvest_count,
            COALESCE((SELECT COUNT(*) FROM drying_output WHERE recorded_by = %s), 0) AS drying_count
    """, (username, username, username, username, username, username))
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
    waste = db.fetch_all(
        "SELECT 'Waste Sourcing' AS type, recorded_by, waste_type AS detail, CONCAT(waste_weight, ' kg') AS amount, created_at FROM waste_sourcing ORDER BY created_at DESC LIMIT 8"
    )
    harvest = db.fetch_all(
        "SELECT 'Harvest' AS type, recorded_by, tray_batch_id AS detail, CONCAT(larvae_collected, ' kg') AS amount, harvest_date::timestamp AS created_at FROM harvest_yield ORDER BY harvest_date DESC LIMIT 8"
    )
    drying = db.fetch_all(
        "SELECT 'Drying Output' AS type, recorded_by, batch_id AS detail, CONCAT(dried_produced_kg, ' kg') AS amount, created_at FROM drying_output ORDER BY created_at DESC LIMIT 8"
    )
    activities = list(waste) + list(harvest) + list(drying)
    activities.sort(key=lambda x: str(x.get('created_at') or ''), reverse=True)
    return jsonify({'success': True, 'data': activities[:20]})

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
    days = request.args.get('days', '14')
    try:
        days = max(1, int(days))
    except Exception:
        days = 14
    rows = db.fetch_all(f"""
        SELECT * FROM (
            SELECT
                u.user_id, u.username, u.full_name, u.email, u.is_active, u.last_login,
                GREATEST(
                    COALESCE((SELECT MAX(created_at) FROM waste_sourcing WHERE recorded_by = u.username), '1970-01-01'::timestamp),
                    COALESCE((SELECT MAX(harvest_date::timestamp) FROM harvest_yield WHERE recorded_by = u.username), '1970-01-01'::timestamp),
                    COALESCE((SELECT MAX(created_at) FROM drying_output WHERE recorded_by = u.username), '1970-01-01'::timestamp)
                ) AS last_data_activity
            FROM users u
            WHERE u.role != 'super_admin' AND u.is_active = TRUE
        ) sub
        WHERE last_data_activity < NOW() - INTERVAL '{days} days'
        ORDER BY last_data_activity ASC
    """)
    return jsonify({'success': True, 'data': rows, 'days': days})

@app.route('/api/admin/farmers/export', methods=['GET'])
@login_required
@super_admin_required
def admin_export_farmers():
    import csv, io
    from flask import Response
    farmers = db.fetch_all("""
        SELECT
            u.username, u.full_name, u.email,
            CASE WHEN u.is_active THEN 'Active' ELSE 'Inactive' END as status,
            TO_CHAR(u.created_at, 'YYYY-MM-DD') as joined,
            TO_CHAR(u.last_login, 'YYYY-MM-DD HH24:MI') as last_login,
            COALESCE(ws.waste_records, 0) AS waste_records,
            COALESCE(ws.total_waste_kg, 0) AS total_waste_kg,
            COALESCE(hy.harvest_records, 0) AS harvest_records,
            COALESCE(hy.total_harvest_kg, 0) AS total_harvest_kg,
            COALESCE(dout.dried_records, 0) AS dried_records,
            COALESCE(dout.total_dried_kg, 0) AS total_dried_kg
        FROM users u
        LEFT JOIN (
            SELECT recorded_by, COUNT(*) AS waste_records, SUM(waste_weight) AS total_waste_kg
            FROM waste_sourcing GROUP BY recorded_by
        ) ws ON ws.recorded_by = u.username
        LEFT JOIN (
            SELECT recorded_by, COUNT(*) AS harvest_records, SUM(larvae_collected) AS total_harvest_kg
            FROM harvest_yield GROUP BY recorded_by
        ) hy ON hy.recorded_by = u.username
        LEFT JOIN (
            SELECT recorded_by, COUNT(*) AS dried_records, SUM(dried_produced_kg) AS total_dried_kg
            FROM drying_output GROUP BY recorded_by
        ) dout ON dout.recorded_by = u.username
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
