from flask import Flask, Response, render_template, request, jsonify, redirect, url_for, flash, send_from_directory, abort
from flask_cors import CORS
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_session import Session
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Email, Length, EqualTo, ValidationError, Regexp
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.exceptions import HTTPException
from backend.init_db import init_database
from backend.database import DatabaseConnection
from backend import notifications
import csv
import io
import logging
from datetime import date, datetime, timedelta, timezone
import json
import os
import re
import secrets
import decimal
from decimal import Decimal, InvalidOperation
from backend.waste_management_routes import waste_management
from backend.fly_facility_routes import fly_facility
from backend.location_routes import locations
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from backend.config import EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, ADMIN_EMAIL, DATABASE_URL

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from flask.json.provider import DefaultJSONProvider

class CustomJSONProvider(DefaultJSONProvider):
    def default(self, obj):
        if isinstance(obj, decimal.Decimal):
            return float(obj)
        return super().default(obj)

app = Flask(__name__, 
            static_folder='../frontend',
            template_folder='../frontend')
app.json_provider_class = CustomJSONProvider
app.json = CustomJSONProvider(app)

            
# Trust proxy headers (Replit terminates SSL at proxy level)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

CORS(app, supports_credentials=True)  # Enable CORS for all routes and allow credentials

# Configure Flask app
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY') or os.getenv('SESSION_SECRET') or secrets.token_hex(32)
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)  # Session timeout

# SQLAlchemy configuration
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 300,
}

# Initialize SQLAlchemy for Flask-Session
sqlalchemy_db = SQLAlchemy(app)

# Flask-Session configuration for PostgreSQL-backed sessions
app.config['SESSION_TYPE'] = 'sqlalchemy'
app.config['SESSION_SQLALCHEMY'] = sqlalchemy_db
app.config['SESSION_SQLALCHEMY_TABLE'] = 'flask_sessions'
app.config['SESSION_PERMANENT'] = True
app.config['SESSION_USE_SIGNER'] = True
app.config['SESSION_KEY_PREFIX'] = 'bsf_'

# Session cookie settings for iframe compatibility
app.config['SESSION_COOKIE_SAMESITE'] = 'None'  # Allow cookies in iframe (must be string 'None')
app.config['SESSION_COOKIE_SECURE'] = True  # Set to True (required for SameSite=None)
app.config['SESSION_COOKIE_HTTPONLY'] = False  # Allow JavaScript access for iframe compatibility
app.config['SESSION_COOKIE_DOMAIN'] = None  # Don't restrict cookie domain
app.config['SESSION_COOKIE_PATH'] = '/'  # Set cookie for entire domain
app.config['SESSION_COOKIE_NAME'] = 'bsf_session'  # Custom session cookie name

# Flask-Login remember cookie settings
app.config['REMEMBER_COOKIE_DURATION'] = timedelta(days=7)
app.config['REMEMBER_COOKIE_SAMESITE'] = 'None'  # Allow cookies in iframe (must be string 'None')
app.config['REMEMBER_COOKIE_SECURE'] = True  # Set to True (required for SameSite=None)
app.config['REMEMBER_COOKIE_HTTPONLY'] = False
app.config['REMEMBER_COOKIE_NAME'] = 'bsf_remember'  # Custom remember cookie name
app.config['WTF_CSRF_ENABLED'] = False  # Disable CSRF for API compatibility

# Initialize Flask-Session with SQLAlchemy instance
sess = Session(app)

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.session_protection = 'basic'  # Use 'basic' for Replit iframe compatibility

# Initialize database connection
db = DatabaseConnection()

# Register blueprints
app.register_blueprint(waste_management)
app.register_blueprint(fly_facility)
app.register_blueprint(locations)

# Route to serve static files
@app.route('/<path:filename>')
def serve_static(filename):
    """Serve static files from the frontend folder (supports subdirectories: js/, css/, images/)"""
    return send_from_directory(app.static_folder, filename)

# User class for Flask-Login
class User(UserMixin):
    def __init__(self, user_id, username, email, password_hash, full_name=None, last_login=None, is_active=True, role='viewer'):
        self.id = user_id
        self.username = username
        self.email = email
        self.password_hash = password_hash
        self.full_name = full_name
        self.last_login = last_login
        self._is_active = is_active
        self.role = role

    @property
    def is_active(self):
        return self._is_active

    @property
    def is_super_admin(self):
        return self.role == 'super_admin'

    def get_id(self):
        return str(self.id)

def super_admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'super_admin':
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

# Enhanced Login form with security
class LoginForm(FlaskForm):
    email = StringField('Email', validators=[
        DataRequired(), 
        Email(message='Please enter a valid email address')
    ])
    password = PasswordField('Password', validators=[DataRequired()])
    remember = BooleanField('Remember Me')
    submit = SubmitField('Login')

# Enhanced Registration form with security
class RegistrationForm(FlaskForm):
    username = StringField('Username', validators=[
        DataRequired(), 
        Length(min=3, max=20, message='Username must be between 3 and 20 characters'),
        Regexp(r'^[a-zA-Z0-9_]+$', message='Username can only contain letters, numbers, and underscores')
    ])
    full_name = StringField('Full Name', validators=[
        DataRequired(),
        Length(min=2, max=100, message='Full name must be between 2 and 100 characters')
    ])
    email = StringField('Email', validators=[
        DataRequired(), 
        Email(message='Please enter a valid email address')
    ])
    password = PasswordField('Password', validators=[
        DataRequired(),
        Length(min=8, message='Password must be at least 8 characters long'),
        Regexp(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]', 
               message='Password must contain at least one uppercase letter, one lowercase letter, one number, and one special character')
    ])
    confirm_password = PasswordField('Confirm Password', validators=[
        DataRequired(), 
        EqualTo('password', message='Passwords must match')
    ])
    submit = SubmitField('Register')

    def validate_username(self, username):
        result = db.fetch_one("SELECT user_id FROM users WHERE username = %s", (username.data,))
        if result:
            raise ValidationError('Username already taken. Please choose another one.')

    def validate_email(self, email):
        result = db.fetch_one("SELECT user_id FROM users WHERE email = %s", (email.data,))
        if result:
            raise ValidationError('Email already registered. Please use another email.')

# Database helper functions
def get_user_by_email(email):
    """Get user by email from database"""
    result = db.fetch_one("""
        SELECT user_id, username, email, password_hash, full_name, last_login, is_active, role
        FROM users WHERE email = %s
    """, (email,))
    
    if result:
        return User(
            user_id=result['user_id'],
            username=result['username'],
            email=result['email'],
            password_hash=result['password_hash'],
            full_name=result['full_name'],
            last_login=result['last_login'],
            is_active=result['is_active'],
            role=result.get('role', 'viewer')
        )
    return None

def get_user_by_id(user_id):
    """Get user by ID from database"""
    result = db.fetch_one("""
        SELECT user_id, username, email, password_hash, full_name, last_login, is_active, role
        FROM users WHERE user_id = %s
    """, (user_id,))
    
    if result:
        return User(
            user_id=result['user_id'],
            username=result['username'],
            email=result['email'],
            password_hash=result['password_hash'],
            full_name=result['full_name'],
            last_login=result['last_login'],
            is_active=result['is_active'],
            role=result.get('role', 'viewer')
        )
    return None

def create_user(username, full_name, email, password):
    """Create a new user in the database"""
    password_hash = generate_password_hash(password)
    
    query = """
        INSERT INTO users (username, full_name, email, password_hash, role, created_at)
        VALUES (%s, %s, %s, %s, %s, NOW())
    """
    user_id = db.execute_query(query, (username, full_name, email, password_hash, 'viewer'))
    return user_id

def update_last_login(user_id):
    """Update user's last login time"""
    db.execute_query("""
        UPDATE users SET last_login = NOW()
        WHERE user_id = %s
    """, (user_id,))

@login_manager.user_loader
def load_user(user_id):
    return get_user_by_id(int(user_id))

# Authentication routes
def _safe_next(target):
    """Return ``target`` only if it is a path on this site (no open redirect)."""
    if not target or not target.startswith('/') or target.startswith('//') or '\\' in target:
        return None
    return target


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(_safe_next(request.args.get('next')) or url_for('dashboard'))
    
    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data.lower().strip()
        password = form.password.data
        
        # Verify credentials
        user = get_user_by_email(email)
        if user and user.is_active and check_password_hash(user.password_hash, password):
            # Successful login
            login_user(user, remember=form.remember.data)
            update_last_login(user.id)
            
            if user.role == 'super_admin':
                return redirect(url_for('zehunger_portal'))
            
            return redirect(_safe_next(request.args.get('next')) or url_for('dashboard'))
        else:
            # Failed login
            flash('Invalid email or password', 'danger')
    
    return render_template('login.html', form=form)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    form = RegistrationForm()
    if form.validate_on_submit():
        try:
            username = form.username.data.strip()
            full_name = form.full_name.data.strip()
            email = form.email.data.lower().strip()
            password = form.password.data
            
            user_id = create_user(username, full_name, email, password)
            flash('Registration successful! Please login with your new account.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            flash('Registration failed. Please try again.', 'danger')
            logger.error(f'Registration error: {e}')
    
    return render_template('register.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for('login'))

# API routes for AJAX requests
@app.route('/api/auth/login', methods=['POST'])
def api_login():
    """API endpoint for AJAX login requests"""
    from flask import session, make_response
    
    data = request.get_json()
    email = data.get('username', '').lower().strip()  # Frontend sends username field
    password = data.get('password', '')
    remember_me = data.get('rememberMe', False)
    
    if not email or not password:
        return jsonify({'success': False, 'message': 'Email and password are required'}), 400
    
    # Verify credentials
    user = get_user_by_email(email)
    if user and user.is_active and check_password_hash(user.password_hash, password):
        # Successful login
        session.permanent = True  # Make session permanent
        session.modified = True  # Force session to be saved
        login_user(user, remember=True, duration=timedelta(days=7), fresh=True)  # Force remember for 7 days
        update_last_login(user.id)
        
        redirect_url = '/zehunger' if user.role == 'super_admin' else '/dashboard'
        # Create response with explicit cookie settings
        response = make_response(jsonify({'success': True, 'message': 'Login successful', 'redirect': redirect_url, 'role': user.role}))
        
        logger.info(f"User {user.email} logged in successfully. Session ID: {session.get('_id', 'None')}")
        return response
    else:
        # Failed login
        return jsonify({'success': False, 'message': 'Invalid email or password'}), 401

@app.route('/api/auth/register', methods=['POST'])
def api_register():
    """API endpoint for AJAX registration requests"""
    data = request.get_json()
    username = data.get('username', '').strip()
    full_name = data.get('fullName', '').strip()
    email = data.get('email', '').lower().strip()
    password = data.get('password', '')
    confirm_password = data.get('confirmPassword', '')
    
    # Simple validation
    if not all([username, full_name, email, password, confirm_password]):
        return jsonify({'success': False, 'message': 'All fields are required'}), 400
    if password != confirm_password:
        return jsonify({'success': False, 'message': 'Passwords do not match'}), 400
        
    # Check if user already exists
    if get_user_by_email(email):
        return jsonify({'success': False, 'message': 'Email is already registered'}), 409

    try:
        create_user(username, full_name, email, password)
        return jsonify({'success': True, 'message': 'Registration successful'}), 201
    except Exception as e:
        logger.error(f"API Registration error: {e}")
        return jsonify({'success': False, 'message': 'Registration failed due to a server error'}), 500

@app.route('/')
def index():
    """Serve the main landing page"""
    return send_from_directory(app.static_folder, 'main.html')

@app.route('/dashboard')
@login_required
def dashboard():
    """Serve the main dashboard page"""
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/analytics')
@login_required
def analytics():
    """Serve the analytics dashboard page"""
    return send_from_directory(app.static_folder, 'analytics.html')

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
    db.execute_query("UPDATE users SET is_active = %s WHERE user_id = %s", (new_status, user_id))
    return jsonify({'success': True, 'is_active': new_status, 'message': f"Farmer {'activated' if new_status else 'deactivated'} successfully"})

@app.route('/api/admin/users', methods=['POST'])
@login_required
@super_admin_required
def admin_create_farmer():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'No data provided'}), 400
    username = data.get('username', '').strip()
    full_name = data.get('full_name', '').strip()
    email = data.get('email', '').lower().strip()
    password = data.get('password', '')
    if not all([username, full_name, email, password]):
        return jsonify({'success': False, 'message': 'All fields are required'}), 400
    if get_user_by_email(email):
        return jsonify({'success': False, 'message': 'Email already registered'}), 409
    try:
        create_user(username, full_name, email, password)
        return jsonify({'success': True, 'message': f"Farmer account for {full_name} created successfully"}), 201
    except Exception as e:
        logger.error(f"Admin create farmer error: {e}")
        return jsonify({'success': False, 'message': 'Failed to create farmer account'}), 500

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
    new_password = data.get('password', '')
    if len(new_password) < 8:
        return jsonify({'success': False, 'message': 'Password must be at least 8 characters'}), 400
    user = db.fetch_one("SELECT user_id FROM users WHERE user_id = %s AND role != 'super_admin'", (user_id,))
    if not user:
        return jsonify({'success': False, 'message': 'User not found'}), 404
    pw_hash = generate_password_hash(new_password)
    db.execute_query("UPDATE users SET password_hash = %s WHERE user_id = %s", (pw_hash, user_id))
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
    full_name = data.get('full_name', '').strip()
    email = data.get('email', '').lower().strip()
    if not full_name or not email:
        return jsonify({'success': False, 'message': 'Full name and email are required'}), 400
    existing = db.fetch_one("SELECT user_id FROM users WHERE email = %s AND user_id != %s", (email, user_id))
    if existing:
        return jsonify({'success': False, 'message': 'Email already registered to another account'}), 409
    db.execute_query(
        "UPDATE users SET full_name = %s, email = %s WHERE user_id = %s AND role != 'super_admin'",
        (full_name, email, user_id)
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


def _parse_chain_quantity(value, field_name):
    try:
        quantity = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f'{field_name} must be a valid number')
    if not quantity.is_finite() or quantity <= 0:
        raise ValueError(f'{field_name} must be greater than zero')
    if quantity.as_tuple().exponent < -3:
        raise ValueError(f'{field_name} supports at most three decimal places')
    return quantity


def _chain_actor(data):
    return getattr(current_user, 'username', None) or data.get('recorded_by') or 'system'


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


def _production_actor(data):
    actor = _chain_actor(data)
    actor_user_id = None
    if getattr(current_user, 'is_authenticated', False):
        try:
            actor_user_id = int(current_user.id)
        except (TypeError, ValueError):
            actor_user_id = None
    return actor, actor_user_id


class ProductionEventPermissionError(Exception):
    """Raised when an event is outside the caller's authorized scope."""


EVENT_BATCH_CLOSED_STATUSES = {'COMPLETED', 'CANCELLED'}
EVENT_UNIT_CODES = {'kg', 'g', 'count', 'days', 'celsius', 'percent', 'ppm', 'none'}


def _event_bool(value):
    return value is True or str(value).strip().lower() in {'1', 'true', 'yes'}


def _event_decimal(value, field_name, *, minimum=None, maximum=None, required=False):
    if value in (None, ''):
        if required:
            raise ValueError(f'{field_name} is required')
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f'{field_name} must be a valid number')
    if not parsed.is_finite():
        raise ValueError(f'{field_name} must be a finite number')
    if minimum is not None and parsed < Decimal(str(minimum)):
        raise ValueError(f'{field_name} must be at least {minimum}')
    if maximum is not None and parsed > Decimal(str(maximum)):
        raise ValueError(f'{field_name} must be at most {maximum}')
    if parsed.as_tuple().exponent < -3:
        raise ValueError(f'{field_name} supports at most three decimal places')
    return parsed


def _event_unit(value, field_name, default=None, allowed=None):
    unit = str(value or default or '').strip().lower()
    allowed_units = set(allowed or EVENT_UNIT_CODES)
    if unit not in allowed_units:
        raise ValueError(f'{field_name} must be one of: {", ".join(sorted(allowed_units))}')
    return unit


def _event_occurred_at(data, date_fields):
    raw = data.get('occurred_at')
    if raw in (None, ''):
        date_value = next((data.get(field) for field in date_fields if data.get(field)), None)
        if not date_value:
            raise ValueError('occurred_at or an event date is required')
        raw = f'{date_value}T{data.get("event_time") or data.get("monitoring_time") or "00:00:00"}'
    try:
        parsed = datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('occurred_at must be a valid ISO timestamp or date')
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _assert_production_scope_access(cursor, farm_id, site_id, facility_id):
    if app.config.get('LOGIN_DISABLED') or (
        getattr(current_user, 'is_authenticated', False)
        and current_user.role == 'super_admin'
    ):
        return
    if not getattr(current_user, 'is_authenticated', False):
        raise ProductionEventPermissionError('You must be signed in to record operational data')
    cursor.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM facilities AS fa
            JOIN sites AS s ON s.id = fa.site_id AND s.farm_id = %s
            JOIN farms AS f ON f.id = s.farm_id
            WHERE f.id = %s AND s.id = %s AND fa.id = %s
              AND (
                  EXISTS (
                      SELECT 1 FROM user_organization_access uoa
                      JOIN organizations o ON o.id = uoa.organization_id
                      WHERE uoa.user_id = %s AND o.id = f.organization_id
                  )
                  OR EXISTS (
                      SELECT 1 FROM user_farm_access ufa
                      WHERE ufa.user_id = %s AND ufa.farm_id = f.id
                  )
                  OR EXISTS (
                      SELECT 1 FROM user_site_access usa
                      WHERE usa.user_id = %s AND usa.site_id = s.id
                  )
                  OR EXISTS (
                      SELECT 1 FROM user_facility_access uca
                      WHERE uca.user_id = %s AND uca.facility_id = fa.id
                  )
              )
        ) AS allowed
        """,
        (
            farm_id, farm_id, site_id, facility_id,
            current_user.id, current_user.id, current_user.id, current_user.id,
        ),
    )
    if not cursor.fetchone()['allowed']:
        raise ProductionEventPermissionError(
            'You are not authorized for this farm, site, and facility'
        )


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


def _event_response(event, legacy_record=None):
    result = {'event': dict(event)}
    if legacy_record:
        result['legacy_record'] = dict(legacy_record)
    return result


def _harvest_report_rows():
    user_id = getattr(current_user, 'id', None)
    username = getattr(current_user, 'username', '')
    can_view_all = app.config.get('LOGIN_DISABLED') or (
        getattr(current_user, 'is_authenticated', False)
        and getattr(current_user, 'role', None) == 'super_admin'
    )
    return db.fetch_all(
        """
        SELECT *
        FROM (
            SELECT
                hy.id,
                hy.business_id,
                hy.harvest_date,
                hy.tray_batch_id,
                hy.instar_stage,
                hy.larvae_collected,
                hy.processing_method,
                hy.storage_temp,
                hy.notes,
                hy.recorded_by,
                NULL::INTEGER AS production_batch_id,
                NULL::VARCHAR AS unit,
                NULL::NUMERIC AS wet_weight,
                'legacy'::VARCHAR AS record_type
            FROM harvest_yield AS hy
            WHERE %s OR hy.recorded_by = %s
            UNION ALL
            SELECT
                h.id,
                h.harvest_code AS business_id,
                pe.occurred_at::date AS harvest_date,
                COALESCE(pb.business_id, pb.batch_code) AS tray_batch_id,
                h.harvest_stage AS instar_stage,
                pe.quantity AS larvae_collected,
                NULL::VARCHAR AS processing_method,
                NULL::NUMERIC AS storage_temp,
                pe.notes,
                h.operator AS recorded_by,
                pe.production_batch_id,
                h.unit,
                h.wet_weight,
                'production_batch'::VARCHAR AS record_type
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
            username,
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
    if larvae_age not in (None, ''):
        try:
            larvae_age = int(larvae_age)
        except (TypeError, ValueError):
            raise ValueError('larvae_age_days must be a valid integer')
        if larvae_age < 0:
            raise ValueError('larvae_age_days must be zero or greater')
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
                larvae_age_days
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                event['id'], feed_type, offered, offered_unit, consumed, consumed_unit,
                biomass, biomass_unit, larvae_age,
            ),
        )
        cursor.execute(
            """
            INSERT INTO feeding_schedule (
                feeding_date, tray_batch_id, larvae_age_days, larvae_weight,
                feed_type, feed_quantity, start_weight, end_weight, consumption,
                operator, recorded_by, production_event_id, production_batch_id,
                actor_user_id, occurred_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                data.get('feeding_date') or occurred_at[:10],
                data.get('tray_batch_id') or str(batch['business_id'] or batch['batch_code']),
                data.get('larvae_age_days') if data.get('larvae_age_days') not in (None, '') else 0,
                # Legacy column is in grams; mirror the canonical biomass.
                (biomass * 1000 if biomass_unit == 'kg' else biomass) if biomass is not None else None,
                feed_type,
                offered,
                data.get('start_weight_g'),
                data.get('end_weight_kg'),
                data.get('consumption_g'),
                operator,
                _chain_actor(data),
                event['id'],
                batch['id'],
                getattr(current_user, 'id', None) if getattr(current_user, 'is_authenticated', False) else None,
                occurred_at,
            ),
        )
        legacy = cursor.fetchone()
    return _event_response(event, legacy)


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
        cursor.execute(
            """
            INSERT INTO environmental_monitoring_larvaefeeding (
                monitoring_date, monitoring_time, tray_facility_id, temperature,
                humidity, ammonia_odor, notes, recorded_by, production_event_id,
                production_batch_id, actor_user_id, occurred_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                data.get('monitoring_date') or occurred_at[:10],
                data.get('monitoring_time') or occurred_at[11:19],
                asset_reference, temperature, humidity, ammonia_odor or 'no',
                data.get('notes'), _chain_actor(data), event['id'], batch['id'],
                getattr(current_user, 'id', None) if getattr(current_user, 'is_authenticated', False) else None,
                occurred_at,
            ),
        )
        legacy = cursor.fetchone()
    return _event_response(event, legacy)


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
                action_taken, follow_up_date, resolved_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                event['id'], health_status, issue, severity, action,
                data.get('follow_up_date'), resolved_at,
            ),
        )
        cursor.execute(
            """
            INSERT INTO health_intervention (
                health_date, tray_batch_id, observed_issue, severity,
                action_taken, follow_up_date, resolved, comments, recorded_by,
                production_event_id, production_batch_id, actor_user_id, occurred_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                data.get('health_date') or occurred_at[:10],
                data.get('tray_batch_id') or str(batch['business_id'] or batch['batch_code']),
                issue, severity, action, data.get('follow_up_date'),
                data.get('resolved') or ('yes' if health_status in {'resolved', 'closed'} else 'no'),
                data.get('comments'), _chain_actor(data), event['id'], batch['id'],
                getattr(current_user, 'id', None) if getattr(current_user, 'is_authenticated', False) else None,
                occurred_at,
            ),
        )
        legacy = cursor.fetchone()
    return _event_response(event, legacy)


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

    result = _event_response(event)
    result['harvest'] = dict(harvest)
    result['harvest']['production_batch_id'] = batch['id']
    result['harvest']['occurred_at'] = event['occurred_at']
    result['harvest']['notes'] = event['notes']
    return result


def _parse_positive_integer(value, field_name):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f'{field_name} must be a valid integer')
    if parsed <= 0:
        raise ValueError(f'{field_name} must be greater than zero')
    return parsed


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


def _production_scope_values(data, record_label='a Production Batch'):
    values = [data.get(field) for field in ('farm_id', 'site_id', 'facility_id')]
    if any(value in (None, '') for value in values):
        raise ValueError(f'farm_id, site_id, and facility_id are required for {record_label}')
    return tuple(
        _parse_positive_integer(value, field)
        for value, field in zip(values, ('farm_id', 'site_id', 'facility_id'))
    )


def _scope_visibility_clause(alias):
    """SQL predicate limiting ``alias`` rows to locations the caller may access.

    ``alias`` must expose farm_id, site_id and facility_id columns and is an
    internal constant, never user input.  Rows without canonical scope are
    legacy records and are visible only to super admins.
    """
    if app.config.get('LOGIN_DISABLED') or (
        getattr(current_user, 'is_authenticated', False)
        and current_user.role == 'super_admin'
    ):
        return 'TRUE', ()
    if not getattr(current_user, 'is_authenticated', False):
        return 'FALSE', ()
    return (
        f"""
        EXISTS (
            SELECT 1
            FROM facilities AS scope_fa
            JOIN sites AS scope_s ON scope_s.id = scope_fa.site_id
            JOIN farms AS scope_f ON scope_f.id = scope_s.farm_id
            WHERE scope_fa.id = {alias}.facility_id
              AND scope_s.id = {alias}.site_id
              AND scope_f.id = {alias}.farm_id
              AND (
                  EXISTS (
                      SELECT 1 FROM user_organization_access AS uoa
                      WHERE uoa.user_id = %s
                        AND uoa.organization_id = scope_f.organization_id
                  )
                  OR EXISTS (
                      SELECT 1 FROM user_farm_access AS ufa
                      WHERE ufa.user_id = %s AND ufa.farm_id = scope_f.id
                  )
                  OR EXISTS (
                      SELECT 1 FROM user_site_access AS usa
                      WHERE usa.user_id = %s AND usa.site_id = scope_s.id
                  )
                  OR EXISTS (
                      SELECT 1 FROM user_facility_access AS uca
                      WHERE uca.user_id = %s AND uca.facility_id = scope_fa.id
                  )
              )
        )
        """,
        (current_user.id,) * 4,
    )


def _optional_scope_filters(alias):
    """Translate optional farm/site/facility query parameters into SQL."""
    clauses = []
    params = []
    for field in ('farm_id', 'site_id', 'facility_id'):
        value = request.args.get(field)
        if value not in (None, ''):
            clauses.append(f'{alias}.{field} = %s')
            params.append(_parse_positive_integer(value, field))
    return clauses, params


def _assert_production_location(cursor, farm_id, site_id, facility_id):
    cursor.execute(
        """
        SELECT f.id AS farm_id, s.id AS site_id, fa.id AS facility_id,
               f.name AS farm_name, s.name AS site_name, fa.name AS facility_name
        FROM facilities AS fa
        JOIN sites AS s ON s.id = fa.site_id AND s.farm_id = %s
        JOIN farms AS f ON f.id = s.farm_id
        WHERE f.id = %s
          AND s.id = %s
          AND fa.id = %s
          AND f.status = 'active'
          AND s.status = 'active'
          AND fa.status = 'active'
        """,
        (farm_id, farm_id, site_id, facility_id),
    )
    location = cursor.fetchone()
    if not location:
        raise ValueError('The selected farm, site, and facility ownership is invalid')
    return location


def _location_label(location):
    """Legacy farm_site display text derived from the canonical hierarchy."""
    return f"{location['farm_name']} / {location['site_name']}"[:150]


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


@app.route('/api/waste-sourcing', methods=['POST'])
@login_required
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

@app.route('/api/storage-records', methods=['POST'])
@login_required
def handle_storage_records():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'No data provided'}), 400
    
    normalized_data = normalize_keys(data)

    required_fields = ['storage_date', 'storage_method', 'storage_conditions', 'storage_duration', 'planned_utilization']
    missing_fields = [field for field in required_fields if field not in normalized_data or not normalized_data.get(field)]
    if missing_fields:
        return jsonify({'success': False, 'message': f'Missing required fields: {", ".join(missing_fields)}'}), 400

    try:
        query = """
            INSERT INTO storage_records (
                storage_date, storage_method, storage_conditions, storage_duration, 
                planned_utilization, storage_observations, recorded_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        params = (
            normalized_data['storage_date'],
            normalized_data['storage_method'],
            normalized_data['storage_conditions'],
            normalized_data['storage_duration'],
            normalized_data['planned_utilization'],
            normalized_data.get('storage_observations', ''),
            current_user.username
        )
        db.execute_query(query, params)
        return jsonify({'success': True, 'message': 'Storage record saved successfully'}), 201
    except Exception as e:
        logger.error(f"Error saving storage record: {e}")
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/api/processing-records', methods=['POST'])
@login_required
def handle_processing_records():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'No data provided'}), 400

    normalized_data = normalize_keys(data)
    
    required_fields = ['processing_date', 'processing_type', 'processing_method', 'waste_processed']
    missing_fields = [field for field in required_fields if field not in normalized_data or not normalized_data.get(field)]
    if missing_fields:
        return jsonify({'success': False, 'message': f'Missing required fields: {", ".join(missing_fields)}'}), 400

    try:
        query = """
            INSERT INTO processing_records (
                processing_date, processing_type, processing_method, waste_processed, 
                waste_reduction, processing_remarks, recorded_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        params = (
            normalized_data['processing_date'],
            normalized_data['processing_type'],
            normalized_data['processing_method'],
            normalized_data['waste_processed'],
            normalized_data.get('waste_reduction'),
            normalized_data.get('processing_remarks', ''),
            current_user.username
        )
        db.execute_query(query, params)
        return jsonify({'success': True, 'message': 'Processing record saved successfully'}), 201
    except Exception as e:
        logger.error(f"Error saving processing record: {e}")
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500

@app.route('/api/substrate-preparation', methods=['POST'])
@login_required
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
            legacy_record = cursor.fetchone()

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
                'legacy_record_id': legacy_record['id'],
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
    """Assign canonical scope to a legacy Waste Lot exactly once.

    Legacy lots carry only free-text farm_site, which cannot prove ownership,
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


@app.route('/api/production/batches', methods=['POST'])
@login_required
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
def change_production_batch_status(batch_ref):
    data = normalize_keys(request.get_json() or {})
    target_status = str(data.get('status', '')).strip().upper()
    if target_status not in PRODUCTION_BATCH_STATUSES:
        return jsonify({
            'success': False,
            'message': f'Invalid Production Batch status: {target_status or "missing"}',
        }), 400
    reason = str(data.get('reason', '')).strip() or None
    if target_status in {'PAUSED', 'HEALTH_ALERT', 'CANCELLED'} and not reason:
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
                SET status = %s, current_stage = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                RETURNING id, business_id, batch_code, status, current_stage, updated_at
                """,
                (target_status, target_status, batch['id']),
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
def create_production_harvest_event(batch_ref):
    try:
        result = _create_harvest_event(_event_request_data(batch_ref))
        return jsonify({
            'success': True,
            'message': 'Harvest recorded',
            **result,
        }), 201
    except ProductionEventPermissionError as e:
        return jsonify({'success': False, 'message': str(e)}), 403
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        logger.error(f"Error saving Production Batch harvest: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


def _to_kg(quantity, unit):
    if quantity is None:
        return None
    value = Decimal(str(quantity))
    return value / Decimal('1000') if str(unit or 'kg').lower() == 'g' else value


def _ratio_percent(numerator, denominator):
    if numerator is None or not denominator:
        return None
    return (Decimal(str(numerator)) / Decimal(str(denominator)) * Decimal('100')).quantize(
        Decimal('0.01')
    )


def _kg_text(value):
    """Human-readable kilograms without trailing zeros (e.g. 2.5 kg)."""
    if value is None:
        return '—'
    text = f"{Decimal(str(value)):.3f}".rstrip('0').rstrip('.')
    return f'{text} kg'


def _jsonable(value):
    """Recursively convert dates to ISO strings for the Batch 360 payload."""
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


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


@app.route('/product-lot')
@login_required
def product_lot_page():
    return render_template('product_lot.html')


@app.route('/api/product-lots', methods=['POST'])
@login_required
def create_product_lot():
    """Release one approved Drying Output as an available Product Lot."""
    try:
        data = normalize_keys(request.get_json() or {})
        record = _release_product_lot(data)
        return jsonify({
            'success': True,
            'message': 'Approved Drying Output released as a Product Lot',
            'data': record,
            'record': record,
            'id': record['id'],
            'business_id': record['business_id'],
        }), 201
    except ProductionEventPermissionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 403
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception as exc:
        if getattr(exc, 'pgcode', None) == '23505':
            return jsonify({
                'success': False,
                'message': 'This Drying Output or lot number has already been released',
            }), 409
        logger.exception('Error releasing approved Drying Output as Product Lot')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/api/product-lots/<string:lot_ref>', methods=['GET'])
@login_required
def get_product_lot(lot_ref):
    try:
        with db.transaction() as cursor:
            record = _product_lot_detail(cursor, lot_ref)
        return jsonify({'success': True, 'data': record}), 200
    except ProductionEventPermissionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 403
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 404
    except Exception:
        logger.exception('Error fetching Product Lot detail')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


INVENTORY_MOVEMENT_TYPES = {
    'RECEIPT', 'TRANSFER', 'ADJUSTMENT_IN', 'ADJUSTMENT_OUT', 'WASTAGE',
}
# Adjustments and write-offs change stock without a physical receipt, so they
# need an administrator and a written reason.  This is the interim rule until
# Phase One RBAC introduces dedicated inventory roles.
INVENTORY_PRIVILEGED_TYPES = {'ADJUSTMENT_IN', 'ADJUSTMENT_OUT', 'WASTAGE'}
INVENTORY_INBOUND_TYPES = {'RECEIPT', 'ADJUSTMENT_IN'}
INVENTORY_OUTBOUND_TYPES = {'ADJUSTMENT_OUT', 'WASTAGE'}

# True when the lot's release approval is still the latest approved decision
# for a passing QC check.  ``pl`` must alias product_lots.
PRODUCT_LOT_RELEASABLE_SQL = """
    EXISTS (
        SELECT 1
        FROM quality_approvals AS rel_qa
        JOIN quality_checks AS rel_qc ON rel_qc.id = rel_qa.quality_check_id
        WHERE rel_qa.id = pl.release_approval_id
          AND rel_qc.status = 'passed'
          AND (
              SELECT latest.decision
              FROM quality_approvals AS latest
              WHERE latest.quality_check_id = rel_qc.id
              ORDER BY latest.id DESC
              LIMIT 1
          ) = 'approved'
    )
"""

# One signed row per ledger leg: a transfer contributes -qty to its source
# and +qty to its destination.
INVENTORY_LEDGER_CTE = """
    ledger AS (
        SELECT product_lot_id, to_location_id AS location_id,
               quantity_kg AS delta, occurred_at, id
        FROM inventory_movements
        WHERE status = 'posted' AND to_location_id IS NOT NULL
        UNION ALL
        SELECT product_lot_id, from_location_id AS location_id,
               -quantity_kg AS delta, occurred_at, id
        FROM inventory_movements
        WHERE status = 'posted' AND from_location_id IS NOT NULL
    )
"""


# Outstanding (still reserved) quantity per allocation: allocated minus what
# has been dispatched and what was released back to stock.
ALLOCATION_STATE_CTE = """
    allocation_state AS (
        SELECT a.id, a.order_line_id, a.product_lot_id, a.location_id,
               a.quantity_kg, a.released_kg,
               COALESCE((
                   SELECT SUM(dl.quantity_kg) FROM customer_delivery_lines AS dl
                   WHERE dl.allocation_id = a.id
               ), 0) AS dispatched_kg
        FROM order_allocations AS a
    )
"""


def _reserved_kg(cursor, lot_id, location_id):
    cursor.execute(
        f"""
        WITH {ALLOCATION_STATE_CTE}
        SELECT COALESCE(SUM(quantity_kg - released_kg - dispatched_kg), 0) AS reserved
        FROM allocation_state
        WHERE product_lot_id = %s AND location_id = %s
        """,
        (lot_id, location_id),
    )
    return Decimal(str(cursor.fetchone()['reserved']))


class RecordNotFoundError(ValueError):
    """Raised when a requested record does not exist or is not visible."""


class InventoryConflictError(ValueError):
    """Raised when a movement would duplicate an existing ledger fact."""


def _is_inventory_administrator():
    return bool(app.config.get('LOGIN_DISABLED')) or (
        getattr(current_user, 'is_authenticated', False)
        and current_user.role == 'super_admin'
    )


def _inventory_location_row(cursor, location_ref, label):
    location_id = _parse_positive_integer(location_ref, f'{label}_location_id')
    cursor.execute(
        """
        SELECT il.id, il.location_code, il.name, il.farm_id, il.site_id,
               il.facility_id, il.status, fa.name AS facility_name
        FROM inventory_locations AS il
        JOIN facilities AS fa ON fa.id = il.facility_id
        WHERE il.id = %s
        """,
        (location_id,),
    )
    location = cursor.fetchone()
    if not location:
        raise ValueError(f'The {label} inventory location does not exist')
    if location['status'] != 'active':
        raise ValueError(f"Inventory location {location['location_code']} is inactive")
    _assert_production_scope_access(
        cursor, location['farm_id'], location['site_id'], location['facility_id']
    )
    return location


def _inventory_lot_row(cursor, lot_ref):
    """Lock a canonical Product Lot and check the caller may act on it."""
    lookup_id = int(lot_ref) if str(lot_ref).isdigit() else -1
    cursor.execute(
        f"""
        SELECT pl.id, pl.business_id, pl.lot_code, pl.product_type,
               pl.quantity_kg, pl.farm_id, pl.release_approval_id,
               batch.site_id, batch.facility_id,
               {PRODUCT_LOT_RELEASABLE_SQL} AS releasable
        FROM product_lots AS pl
        JOIN drying_outputs AS output ON output.id = pl.drying_output_id
        JOIN drying_batches AS batch ON batch.id = output.drying_batch_id
        WHERE pl.drying_output_id IS NOT NULL
          AND (pl.id = %s OR pl.business_id = %s OR pl.lot_code = %s)
        FOR UPDATE OF pl
        """,
        (lookup_id, str(lot_ref), str(lot_ref)),
    )
    lot = cursor.fetchone()
    if not lot:
        raise RecordNotFoundError('Canonical Product Lot not found')
    _assert_production_scope_access(
        cursor, lot['farm_id'], lot['site_id'], lot['facility_id']
    )
    return lot


def _inventory_balances(cursor, lot_id):
    cursor.execute(
        f"""
        WITH {INVENTORY_LEDGER_CTE}, {ALLOCATION_STATE_CTE}
        SELECT il.id AS location_id, il.location_code, il.name AS location_name,
               fa.name AS facility_name, SUM(ledger.delta) AS quantity_kg,
               MAX(ledger.occurred_at) AS last_movement_at,
               COALESCE((
                   SELECT SUM(s.quantity_kg - s.released_kg - s.dispatched_kg)
                   FROM allocation_state AS s
                   WHERE s.product_lot_id = %s AND s.location_id = il.id
               ), 0) AS reserved_kg
        FROM ledger
        JOIN inventory_locations AS il ON il.id = ledger.location_id
        JOIN facilities AS fa ON fa.id = il.facility_id
        WHERE ledger.product_lot_id = %s
        GROUP BY il.id, fa.name
        HAVING SUM(ledger.delta) <> 0
        ORDER BY il.name, il.id
        """,
        (lot_id, lot_id),
    )
    rows = [dict(row) for row in cursor.fetchall()]
    for row in rows:
        row['free_kg'] = Decimal(str(row['quantity_kg'])) - Decimal(str(row['reserved_kg']))
    return rows


def _inventory_movement_history(cursor, lot_id):
    cursor.execute(
        """
        SELECT im.id, im.business_id, im.movement_type, im.quantity_kg,
               im.unit, im.status, im.occurred_at, im.posted_at, im.reason,
               im.notes, im.reference_type, im.reference_id, im.recorded_by,
               src.location_code AS from_location_code,
               src.name AS from_location_name,
               dst.location_code AS to_location_code,
               dst.name AS to_location_name
        FROM inventory_movements AS im
        LEFT JOIN inventory_locations AS src ON src.id = im.from_location_id
        LEFT JOIN inventory_locations AS dst ON dst.id = im.to_location_id
        WHERE im.product_lot_id = %s
          AND (im.from_location_id IS NOT NULL OR im.to_location_id IS NOT NULL)
        ORDER BY im.occurred_at, im.id
        """,
        (lot_id,),
    )
    return [dict(row) for row in cursor.fetchall()]


def _inventory_summary(cursor, lot_id):
    balances = _inventory_balances(cursor, lot_id)
    return {
        'on_hand_kg': sum(
            (Decimal(str(row['quantity_kg'])) for row in balances), Decimal('0')
        ),
        'unit': 'kg',
        'balances': balances,
        'movements': _inventory_movement_history(cursor, lot_id),
    }


def _insert_inventory_movement(
    cursor, lot, movement_type, quantity_kg, data, *, from_location=None,
    to_location=None, occurred_at=None, reason=None, notes=None,
    reference_type=None, reference_id=None,
):
    actor, actor_user_id = _production_actor(data)
    cursor.execute(
        """
        INSERT INTO inventory_movements (
            product_lot_id, farm_id, movement_type, quantity_kg, unit,
            from_location_id, to_location_id, status, occurred_at, posted_at,
            reason, notes, reference_type, reference_id, recorded_by,
            actor_user_id
        ) VALUES (
            %s, %s, %s, %s, 'kg', %s, %s, 'posted',
            COALESCE(%s, CURRENT_TIMESTAMP), CURRENT_TIMESTAMP,
            %s, %s, %s, %s, %s, %s
        )
        RETURNING id, business_id, product_lot_id, farm_id, movement_type,
                  quantity_kg, unit, from_location_id, to_location_id, status,
                  occurred_at, posted_at, reason, notes, reference_type,
                  reference_id, recorded_by
        """,
        (
            lot['id'], lot['farm_id'], movement_type, quantity_kg,
            from_location['id'] if from_location else None,
            to_location['id'] if to_location else None,
            occurred_at, reason, notes, reference_type, reference_id,
            actor, actor_user_id,
        ),
    )
    return dict(cursor.fetchone())


def _location_balance(cursor, lot_id, location_id):
    cursor.execute(
        """
        SELECT
            COALESCE(SUM(quantity_kg) FILTER (WHERE to_location_id = %s), 0)
          - COALESCE(SUM(quantity_kg) FILTER (WHERE from_location_id = %s), 0)
            AS balance
        FROM inventory_movements
        WHERE product_lot_id = %s AND status = 'posted'
        """,
        (location_id, location_id, lot_id),
    )
    return Decimal(str(cursor.fetchone()['balance']))


def _optional_text(data, field, maximum):
    value = str(data.get(field) or '').strip() or None
    if value and len(value) > maximum:
        raise ValueError(f'{field} must be at most {maximum} characters')
    return value


def _record_inventory_movement(data):
    movement_type = str(data.get('movement_type') or '').strip().upper()
    if movement_type not in INVENTORY_MOVEMENT_TYPES:
        raise ValueError(
            'movement_type must be one of: ' + ', '.join(sorted(INVENTORY_MOVEMENT_TYPES))
        )
    lot_ref = data.get('product_lot_id') or data.get('product_lot')
    if lot_ref in (None, ''):
        raise ValueError('product_lot_id is required')
    quantity = _parse_chain_quantity(
        data.get('quantity_kg', data.get('quantity')), 'quantity_kg'
    )
    if str(data.get('unit') or 'kg').strip().lower() != 'kg':
        raise ValueError('Inventory quantities must be recorded in kg')
    reason = _optional_text(data, 'reason', 500)
    notes = _optional_text(data, 'notes', 2000)
    occurred_at = None
    if data.get('occurred_at') not in (None, ''):
        occurred_at = _event_occurred_at({'occurred_at': data['occurred_at']}, ())
    if movement_type in INVENTORY_PRIVILEGED_TYPES:
        if not _is_inventory_administrator():
            raise ProductionEventPermissionError(
                'Only an administrator can post inventory adjustments or wastage'
            )
        if not reason:
            raise ValueError(f'A reason is required for {movement_type}')

    needs_source = movement_type in INVENTORY_OUTBOUND_TYPES or movement_type == 'TRANSFER'
    needs_destination = movement_type in INVENTORY_INBOUND_TYPES or movement_type == 'TRANSFER'
    source_ref = data.get('from_location_id')
    destination_ref = data.get('to_location_id')
    if needs_source != (source_ref not in (None, '')):
        raise ValueError(
            f"{movement_type} {'requires' if needs_source else 'must not have'} a from_location_id"
        )
    if needs_destination != (destination_ref not in (None, '')):
        raise ValueError(
            f"{movement_type} {'requires' if needs_destination else 'must not have'} a to_location_id"
        )

    with db.transaction() as cursor:
        # Locking the lot serializes every movement for it, so balance checks
        # below cannot race with a concurrent withdrawal.
        lot = _inventory_lot_row(cursor, lot_ref)
        source = _inventory_location_row(cursor, source_ref, 'from') if needs_source else None
        destination = (
            _inventory_location_row(cursor, destination_ref, 'to') if needs_destination else None
        )
        for location in (source, destination):
            if location and location['farm_id'] != lot['farm_id']:
                raise ValueError(
                    f"Inventory location {location['location_code']} belongs to a different farm "
                    f"than Product Lot {lot['business_id']}"
                )
        if source and destination and source['id'] == destination['id']:
            raise ValueError('A transfer needs two different inventory locations')
        if (movement_type in INVENTORY_INBOUND_TYPES or movement_type == 'TRANSFER') \
                and not lot['releasable']:
            raise ValueError(
                f"Product Lot {lot['business_id']} is blocked by QC and cannot be received or moved"
            )

        released = Decimal(str(lot['quantity_kg']))
        if movement_type == 'RECEIPT':
            cursor.execute(
                """
                SELECT 1 FROM inventory_movements
                WHERE product_lot_id = %s AND movement_type = 'RECEIPT'
                  AND status = 'posted'
                """,
                (lot['id'],),
            )
            if cursor.fetchone():
                raise InventoryConflictError(
                    f"Product Lot {lot['business_id']} has already been received into inventory"
                )
            if quantity != released:
                raise ValueError(
                    f'A RECEIPT must receive the full released quantity of {released:.3f} kg'
                )
        if movement_type == 'ADJUSTMENT_IN':
            cursor.execute(
                """
                SELECT
                    COALESCE(SUM(quantity_kg) FILTER (WHERE to_location_id IS NOT NULL), 0)
                  - COALESCE(SUM(quantity_kg) FILTER (WHERE from_location_id IS NOT NULL), 0)
                    AS on_hand
                FROM inventory_movements
                WHERE product_lot_id = %s AND status = 'posted'
                """,
                (lot['id'],),
            )
            on_hand = Decimal(str(cursor.fetchone()['on_hand']))
            if on_hand + quantity > released:
                raise ValueError(
                    f'Stock cannot exceed the released quantity of {released:.3f} kg; '
                    f'{on_hand:.3f} kg is already on hand'
                )
        if source:
            on_hand = _location_balance(cursor, lot['id'], source['id'])
            # Stock allocated to customer orders can only leave by dispatch.
            reserved = _reserved_kg(cursor, lot['id'], source['id'])
            available = on_hand - reserved
            if quantity > available:
                if reserved:
                    raise ValueError(
                        f"Only {available:.3f} kg of {lot['business_id']} at "
                        f"{source['location_code']} is free; {reserved:.3f} kg is "
                        'reserved for customer orders'
                    )
                raise ValueError(
                    f"Only {available:.3f} kg of {lot['business_id']} is at "
                    f"{source['location_code']}"
                )

        movement = _insert_inventory_movement(
            cursor, lot, movement_type, quantity, data,
            from_location=source, to_location=destination,
            occurred_at=occurred_at, reason=reason, notes=notes,
        )
        movement['product_lot_business_id'] = lot['business_id']
        movement['inventory'] = _inventory_summary(cursor, lot['id'])
        return movement


@app.route('/api/inventory/movements', methods=['POST'])
@login_required
def create_inventory_movement():
    """Post one validated movement to the Product Lot inventory ledger."""
    try:
        movement = _record_inventory_movement(normalize_keys(request.get_json() or {}))
        return jsonify({
            'success': True,
            'message': 'Inventory movement posted',
            'data': movement,
            'record': movement,
            'id': movement['id'],
            'business_id': movement['business_id'],
        }), 201
    except ProductionEventPermissionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 403
    except RecordNotFoundError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 404
    except InventoryConflictError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 409
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception as exc:
        if getattr(exc, 'pgcode', None) == '23505':
            return jsonify({
                'success': False,
                'message': 'This Product Lot has already been received into inventory',
            }), 409
        logger.exception('Error posting inventory movement')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/api/inventory/locations', methods=['GET'])
@login_required
def list_inventory_locations():
    try:
        visibility, visibility_params = _scope_visibility_clause('il')
        filters, filter_params = _optional_scope_filters('il')
        if request.args.get('include_inactive') not in ('1', 'true'):
            filters.append("il.status = 'active'")
        rows = db.fetch_all(
            f"""
            SELECT il.id, il.location_code, il.name, il.status,
                   il.farm_id, il.site_id, il.facility_id,
                   f.name AS farm_name, s.name AS site_name,
                   fa.name AS facility_name
            FROM inventory_locations AS il
            JOIN farms AS f ON f.id = il.farm_id
            JOIN sites AS s ON s.id = il.site_id
            JOIN facilities AS fa ON fa.id = il.facility_id
            WHERE {' AND '.join([visibility, *filters])}
            ORDER BY f.name, s.name, fa.name, il.name
            """,
            (*visibility_params, *filter_params),
        )
        return jsonify({'success': True, 'data': rows}), 200
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception:
        logger.exception('Error listing inventory locations')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/api/inventory/locations', methods=['POST'])
@login_required
@super_admin_required
def create_inventory_location():
    data = normalize_keys(request.get_json() or {})
    try:
        farm_id, site_id, facility_id = _production_scope_values(
            data, 'an inventory location'
        )
        location_code = _optional_text(data, 'location_code', 30)
        name = _optional_text(data, 'name', 100)
        if not location_code or not name:
            raise ValueError('location_code and name are required')
        actor_user_id = _production_actor(data)[1]
        with db.transaction() as cursor:
            _assert_production_location(cursor, farm_id, site_id, facility_id)
            cursor.execute(
                """
                INSERT INTO inventory_locations (
                    location_code, name, farm_id, site_id, facility_id,
                    created_by_user_id
                ) VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, location_code, name, status, farm_id, site_id,
                          facility_id, created_at
                """,
                (location_code, name, farm_id, site_id, facility_id, actor_user_id),
            )
            location = cursor.fetchone()
        return jsonify({'success': True, 'data': location}), 201
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception as exc:
        if getattr(exc, 'pgcode', None) == '23505':
            return jsonify({
                'success': False,
                'message': 'This location code already exists in the facility',
            }), 409
        logger.exception('Error creating inventory location')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/api/inventory/locations/<int:location_id>/status', methods=['POST'])
@login_required
@super_admin_required
def set_inventory_location_status(location_id):
    """Deactivate or reactivate a store; history and balances are kept."""
    data = request.get_json() or {}
    status = str(data.get('status') or '').strip().lower()
    if status not in ('active', 'inactive'):
        return jsonify({'success': False, 'message': 'status must be active or inactive'}), 400
    try:
        with db.transaction() as cursor:
            if status == 'inactive':
                cursor.execute(
                    f"""
                    WITH {INVENTORY_LEDGER_CTE}
                    SELECT COALESCE(SUM(delta), 0) AS on_hand
                    FROM ledger WHERE location_id = %s
                    """,
                    (location_id,),
                )
                if Decimal(str(cursor.fetchone()['on_hand'])) > 0:
                    return jsonify({
                        'success': False,
                        'message': 'Move the stock out of this location before deactivating it',
                    }), 400
            cursor.execute(
                """
                UPDATE inventory_locations SET status = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s RETURNING id, status
                """,
                (status, location_id),
            )
            row = cursor.fetchone()
        if not row:
            return jsonify({'success': False, 'message': 'Inventory location not found'}), 404
        return jsonify({'success': True, 'data': dict(row)}), 200
    except Exception:
        logger.exception('Error updating inventory location status')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/api/inventory', methods=['GET'])
@login_required
def get_inventory_stock():
    """Stock on hand by product, lot and location, derived from the ledger."""
    try:
        visibility, visibility_params = _scope_visibility_clause('il')
        filters, filter_params = _optional_scope_filters('il')
        product_type = request.args.get('product_type')
        if product_type:
            filters.append('pl.product_type = %s')
            filter_params.append(product_type)
        rows = db.fetch_all(
            f"""
            WITH {INVENTORY_LEDGER_CTE}, {ALLOCATION_STATE_CTE}
            SELECT pl.product_type, pl.id AS product_lot_id, pl.business_id,
                   pl.lot_code,
                   CASE WHEN {PRODUCT_LOT_RELEASABLE_SQL}
                        THEN 'AVAILABLE' ELSE 'BLOCKED' END AS lot_status,
                   il.id AS location_id, il.location_code,
                   il.name AS location_name, fa.name AS facility_name,
                   f.name AS farm_name, il.farm_id,
                   SUM(ledger.delta) AS quantity_kg, 'kg' AS unit,
                   MAX(ledger.occurred_at) AS last_movement_at,
                   COALESCE((
                       SELECT SUM(s.quantity_kg - s.released_kg - s.dispatched_kg)
                       FROM allocation_state AS s
                       WHERE s.product_lot_id = pl.id AND s.location_id = il.id
                   ), 0) AS reserved_kg
            FROM ledger
            JOIN product_lots AS pl ON pl.id = ledger.product_lot_id
            JOIN inventory_locations AS il ON il.id = ledger.location_id
            JOIN facilities AS fa ON fa.id = il.facility_id
            JOIN farms AS f ON f.id = il.farm_id
            WHERE {' AND '.join([visibility, *filters])}
            GROUP BY pl.id, il.id, fa.name, f.name
            HAVING SUM(ledger.delta) <> 0
            ORDER BY pl.product_type, pl.business_id, il.name
            """,
            (*visibility_params, *filter_params),
        )
        totals = {}
        for row in rows:
            entry = totals.setdefault(row['product_type'], {
                'product_type': row['product_type'],
                'quantity_kg': Decimal('0'),
                'reserved_kg': Decimal('0'),
                'available_kg': Decimal('0'),
            })
            quantity = Decimal(str(row['quantity_kg']))
            reserved = Decimal(str(row['reserved_kg']))
            # Free stock: on hand, not reserved for an order, and QC released.
            row['free_kg'] = quantity - reserved
            entry['quantity_kg'] += quantity
            entry['reserved_kg'] += reserved
            if row['lot_status'] == 'AVAILABLE':
                entry['available_kg'] += quantity - reserved
        return jsonify({
            'success': True,
            'data': rows,
            'totals': sorted(totals.values(), key=lambda item: item['product_type']),
        }), 200
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception:
        logger.exception('Error loading inventory stock')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/api/product-lots', methods=['GET'])
@login_required
def list_product_lots():
    try:
        visibility, visibility_params = _scope_visibility_clause('batch')
        filters = []
        filter_params = []
        if request.args.get('farm_id') not in (None, ''):
            filters.append('pl.farm_id = %s')
            filter_params.append(_parse_positive_integer(request.args['farm_id'], 'farm_id'))
        rows = db.fetch_all(
            f"""
            WITH {INVENTORY_LEDGER_CTE}
            SELECT pl.id, pl.business_id, pl.lot_code, pl.product_type,
                   pl.quantity_kg, pl.unit, pl.production_date,
                   pl.farm_id, f.name AS farm_name,
                   batch.business_id AS drying_batch_business_id,
                   CASE WHEN {PRODUCT_LOT_RELEASABLE_SQL}
                        THEN 'AVAILABLE' ELSE 'BLOCKED' END AS status,
                   COALESCE((
                       SELECT SUM(ledger.delta) FROM ledger
                       WHERE ledger.product_lot_id = pl.id
                   ), 0) AS on_hand_kg
            FROM product_lots AS pl
            JOIN drying_outputs AS output ON output.id = pl.drying_output_id
            JOIN drying_batches AS batch ON batch.id = output.drying_batch_id
            JOIN farms AS f ON f.id = pl.farm_id
            WHERE {' AND '.join([visibility, *filters])}
            ORDER BY pl.production_date DESC, pl.id DESC
            LIMIT 500
            """,
            (*visibility_params, *filter_params),
        )
        return jsonify({'success': True, 'data': rows}), 200
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception:
        logger.exception('Error listing Product Lots')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


# ---- Traceability --------------------------------------------------------
#
# Lineage is walked over the stored foreign keys of the Phase One chain:
#   waste_lot -> substrate_batch -> production_batch -> harvest
#   -> drying_batch -> product_lot -> inventory_location (current stock)
# Upstream walks only follow edges backwards and downstream only forwards,
# so a production batch never pulls in its sibling batches' unrelated data.

TRACE_STAGES = (
    'waste_lot', 'substrate_batch', 'production_batch', 'harvest',
    'drying_batch', 'product_lot', 'inventory_location', 'customer_order',
    'delivery',
)
TRACE_LABELS = {
    'waste_lot': 'Waste Lot',
    'substrate_batch': 'Substrate Batch',
    'production_batch': 'Production Batch',
    'harvest': 'Harvest',
    'drying_batch': 'Drying Batch',
    'product_lot': 'Product Lot',
    'inventory_location': 'Inventory Location',
    'customer_order': 'Customer Order',
    'delivery': 'Delivery',
}
TRACE_ROOT_TYPES = tuple(kind for kind in TRACE_STAGES if kind != 'inventory_location')
# Commercial records need farm-level access; walks stop at these node types
# unless the trace starts from one, so an order never pulls in other lots.
TRACE_COMMERCIAL = {'customer_order', 'delivery'}
TRACE_TERMINAL = {'inventory_location'} | TRACE_COMMERCIAL
# Lookup by numeric database ID (only when the caller names the type).
TRACE_ID_SQL = {
    'waste_lot': "SELECT id FROM waste_lots WHERE id = %s",
    'substrate_batch': "SELECT id FROM substrate_batches WHERE id = %s",
    'production_batch': "SELECT id FROM production_batches WHERE id = %s",
    'harvest': "SELECT id FROM harvests WHERE id = %s",
    'drying_batch': "SELECT id FROM drying_batches WHERE id = %s",
    'product_lot': "SELECT id FROM product_lots WHERE id = %s AND drying_output_id IS NOT NULL",
    'customer_order': "SELECT id FROM customer_orders WHERE id = %s",
    'delivery': "SELECT id FROM customer_deliveries WHERE id = %s",
}
TRACE_NODE_LIMIT = 300

# How each searchable record type is matched by its human-readable IDs.
TRACE_REF_SQL = {
    'waste_lot': (
        "SELECT id FROM waste_lots WHERE UPPER(business_id) = UPPER(%s)", 1,
    ),
    'substrate_batch': (
        "SELECT id FROM substrate_batches "
        "WHERE UPPER(business_id) = UPPER(%s) OR UPPER(batch_code) = UPPER(%s)", 2,
    ),
    'production_batch': (
        "SELECT id FROM production_batches "
        "WHERE UPPER(business_id) = UPPER(%s) OR UPPER(batch_code) = UPPER(%s)", 2,
    ),
    'harvest': (
        "SELECT id FROM harvests WHERE UPPER(harvest_code) = UPPER(%s)", 1,
    ),
    'drying_batch': (
        "SELECT id FROM drying_batches WHERE UPPER(business_id) = UPPER(%s) "
        "OR UPPER(batch_code) = UPPER(%s) OR UPPER(batch_id) = UPPER(%s)", 3,
    ),
    'product_lot': (
        "SELECT id FROM product_lots WHERE drying_output_id IS NOT NULL "
        "AND (UPPER(business_id) = UPPER(%s) OR UPPER(lot_code) = UPPER(%s))", 2,
    ),
    'customer_order': (
        "SELECT id FROM customer_orders WHERE UPPER(business_id) = UPPER(%s)", 1,
    ),
    'delivery': (
        "SELECT id FROM customer_deliveries WHERE UPPER(business_id) = UPPER(%s)", 1,
    ),
}

TRACE_NODE_SQL = {
    'waste_lot': """
        SELECT wl.id, wl.business_id AS ref, wl.source_name || ' · ' || wl.waste_type AS title,
               UPPER(wl.status) AS status, wl.collection_date AS occurred,
               wl.quantity, wl.unit, wl.recorded_by AS actor,
               wl.farm_id, wl.site_id, wl.facility_id,
               json_build_object('source_type', wl.source_type,
                                 'quality_status', wl.quality_status) AS details
        FROM waste_lots AS wl WHERE wl.id = ANY(%s)
    """,
    'substrate_batch': """
        SELECT sb.id, sb.business_id AS ref, NULL AS title,
               NULL AS status, sb.preparation_date AS occurred,
               sb.total_input_weight_kg AS quantity, 'kg' AS unit,
               sb.recorded_by AS actor, sb.farm_id, sb.site_id, sb.facility_id,
               json_build_object('particle_size', sb.particle_size) AS details
        FROM substrate_batches AS sb WHERE sb.id = ANY(%s)
    """,
    'production_batch': """
        SELECT pb.id, pb.business_id AS ref,
               CASE WHEN UPPER(pb.current_stage) = UPPER(pb.status) THEN NULL
                    ELSE 'Stage: ' || pb.current_stage END AS title,
               UPPER(pb.status) AS status, pb.start_date AS occurred,
               (SELECT SUM(quantity_issued) FROM production_batch_inputs
                 WHERE production_batch_id = pb.id) AS quantity,
               'kg' AS unit, pb.recorded_by AS actor,
               pb.farm_id, pb.site_id, pb.facility_id,
               json_build_object('harvest_limit_kg', pb.harvest_limit_kg) AS details
        FROM production_batches AS pb WHERE pb.id = ANY(%s)
    """,
    'harvest': """
        SELECT h.id, h.harvest_code AS ref, h.harvest_stage AS title,
               NULL AS status, pe.occurred_at AS occurred,
               pe.quantity, 'kg' AS unit, h.operator AS actor,
               pe.farm_id, pe.site_id, pe.facility_id,
               json_build_object('location', h.location) AS details
        FROM harvests AS h
        JOIN production_events AS pe ON pe.id = h.production_event_id
        WHERE h.id = ANY(%s)
    """,
    'drying_batch': """
        SELECT db.id, COALESCE(db.business_id, db.batch_code, db.batch_id) AS ref,
               db.drying_method AS title, UPPER(db.status) AS status,
               db.drying_date AS occurred,
               (SELECT SUM(CASE WHEN o.unit = 'g' THEN o.quantity / 1000 ELSE o.quantity END)
                  FROM drying_outputs AS o WHERE o.drying_batch_id = db.id) AS quantity,
               'kg' AS unit, db.personnel AS actor,
               db.farm_id, db.site_id, db.facility_id,
               json_build_object(
                   'qc', (SELECT qc.status FROM quality_checks AS qc
                           WHERE qc.drying_batch_id = db.id ORDER BY qc.id DESC LIMIT 1)
               ) AS details
        FROM drying_batches AS db WHERE db.id = ANY(%s)
    """,
    'product_lot': f"""
        SELECT pl.id, pl.business_id AS ref, pl.product_type AS title,
               CASE WHEN {PRODUCT_LOT_RELEASABLE_SQL}
                    THEN 'AVAILABLE' ELSE 'BLOCKED' END AS status,
               pl.production_date AS occurred, pl.quantity_kg AS quantity,
               pl.unit, pl.recorded_by AS actor,
               pl.farm_id, batch.site_id, batch.facility_id,
               json_build_object('lot_code', pl.lot_code,
                                 'qc_status', qc.status,
                                 'approval', qa.decision) AS details
        FROM product_lots AS pl
        JOIN drying_outputs AS output ON output.id = pl.drying_output_id
        JOIN drying_batches AS batch ON batch.id = output.drying_batch_id
        LEFT JOIN quality_approvals AS qa ON qa.id = pl.release_approval_id
        LEFT JOIN quality_checks AS qc ON qc.id = qa.quality_check_id
        WHERE pl.id = ANY(%s)
    """,
    'inventory_location': """
        SELECT il.id, il.location_code AS ref, il.name AS title,
               UPPER(il.status) AS status, NULL::date AS occurred,
               NULL::numeric AS quantity, 'kg' AS unit, NULL AS actor,
               il.farm_id, il.site_id, il.facility_id,
               '{}'::json AS details
        FROM inventory_locations AS il WHERE il.id = ANY(%s)
    """,
    'customer_order': """
        SELECT o.id, o.business_id AS ref, c.name AS title, o.status,
               o.order_date AS occurred,
               (SELECT SUM(quantity_kg) FROM customer_order_lines
                 WHERE order_id = o.id) AS quantity,
               'kg' AS unit, o.created_by AS actor,
               o.farm_id, NULL::int AS site_id, NULL::int AS facility_id,
               json_build_object('farm_name', f.name,
                                 'requested_delivery_date', o.requested_delivery_date) AS details
        FROM customer_orders AS o
        JOIN customers AS c ON c.id = o.customer_id
        JOIN farms AS f ON f.id = o.farm_id
        WHERE o.id = ANY(%s)
    """,
    'delivery': """
        SELECT d.id, d.business_id AS ref, c.name AS title, d.status,
               d.dispatched_at AS occurred,
               (SELECT SUM(quantity_kg) FROM customer_delivery_lines
                 WHERE delivery_id = d.id) AS quantity,
               'kg' AS unit, d.created_by AS actor,
               o.farm_id, NULL::int AS site_id, NULL::int AS facility_id,
               json_build_object('farm_name', f.name, 'order_ref', o.business_id,
                                 'received_by', d.received_by,
                                 'delivered_at', d.delivered_at) AS details
        FROM customer_deliveries AS d
        JOIN customer_orders AS o ON o.id = d.order_id
        JOIN customers AS c ON c.id = o.customer_id
        JOIN farms AS f ON f.id = o.farm_id
        WHERE d.id = ANY(%s)
    """,
}

# (from_type, to_type, SQL returning from_id, to_id, quantity, unit)
TRACE_EDGE_SQL = [
    ('waste_lot', 'substrate_batch', """
        SELECT waste_lot_id AS from_id, substrate_batch_id AS to_id,
               quantity_used AS quantity, unit
        FROM substrate_batch_inputs WHERE {side} = ANY(%s)
    """, ('waste_lot_id', 'substrate_batch_id')),
    ('substrate_batch', 'production_batch', """
        SELECT substrate_batch_id AS from_id, production_batch_id AS to_id,
               quantity_issued AS quantity, unit
        FROM production_batch_inputs WHERE {side} = ANY(%s)
    """, ('substrate_batch_id', 'production_batch_id')),
    ('production_batch', 'harvest', """
        SELECT pe.production_batch_id AS from_id, h.id AS to_id,
               pe.quantity, 'kg' AS unit
        FROM harvests AS h
        JOIN production_events AS pe ON pe.id = h.production_event_id
        WHERE pe.status = 'recorded' AND {side} = ANY(%s)
    """, ('pe.production_batch_id', 'h.id')),
    ('harvest', 'drying_batch', """
        SELECT harvest_id AS from_id, drying_batch_id AS to_id,
               CASE WHEN unit = 'g' THEN quantity / 1000 ELSE quantity END AS quantity,
               'kg' AS unit
        FROM drying_inputs WHERE {side} = ANY(%s)
    """, ('harvest_id', 'drying_batch_id')),
    ('drying_batch', 'product_lot', """
        SELECT output.drying_batch_id AS from_id, pl.id AS to_id,
               pl.quantity_kg AS quantity, 'kg' AS unit
        FROM product_lots AS pl
        JOIN drying_outputs AS output ON output.id = pl.drying_output_id
        WHERE {side} = ANY(%s)
    """, ('output.drying_batch_id', 'pl.id')),
    # Current stock only: a location is a terminal node, never traversed
    # onwards to the other lots it happens to hold.
    ('product_lot', 'inventory_location', f"""
        WITH {INVENTORY_LEDGER_CTE}
        SELECT ledger.product_lot_id AS from_id, ledger.location_id AS to_id,
               SUM(ledger.delta) AS quantity, 'kg' AS unit
        FROM ledger WHERE {{side}} = ANY(%s)
        GROUP BY ledger.product_lot_id, ledger.location_id
        HAVING SUM(ledger.delta) <> 0
    """, ('ledger.product_lot_id', None)),
    # Quantity still committed to the order (allocated minus released).
    ('product_lot', 'customer_order', """
        SELECT a.product_lot_id AS from_id, l.order_id AS to_id,
               SUM(a.quantity_kg - a.released_kg) AS quantity, 'kg' AS unit
        FROM order_allocations AS a
        JOIN customer_order_lines AS l ON l.id = a.order_line_id
        WHERE {side} = ANY(%s)
        GROUP BY a.product_lot_id, l.order_id
        HAVING SUM(a.quantity_kg - a.released_kg) > 0
    """, ('a.product_lot_id', 'l.order_id')),
    ('product_lot', 'delivery', """
        SELECT a.product_lot_id AS from_id, dl.delivery_id AS to_id,
               SUM(dl.quantity_kg) AS quantity, 'kg' AS unit
        FROM customer_delivery_lines AS dl
        JOIN order_allocations AS a ON a.id = dl.allocation_id
        WHERE {side} = ANY(%s)
        GROUP BY a.product_lot_id, dl.delivery_id
    """, ('a.product_lot_id', 'dl.delivery_id')),
    ('customer_order', 'delivery', """
        SELECT d.order_id AS from_id, d.id AS to_id,
               (SELECT SUM(quantity_kg) FROM customer_delivery_lines
                 WHERE delivery_id = d.id) AS quantity, 'kg' AS unit
        FROM customer_deliveries AS d
        WHERE {side} = ANY(%s)
    """, ('d.order_id', 'd.id')),
]


def _trace_resolve(cursor, ref, record_type=None):
    ref = str(ref or '').strip()
    if not ref:
        raise ValueError('Enter a record ID to trace')
    if record_type:
        if record_type not in TRACE_ROOT_TYPES:
            raise ValueError('Unknown record type')
        types = [record_type]
    else:
        types = list(TRACE_ROOT_TYPES)
    matches = []
    for kind in types:
        if ref.isdigit() and record_type:
            cursor.execute(TRACE_ID_SQL[kind], (int(ref),))
        else:
            sql, count = TRACE_REF_SQL[kind]
            cursor.execute(sql, (ref,) * count)
        matches.extend((kind, row['id']) for row in cursor.fetchall())
    if not matches:
        if ref.isdigit() and not record_type:
            raise ValueError('Choose a record type to trace a numeric database ID')
        raise RecordNotFoundError(f'No traceable record matches {ref}')
    if len(matches) > 1:
        raise InventoryConflictError(
            'This ID matches more than one record; choose a record type: '
            + ', '.join(sorted({TRACE_LABELS[kind] for kind, _ in matches}))
        )
    return matches[0]


def _trace_walk(cursor, root, direction):
    """Breadth-first walk from ``root`` in one direction over stored edges."""
    seen = {root}
    frontier = {root}
    edges = []
    truncated = False
    while frontier:
        next_frontier = set()
        for from_type, to_type, sql, (from_col, to_col) in TRACE_EDGE_SQL:
            source_type = from_type if direction == 'down' else to_type
            ids = [node_id for kind, node_id in frontier if kind == source_type]
            side = from_col if direction == 'down' else to_col
            if not ids or side is None:
                continue
            cursor.execute(sql.format(side=side), (ids,))
            for row in cursor.fetchall():
                edges.append({
                    'from': f"{from_type}:{row['from_id']}",
                    'to': f"{to_type}:{row['to_id']}",
                    'quantity': row['quantity'],
                    'unit': row['unit'],
                })
                neighbour = (
                    (to_type, row['to_id']) if direction == 'down' else (from_type, row['from_id'])
                )
                if neighbour not in seen:
                    if len(seen) >= TRACE_NODE_LIMIT:
                        truncated = True
                        continue
                    seen.add(neighbour)
                    if neighbour[0] not in TRACE_TERMINAL:
                        next_frontier.add(neighbour)
        frontier = next_frontier
    return seen - {root}, edges, truncated


def _trace_can_access(cursor, farm_id, site_id, facility_id):
    try:
        _assert_production_scope_access(cursor, farm_id, site_id, facility_id)
        return True
    except ProductionEventPermissionError:
        return False


def _trace_nodes(cursor, keys, root):
    by_type = {}
    for kind, node_id in keys:
        by_type.setdefault(kind, []).append(node_id)
    nodes = {}
    for kind, ids in by_type.items():
        cursor.execute(TRACE_NODE_SQL[kind], (ids,))
        for row in cursor.fetchall():
            key = f"{kind}:{row['id']}"
            node = {'key': key, 'type': kind, 'type_label': TRACE_LABELS[kind], **dict(row)}
            node['is_root'] = (kind, row['id']) == root
            if kind in TRACE_COMMERCIAL:
                allowed = _farm_access_allowed(cursor, row['farm_id'])
            else:
                allowed = _trace_can_access(cursor, row['farm_id'], row['site_id'], row['facility_id'])
            if not allowed:
                # Show that a link exists without disclosing another
                # location's record.
                node = {
                    'key': key, 'type': kind, 'type_label': TRACE_LABELS[kind],
                    'restricted': True, 'is_root': False,
                }
            else:
                node['restricted'] = False
                if kind == 'production_batch':
                    node['href'] = f"/batch-360?ref={row['ref']}"
                elif kind == 'product_lot':
                    node['href'] = f"/product-lot?ref={row['ref']}"
                elif kind == 'customer_order':
                    node['href'] = f"/orders?ref={row['ref']}"
                    node['location'] = row['details'].get('farm_name')
                elif kind == 'delivery':
                    node['href'] = f"/orders?ref={row['details'].get('order_ref')}"
                    node['location'] = row['details'].get('farm_name')
            nodes[key] = node
    names = {}
    scope_ids = {
        (n['farm_id'], n['site_id'], n['facility_id'])
        for n in nodes.values() if not n['restricted'] and n.get('facility_id')
    }
    if scope_ids:
        cursor.execute(
            """
            SELECT f.id AS farm_id, s.id AS site_id, fa.id AS facility_id,
                   f.name AS farm_name, s.name AS site_name, fa.name AS facility_name
            FROM facilities AS fa
            JOIN sites AS s ON s.id = fa.site_id
            JOIN farms AS f ON f.id = s.farm_id
            WHERE fa.id = ANY(%s)
            """,
            ([scope[2] for scope in scope_ids],),
        )
        names = {row['facility_id']: dict(row) for row in cursor.fetchall()}
    for node in nodes.values():
        place = names.get(node.get('facility_id'))
        if place and not node['restricted']:
            node['location'] = f"{place['farm_name']} / {place['site_name']} / {place['facility_name']}"
    return nodes


def _traceability(cursor, ref, record_type=None):
    root = _trace_resolve(cursor, ref, record_type)
    root_nodes = _trace_nodes(cursor, [root], root)
    root_node = root_nodes[f'{root[0]}:{root[1]}']
    if root_node['restricted']:
        raise ProductionEventPermissionError('You are not authorized for this record')

    upstream_keys, upstream_edges, up_truncated = _trace_walk(cursor, root, 'up')
    downstream_keys, downstream_edges, down_truncated = _trace_walk(cursor, root, 'down')
    nodes = _trace_nodes(cursor, upstream_keys | downstream_keys, root)
    nodes[root_node['key']] = root_node
    for key in (f'{kind}:{node_id}' for kind, node_id in upstream_keys):
        nodes[key]['direction'] = 'upstream'
    for key in (f'{kind}:{node_id}' for kind, node_id in downstream_keys):
        nodes[key].setdefault('direction', 'downstream')
    root_node['direction'] = 'root'

    def column(kind):
        rows = [node for node in nodes.values() if node['type'] == kind]
        rows.sort(key=lambda node: (not node.get('is_root'), node.get('restricted', False),
                                    str(node.get('ref') or '')))
        return rows

    stages = [
        {'type': kind, 'label': TRACE_LABELS[kind], 'nodes': column(kind)}
        for kind in TRACE_STAGES
    ]
    # Restricted neighbours keep their edge but lose quantities.
    edges = []
    for edge in upstream_edges + downstream_edges:
        hidden = nodes.get(edge['from'], {}).get('restricted') or nodes.get(edge['to'], {}).get('restricted')
        edges.append({**edge, 'quantity': None if hidden else edge['quantity']})

    return _jsonable({
        'root': root_node,
        'stages': stages,
        'edges': edges,
        'counts': {
            'upstream': len(upstream_keys),
            'downstream': len(downstream_keys),
            'restricted': sum(1 for node in nodes.values() if node['restricted']),
        },
        'truncated': up_truncated or down_truncated,
        'commercial': {'linked': True},
    })


@app.route('/api/traceability', methods=['GET'])
@login_required
def get_traceability():
    try:
        with db.transaction() as cursor:
            result = _traceability(
                cursor, request.args.get('ref'), request.args.get('type') or None
            )
        return jsonify({'success': True, 'data': result}), 200
    except ProductionEventPermissionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 403
    except RecordNotFoundError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 404
    except InventoryConflictError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 409
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception:
        logger.exception('Error building traceability graph')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/api/traceability/search', methods=['GET'])
@login_required
def search_traceability():
    """Suggest traceable records whose ID starts with ``q`` (scoped)."""
    query = str(request.args.get('q') or '').strip()
    if len(query) < 2:
        return jsonify({'success': True, 'data': []}), 200
    pattern = query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
    sources = [
        ('waste_lot', 'waste_lots AS t', 't.business_id', 't'),
        ('substrate_batch', 'substrate_batches AS t', 't.business_id', 't'),
        ('production_batch', 'production_batches AS t', 't.business_id', 't'),
        ('harvest', 'harvests AS h JOIN production_events AS t ON t.id = h.production_event_id',
         'h.harvest_code', 't'),
        ('drying_batch', 'drying_batches AS t', 'COALESCE(t.business_id, t.batch_code)', 't'),
        ('product_lot',
         'product_lots AS p JOIN drying_outputs AS o ON o.id = p.drying_output_id '
         'JOIN drying_batches AS t ON t.id = o.drying_batch_id',
         'p.business_id', 't'),
        ('customer_order', 'customer_orders AS t', 't.business_id', 't'),
        ('delivery', 'customer_deliveries AS d JOIN customer_orders AS t ON t.id = d.order_id',
         'd.business_id', 't'),
    ]
    try:
        results = []
        for kind, source, column_sql, alias in sources:
            visibility, params = (
                _farm_visibility_clause(alias) if kind in TRACE_COMMERCIAL
                else _scope_visibility_clause(alias)
            )
            rows = db.fetch_all(
                f"SELECT {column_sql} AS ref FROM {source} "
                f"WHERE {column_sql} ILIKE %s AND {visibility} "
                f"ORDER BY 1 DESC LIMIT 10",
                (pattern, *params),
            )
            results.extend(
                {'type': kind, 'type_label': TRACE_LABELS[kind], 'ref': row['ref']}
                for row in rows if row['ref']
            )
        return jsonify({'success': True, 'data': results[:20]}), 200
    except Exception:
        logger.exception('Error searching traceable records')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/traceability')
@login_required
def traceability_page():
    return render_template('traceability.html')


# ---- Customer orders, allocations and deliveries -------------------------
#
# Commercial records are farm-scoped and visible only to users with farm or
# organization access (or super admins); facility-only operators do not see
# customers or order quantities.

def _farm_access_allowed(cursor, farm_id):
    if app.config.get('LOGIN_DISABLED') or (
        getattr(current_user, 'is_authenticated', False)
        and current_user.role == 'super_admin'
    ):
        return True
    if not getattr(current_user, 'is_authenticated', False) or farm_id is None:
        return False
    cursor.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM user_farm_access WHERE user_id = %s AND farm_id = %s
        ) OR EXISTS (
            SELECT 1 FROM user_organization_access AS uoa
            JOIN farms AS f ON f.organization_id = uoa.organization_id
            WHERE uoa.user_id = %s AND f.id = %s
        ) AS allowed
        """,
        (current_user.id, farm_id, current_user.id, farm_id),
    )
    return bool(cursor.fetchone()['allowed'])


def _assert_farm_access(cursor, farm_id):
    if not _farm_access_allowed(cursor, farm_id):
        raise ProductionEventPermissionError(
            "You are not authorized for this farm's customer orders"
        )


def _farm_visibility_clause(alias):
    if app.config.get('LOGIN_DISABLED') or (
        getattr(current_user, 'is_authenticated', False)
        and current_user.role == 'super_admin'
    ):
        return 'TRUE', ()
    if not getattr(current_user, 'is_authenticated', False):
        return 'FALSE', ()
    return (
        f"""
        (EXISTS (SELECT 1 FROM user_farm_access AS ufa
                 WHERE ufa.user_id = %s AND ufa.farm_id = {alias}.farm_id)
         OR EXISTS (SELECT 1 FROM user_organization_access AS uoa
                    JOIN farms AS vf ON vf.organization_id = uoa.organization_id
                    WHERE uoa.user_id = %s AND vf.id = {alias}.farm_id))
        """,
        (current_user.id, current_user.id),
    )


def _order_row(cursor, order_ref, *, for_update=False):
    lookup_id = int(order_ref) if str(order_ref).isdigit() else -1
    cursor.execute(
        f"""
        SELECT o.*, c.name AS customer_name, c.contact AS customer_contact,
               f.name AS farm_name
        FROM customer_orders AS o
        JOIN customers AS c ON c.id = o.customer_id
        JOIN farms AS f ON f.id = o.farm_id
        WHERE o.id = %s OR UPPER(o.business_id) = UPPER(%s)
        {'FOR UPDATE OF o' if for_update else ''}
        """,
        (lookup_id, str(order_ref)),
    )
    order = cursor.fetchone()
    if not order:
        raise RecordNotFoundError('Customer order not found')
    _assert_farm_access(cursor, order['farm_id'])
    return dict(order)


def _order_detail(cursor, order):
    order_id = order['id']
    cursor.execute(
        """
        SELECT id, line_no, product_type, quantity_kg, unit, notes
        FROM customer_order_lines WHERE order_id = %s ORDER BY line_no
        """,
        (order_id,),
    )
    lines = [dict(row) for row in cursor.fetchall()]
    cursor.execute(
        f"""
        WITH {ALLOCATION_STATE_CTE}
        SELECT s.id, s.order_line_id, s.product_lot_id, s.location_id,
               s.quantity_kg, s.released_kg, s.dispatched_kg,
               s.quantity_kg - s.released_kg - s.dispatched_kg AS outstanding_kg,
               a.created_at, a.created_by, a.released_at, a.release_reason,
               pl.business_id AS product_lot_business_id, pl.product_type,
               il.location_code, il.name AS location_name
        FROM allocation_state AS s
        JOIN order_allocations AS a ON a.id = s.id
        JOIN customer_order_lines AS l ON l.id = s.order_line_id
        JOIN product_lots AS pl ON pl.id = s.product_lot_id
        JOIN inventory_locations AS il ON il.id = s.location_id
        WHERE l.order_id = %s
        ORDER BY s.id
        """,
        (order_id,),
    )
    allocations = [dict(row) for row in cursor.fetchall()]
    cursor.execute(
        """
        SELECT d.id, d.business_id, d.status, d.dispatched_at, d.delivered_at,
               d.received_by, d.vehicle, d.driver, d.notes, d.created_by
        FROM customer_deliveries AS d WHERE d.order_id = %s ORDER BY d.id
        """,
        (order_id,),
    )
    deliveries = [dict(row) for row in cursor.fetchall()]
    if deliveries:
        cursor.execute(
            """
            SELECT dl.delivery_id, dl.allocation_id, dl.quantity_kg,
                   im.business_id AS movement_business_id,
                   pl.business_id AS product_lot_business_id,
                   il.location_code
            FROM customer_delivery_lines AS dl
            JOIN order_allocations AS a ON a.id = dl.allocation_id
            JOIN product_lots AS pl ON pl.id = a.product_lot_id
            JOIN inventory_locations AS il ON il.id = a.location_id
            JOIN inventory_movements AS im ON im.id = dl.inventory_movement_id
            WHERE dl.delivery_id = ANY(%s)
            ORDER BY dl.id
            """,
            ([d['id'] for d in deliveries],),
        )
        delivery_lines = {}
        for row in cursor.fetchall():
            delivery_lines.setdefault(row['delivery_id'], []).append(dict(row))
        for delivery in deliveries:
            delivery['lines'] = delivery_lines.get(delivery['id'], [])
            delivery['quantity_kg'] = sum(
                (Decimal(str(line['quantity_kg'])) for line in delivery['lines']), Decimal('0')
            )

    zero = Decimal('0')
    for line in lines:
        mine = [a for a in allocations if a['order_line_id'] == line['id']]
        line['allocations'] = mine
        line['outstanding_allocated_kg'] = sum((Decimal(str(a['outstanding_kg'])) for a in mine), zero)
        line['dispatched_kg'] = sum((Decimal(str(a['dispatched_kg'])) for a in mine), zero)
        line['remaining_to_allocate_kg'] = max(
            Decimal(str(line['quantity_kg'])) - line['dispatched_kg'] - line['outstanding_allocated_kg'],
            zero,
        )
    totals = {
        'ordered_kg': sum((Decimal(str(line['quantity_kg'])) for line in lines), zero),
        'allocated_kg': sum((line['outstanding_allocated_kg'] for line in lines), zero),
        'dispatched_kg': sum((line['dispatched_kg'] for line in lines), zero),
        'delivered_kg': sum(
            (d['quantity_kg'] for d in deliveries if d['status'] == 'DELIVERED'), zero
        ),
    }
    return _jsonable({
        **order,
        'lines': lines,
        'allocations': allocations,
        'deliveries': deliveries,
        'totals': totals,
    })


def _order_line(cursor, order_id, line_ref):
    line_id = _parse_positive_integer(line_ref, 'order_line_id')
    cursor.execute(
        "SELECT * FROM customer_order_lines WHERE id = %s AND order_id = %s",
        (line_id, order_id),
    )
    line = cursor.fetchone()
    if not line:
        raise ValueError('The order line does not belong to this order')
    return dict(line)


def _line_commitments(cursor, line_id):
    """Dispatched plus still-reserved quantity for one order line."""
    cursor.execute(
        f"""
        WITH {ALLOCATION_STATE_CTE}
        SELECT COALESCE(SUM(quantity_kg - released_kg), 0) AS committed
        FROM allocation_state WHERE order_line_id = %s
        """,
        (line_id,),
    )
    return Decimal(str(cursor.fetchone()['committed']))


def _refresh_order_status(cursor, order_id):
    cursor.execute(
        f"""
        WITH {ALLOCATION_STATE_CTE}
        SELECT bool_and(
            COALESCE((SELECT SUM(s.dispatched_kg) FROM allocation_state AS s
                      WHERE s.order_line_id = l.id), 0) >= l.quantity_kg
        ) AS fulfilled
        FROM customer_order_lines AS l WHERE l.order_id = %s
        """,
        (order_id,),
    )
    if cursor.fetchone()['fulfilled']:
        cursor.execute(
            """
            UPDATE customer_orders SET status = 'FULFILLED', updated_at = CURRENT_TIMESTAMP
            WHERE id = %s AND status = 'OPEN'
            """,
            (order_id,),
        )


def _optional_date(data, field):
    value = data.get(field)
    if value in (None, ''):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise ValueError(f'{field} must be a valid date (YYYY-MM-DD)')


def _create_order(data):
    customer_id = _parse_positive_integer(data.get('customer_id'), 'customer_id')
    farm_id = _parse_positive_integer(data.get('farm_id'), 'farm_id')
    order_date = _optional_date(data, 'order_date') or date.today()
    requested = _optional_date(data, 'requested_delivery_date')
    if requested and requested < order_date:
        raise ValueError('requested_delivery_date cannot be before the order date')
    lines = data.get('lines')
    if not isinstance(lines, list) or not lines:
        raise ValueError('Add at least one order line')
    if len(lines) > 50:
        raise ValueError('An order can have at most 50 lines')
    parsed_lines = []
    for index, line in enumerate(lines, start=1):
        if not isinstance(line, dict):
            raise ValueError('Each order line must be an object')
        product_type = str(line.get('product_type') or '').strip()
        if not product_type or len(product_type) > 50:
            raise ValueError(f'Line {index}: product_type is required (max 50 characters)')
        if str(line.get('unit') or 'kg').strip().lower() != 'kg':
            raise ValueError(f'Line {index}: quantities must be in kg')
        parsed_lines.append((
            index, product_type,
            _parse_chain_quantity(line.get('quantity_kg'), f'Line {index} quantity_kg'),
            _optional_text(line, 'notes', 500),
        ))
    customer_reference = _optional_text(data, 'customer_reference', 60)
    notes = _optional_text(data, 'notes', 2000)
    actor, actor_user_id = _production_actor(data)
    with db.transaction() as cursor:
        cursor.execute("SELECT status FROM farms WHERE id = %s", (farm_id,))
        farm = cursor.fetchone()
        if not farm or farm['status'] != 'active':
            raise ValueError('Select an active farm')
        _assert_farm_access(cursor, farm_id)
        cursor.execute("SELECT id FROM customers WHERE id = %s", (customer_id,))
        if not cursor.fetchone():
            raise ValueError('Customer not found')
        cursor.execute(
            """
            INSERT INTO customer_orders (
                customer_id, farm_id, order_date, requested_delivery_date,
                customer_reference, notes, created_by, created_by_user_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (customer_id, farm_id, order_date, requested, customer_reference, notes,
             actor, actor_user_id),
        )
        order_id = cursor.fetchone()['id']
        for line_no, product_type, quantity, line_notes in parsed_lines:
            cursor.execute(
                """
                INSERT INTO customer_order_lines (order_id, line_no, product_type, quantity_kg, notes)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (order_id, line_no, product_type, quantity, line_notes),
            )
        return _order_detail(cursor, _order_row(cursor, order_id))


def _available_stock_for_line(cursor, order, line):
    """Free, QC-released stock of the line's product on the order's farm."""
    visibility, params = _scope_visibility_clause('il')
    cursor.execute(
        f"""
        WITH {INVENTORY_LEDGER_CTE}, {ALLOCATION_STATE_CTE},
        balances AS (
            SELECT ledger.product_lot_id, ledger.location_id,
                   SUM(ledger.delta) AS on_hand_kg
            FROM ledger GROUP BY ledger.product_lot_id, ledger.location_id
        )
        SELECT pl.id AS product_lot_id, pl.business_id AS product_lot_business_id,
               pl.product_type, pl.production_date,
               il.id AS location_id, il.location_code, il.name AS location_name,
               fa.name AS facility_name, b.on_hand_kg,
               COALESCE((
                   SELECT SUM(s.quantity_kg - s.released_kg - s.dispatched_kg)
                   FROM allocation_state AS s
                   WHERE s.product_lot_id = pl.id AND s.location_id = il.id
               ), 0) AS reserved_kg
        FROM balances AS b
        JOIN product_lots AS pl ON pl.id = b.product_lot_id
        JOIN inventory_locations AS il ON il.id = b.location_id
        JOIN facilities AS fa ON fa.id = il.facility_id
        WHERE pl.farm_id = %s AND LOWER(pl.product_type) = LOWER(%s)
          AND il.status = 'active' AND {PRODUCT_LOT_RELEASABLE_SQL}
          AND {visibility}
        ORDER BY pl.production_date, pl.id, il.name
        """,
        (order['farm_id'], line['product_type'], *params),
    )
    rows = []
    for row in cursor.fetchall():
        row = dict(row)
        row['free_kg'] = Decimal(str(row['on_hand_kg'])) - Decimal(str(row['reserved_kg']))
        if row['free_kg'] > 0:
            rows.append(row)
    return rows


def _allocate(order_ref, data):
    quantity = _parse_chain_quantity(data.get('quantity_kg'), 'quantity_kg')
    with db.transaction() as cursor:
        order = _order_row(cursor, order_ref, for_update=True)
        if order['status'] != 'OPEN':
            raise ValueError(f"Order {order['business_id']} is {order['status']} and cannot be allocated")
        line = _order_line(cursor, order['id'], data.get('order_line_id'))
        for field in ('product_lot_id', 'location_id'):
            if data.get(field) in (None, ''):
                raise ValueError(f'{field} is required')
        lot = _inventory_lot_row(cursor, data.get('product_lot_id'))
        location = _inventory_location_row(cursor, data.get('location_id'), 'allocation')
        if lot['farm_id'] != order['farm_id'] or location['farm_id'] != order['farm_id']:
            raise ValueError('Allocated stock must be on the same farm as the order')
        if lot['product_type'].lower() != line['product_type'].lower():
            raise ValueError(
                f"Product Lot {lot['business_id']} is {lot['product_type']}, "
                f"but the order line is for {line['product_type']}"
            )
        if not lot['releasable']:
            raise ValueError(f"Product Lot {lot['business_id']} is blocked by QC and cannot be allocated")
        remaining = Decimal(str(line['quantity_kg'])) - _line_commitments(cursor, line['id'])
        if quantity > remaining:
            raise ValueError(f'Only {max(remaining, Decimal("0")):.3f} kg of this order line is left to allocate')
        free = _location_balance(cursor, lot['id'], location['id']) - _reserved_kg(
            cursor, lot['id'], location['id']
        )
        if quantity > free:
            raise ValueError(
                f"Only {max(free, Decimal('0')):.3f} kg of {lot['business_id']} at "
                f"{location['location_code']} is free to allocate"
            )
        actor, actor_user_id = _production_actor(data)
        cursor.execute(
            """
            INSERT INTO order_allocations (
                order_line_id, product_lot_id, location_id, quantity_kg,
                created_by, created_by_user_id
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (line['id'], lot['id'], location['id'], quantity, actor, actor_user_id),
        )
        cursor.execute(
            "UPDATE customer_orders SET updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (order['id'],),
        )
        return _order_detail(cursor, order)


def _release_outstanding(cursor, allocation_ids, reason):
    if not allocation_ids:
        return
    cursor.execute(
        f"""
        WITH {ALLOCATION_STATE_CTE}
        UPDATE order_allocations AS a
        SET released_kg = a.released_kg + (s.quantity_kg - s.released_kg - s.dispatched_kg),
            released_at = CURRENT_TIMESTAMP,
            release_reason = %s
        FROM allocation_state AS s
        WHERE s.id = a.id AND a.id = ANY(%s)
          AND s.quantity_kg - s.released_kg - s.dispatched_kg > 0
        """,
        (reason, allocation_ids),
    )


def _release_allocation(order_ref, allocation_id, data):
    reason = _optional_text(data, 'reason', 500)
    if not reason:
        raise ValueError('A reason is required to release an allocation')
    with db.transaction() as cursor:
        order = _order_row(cursor, order_ref, for_update=True)
        cursor.execute(
            f"""
            WITH {ALLOCATION_STATE_CTE}
            SELECT s.*, s.quantity_kg - s.released_kg - s.dispatched_kg AS outstanding
            FROM allocation_state AS s
            JOIN customer_order_lines AS l ON l.id = s.order_line_id
            WHERE s.id = %s AND l.order_id = %s
            """,
            (allocation_id, order['id']),
        )
        allocation = cursor.fetchone()
        if not allocation:
            raise RecordNotFoundError('Allocation not found on this order')
        if allocation['outstanding'] <= 0:
            raise ValueError('This allocation has nothing left to release')
        _release_outstanding(cursor, [allocation['id']], reason)
        return _order_detail(cursor, order)


def _cancel_order(order_ref, data):
    reason = _optional_text(data, 'reason', 500)
    if not reason:
        raise ValueError('A reason is required to cancel an order')
    with db.transaction() as cursor:
        order = _order_row(cursor, order_ref, for_update=True)
        if order['status'] != 'OPEN':
            raise ValueError(f"Order {order['business_id']} is already {order['status']}")
        cursor.execute(
            "SELECT 1 FROM customer_deliveries WHERE order_id = %s LIMIT 1", (order['id'],)
        )
        if cursor.fetchone():
            raise ValueError(
                'This order already has dispatched deliveries and cannot be cancelled; '
                'release the remaining allocations instead'
            )
        cursor.execute(
            """
            SELECT a.id FROM order_allocations AS a
            JOIN customer_order_lines AS l ON l.id = a.order_line_id
            WHERE l.order_id = %s
            """,
            (order['id'],),
        )
        _release_outstanding(cursor, [row['id'] for row in cursor.fetchall()], f'Order cancelled: {reason}')
        cursor.execute(
            """
            UPDATE customer_orders
            SET status = 'CANCELLED', cancel_reason = %s, cancelled_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (reason, order['id']),
        )
        return _order_detail(cursor, _order_row(cursor, order['id']))


def _dispatch(order_ref, data):
    requested = data.get('lines')
    if not isinstance(requested, list) or not requested:
        raise ValueError('Choose at least one allocation to dispatch')
    parsed = {}
    for item in requested:
        if not isinstance(item, dict):
            raise ValueError('Each dispatch line must be an object')
        allocation_id = _parse_positive_integer(item.get('allocation_id'), 'allocation_id')
        if allocation_id in parsed:
            raise ValueError('Each allocation can appear only once per delivery')
        parsed[allocation_id] = _parse_chain_quantity(item.get('quantity_kg'), 'quantity_kg')
    vehicle = _optional_text(data, 'vehicle', 60)
    driver = _optional_text(data, 'driver', 100)
    notes = _optional_text(data, 'notes', 2000)
    dispatched_at = None
    if data.get('dispatched_at') not in (None, ''):
        dispatched_at = _event_occurred_at({'occurred_at': data['dispatched_at']}, ())
    actor, actor_user_id = _production_actor(data)

    with db.transaction() as cursor:
        order = _order_row(cursor, order_ref, for_update=True)
        if order['status'] != 'OPEN':
            raise ValueError(f"Order {order['business_id']} is {order['status']} and cannot be dispatched")
        cursor.execute(
            f"""
            WITH {ALLOCATION_STATE_CTE}
            SELECT s.*, s.quantity_kg - s.released_kg - s.dispatched_kg AS outstanding
            FROM allocation_state AS s
            JOIN customer_order_lines AS l ON l.id = s.order_line_id
            WHERE l.order_id = %s AND s.id = ANY(%s)
            ORDER BY s.product_lot_id, s.id
            """,
            (order['id'], list(parsed)),
        )
        allocations = {row['id']: dict(row) for row in cursor.fetchall()}
        missing = set(parsed) - set(allocations)
        if missing:
            raise ValueError('One or more allocations do not belong to this order')

        cursor.execute(
            """
            INSERT INTO customer_deliveries (
                order_id, dispatched_at, vehicle, driver, notes, created_by, created_by_user_id
            ) VALUES (%s, COALESCE(%s, CURRENT_TIMESTAMP), %s, %s, %s, %s, %s)
            RETURNING id, business_id
            """,
            (order['id'], dispatched_at, vehicle, driver, notes, actor, actor_user_id),
        )
        delivery = cursor.fetchone()
        # Lock lots in a stable order so concurrent dispatches cannot deadlock.
        for allocation_id in sorted(allocations, key=lambda key: (allocations[key]['product_lot_id'], key)):
            allocation = allocations[allocation_id]
            quantity = parsed[allocation_id]
            lot = _inventory_lot_row(cursor, allocation['product_lot_id'])
            if not lot['releasable']:
                raise ValueError(f"Product Lot {lot['business_id']} is blocked by QC and cannot be dispatched")
            location = _inventory_location_row(cursor, allocation['location_id'], 'dispatch')
            if quantity > Decimal(str(allocation['outstanding'])):
                raise ValueError(
                    f"Only {Decimal(str(allocation['outstanding'])):.3f} kg of the "
                    f"{lot['business_id']} allocation is left to dispatch"
                )
            on_hand = _location_balance(cursor, lot['id'], location['id'])
            if quantity > on_hand:
                raise ValueError(
                    f"Only {on_hand:.3f} kg of {lot['business_id']} is at {location['location_code']}"
                )
            movement = _insert_inventory_movement(
                cursor, lot, 'DISPATCH', quantity, data,
                from_location=location, occurred_at=dispatched_at,
                notes=f"{delivery['business_id']} for {order['business_id']}",
                reference_type='customer_delivery', reference_id=delivery['id'],
            )
            cursor.execute(
                """
                INSERT INTO customer_delivery_lines (
                    delivery_id, allocation_id, quantity_kg, inventory_movement_id
                ) VALUES (%s, %s, %s, %s)
                """,
                (delivery['id'], allocation_id, quantity, movement['id']),
            )
        _refresh_order_status(cursor, order['id'])
        detail = _order_detail(cursor, _order_row(cursor, order['id']))
        detail['created_delivery'] = delivery['business_id']
        return detail


def _confirm_delivery(delivery_ref, data):
    received_by = _optional_text(data, 'received_by', 100)
    if not received_by:
        raise ValueError('received_by is required to confirm a delivery')
    delivered_at = None
    if data.get('delivered_at') not in (None, ''):
        delivered_at = _event_occurred_at({'occurred_at': data['delivered_at']}, ())
    lookup_id = int(delivery_ref) if str(delivery_ref).isdigit() else -1
    with db.transaction() as cursor:
        cursor.execute(
            """
            SELECT id, order_id, status, dispatched_at FROM customer_deliveries
            WHERE id = %s OR UPPER(business_id) = UPPER(%s)
            FOR UPDATE
            """,
            (lookup_id, str(delivery_ref)),
        )
        delivery = cursor.fetchone()
        if not delivery:
            raise RecordNotFoundError('Delivery not found')
        order = _order_row(cursor, delivery['order_id'])
        if delivery['status'] != 'DISPATCHED':
            raise InventoryConflictError('This delivery has already been confirmed')
        cursor.execute(
            """
            UPDATE customer_deliveries
            SET status = 'DELIVERED', received_by = %s,
                delivered_at = COALESCE(%s, CURRENT_TIMESTAMP)
            WHERE id = %s AND COALESCE(%s, CURRENT_TIMESTAMP) >= dispatched_at
            RETURNING id
            """,
            (received_by, delivered_at, delivery['id'], delivered_at),
        )
        if not cursor.fetchone():
            raise ValueError('delivered_at cannot be before the dispatch time')
        return _order_detail(cursor, order)


def _order_response(handler, *args, status=200):
    try:
        return jsonify({'success': True, 'data': handler(*args)}), status
    except ProductionEventPermissionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 403
    except RecordNotFoundError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 404
    except InventoryConflictError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 409
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception:
        logger.exception('Error processing customer order request')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/api/orders', methods=['POST'])
@login_required
def create_customer_order():
    return _order_response(_create_order, normalize_keys(request.get_json() or {}), status=201)


@app.route('/api/orders', methods=['GET'])
@login_required
def list_customer_orders():
    def handler():
        visibility, params = _farm_visibility_clause('o')
        filters = [visibility]
        filter_params = list(params)
        status = str(request.args.get('status') or '').strip().upper()
        if status:
            if status not in {'OPEN', 'FULFILLED', 'CANCELLED'}:
                raise ValueError('Unknown order status')
            filters.append('o.status = %s')
            filter_params.append(status)
        if request.args.get('farm_id') not in (None, ''):
            filters.append('o.farm_id = %s')
            filter_params.append(_parse_positive_integer(request.args['farm_id'], 'farm_id'))
        rows = db.fetch_all(
            f"""
            WITH {ALLOCATION_STATE_CTE}
            SELECT o.id, o.business_id, o.status, o.order_date,
                   o.requested_delivery_date, o.customer_reference,
                   c.name AS customer_name, f.name AS farm_name, o.farm_id,
                   (SELECT SUM(l.quantity_kg) FROM customer_order_lines AS l
                     WHERE l.order_id = o.id) AS ordered_kg,
                   COALESCE((SELECT SUM(s.dispatched_kg) FROM allocation_state AS s
                     JOIN customer_order_lines AS l ON l.id = s.order_line_id
                     WHERE l.order_id = o.id), 0) AS dispatched_kg,
                   COALESCE((SELECT SUM(s.quantity_kg - s.released_kg - s.dispatched_kg)
                     FROM allocation_state AS s
                     JOIN customer_order_lines AS l ON l.id = s.order_line_id
                     WHERE l.order_id = o.id), 0) AS allocated_kg
            FROM customer_orders AS o
            JOIN customers AS c ON c.id = o.customer_id
            JOIN farms AS f ON f.id = o.farm_id
            WHERE {' AND '.join(filters)}
            ORDER BY o.order_date DESC, o.id DESC
            LIMIT 500
            """,
            tuple(filter_params),
        )
        return _jsonable(rows)
    return _order_response(handler)


@app.route('/api/orders/<string:order_ref>', methods=['GET'])
@login_required
def get_customer_order(order_ref):
    def handler():
        with db.transaction() as cursor:
            return _order_detail(cursor, _order_row(cursor, order_ref))
    return _order_response(handler)


@app.route('/api/orders/<string:order_ref>/available-stock', methods=['GET'])
@login_required
def get_order_available_stock(order_ref):
    def handler():
        with db.transaction() as cursor:
            order = _order_row(cursor, order_ref)
            line = _order_line(cursor, order['id'], request.args.get('line_id'))
            return _jsonable(_available_stock_for_line(cursor, order, line))
    return _order_response(handler)


@app.route('/api/orders/<string:order_ref>/allocations', methods=['POST'])
@login_required
def allocate_customer_order(order_ref):
    return _order_response(_allocate, order_ref, normalize_keys(request.get_json() or {}), status=201)


@app.route('/api/orders/<string:order_ref>/allocations/<int:allocation_id>/release', methods=['POST'])
@login_required
def release_order_allocation(order_ref, allocation_id):
    return _order_response(
        _release_allocation, order_ref, allocation_id, normalize_keys(request.get_json() or {})
    )


@app.route('/api/orders/<string:order_ref>/cancel', methods=['POST'])
@login_required
def cancel_customer_order(order_ref):
    return _order_response(_cancel_order, order_ref, normalize_keys(request.get_json() or {}))


@app.route('/api/orders/<string:order_ref>/deliveries', methods=['POST'])
@login_required
def dispatch_customer_order(order_ref):
    return _order_response(_dispatch, order_ref, normalize_keys(request.get_json() or {}), status=201)


@app.route('/api/deliveries/<string:delivery_ref>/confirm', methods=['POST'])
@login_required
def confirm_customer_delivery(delivery_ref):
    return _order_response(_confirm_delivery, delivery_ref, normalize_keys(request.get_json() or {}))


@app.route('/orders')
@login_required
def orders_page():
    return render_template('orders.html')


# ---- Operational alerts ----------------------------------------------------
#
# Every alert is derived from transactional records by a rule below.  Rules
# only read data; _sync_alerts turns their candidates into stored alerts so
# people can acknowledge or snooze them, and resolves alerts whose condition
# no longer holds.  Thresholds are deliberately few and documented here.

ALERT_SEVERITY_RANK = {'info': 0, 'warning': 1, 'critical': 2}
ALERT_SYNC_INTERVAL = timedelta(seconds=60)
ALERT_FORCE_INTERVAL = timedelta(seconds=10)
HARVEST_DUE_SOON = timedelta(days=3)       # info before the expected harvest
LATE_ESCALATION_DAYS = 3                    # warning becomes critical after this
QC_PENDING_LIMIT = timedelta(hours=24)      # QC should be decided within a day
DELIVERY_CONFIRM_LIMIT = timedelta(hours=48)
ALERT_MAX_SNOOZE_HOURS = 14 * 24


def _alert(rule, severity, title, message, entity_type, entity_id, *, ref=None,
           href=None, farm_id=None, site_id=None, facility_id=None, details=None):
    return {
        'alert_key': f'{rule}:{entity_type}:{entity_id}',
        'rule': rule, 'severity': severity, 'title': title, 'message': message,
        'entity_type': entity_type, 'entity_id': entity_id, 'entity_ref': ref,
        'href': href, 'farm_id': farm_id, 'site_id': site_id,
        'facility_id': facility_id, 'details': details or {},
    }


def _days(value):
    return f"{value} day{'s' if value != 1 else ''}"


def _alert_candidates(cursor):
    """Evaluate every rule against current data; returns {alert_key: alert}."""
    found = []
    now = datetime.now(timezone.utc)

    # Production batches: harvest overdue / due soon (no harvest recorded yet).
    cursor.execute(
        """
        SELECT pb.id, pb.business_id, UPPER(pb.status) AS status,
               pb.farm_id, pb.site_id, pb.facility_id, pb.expected_harvest_at
        FROM production_batches AS pb
        WHERE pb.expected_harvest_at IS NOT NULL
          AND UPPER(pb.status) NOT IN ('HARVESTED', 'COMPLETED', 'CANCELLED')
          AND pb.expected_harvest_at < now() + %s
          AND NOT EXISTS (
              SELECT 1 FROM production_events AS pe
              WHERE pe.production_batch_id = pb.id
                AND pe.event_type = 'harvest' AND pe.status = 'recorded'
          )
        """,
        (HARVEST_DUE_SOON,),
    )
    for row in cursor.fetchall():
        scope = dict(farm_id=row['farm_id'], site_id=row['site_id'], facility_id=row['facility_id'])
        href = f"/batch-360?ref={row['business_id']}"
        expected = row['expected_harvest_at']
        if expected < now:
            late = (now - expected).days
            found.append(_alert(
                'harvest_overdue', 'critical' if late >= LATE_ESCALATION_DAYS else 'warning',
                f"Harvest overdue · {row['business_id']}",
                f"Expected {expected:%d %b %Y}; no harvest recorded"
                + (f" ({_days(late)} late)" if late else '') + f". Status {row['status']}.",
                'production_batch', row['id'], ref=row['business_id'], href=href,
                details={'expected_harvest_at': expected.isoformat()}, **scope,
            ))
        else:
            found.append(_alert(
                'harvest_due', 'info', f"Harvest due soon · {row['business_id']}",
                f"Expected harvest {expected:%d %b %Y}. Status {row['status']}.",
                'production_batch', row['id'], ref=row['business_id'], href=href,
                details={'expected_harvest_at': expected.isoformat()}, **scope,
            ))

    # Production batches flagged HEALTH_ALERT.
    cursor.execute(
        """
        SELECT id, business_id, farm_id, site_id, facility_id
        FROM production_batches WHERE UPPER(status) = 'HEALTH_ALERT'
        """
    )
    for row in cursor.fetchall():
        found.append(_alert(
            'batch_health_alert', 'critical', f"Batch in health alert · {row['business_id']}",
            'The batch status is HEALTH_ALERT. Record the intervention and return it to production.',
            'production_batch', row['id'], ref=row['business_id'],
            href=f"/batch-360?ref={row['business_id']}",
            farm_id=row['farm_id'], site_id=row['site_id'], facility_id=row['facility_id'],
        ))

    # Open health issues that are severe or past their follow-up date.
    cursor.execute(
        """
        SELECT pe.id, pe.event_code, pb.id AS batch_id, pb.business_id,
               pe.farm_id, pe.site_id, pe.facility_id,
               he.severity, he.status, he.observed_issue, he.follow_up_date
        FROM health_events AS he
        JOIN production_events AS pe ON pe.id = he.production_event_id
        JOIN production_batches AS pb ON pb.id = pe.production_batch_id
        WHERE pe.status = 'recorded' AND he.status IN ('open', 'follow_up')
          AND UPPER(pb.status) NOT IN ('COMPLETED', 'CANCELLED')
          AND (he.severity IN ('high', 'critical')
               OR (he.follow_up_date IS NOT NULL AND he.follow_up_date < CURRENT_DATE))
        """
    )
    for row in cursor.fetchall():
        overdue = row['follow_up_date'] is not None and row['follow_up_date'] < now.date()
        found.append(_alert(
            'health_issue_open', 'critical' if row['severity'] == 'critical' else 'warning',
            f"Health issue open · {row['business_id']}",
            f"{row['severity'].title()} severity: {row['observed_issue']}"
            + (f". Follow-up was due {row['follow_up_date']:%d %b %Y}." if overdue else '.'),
            'production_event', row['id'], ref=row['event_code'],
            href=f"/batch-360?ref={row['business_id']}",
            farm_id=row['farm_id'], site_id=row['site_id'], facility_id=row['facility_id'],
            details={'production_batch_id': row['batch_id']},
        ))

    # Drying batches awaiting QC: failed/rejected, or pending too long.
    cursor.execute(
        """
        SELECT db.id, COALESCE(db.business_id, db.batch_code, db.batch_id) AS ref,
               db.farm_id, db.site_id, db.facility_id,
               COALESCE((
                   SELECT MAX(h.changed_at) FROM drying_batch_status_history AS h
                   WHERE h.drying_batch_id = db.id AND h.new_status = 'QC_PENDING'
               ), db.updated_at) AS pending_since,
               EXISTS (
                   SELECT 1 FROM drying_outputs AS o
                   WHERE o.drying_batch_id = db.id AND (
                       (SELECT qc.status FROM quality_checks AS qc
                         WHERE qc.drying_output_id = o.id ORDER BY qc.id DESC LIMIT 1) = 'failed'
                       OR (SELECT qa.decision FROM quality_approvals AS qa
                           JOIN quality_checks AS qc ON qc.id = qa.quality_check_id
                           WHERE qc.drying_output_id = o.id ORDER BY qa.id DESC LIMIT 1) = 'rejected'
                   )
               ) OR (
                   SELECT qc.status FROM quality_checks AS qc
                   WHERE qc.drying_batch_id = db.id AND qc.drying_output_id IS NULL
                   ORDER BY qc.id DESC LIMIT 1
               ) = 'failed' AS failed
        FROM drying_batches AS db
        WHERE UPPER(db.status) = 'QC_PENDING'
        """
    )
    for row in cursor.fetchall():
        scope = dict(farm_id=row['farm_id'], site_id=row['site_id'], facility_id=row['facility_id'])
        href = f"/traceability?ref={row['ref']}&type=drying_batch"
        if row['failed']:
            found.append(_alert(
                'qc_failed', 'critical', f"QC failed · {row['ref']}",
                'The latest quality check failed or was rejected. Decide whether to rework or dispose of the output.',
                'drying_batch', row['id'], ref=row['ref'], href=href, **scope,
            ))
        elif row['pending_since'] and now - row['pending_since'] > QC_PENDING_LIMIT:
            hours = int((now - row['pending_since']).total_seconds() // 3600)
            found.append(_alert(
                'qc_pending', 'warning', f"QC decision pending · {row['ref']}",
                f'Waiting for a QC decision for {hours} hours.',
                'drying_batch', row['id'], ref=row['ref'], href=href, **scope,
            ))

    # Stock on hand from lots whose QC release is no longer valid.
    cursor.execute(
        f"""
        WITH {INVENTORY_LEDGER_CTE}
        SELECT pl.id, pl.business_id, pl.farm_id, batch.site_id, batch.facility_id,
               SUM(ledger.delta) AS on_hand_kg
        FROM ledger
        JOIN product_lots AS pl ON pl.id = ledger.product_lot_id
        JOIN drying_outputs AS output ON output.id = pl.drying_output_id
        JOIN drying_batches AS batch ON batch.id = output.drying_batch_id
        WHERE NOT {PRODUCT_LOT_RELEASABLE_SQL}
        GROUP BY pl.id, batch.site_id, batch.facility_id
        HAVING SUM(ledger.delta) > 0
        """
    )
    for row in cursor.fetchall():
        found.append(_alert(
            'quarantined_stock', 'critical', f"Blocked stock on hand · {row['business_id']}",
            f"{_kg_text(row['on_hand_kg'])} is in stock but its QC release was revoked. "
            'It cannot be moved or dispatched; write it off or re-approve it.',
            'product_lot', row['id'], ref=row['business_id'],
            href=f"/product-lot?ref={row['business_id']}",
            farm_id=row['farm_id'], site_id=row['site_id'], facility_id=row['facility_id'],
        ))

    # Free QC-released stock below the farm's configured minimum.
    cursor.execute(
        f"""
        WITH {INVENTORY_LEDGER_CTE}, {ALLOCATION_STATE_CTE},
        on_hand AS (
            SELECT pl.farm_id, LOWER(pl.product_type) AS product, SUM(ledger.delta) AS kg
            FROM ledger JOIN product_lots AS pl ON pl.id = ledger.product_lot_id
            WHERE {PRODUCT_LOT_RELEASABLE_SQL}
            GROUP BY 1, 2
        ),
        reserved AS (
            SELECT pl.farm_id, LOWER(pl.product_type) AS product,
                   SUM(s.quantity_kg - s.released_kg - s.dispatched_kg) AS kg
            FROM allocation_state AS s JOIN product_lots AS pl ON pl.id = s.product_lot_id
            WHERE {PRODUCT_LOT_RELEASABLE_SQL}
            GROUP BY 1, 2
        )
        SELECT t.id, t.farm_id, t.product_type, t.minimum_kg, f.name AS farm_name,
               COALESCE(o.kg, 0) - COALESCE(r.kg, 0) AS free_kg
        FROM inventory_alert_thresholds AS t
        JOIN farms AS f ON f.id = t.farm_id
        LEFT JOIN on_hand AS o ON o.farm_id = t.farm_id AND o.product = LOWER(t.product_type)
        LEFT JOIN reserved AS r ON r.farm_id = t.farm_id AND r.product = LOWER(t.product_type)
        WHERE COALESCE(o.kg, 0) - COALESCE(r.kg, 0) < t.minimum_kg
        """
    )
    for row in cursor.fetchall():
        found.append(_alert(
            'low_stock', 'critical' if row['free_kg'] <= 0 else 'warning',
            f"Low stock · {row['product_type']} at {row['farm_name']}",
            f"{_kg_text(max(row['free_kg'], 0))} free against a minimum of {_kg_text(row['minimum_kg'])}.",
            'inventory_threshold', row['id'], ref=row['product_type'], href='/product-lot',
            farm_id=row['farm_id'],
            details={'free_kg': str(row['free_kg']), 'minimum_kg': str(row['minimum_kg'])},
        ))

    # Customer orders past their requested delivery date.
    cursor.execute(
        """
        SELECT o.id, o.business_id, o.farm_id, o.requested_delivery_date,
               c.name AS customer_name, CURRENT_DATE - o.requested_delivery_date AS days_late
        FROM customer_orders AS o
        JOIN customers AS c ON c.id = o.customer_id
        WHERE o.status = 'OPEN' AND o.requested_delivery_date < CURRENT_DATE
        """
    )
    for row in cursor.fetchall():
        found.append(_alert(
            'order_overdue', 'critical' if row['days_late'] >= LATE_ESCALATION_DAYS else 'warning',
            f"Order overdue · {row['business_id']}",
            f"{row['customer_name']} requested delivery by {row['requested_delivery_date']:%d %b %Y} "
            f"({_days(row['days_late'])} ago) and the order is not fully dispatched.",
            'customer_order', row['id'], ref=row['business_id'],
            href=f"/orders?ref={row['business_id']}", farm_id=row['farm_id'],
        ))

    # Dispatched deliveries never confirmed as received.
    cursor.execute(
        """
        SELECT d.id, d.business_id, d.dispatched_at, o.business_id AS order_ref,
               o.farm_id, c.name AS customer_name
        FROM customer_deliveries AS d
        JOIN customer_orders AS o ON o.id = d.order_id
        JOIN customers AS c ON c.id = o.customer_id
        WHERE d.status = 'DISPATCHED' AND d.dispatched_at < now() - %s
        """,
        (DELIVERY_CONFIRM_LIMIT,),
    )
    for row in cursor.fetchall():
        found.append(_alert(
            'delivery_unconfirmed', 'warning', f"Delivery not confirmed · {row['business_id']}",
            f"Dispatched to {row['customer_name']} on {row['dispatched_at']:%d %b %Y} "
            'and not yet confirmed as received.',
            'customer_delivery', row['id'], ref=row['business_id'],
            href=f"/orders?ref={row['order_ref']}", farm_id=row['farm_id'],
        ))

    return {item['alert_key']: item for item in found}


def _sync_alerts(*, force=False):
    """Reconcile stored alerts with the rules and notify people.

    Returns True if the rules ran.  Notifications are written in the same
    transaction as the alert changes; queued email is sent afterwards.
    """
    ran = _sync_alerts_transaction(force=force)
    if ran:
        notifications.kick_background_delivery(db)
    return ran


def _sync_alerts_transaction(*, force=False):
    email_configured = notifications.channel_factory().configured
    with db.transaction() as cursor:
        cursor.execute(
            "SELECT pg_try_advisory_xact_lock(hashtext('operational_alert_sync')) AS locked"
        )
        if not cursor.fetchone()['locked']:
            return False  # another request is already syncing
        cursor.execute(
            "SELECT last_run_at, now() AS now FROM operational_alert_sync WHERE id = 1"
        )
        state = cursor.fetchone()
        if state['last_run_at'] is not None:
            elapsed = state['now'] - state['last_run_at']
            if elapsed < (ALERT_FORCE_INTERVAL if force else ALERT_SYNC_INTERVAL):
                return False
        candidates = _alert_candidates(cursor)
        cursor.execute(
            "SELECT * FROM operational_alerts WHERE status <> 'RESOLVED' FOR UPDATE"
        )
        active = {row['alert_key']: dict(row) for row in cursor.fetchall()}
        for key, alert in candidates.items():
            existing = active.pop(key, None)
            payload = (
                alert['severity'], alert['title'], alert['message'], alert['entity_ref'],
                alert['href'], alert['farm_id'], alert['site_id'], alert['facility_id'],
                json.dumps(alert['details'], default=str),
            )
            if existing is None:
                cursor.execute(
                    """
                    INSERT INTO operational_alerts (
                        severity, title, message, entity_ref, href, farm_id, site_id,
                        facility_id, details, alert_key, rule, entity_type, entity_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    payload + (key, alert['rule'], alert['entity_type'], alert['entity_id']),
                )
                notifications.enqueue_alert_notifications(
                    cursor, dict(cursor.fetchone()), 'alert_opened',
                    email_configured=email_configured,
                )
                continue
            status = existing['status']
            snoozed_until = existing['snoozed_until']
            snooze_ended = status == 'SNOOZED' and snoozed_until <= state['now']
            if snooze_ended:
                status = 'OPEN'
            escalated = ALERT_SEVERITY_RANK[alert['severity']] > ALERT_SEVERITY_RANK[existing['severity']]
            if escalated and status in ('ACKNOWLEDGED', 'SNOOZED'):
                status = 'OPEN'  # a worse condition needs fresh attention
            if status == 'OPEN':
                snoozed_until = None
            cursor.execute(
                """
                UPDATE operational_alerts
                SET severity = %s, title = %s, message = %s, entity_ref = %s, href = %s,
                    farm_id = %s, site_id = %s, facility_id = %s, details = %s::jsonb,
                    status = %s, snoozed_until = %s, last_detected_at = now()
                WHERE id = %s
                """,
                payload + (status, snoozed_until, existing['id']),
            )
            if escalated or snooze_ended:
                notifications.enqueue_alert_notifications(
                    cursor, {**existing, **alert, 'id': existing['id'], 'status': status},
                    'alert_escalated' if escalated else 'alert_reminder',
                    email_configured=email_configured,
                )
        for existing in active.values():
            cursor.execute(
                """
                UPDATE operational_alerts
                SET status = 'RESOLVED', resolved_at = now(),
                    resolved_reason = 'Condition cleared', snoozed_until = NULL
                WHERE id = %s
                """,
                (existing['id'],),
            )
        cursor.execute("UPDATE operational_alert_sync SET last_run_at = now() WHERE id = 1")
        return True


def _alert_visibility_clause():
    """Facility-scoped alerts follow location access; farm-level ones need farm access."""
    scope_sql, scope_params = _scope_visibility_clause('a')
    farm_sql, farm_params = _farm_visibility_clause('a')
    return (
        f"((a.facility_id IS NOT NULL AND {scope_sql}) OR (a.facility_id IS NULL AND {farm_sql}))",
        (*scope_params, *farm_params),
    )


def _alert_counts(visibility, params):
    row = db.fetch_one(
        f"""
        SELECT COUNT(*) FILTER (WHERE a.status = 'OPEN') AS open,
               COUNT(*) FILTER (WHERE a.status = 'OPEN' AND a.severity = 'critical') AS critical,
               COUNT(*) FILTER (WHERE a.status = 'OPEN' AND a.severity = 'warning') AS warning,
               COUNT(*) FILTER (WHERE a.status = 'OPEN' AND a.severity = 'info') AS info,
               COUNT(*) FILTER (WHERE a.status = 'ACKNOWLEDGED') AS acknowledged,
               COUNT(*) FILTER (WHERE a.status = 'SNOOZED') AS snoozed
        FROM operational_alerts AS a
        WHERE a.status <> 'RESOLVED' AND {visibility}
        """,
        params,
    )
    return {key: int(value or 0) for key, value in row.items()}


def _alert_response(handler, *args, status=200):
    try:
        return jsonify({'success': True, **handler(*args)}), status
    except ProductionEventPermissionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 403
    except RecordNotFoundError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 404
    except InventoryConflictError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 409
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception:
        logger.exception('Error processing alerts request')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/api/alerts', methods=['GET'])
@login_required
def list_alerts():
    def handler():
        _sync_alerts()
        visibility, params = _alert_visibility_clause()
        filters = [visibility]
        filter_params = list(params)
        view = str(request.args.get('status') or 'active').lower()
        if view == 'active':
            filters.append("a.status <> 'RESOLVED'")
        elif view == 'resolved':
            filters.append("a.status = 'RESOLVED'")
        elif view != 'all':
            raise ValueError('status must be active, resolved or all')
        severity = str(request.args.get('severity') or '').lower()
        if severity:
            if severity not in ALERT_SEVERITY_RANK:
                raise ValueError('severity must be info, warning or critical')
            filters.append('a.severity = %s')
            filter_params.append(severity)
        for field in ('farm_id', 'entity_id'):
            if request.args.get(field) not in (None, ''):
                filters.append(f'a.{field} = %s')
                filter_params.append(_parse_positive_integer(request.args[field], field))
        if request.args.get('entity_type'):
            filters.append('a.entity_type = %s')
            filter_params.append(str(request.args['entity_type'])[:40])
        rows = db.fetch_all(
            f"""
            SELECT a.id, a.rule, a.severity, a.title, a.message, a.entity_type,
                   a.entity_id, a.entity_ref, a.href, a.farm_id, a.status, a.details,
                   a.first_detected_at, a.last_detected_at, a.acknowledged_at,
                   a.acknowledged_by, a.acknowledgement_note, a.snoozed_until,
                   a.resolved_at, a.resolved_reason, f.name AS farm_name,
                   fa.name AS facility_name
            FROM operational_alerts AS a
            LEFT JOIN farms AS f ON f.id = a.farm_id
            LEFT JOIN facilities AS fa ON fa.id = a.facility_id
            WHERE {' AND '.join(filters)}
            ORDER BY (a.status = 'OPEN') DESC,
                     CASE a.severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
                     a.first_detected_at DESC
            LIMIT 500
            """,
            tuple(filter_params),
        )
        return {'data': _jsonable(rows), 'counts': _alert_counts(visibility, params)}
    return _alert_response(handler)


@app.route('/api/alerts/summary', methods=['GET'])
@login_required
def alert_summary():
    def handler():
        _sync_alerts()
        visibility, params = _alert_visibility_clause()
        return {'counts': _alert_counts(visibility, params)}
    return _alert_response(handler)


@app.route('/api/alerts/refresh', methods=['POST'])
@login_required
def refresh_alerts():
    def handler():
        ran = _sync_alerts(force=True)
        visibility, params = _alert_visibility_clause()
        return {'refreshed': ran, 'counts': _alert_counts(visibility, params)}
    return _alert_response(handler)


def _visible_alert(cursor, alert_id):
    visibility, params = _alert_visibility_clause()
    cursor.execute(
        f"SELECT a.* FROM operational_alerts AS a WHERE a.id = %s AND {visibility} FOR UPDATE",
        (alert_id, *params),
    )
    alert = cursor.fetchone()
    if not alert:
        raise RecordNotFoundError('Alert not found')
    return dict(alert)


def _acknowledge_alert(alert_id, data):
    note = _optional_text(data, 'note', 500)
    actor, actor_user_id = _production_actor(data)
    with db.transaction() as cursor:
        alert = _visible_alert(cursor, alert_id)
        if alert['status'] not in ('OPEN', 'SNOOZED'):
            raise InventoryConflictError(f"This alert is already {alert['status'].lower()}")
        cursor.execute(
            """
            UPDATE operational_alerts
            SET status = 'ACKNOWLEDGED', acknowledged_at = now(), acknowledged_by = %s,
                acknowledged_by_user_id = %s, acknowledgement_note = %s, snoozed_until = NULL
            WHERE id = %s
            RETURNING id, status, acknowledged_at, acknowledged_by, acknowledgement_note
            """,
            (actor, actor_user_id, note, alert_id),
        )
        return {'data': _jsonable(dict(cursor.fetchone()))}


def _snooze_alert(alert_id, data):
    try:
        hours = int(data.get('hours'))
    except (TypeError, ValueError):
        raise ValueError('hours must be a whole number')
    if not 1 <= hours <= ALERT_MAX_SNOOZE_HOURS:
        raise ValueError(f'hours must be between 1 and {ALERT_MAX_SNOOZE_HOURS}')
    with db.transaction() as cursor:
        alert = _visible_alert(cursor, alert_id)
        if alert['status'] == 'RESOLVED':
            raise InventoryConflictError('This alert is already resolved')
        cursor.execute(
            """
            UPDATE operational_alerts
            SET status = 'SNOOZED', snoozed_until = now() + make_interval(hours => %s)
            WHERE id = %s
            RETURNING id, status, snoozed_until
            """,
            (hours, alert_id),
        )
        return {'data': _jsonable(dict(cursor.fetchone()))}


@app.route('/api/alerts/<int:alert_id>/acknowledge', methods=['POST'])
@login_required
def acknowledge_alert(alert_id):
    return _alert_response(_acknowledge_alert, alert_id, normalize_keys(request.get_json() or {}))


@app.route('/api/alerts/<int:alert_id>/snooze', methods=['POST'])
@login_required
def snooze_alert(alert_id):
    return _alert_response(_snooze_alert, alert_id, normalize_keys(request.get_json() or {}))


@app.route('/api/alerts/thresholds', methods=['GET'])
@login_required
def list_alert_thresholds():
    def handler():
        visibility, params = _farm_visibility_clause('t')
        rows = db.fetch_all(
            f"""
            SELECT t.id, t.farm_id, f.name AS farm_name, t.product_type, t.minimum_kg,
                   t.updated_by, t.updated_at
            FROM inventory_alert_thresholds AS t
            JOIN farms AS f ON f.id = t.farm_id
            WHERE {visibility}
            ORDER BY f.name, t.product_type
            """,
            params,
        )
        return {'data': _jsonable(rows)}
    return _alert_response(handler)


@app.route('/api/alerts/thresholds', methods=['PUT'])
@login_required
@super_admin_required
def set_alert_threshold():
    def handler(data):
        farm_id = _parse_positive_integer(data.get('farm_id'), 'farm_id')
        product_type = _optional_text(data, 'product_type', 50)
        if not product_type:
            raise ValueError('product_type is required')
        minimum = _parse_chain_quantity(data.get('minimum_kg'), 'minimum_kg')
        actor, actor_user_id = _production_actor(data)
        with db.transaction() as cursor:
            cursor.execute("SELECT 1 FROM farms WHERE id = %s", (farm_id,))
            if not cursor.fetchone():
                raise ValueError('Farm not found')
            cursor.execute(
                """
                INSERT INTO inventory_alert_thresholds
                    (farm_id, product_type, minimum_kg, updated_by, updated_by_user_id)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (farm_id, product_type) DO UPDATE SET
                    minimum_kg = EXCLUDED.minimum_kg, updated_by = EXCLUDED.updated_by,
                    updated_by_user_id = EXCLUDED.updated_by_user_id,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id, farm_id, product_type, minimum_kg
                """,
                (farm_id, product_type, minimum, actor, actor_user_id),
            )
            return {'data': _jsonable(dict(cursor.fetchone()))}
    return _alert_response(handler, normalize_keys(request.get_json() or {}))


@app.route('/api/alerts/thresholds/<int:threshold_id>', methods=['DELETE'])
@login_required
@super_admin_required
def delete_alert_threshold(threshold_id):
    def handler():
        with db.transaction() as cursor:
            cursor.execute(
                "DELETE FROM inventory_alert_thresholds WHERE id = %s RETURNING id", (threshold_id,)
            )
            if not cursor.fetchone():
                raise RecordNotFoundError('Threshold not found')
        return {'data': {'id': threshold_id}}
    return _alert_response(handler)


def _notification_user_id():
    if not getattr(current_user, 'is_authenticated', False):
        raise ProductionEventPermissionError('Sign in to see your notifications')
    return int(current_user.id)


@app.route('/api/notifications', methods=['GET'])
@login_required
def list_notifications():
    def handler():
        user_id = _notification_user_id()
        try:
            limit = min(max(int(request.args.get('limit', 20)), 1), 100)
        except ValueError:
            raise ValueError('limit must be a number')
        unread_only = request.args.get('unread') in ('1', 'true')
        rows = db.fetch_all(
            f"""
            SELECT n.id, n.kind, n.severity, n.title, n.body, n.href, n.created_at,
                   n.read_at, n.alert_id, a.status AS alert_status
            FROM notifications AS n
            LEFT JOIN operational_alerts AS a ON a.id = n.alert_id
            WHERE n.user_id = %s {'AND n.read_at IS NULL' if unread_only else ''}
            ORDER BY n.created_at DESC, n.id DESC
            LIMIT %s
            """,
            (user_id, limit),
        )
        unread = db.fetch_one(
            "SELECT COUNT(*) AS n FROM notifications WHERE user_id = %s AND read_at IS NULL",
            (user_id,),
        )['n']
        return {'data': _jsonable(rows), 'unread': unread}
    return _alert_response(handler)


@app.route('/api/notifications/unread-count', methods=['GET'])
@login_required
def unread_notification_count():
    def handler():
        user_id = _notification_user_id()
        try:
            _sync_alerts()  # throttled; keeps the bell current without a scheduler
        except Exception:
            logger.exception('Alert sync failed while counting notifications')
        row = db.fetch_one(
            """
            SELECT COUNT(*) AS unread,
                   COUNT(*) FILTER (WHERE severity = 'critical') AS critical
            FROM notifications WHERE user_id = %s AND read_at IS NULL
            """,
            (user_id,),
        )
        return {'unread': row['unread'], 'critical': row['critical']}
    return _alert_response(handler)


@app.route('/api/notifications/<int:notification_id>/read', methods=['POST'])
@login_required
def mark_notification_read(notification_id):
    def handler():
        row = db.execute_returning(
            """
            UPDATE notifications SET read_at = COALESCE(read_at, now())
            WHERE id = %s AND user_id = %s
            RETURNING id, read_at
            """,
            (notification_id, _notification_user_id()),
        )
        if not row:
            raise RecordNotFoundError('Notification not found')
        return {'data': _jsonable(dict(row))}
    return _alert_response(handler)


@app.route('/api/notifications/read-all', methods=['POST'])
@login_required
def mark_all_notifications_read():
    def handler():
        with db.transaction() as cursor:
            cursor.execute(
                "UPDATE notifications SET read_at = now() WHERE user_id = %s AND read_at IS NULL",
                (_notification_user_id(),),
            )
            return {'updated': cursor.rowcount}
    return _alert_response(handler)


@app.route('/api/notifications/preferences', methods=['GET'])
@login_required
def get_notification_preferences():
    def handler():
        user_id = _notification_user_id()
        row = db.fetch_one(
            "SELECT in_app_min_severity, email_min_severity FROM notification_preferences WHERE user_id = %s",
            (user_id,),
        ) or {}
        return {'data': {
            'in_app_min_severity': row.get('in_app_min_severity', notifications.DEFAULT_IN_APP_MIN),
            'email_min_severity': row.get('email_min_severity', notifications.DEFAULT_EMAIL_MIN),
            'email': getattr(current_user, 'email', None),
            'email_configured': notifications.channel_factory().configured,
        }}
    return _alert_response(handler)


@app.route('/api/notifications/preferences', methods=['PUT'])
@login_required
def set_notification_preferences():
    def handler(data):
        user_id = _notification_user_id()
        values = {}
        for field in ('in_app_min_severity', 'email_min_severity'):
            value = str(data.get(field) or '').strip().lower()
            if value not in notifications.PREFERENCE_LEVELS:
                raise ValueError(f"{field} must be one of: {', '.join(notifications.PREFERENCE_LEVELS)}")
            values[field] = value
        row = db.execute_returning(
            """
            INSERT INTO notification_preferences (user_id, in_app_min_severity, email_min_severity)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                in_app_min_severity = EXCLUDED.in_app_min_severity,
                email_min_severity = EXCLUDED.email_min_severity,
                updated_at = now()
            RETURNING in_app_min_severity, email_min_severity
            """,
            (user_id, values['in_app_min_severity'], values['email_min_severity']),
        )
        return {'data': dict(row)}
    return _alert_response(handler, normalize_keys(request.get_json() or {}))


@app.route('/api/notifications/email-status', methods=['GET'])
@login_required
@super_admin_required
def notification_email_status():
    def handler():
        counts = db.fetch_one(
            """
            SELECT COUNT(*) FILTER (WHERE status = 'PENDING') AS pending,
                   COUNT(*) FILTER (WHERE status = 'SENT') AS sent,
                   COUNT(*) FILTER (WHERE status = 'FAILED') AS failed,
                   MAX(sent_at) AS last_sent_at
            FROM notification_outbox
            """
        )
        failures = db.fetch_all(
            """
            SELECT id, recipient, subject, attempts, last_error, status, next_attempt_at
            FROM notification_outbox
            WHERE last_error IS NOT NULL AND status <> 'SENT'
            ORDER BY id DESC LIMIT 10
            """
        )
        return {'data': _jsonable({
            'configured': notifications.channel_factory().configured,
            **dict(counts),
            'recent_failures': failures,
        })}
    return _alert_response(handler)


@app.route('/api/notifications/test-email', methods=['POST'])
@login_required
@super_admin_required
def send_test_notification():
    def handler():
        user_id = _notification_user_id()
        if not notifications.channel_factory().configured:
            raise ValueError('Email is not configured: set EMAIL_HOST_USER and EMAIL_HOST_PASSWORD')
        with db.transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO notifications (user_id, kind, severity, title, body, href)
                VALUES (%s, 'test', 'info', 'Test notification',
                        'Email notifications are working for this account.', '/alerts')
                RETURNING id
                """,
                (user_id,),
            )
            notification_id = cursor.fetchone()['id']
            cursor.execute(
                """
                INSERT INTO notification_outbox (notification_id, user_id, recipient, subject, body)
                SELECT %s, user_id, email, '[Zehunger] Test notification',
                       'Email notifications are working for this account.'
                FROM users WHERE user_id = %s
                RETURNING id
                """,
                (notification_id, user_id),
            )
            outbox_id = cursor.fetchone()['id']
        notifications.kick_background_delivery(db)
        return {'data': {'outbox_id': outbox_id}}
    return _alert_response(handler)


@app.route('/alerts')
@login_required
def alerts_page():
    return render_template('alerts.html')


@app.route('/setup')
@login_required
@super_admin_required
def setup_page():
    return render_template('setup.html')


@app.route('/api/waste-monitoring', methods=['POST'])
@login_required
def handle_waste_environmental_monitoring():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'No data provided'}), 400

    normalized_data = normalize_keys(data)
    required_fields = ['monitoring_date', 'monitoring_time', 'temperature', 'water_consistency', 'odor_level', 'pest_presence']
    
    missing_fields = [field for field in required_fields if field not in normalized_data or not normalized_data.get(field)]
    if missing_fields:
        return jsonify({'success': False, 'message': f'Missing or empty required fields: {", ".join(missing_fields)}'}), 400

    query = """
        INSERT INTO waste_monitoring (
            monitoring_date, monitoring_time, temperature, water_consistency, odor_level, 
            pest_presence, pest_details, mitigation_actions, remarks, recorded_by
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    params = (
        normalized_data.get('monitoring_date'),
        normalized_data.get('monitoring_time'),
        normalized_data.get('temperature'),
        normalized_data.get('water_consistency'),
        normalized_data.get('odor_level'),
        normalized_data.get('pest_presence'),
        normalized_data.get('pest_details'),
        normalized_data.get('mitigation_actions'),
        normalized_data.get('remarks'),
        current_user.username
    )

    try:
        db.execute_query(query, params)
        logger.info(f"Waste environmental monitoring data saved for {normalized_data.get('monitoring_date')}")
        return jsonify({'success': True, 'message': 'Environmental monitoring record created successfully'})
    except Exception as e:
        logger.error(f"Error creating waste environmental monitoring record: {e}")
        return jsonify({'success': False, 'message': 'Failed to create environmental monitoring record'}), 500


# --- Statistics & Reporting ---
@app.route('/api/statistics/waste-processing', methods=['GET'])
@login_required
def get_waste_processing_stats():
    try:
        query = """
            SELECT 
                DATE(processing_date) as date,
                SUM(waste_processed) as total_processed
            FROM processing_records
            GROUP BY DATE(processing_date)
            ORDER BY date DESC
            LIMIT 30;
        """
        stats = db.fetch_all(query)
        # Convert decimal and date objects to string/float for JSON serialization
        for row in stats:
            for key, value in row.items():
                if isinstance(value, (datetime,)):
                    row[key] = value.isoformat()
                elif isinstance(value, float):
                    row[key] = float(value)
        return jsonify(stats)
    except Exception as e:
        logger.error(f"Error fetching waste processing stats: {e}")
        return jsonify([]), 500


@app.route('/api/statistics/environmental', methods=['GET'])
@login_required
def get_environmental_stats():
    try:
        query = """
            SELECT 
                DATE(monitoring_date) as date,
                AVG(temperature) as avg_temp,
                MODE() WITHIN GROUP (ORDER BY water_consistency) as common_water_consistency
            FROM waste_monitoring
            GROUP BY DATE(monitoring_date)
            ORDER BY date DESC
            LIMIT 30;
        """
        stats = db.fetch_all(query)
        for row in stats:
            for key, value in row.items():
                if isinstance(value, (datetime,)):
                    row[key] = value.isoformat()
                elif isinstance(value, float):
                    row[key] = float(value)
        return jsonify(stats)
    except Exception as e:
        logger.error(f"Error fetching environmental stats: {e}")
        return jsonify([]), 500

@app.route('/api/statistics/larval-growth', methods=['GET'])
@login_required
def get_larval_growth_stats():
    try:
        query = """
            SELECT 
                DATE(feeding_date) as date,
                AVG(larvae_weight) as avg_weight,
                AVG(consumption) as avg_consumption
            FROM feeding_schedule
            GROUP BY DATE(feeding_date)
            ORDER BY date DESC
            LIMIT 30;
        """
        stats = db.fetch_all(query)
        for row in stats:
            for key, value in row.items():
                if isinstance(value, (datetime,)):
                    row[key] = value.isoformat()
                elif isinstance(value, float):
                    row[key] = float(value)
        return jsonify(stats)
    except Exception as e:
        logger.error(f"Error fetching larval growth stats: {e}")
        return jsonify([]), 500

@app.route('/api/statistics/system-efficiency', methods=['GET'])
@login_required
def get_system_efficiency():
    try:
        query_waste = """
            SELECT SUM(waste_weight) as total_waste_in
            FROM waste_sourcing;
        """
        total_waste_in = db.fetch_one(query_waste)['total_waste_in'] or 0

        query_larvae = """
            SELECT SUM(larvae_collected) as total_larvae_out
            FROM harvest_yield;
        """
        total_larvae_out = db.fetch_one(query_larvae)['total_larvae_out'] or 0
        
        query_compost = """
            SELECT COUNT(*) as total_processing_records
            FROM processing_records;
        """
        total_processing_records = db.fetch_one(query_compost)['total_processing_records'] or 0

        efficiency = float(total_larvae_out) / float(total_waste_in) if total_waste_in > 0 else 0

        return jsonify({
            'total_waste_in': float(total_waste_in),
            'total_larvae_out': float(total_larvae_out),
            'total_processing_records': int(total_processing_records),
            'overall_efficiency': efficiency
        })
    except Exception as e:
        logger.error(f"Error calculating system efficiency: {e}")
        return jsonify({}), 500

@app.route('/api/statistics/daily-report', methods=['GET'])
@login_required
def get_daily_report():
    today = datetime.now().date()
    try:
        # Waste Sourced Today
        waste_sourced_query = "SELECT SUM(waste_weight) as total FROM waste_sourcing WHERE DATE(collection_date) = %s"
        waste_sourced = db.fetch_one(waste_sourced_query, (today,))['total'] or 0

        # Larvae Harvested Today
        larvae_harvested_query = "SELECT SUM(larvae_collected) as total FROM harvest_yield WHERE DATE(harvest_date) = %s"
        larvae_harvested = db.fetch_one(larvae_harvested_query, (today,))['total'] or 0

        # Feed Given Today
        feed_given_query = "SELECT SUM(feed_quantity) as total FROM feeding_schedule WHERE DATE(feeding_date) = %s"
        feed_given = db.fetch_one(feed_given_query, (today,))['total'] or 0

        # Eggs Collected Today
        eggs_collected_query = "SELECT SUM(eggs_collected) as total FROM egg_collection WHERE DATE(collection_date) = %s"
        eggs_collected = db.fetch_one(eggs_collected_query, (today,))['total'] or 0

        return jsonify({
            'waste_sourced_today': float(waste_sourced),
            'larvae_harvested_today': float(larvae_harvested),
            'feed_given_today': float(feed_given),
            'eggs_collected_today': float(eggs_collected)
        })
    except Exception as e:
        logger.error(f"Error fetching daily report: {e}")
        return jsonify({}), 500

@app.route('/api/statistics/harvest-efficiency', methods=['GET'])
@login_required
def get_harvest_efficiency():
    try:
        query = """
            WITH input_totals AS (
                SELECT
                    batch_id,
                    SUM(wet_placed_for_drying_kg) AS total_wet_weight
                FROM drying_input
                GROUP BY batch_id
            ),
            output_totals AS (
                SELECT
                    batch_id,
                    MAX(created_at) AS output_date,
                    SUM(dried_produced_kg) AS total_dried_weight
                FROM drying_output
                GROUP BY batch_id
            )
            SELECT
                input_totals.batch_id,
                output_totals.output_date,
                input_totals.total_wet_weight,
                output_totals.total_dried_weight
            FROM input_totals
            JOIN output_totals ON input_totals.batch_id = output_totals.batch_id
            ORDER BY output_totals.output_date ASC;
        """
        results = db.fetch_all(query)

        efficiency_data = []
        target_ratio = 3.0

        for row in results:
            batch_id = row['batch_id']
            drying_date = row['output_date'].strftime('%Y-%m-%d') if row['output_date'] else None
            total_wet = float(row['total_wet_weight']) if row['total_wet_weight'] is not None else 0
            total_dried = float(row['total_dried_weight']) if row['total_dried_weight'] is not None else 0

            if total_dried > 0:
                actual_ratio_val = total_wet / total_dried
                efficiency_status = 'Efficient' if actual_ratio_val <= target_ratio else 'Inefficient'
            else:
                actual_ratio_val = None
                efficiency_status = 'Inefficient'

            efficiency_data.append({
                'batch_id': batch_id,
                'drying_date': drying_date,
                'wet_placed': round(total_wet, 2),
                'dried_produced': round(total_dried, 2),
                'actual_ratio': round(actual_ratio_val, 4) if actual_ratio_val is not None else None,
                'efficiency_status': efficiency_status,
            })

        return jsonify({'success': True, 'data': efficiency_data})
    except Exception as e:
        logger.error(f"Error fetching harvest efficiency: {e}")
        return jsonify({'success': False, 'error': 'Could not fetch harvest efficiency data'}), 500


def camel_to_snake(name):
  pattern = re.compile(r'(?<!^)(?=[A-Z])')
  return pattern.sub('_', name).lower()

def serialize_records(records):
    import datetime as _dt
    result = []
    for row in records:
        serialized = {}
        for k, v in row.items():
            if isinstance(v, _dt.datetime):
                serialized[k] = v.isoformat()
            elif isinstance(v, _dt.date):
                serialized[k] = v.isoformat()
            elif isinstance(v, _dt.time):
                serialized[k] = v.strftime('%H:%M:%S')
            elif isinstance(v, decimal.Decimal):
                serialized[k] = float(v)
            else:
                serialized[k] = v
        result.append(serialized)
    return result


def normalize_keys(data):
    if isinstance(data, dict):
        return {camel_to_snake(k): normalize_keys(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [normalize_keys(i) for i in data]
    else:
        return data

def validate_fields(data, required_fields):
    missing_fields = [field for field in required_fields if field not in data]
    return missing_fields


DRYING_BATCH_STATUSES = {'DRAFT', 'RECEIVED', 'DRYING', 'QC_PENDING', 'COMPLETED'}
DRYING_BATCH_TRANSITIONS = {
    'DRAFT': {'RECEIVED'},
    'RECEIVED': {'DRYING'},
    'DRYING': {'QC_PENDING'},
    'QC_PENDING': {'COMPLETED'},
    'COMPLETED': set(),
}


def _drying_actor(data):
    actor, actor_user_id = _production_actor(data)
    return actor, actor_user_id


def _drying_scope_values(data):
    values = [data.get(field) for field in ('farm_id', 'site_id', 'facility_id')]
    if any(value in (None, '') for value in values):
        raise ValueError('farm_id, site_id, and facility_id are required for a Drying Batch')
    return tuple(
        _parse_positive_integer(value, field)
        for value, field in zip(values, ('farm_id', 'site_id', 'facility_id'))
    )


def _drying_timestamp(value, field_name, *, required=False):
    if value in (None, ''):
        if required:
            raise ValueError(f'{field_name} is required')
        return None
    raw = str(value)
    if len(raw) == 10:
        raw = f'{raw}T00:00:00+00:00'
    try:
        parsed = datetime.fromisoformat(raw.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError(f'{field_name} must be a valid ISO date or timestamp')
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _drying_batch_row(cursor, batch_ref, *, for_update=False):
    lookup_id = int(batch_ref) if str(batch_ref).isdigit() else -1
    cursor.execute(
        f"""
        SELECT db.id, db.batch_id, db.batch_code, db.business_id,
               db.drying_date, db.drying_method, db.personnel,
               UPPER(db.status) AS status, db.farm_id, db.site_id, db.facility_id,
               db.started_at, db.ended_at, db.created_at, db.updated_at
        FROM drying_batches AS db
        WHERE db.id = %s
           OR db.batch_id = %s
           OR db.batch_code = %s
           OR db.business_id = %s
        {'FOR UPDATE' if for_update else ''}
        """,
        (lookup_id, str(batch_ref), str(batch_ref), str(batch_ref)),
    )
    row = cursor.fetchone()
    if not row:
        raise ValueError('Drying Batch not found')
    if row['farm_id'] is None or row['site_id'] is None or row['facility_id'] is None:
        raise ValueError(
            'Drying Batch has no canonical farm, site, and facility scope'
        )
    _assert_production_location(
        cursor, row['farm_id'], row['site_id'], row['facility_id']
    )
    _assert_production_scope_access(
        cursor, row['farm_id'], row['site_id'], row['facility_id']
    )
    return row


def _drying_harvest_row(cursor, harvest_ref):
    lookup_id = int(harvest_ref) if str(harvest_ref).isdigit() else -1
    cursor.execute(
        """
        SELECT h.id, h.harvest_code, h.wet_weight, h.unit,
               pe.production_batch_id, pe.farm_id, pe.site_id, pe.facility_id,
               pe.occurred_at
        FROM harvests AS h
        JOIN production_events AS pe ON pe.id = h.production_event_id
        WHERE (h.id = %s OR h.harvest_code = %s)
          AND pe.event_type = 'harvest'
          AND pe.status = 'recorded'
        FOR UPDATE OF h
        """,
        (lookup_id, str(harvest_ref)),
    )
    row = cursor.fetchone()
    if not row:
        raise ValueError('Harvest not found or it is not an active harvest event')
    return row


def _drying_input_rows(data):
    rows = data.get('inputs')
    if rows is None:
        rows = data.get('harvest_inputs')
    if rows is None:
        rows = data.get('harvests')
    if rows is None:
        source_ids = data.get('source_harvest_ids')
        if source_ids is None:
            source_ids = data.get('source_harvests')
        if source_ids is not None:
            if not isinstance(source_ids, list) or not source_ids:
                raise ValueError('source_harvest_ids must be a non-empty list')
            rows = [
                item if isinstance(item, dict) else {'harvest_id': item}
                for item in source_ids
            ]
    if rows is None and any(
        data.get(key) not in (None, '')
        for key in ('harvest_id', 'harvest_code')
    ):
        rows = [data]
    if not isinstance(rows, list) or not rows:
        raise ValueError('At least one harvest input is required')

    normalized = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Each drying input must be an object')
        harvest_ref = row.get('harvest_id', row.get('harvest_code'))
        if harvest_ref in (None, ''):
            raise ValueError('harvest_id or harvest_code is required for each input')
        ref_key = str(harvest_ref)
        if ref_key in seen:
            raise ValueError('Each Harvest can be selected only once per Drying Batch')
        seen.add(ref_key)
        quantity = _event_decimal(
            row.get(
                'quantity',
                row.get('input_quantity', row.get('quantity_kg')),
            ),
            'quantity',
            minimum='0.001',
            required=True,
        )
        unit = _event_unit(row.get('unit'), 'unit', 'kg', {'kg', 'g'})
        moisture = _event_decimal(
            row.get(
                'incoming_moisture_percent',
                row.get('moisture_percent', row.get('moisture')),
            ),
            'incoming_moisture_percent',
            minimum=0,
            maximum=100,
        )
        normalized.append({
            'harvest_ref': harvest_ref,
            'quantity': quantity,
            'unit': unit,
            'incoming_moisture_percent': moisture,
            'notes': row.get('notes'),
        })
    return normalized


def _drying_quantity_kg(quantity, unit):
    return quantity if unit == 'kg' else quantity / Decimal('1000')


def _drying_add_inputs(cursor, batch, rows, data):
    if batch['status'] not in {'DRAFT', 'RECEIVED'}:
        raise ValueError('Harvest inputs can only be added while a Drying Batch is DRAFT or RECEIVED')
    actor, actor_user_id = _drying_actor(data)
    for row in rows:
        harvest = _drying_harvest_row(cursor, row['harvest_ref'])
        # Wet larvae may go to a dedicated drying facility, but never leave
        # the farm, and the caller must also be allowed at the harvest site.
        if harvest['farm_id'] != batch['farm_id']:
            raise ValueError('Harvest and Drying Batch must be on the same farm')
        _assert_production_scope_access(
            cursor, harvest['farm_id'], harvest['site_id'], harvest['facility_id']
        )
        quantity_kg = _drying_quantity_kg(row['quantity'], row['unit'])
        available_kg = (
            harvest['wet_weight']
            if harvest['unit'] == 'kg'
            else harvest['wet_weight'] / Decimal('1000')
        )
        cursor.execute(
            """
            SELECT COALESCE(
                SUM(CASE WHEN unit = 'kg' THEN quantity ELSE quantity / 1000 END),
                0
            ) AS consumed_kg
            FROM drying_inputs
            WHERE harvest_id = %s
            """,
            (harvest['id'],),
        )
        consumed_kg = Decimal(str(cursor.fetchone()['consumed_kg']))
        if consumed_kg + quantity_kg > available_kg:
            remaining = max(available_kg - consumed_kg, Decimal('0'))
            raise ValueError(
                f'Input exceeds available Harvest material; only {remaining:.3f} kg remains'
            )
        cursor.execute(
            """
            SELECT COALESCE(MAX(line_no), 0) + 1 AS line_no
            FROM drying_inputs
            WHERE drying_batch_id = %s
            """,
            (batch['id'],),
        )
        line_no = cursor.fetchone()['line_no']
        cursor.execute(
            """
            INSERT INTO drying_inputs (
                drying_batch_id, line_no, harvest_id, quantity, unit,
                incoming_moisture_percent, added_at, recorded_by_user_id,
                recorded_by, notes
            ) VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, %s, %s, %s)
            RETURNING id, line_no, harvest_id, quantity, unit,
                      incoming_moisture_percent, added_at, recorded_by, notes
            """,
            (
                batch['id'], line_no, harvest['id'], row['quantity'], row['unit'],
                row['incoming_moisture_percent'], actor_user_id, actor, row['notes'],
            ),
        )


def _drying_batch_detail(cursor, batch):
    cursor.execute(
        """
        SELECT di.id, di.line_no, di.harvest_id, h.harvest_code,
               di.quantity, di.unit, di.incoming_moisture_percent,
               di.added_at, di.recorded_by, di.notes
        FROM drying_inputs AS di
        JOIN harvests AS h ON h.id = di.harvest_id
        WHERE di.drying_batch_id = %s
        ORDER BY di.line_no
        """,
        (batch['id'],),
    )
    inputs = [dict(row) for row in cursor.fetchall()]
    cursor.execute(
        """
        SELECT id, line_no, quantity, unit, moisture_percent, output_date,
               operator, input_quantity_kg_at_output, yield_ratio,
               yield_percentage, recorded_by, notes
        FROM drying_outputs
        WHERE drying_batch_id = %s
        ORDER BY line_no
        """,
        (batch['id'],),
    )
    outputs = [dict(row) for row in cursor.fetchall()]
    input_kg = sum(
        (_drying_quantity_kg(row['quantity'], row['unit']) for row in inputs),
        Decimal('0'),
    )
    output_kg = sum(
        (_drying_quantity_kg(row['quantity'], row['unit']) for row in outputs),
        Decimal('0'),
    )
    yield_ratio = output_kg / input_kg if input_kg else None
    result = dict(batch)
    result.update({
        'source': inputs,
        'inputs': inputs,
        'outputs': outputs,
        'input_quantity_kg': input_kg,
        'output_quantity_kg': output_kg,
        'yield_ratio': yield_ratio,
        'yield_percentage': yield_ratio * Decimal('100') if yield_ratio is not None else None,
    })
    return result


def _drying_create_batch(data):
    batch_code = str(data.get('batch_code') or data.get('batch_id') or '').strip()
    if not batch_code:
        raise ValueError('batch_code is required for a Drying Batch')
    drying_date = data.get('drying_date') or data.get('batch_date')
    if not drying_date:
        raise ValueError('drying_date is required')
    method = str(data.get('drying_method') or data.get('method') or '').strip()
    personnel = str(data.get('personnel') or data.get('operator') or '').strip()
    if not method:
        raise ValueError('drying_method is required')
    if not personnel:
        raise ValueError('personnel is required')
    farm_id, site_id, facility_id = _drying_scope_values(data)
    started_at = _drying_timestamp(data.get('started_at'), 'started_at')
    rows = _drying_input_rows(data) if any(
        data.get(key) is not None for key in ('inputs', 'harvest_inputs', 'harvests', 'harvest_id', 'harvest_code')
    ) else None
    actor, actor_user_id = _drying_actor(data)
    with db.transaction() as cursor:
        _assert_production_location(cursor, farm_id, site_id, facility_id)
        _assert_production_scope_access(cursor, farm_id, site_id, facility_id)
        cursor.execute(
            """
            INSERT INTO drying_batches (
                batch_id, batch_code, drying_date, drying_method, personnel,
                status, farm_id, site_id, facility_id, started_at,
                created_by_user_id, updated_at
            ) VALUES (%s, %s, %s, %s, %s, 'DRAFT', %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            RETURNING id, batch_id, batch_code, business_id, drying_date,
                      drying_method, personnel, UPPER(status) AS status,
                      farm_id, site_id, facility_id, started_at, ended_at,
                      created_at, updated_at
            """,
            (
                batch_code, batch_code, drying_date, method, personnel,
                farm_id, site_id, facility_id, started_at, actor_user_id,
            ),
        )
        batch = cursor.fetchone()
        if rows:
            _drying_add_inputs(cursor, batch, rows, data)
        cursor.execute(
            """
            INSERT INTO drying_batch_status_history (
                drying_batch_id, previous_status, new_status,
                actor_user_id, actor, reason
            ) VALUES (%s, NULL, 'DRAFT', %s, %s, %s)
            """,
            (batch['id'], actor_user_id, actor, data.get('reason')),
        )
        detail = _drying_batch_detail(cursor, batch)
    return detail


def _drying_transition(cursor, batch, new_status, data):
    current_status = batch['status']
    if new_status not in DRYING_BATCH_STATUSES:
        raise ValueError(f'status must be one of: {", ".join(sorted(DRYING_BATCH_STATUSES))}')
    if new_status not in DRYING_BATCH_TRANSITIONS.get(current_status, set()):
        raise ValueError(f'Invalid Drying Batch transition from {current_status} to {new_status}')
    cursor.execute(
        "SELECT COUNT(*) AS count FROM drying_inputs WHERE drying_batch_id = %s",
        (batch['id'],),
    )
    input_count = cursor.fetchone()['count']
    if new_status == 'RECEIVED' and input_count == 0:
        raise ValueError('A Drying Batch must have at least one Harvest input before RECEIVED')
    if new_status == 'DRYING' and input_count == 0:
        raise ValueError('A Drying Batch must have at least one Harvest input before DRYING')
    cursor.execute(
        "SELECT COUNT(*) AS count FROM drying_outputs WHERE drying_batch_id = %s",
        (batch['id'],),
    )
    output_count = cursor.fetchone()['count']
    if new_status == 'QC_PENDING' and output_count == 0:
        raise ValueError('A Drying Batch must have at least one output before QC_PENDING')
    if new_status == 'COMPLETED':
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM quality_approvals AS qa
                JOIN quality_checks AS qc ON qc.id = qa.quality_check_id
                WHERE qc.drying_batch_id = %s
                  AND qc.status = 'passed'
                  AND qa.decision = 'approved'
            ) AS approved
            """,
            (batch['id'],),
        )
        if not cursor.fetchone()['approved']:
            raise ValueError(
                'A Drying Batch requires an approved passing quality check before COMPLETED'
            )
    actor, actor_user_id = _drying_actor(data)
    started_at = "CURRENT_TIMESTAMP" if new_status == 'DRYING' else "started_at"
    ended_at = "CURRENT_TIMESTAMP" if new_status == 'COMPLETED' else "ended_at"
    cursor.execute(
        f"""
        UPDATE drying_batches
        SET status = %s,
            started_at = {started_at},
            ended_at = {ended_at},
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        RETURNING id, batch_id, batch_code, business_id, drying_date,
                  drying_method, personnel, UPPER(status) AS status,
                  farm_id, site_id, facility_id, started_at, ended_at,
                  created_at, updated_at
        """,
        (new_status, batch['id']),
    )
    updated = cursor.fetchone()
    cursor.execute(
        """
        INSERT INTO drying_batch_status_history (
            drying_batch_id, previous_status, new_status,
            actor_user_id, actor, reason
        ) VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (batch['id'], current_status, new_status, actor_user_id, actor, data.get('reason')),
    )
    return updated


def _drying_create_quality_check(data):
    batch_ref = data.get('drying_batch_id') or data.get('batch_id') or data.get('batch_code')
    output_ref = data.get('drying_output_id') or data.get('output_id')
    if batch_ref in (None, '') and output_ref in (None, ''):
        raise ValueError('drying_batch_id or batch_code is required')
    inspector = str(data.get('inspector') or data.get('qc_personnel') or '').strip()
    if not inspector:
        raise ValueError('inspector is required')
    status = str(data.get('status') or data.get('check_status') or 'submitted').strip().lower()
    if status not in {'draft', 'submitted', 'passed', 'failed', 'superseded'}:
        raise ValueError('quality check status is invalid')
    moisture = _event_decimal(
        data.get('moisture_percent', data.get('moisture')),
        'moisture_percent',
        minimum=0,
        maximum=100,
    )
    sampled_at = _drying_timestamp(data.get('sampled_at'), 'sampled_at')
    checked_at = _drying_timestamp(data.get('checked_at'), 'checked_at')
    parameters = data.get('parameters') or {}
    if not isinstance(parameters, dict):
        raise ValueError('parameters must be an object')
    with db.transaction() as cursor:
        output = None
        if output_ref not in (None, ''):
            output_id = _parse_positive_integer(output_ref, 'drying_output_id')
            cursor.execute(
                """
                SELECT id, drying_batch_id
                FROM drying_outputs
                WHERE id = %s
                FOR UPDATE
                """,
                (output_id,),
            )
            output = cursor.fetchone()
            if not output:
                raise ValueError('Drying Output not found')
            if batch_ref in (None, ''):
                batch_ref = output['drying_batch_id']
        batch = _drying_batch_row(cursor, batch_ref, for_update=True)
        if output and output['drying_batch_id'] != batch['id']:
            raise ValueError('Drying Output does not belong to this Drying Batch')
        if batch['status'] != 'QC_PENDING':
            raise ValueError('Quality checks can only be recorded while a Drying Batch is QC_PENDING')
        actor, actor_user_id = _drying_actor(data)
        cursor.execute(
            """
            INSERT INTO quality_checks (
                drying_batch_id, drying_output_id, status, moisture_percent, parameters,
                sampled_at, checked_at, inspector, inspector_user_id, notes
            ) VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s)
            RETURNING id, check_code, drying_batch_id, status, moisture_percent,
                      drying_output_id, parameters, sampled_at, checked_at,
                      inspector, notes, created_at
            """,
            (
                batch['id'], output['id'] if output else None, status, moisture,
                json.dumps(parameters),
                sampled_at, checked_at, inspector, actor_user_id, data.get('notes'),
            ),
        )
        return dict(cursor.fetchone())


def _drying_create_quality_approval(data):
    check_id = data.get('quality_check_id') or data.get('check_id')
    if check_id in (None, ''):
        raise ValueError('quality_check_id is required')
    check_id = _parse_positive_integer(check_id, 'quality_check_id')
    decision = str(data.get('decision') or data.get('approval_status') or '').strip().lower()
    if decision not in {'approved', 'rejected', 'conditional', 'revoked'}:
        raise ValueError('decision must be approved, rejected, conditional, or revoked')
    approver = str(data.get('approver') or data.get('reviewed_by') or '').strip()
    if not approver:
        raise ValueError('approver is required')
    with db.transaction() as cursor:
        cursor.execute(
            """
            SELECT qc.id, qc.check_code, qc.drying_batch_id, qc.status,
                   db.status AS batch_status
            FROM quality_checks AS qc
            JOIN drying_batches AS db ON db.id = qc.drying_batch_id
            WHERE qc.id = %s
            FOR UPDATE OF qc, db
            """,
            (check_id,),
        )
        check = cursor.fetchone()
        if not check:
            raise ValueError('Quality check not found')
        batch = _drying_batch_row(cursor, check['drying_batch_id'], for_update=True)
        if batch['status'] != 'QC_PENDING':
            raise ValueError('Quality approval can only be recorded while a Drying Batch is QC_PENDING')
        if decision == 'approved' and check['status'] != 'passed':
            raise ValueError('An approved Drying Batch requires a passed quality check')
        actor, actor_user_id = _drying_actor(data)
        cursor.execute(
            """
            INSERT INTO quality_approvals (
                quality_check_id, decision, rationale, approver, approver_user_id
            ) VALUES (%s, %s, %s, %s, %s)
            RETURNING id, approval_code, quality_check_id, decision,
                      rationale, decided_at, approver, created_at
            """,
            (check_id, decision, data.get('rationale') or data.get('comments'),
             approver, actor_user_id),
        )
        approval = dict(cursor.fetchone())
        if decision == 'approved':
            _drying_transition(cursor, batch, 'COMPLETED', data)
        return approval


def _release_product_lot(data):
    output_ref = data.get('drying_output_id') or data.get('output_id')
    if output_ref in (None, ''):
        raise ValueError('drying_output_id is required')
    output_id = _parse_positive_integer(output_ref, 'drying_output_id')
    product_type = str(data.get('product_type') or '').strip()
    if not product_type:
        raise ValueError('product_type is required')
    if len(product_type) > 50:
        raise ValueError('product_type must be at most 50 characters')

    lot_code = str(data.get('lot_number') or data.get('lot_code') or '').strip() or None
    if lot_code and len(lot_code) > 30:
        raise ValueError('lot_number must be at most 30 characters')
    storage_location = str(data.get('storage_location') or '').strip() or None
    if storage_location and len(storage_location) > 100:
        raise ValueError('storage_location must be at most 100 characters')

    with db.transaction() as cursor:
        cursor.execute(
            """
            SELECT id, drying_batch_id, quantity, unit,
                   (output_date AT TIME ZONE 'UTC')::date AS production_date
            FROM drying_outputs
            WHERE id = %s
            FOR UPDATE
            """,
            (output_id,),
        )
        output = cursor.fetchone()
        if not output:
            raise ValueError('Drying Output not found')

        batch = _drying_batch_row(cursor, output['drying_batch_id'], for_update=True)

        cursor.execute(
            """
            SELECT id, business_id
            FROM product_lots
            WHERE drying_output_id = %s
            """,
            (output_id,),
        )
        if cursor.fetchone():
            raise ValueError('A Product Lot has already been released from this Drying Output')

        cursor.execute(
            """
            SELECT id, check_code, status
            FROM quality_checks
            WHERE drying_output_id = %s
            ORDER BY id DESC
            LIMIT 1
            FOR UPDATE
            """,
            (output_id,),
        )
        check = cursor.fetchone()
        if not check:
            raise ValueError('This Drying Output has no output-specific QC check')

        cursor.execute(
            """
            SELECT id, approval_code, decision, approver, decided_at
            FROM quality_approvals
            WHERE quality_check_id = %s
            ORDER BY id DESC
            LIMIT 1
            FOR UPDATE
            """,
            (check['id'],),
        )
        approval = cursor.fetchone()
        if check['status'] != 'passed' or not approval or approval['decision'] != 'approved':
            raise ValueError(
                'Only a Drying Output with a passed QC check and latest approved decision can become an available Product Lot'
            )

        if batch['status'] != 'COMPLETED':
            raise ValueError('A Product Lot can only be released from a completed Drying Batch')

        # A released lot is received into stock in the same transaction, so
        # every available canonical lot has exactly one RECEIPT in the ledger.
        if data.get('inventory_location_id') in (None, ''):
            raise ValueError('inventory_location_id is required to receive the lot into stock')
        receipt_location = _inventory_location_row(
            cursor, data['inventory_location_id'], 'to'
        )
        if receipt_location['farm_id'] != batch['farm_id']:
            raise ValueError(
                f"Inventory location {receipt_location['location_code']} belongs to a "
                'different farm than the Drying Batch'
            )
        storage_location = storage_location or receipt_location['name']

        if lot_code:
            cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM product_lots WHERE lot_code = %s) AS exists",
                (lot_code,),
            )
            if cursor.fetchone()['exists']:
                raise ValueError('lot_number is already in use')

        quantity_kg = _drying_quantity_kg(output['quantity'], output['unit'])
        actor, _actor_user_id = _drying_actor(data)
        cursor.execute(
            """
            WITH generated AS (
                SELECT 'LOT-' || to_char(%s::date, 'YYYY') || '-' ||
                       lpad(nextval('phase_one_product_lot_seq')::text, 5, '0') AS business_id
            )
            INSERT INTO product_lots (
                lot_code, business_id, drying_output_id, release_approval_id,
                farm_id, product_type, processing_date, production_date,
                quantity_kg, unit, storage_location, status, recorded_by
            )
            SELECT COALESCE(%s, generated.business_id), generated.business_id,
                   %s, %s, %s, %s, %s, %s, %s, 'kg', %s, 'available', %s
            FROM generated
            RETURNING id
            """,
            (
                output['production_date'], lot_code, output['id'], approval['id'],
                batch['farm_id'], product_type, output['production_date'],
                output['production_date'], quantity_kg, storage_location, actor,
            ),
        )
        created = cursor.fetchone()
        _insert_inventory_movement(
            cursor,
            {'id': created['id'], 'farm_id': batch['farm_id']},
            'RECEIPT',
            quantity_kg,
            data,
            to_location=receipt_location,
            occurred_at=None,
            notes='Received on Product Lot release',
            reference_type='quality_approval',
            reference_id=approval['id'],
        )
        return _product_lot_detail(cursor, created['id'])


def _product_lot_detail(cursor, lot_ref):
    lookup_id = int(lot_ref) if str(lot_ref).isdigit() else -1
    cursor.execute(
        """
        SELECT pl.id, pl.business_id, pl.lot_code, pl.product_type,
               pl.quantity_kg AS quantity, pl.quantity_kg, pl.unit,
               pl.production_date, pl.storage_location,
               UPPER(pl.status) AS stored_status,
               pl.drying_output_id, pl.release_approval_id, pl.farm_id,
               output.quantity AS output_quantity, output.unit AS output_unit,
               output.moisture_percent AS output_moisture_percent,
               output.output_date, batch.id AS drying_batch_id,
               batch.batch_code AS drying_batch_code,
               batch.business_id AS drying_batch_business_id,
               UPPER(batch.status) AS drying_batch_status,
               batch.site_id, batch.facility_id,
               farm.name AS farm_name,
               check_row.id AS quality_check_id,
               check_row.check_code, check_row.status AS qc_status,
               release_approval.approval_code AS release_approval_code,
               release_approval.decision AS release_decision,
               release_approval.approver AS released_by,
               release_approval.decided_at AS released_at,
               latest_approval.decision AS approval_status,
               CASE
                   WHEN check_row.status = 'passed'
                    AND latest_approval.decision = 'approved'
                   THEN UPPER(pl.status)
                   ELSE 'BLOCKED'
               END AS status
        FROM product_lots AS pl
        JOIN drying_outputs AS output ON output.id = pl.drying_output_id
        JOIN drying_batches AS batch ON batch.id = output.drying_batch_id
        JOIN farms AS farm ON farm.id = pl.farm_id
        JOIN quality_approvals AS release_approval
          ON release_approval.id = pl.release_approval_id
        JOIN quality_checks AS check_row
          ON check_row.id = release_approval.quality_check_id
        LEFT JOIN LATERAL (
            SELECT decision
            FROM quality_approvals
            WHERE quality_check_id = check_row.id
            ORDER BY id DESC
            LIMIT 1
        ) AS latest_approval ON TRUE
        WHERE pl.drying_output_id IS NOT NULL
          AND (pl.id = %s OR pl.business_id = %s OR pl.lot_code = %s)
        """,
        (lookup_id, str(lot_ref), str(lot_ref)),
    )
    lot = cursor.fetchone()
    if not lot:
        raise ValueError('Canonical Product Lot not found')
    _assert_production_scope_access(
        cursor, lot['farm_id'], lot['site_id'], lot['facility_id']
    )

    cursor.execute(
        """
        SELECT di.id AS drying_input_id, di.quantity AS drying_input_quantity,
               di.unit AS drying_input_unit,
               harvest.id AS harvest_id, harvest.harvest_code,
               harvest.wet_weight, harvest.unit AS harvest_unit,
               production.id AS production_batch_id,
               production.business_id AS production_batch_business_id,
               production.batch_code AS production_batch_code,
               production_input.quantity_issued AS substrate_issued_quantity,
               production_input.unit AS substrate_issued_unit,
               substrate.id AS substrate_batch_id,
               substrate.business_id AS substrate_batch_business_id,
               substrate.batch_code AS substrate_batch_code,
               substrate_input.quantity_used AS waste_input_quantity,
               substrate_input.unit AS waste_input_unit,
               waste.id AS waste_lot_id,
               waste.business_id AS waste_lot_business_id,
               waste.waste_type, waste.source_name,
               waste.quantity AS waste_lot_quantity,
               waste.unit AS waste_lot_unit
        FROM drying_inputs AS di
        JOIN harvests AS harvest ON harvest.id = di.harvest_id
        JOIN production_events AS event
          ON event.id = harvest.production_event_id
        JOIN production_batches AS production
          ON production.id = event.production_batch_id
        LEFT JOIN production_batch_inputs AS production_input
          ON production_input.production_batch_id = production.id
        LEFT JOIN substrate_batches AS substrate
          ON substrate.id = production_input.substrate_batch_id
        LEFT JOIN substrate_batch_inputs AS substrate_input
          ON substrate_input.substrate_batch_id = substrate.id
        LEFT JOIN waste_lots AS waste
          ON waste.id = substrate_input.waste_lot_id
        WHERE di.drying_batch_id = %s
        ORDER BY harvest.id, production.id, substrate.id, waste.id
        """,
        (lot['drying_batch_id'],),
    )
    result = dict(lot)
    production_date = result.get('production_date')
    if production_date is not None and hasattr(production_date, 'isoformat'):
        result['production_date'] = production_date.isoformat()
    result['source_chain'] = [dict(row) for row in cursor.fetchall()]
    result['source_drying_batch'] = {
        'id': lot['drying_batch_id'],
        'business_id': lot['drying_batch_business_id'],
        'batch_code': lot['drying_batch_code'],
        'status': lot['drying_batch_status'],
    }
    result['inventory'] = _inventory_summary(cursor, lot['id'])
    return result


def _canonical_drying_batch_request(data):
    return any(
        data.get(key) not in (None, '')
        for key in ('farm_id', 'site_id', 'facility_id', 'inputs', 'harvest_inputs',
                    'harvests', 'source_harvest_ids', 'source_harvests',
                    'harvest_id', 'harvest_code')
    )


@app.route('/api/drying/batches', methods=['POST'])
@login_required
def create_canonical_drying_batch():
    try:
        data = normalize_keys(request.get_json() or {})
        record = _drying_create_batch(data)
        return jsonify({'success': True, 'message': 'Drying Batch created', 'data': record}), 201
    except ProductionEventPermissionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 403
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception:
        logger.exception('Error creating canonical Drying Batch')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/api/drying/batches/<string:batch_ref>', methods=['GET'])
@login_required
def get_canonical_drying_batch(batch_ref):
    try:
        with db.transaction() as cursor:
            batch = _drying_batch_row(cursor, batch_ref)
            record = _drying_batch_detail(cursor, batch)
        return jsonify({'success': True, 'data': record}), 200
    except ProductionEventPermissionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 403
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 404
    except Exception:
        logger.exception('Error fetching canonical Drying Batch')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/api/drying/batches/<string:batch_ref>/inputs', methods=['POST'])
@login_required
def add_canonical_drying_inputs(batch_ref):
    try:
        data = normalize_keys(request.get_json() or {})
        rows = _drying_input_rows(data)
        with db.transaction() as cursor:
            batch = _drying_batch_row(cursor, batch_ref, for_update=True)
            _drying_add_inputs(cursor, batch, rows, data)
            record = _drying_batch_detail(cursor, batch)
        return jsonify({'success': True, 'message': 'Drying inputs recorded', 'data': record}), 201
    except ProductionEventPermissionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 403
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception:
        logger.exception('Error recording canonical Drying inputs')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/api/drying/batches/<string:batch_ref>/outputs', methods=['POST'])
@login_required
def add_canonical_drying_output(batch_ref):
    try:
        data = normalize_keys(request.get_json() or {})
        quantity = _event_decimal(
            data.get('quantity', data.get('dried_quantity', data.get('dried_produced'))),
            'quantity',
            minimum='0.001',
            required=True,
        )
        unit = _event_unit(data.get('unit', data.get('output_unit')), 'unit', 'kg', {'kg', 'g'})
        moisture = _event_decimal(
            data.get('moisture_percent', data.get('moisture')),
            'moisture_percent',
            minimum=0,
            maximum=100,
        )
        output_date = _drying_timestamp(
            data.get('output_date') or data.get('produced_at'),
            'output_date',
            required=True,
        )
        operator = str(data.get('operator') or '').strip()
        if not operator:
            raise ValueError('operator is required')
        with db.transaction() as cursor:
            batch = _drying_batch_row(cursor, batch_ref, for_update=True)
            if batch['status'] != 'DRYING':
                raise ValueError('Outputs can only be recorded while a Drying Batch is DRYING')
            if batch['drying_date'] and output_date[:10] < str(batch['drying_date']):
                raise ValueError('output_date cannot be before the Drying Batch date')
            cursor.execute(
                "SELECT COUNT(*) AS count FROM drying_inputs WHERE drying_batch_id = %s",
                (batch['id'],),
            )
            if cursor.fetchone()['count'] == 0:
                raise ValueError('A Drying Batch must have Harvest inputs before recording output')
            cursor.execute(
                """
                SELECT COALESCE(SUM(CASE WHEN unit = 'kg' THEN quantity ELSE quantity / 1000 END), 0)
                    AS input_kg
                FROM drying_inputs WHERE drying_batch_id = %s
                """,
                (batch['id'],),
            )
            input_kg = Decimal(str(cursor.fetchone()['input_kg']))
            cursor.execute(
                """
                SELECT COALESCE(SUM(CASE WHEN unit = 'kg' THEN quantity ELSE quantity / 1000 END), 0)
                    AS output_kg
                FROM drying_outputs WHERE drying_batch_id = %s
                """,
                (batch['id'],),
            )
            output_kg = Decimal(str(cursor.fetchone()['output_kg']))
            output_quantity_kg = _drying_quantity_kg(quantity, unit)
            if output_kg + output_quantity_kg > input_kg:
                raise ValueError('Dried output cannot exceed the total wet Harvest input')
            total_output_kg = output_kg + output_quantity_kg
            yield_ratio = total_output_kg / input_kg
            yield_percentage = yield_ratio * Decimal('100')
            cursor.execute(
                """
                SELECT COALESCE(MAX(line_no), 0) + 1 AS line_no
                FROM drying_outputs WHERE drying_batch_id = %s
                """,
                (batch['id'],),
            )
            line_no = cursor.fetchone()['line_no']
            actor, actor_user_id = _drying_actor(data)
            cursor.execute(
                """
                INSERT INTO drying_outputs (
                    drying_batch_id, line_no, quantity, unit, moisture_percent,
                    output_date, operator, input_quantity_kg_at_output,
                    yield_ratio, yield_percentage, recorded_by_user_id,
                    recorded_by, notes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, line_no, quantity, unit, moisture_percent,
                          output_date, operator, input_quantity_kg_at_output,
                          yield_ratio, yield_percentage, recorded_by, notes
                """,
                (
                    batch['id'], line_no, quantity, unit, moisture, output_date,
                    operator, input_kg, yield_ratio, yield_percentage,
                    actor_user_id, actor, data.get('notes'),
                ),
            )
            output = dict(cursor.fetchone())
            record = _drying_batch_detail(cursor, batch)
        return jsonify({
            'success': True,
            'message': 'Drying output recorded',
            'output': output,
            'data': record,
        }), 201
    except ProductionEventPermissionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 403
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception:
        logger.exception('Error recording canonical Drying output')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/api/drying/batches/<string:batch_ref>/status', methods=['POST'])
@login_required
def update_canonical_drying_status(batch_ref):
    try:
        data = normalize_keys(request.get_json() or {})
        new_status = str(data.get('status') or '').strip().upper()
        with db.transaction() as cursor:
            batch = _drying_batch_row(cursor, batch_ref, for_update=True)
            updated = _drying_transition(cursor, batch, new_status, data)
            record = _drying_batch_detail(cursor, updated)
        return jsonify({'success': True, 'message': 'Drying Batch status updated', 'data': record}), 200
    except ProductionEventPermissionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 403
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception:
        logger.exception('Error updating canonical Drying Batch status')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/api/drying/batches/<string:batch_ref>/quality-checks', methods=['POST'])
@login_required
def create_canonical_drying_quality_check(batch_ref):
    data = normalize_keys(request.get_json() or {})
    data['drying_batch_id'] = batch_ref
    return _canonical_quality_check_response(data)


@app.route('/api/drying/outputs/<int:output_id>/quality-checks', methods=['POST'])
@login_required
def create_canonical_drying_output_quality_check(output_id):
    data = normalize_keys(request.get_json() or {})
    data['drying_output_id'] = output_id
    return _canonical_quality_check_response(data)


def _canonical_quality_check_response(data):
    try:
        record = _drying_create_quality_check(data)
        return jsonify({'success': True, 'message': 'Drying quality check recorded', 'data': record}), 201
    except ProductionEventPermissionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 403
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception:
        logger.exception('Error recording canonical Drying quality check')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/api/drying/quality-approvals', methods=['POST'])
@login_required
def create_canonical_drying_quality_approval():
    try:
        data = normalize_keys(request.get_json() or {})
        record = _drying_create_quality_approval(data)
        return jsonify({'success': True, 'message': 'Drying quality approval recorded', 'data': record}), 201
    except ProductionEventPermissionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 403
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception:
        logger.exception('Error recording canonical Drying quality approval')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/api/drying/batches/<string:batch_ref>/quality-approvals', methods=['POST'])
@login_required
def create_canonical_drying_batch_quality_approval(batch_ref):
    data = normalize_keys(request.get_json() or {})
    data['drying_batch_id'] = batch_ref
    try:
        check_id = data.get('quality_check_id') or data.get('check_id')
        if check_id in (None, ''):
            raise ValueError('quality_check_id is required')
        check_id = _parse_positive_integer(check_id, 'quality_check_id')
        with db.transaction() as cursor:
            cursor.execute(
                """
                SELECT qc.drying_batch_id
                FROM quality_checks AS qc
                WHERE qc.id = %s
                """,
                (check_id,),
            )
            check = cursor.fetchone()
            if not check:
                raise ValueError('Quality check not found')
            batch = _drying_batch_row(cursor, batch_ref)
            if check['drying_batch_id'] != batch['id']:
                raise ValueError('Quality check does not belong to this Drying Batch')
        return create_canonical_drying_quality_approval()
    except ProductionEventPermissionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 403
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400


@app.route('/api/drying/batch', methods=['POST'])
@login_required
def create_drying_batch():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'Invalid JSON format'}), 400

    data = normalize_keys(data)
    if _canonical_drying_batch_request(data):
        try:
            record = _drying_create_batch(data)
            return jsonify({
                'success': True,
                'message': 'Drying Batch created',
                'record': record,
                'data': record,
                'id': record['id'],
                'business_id': record['business_id'],
            }), 201
        except ProductionEventPermissionError as exc:
            return jsonify({'success': False, 'message': str(exc)}), 403
        except ValueError as exc:
            return jsonify({'success': False, 'message': str(exc)}), 400
        except Exception:
            logger.exception('Error creating canonical Drying Batch through legacy route')
            return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500
    required_fields = ['batch_id', 'drying_date', 'drying_method', 'personnel', 'status']
    if any(field not in data for field in required_fields):
        missing_fields = [field for field in required_fields if field not in data]
        return jsonify({'success': False, 'message': f'Missing required fields: {", ".join(missing_fields)}'}), 400

    try:
        query = """INSERT INTO drying_batches (batch_id, drying_date, drying_method, personnel, status) 
                   VALUES (%s, %s, %s, %s, %s)"""
        params = (data['batch_id'], data['drying_date'], data['drying_method'], data['personnel'], data['status'])
        record = db.execute_returning(query + " RETURNING id, business_id, batch_id", params)
        logger.info(f"Drying batch {data['batch_id']} created.")
        return jsonify({
            'success': True,
            'message': 'Drying batch created successfully',
            'record': record,
            'id': record['id'],
            'business_id': record['business_id'],
        }), 201
    except Exception as e:
        logger.error(f"Error creating drying batch: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/drying/input', methods=['POST'])
@login_required
def create_drying_input():
    data = request.get_json()
    data = normalize_keys(data)
    if any(data.get(key) not in (None, '') for key in (
        'drying_batch_id', 'harvest_id', 'harvest_code', 'harvest_inputs', 'inputs'
    )):
        try:
            batch_ref = data.get('drying_batch_id') or data.get('batch_code') or data.get('batch_id')
            if batch_ref in (None, ''):
                raise ValueError('drying_batch_id or batch_code is required')
            rows = _drying_input_rows(data)
            with db.transaction() as cursor:
                batch = _drying_batch_row(cursor, batch_ref, for_update=True)
                _drying_add_inputs(cursor, batch, rows, data)
                record = _drying_batch_detail(cursor, batch)
            return jsonify({
                'success': True,
                'message': 'Drying inputs recorded',
                'data': record,
            }), 201
        except ProductionEventPermissionError as exc:
            return jsonify({'success': False, 'message': str(exc)}), 403
        except ValueError as exc:
            return jsonify({'success': False, 'message': str(exc)}), 400
        except Exception:
            logger.exception('Error recording canonical Drying inputs through legacy route')
            return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500
    
    # Basic validation
    required_fields = ['batch_id', 'wet_harvested', 'wet_placed', 'dried_by_personnel', 'sand_used']
    if any(f not in data for f in required_fields):
        return jsonify({'success': False, 'message': 'Missing required fields.'}), 400

    query = """INSERT INTO drying_input (batch_id, wet_harvested_kg, wet_placed_for_drying_kg, dried_by_personnel_kg, sand_used_kg, sand_reused_kg, notes, recorded_by) 
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"""
    params = (
        data['batch_id'], data['wet_harvested'], data['wet_placed'], 
        data['dried_by_personnel'], data['sand_used'], data.get('sand_reused'), data.get('notes'), current_user.username
    )
    db.execute_query(query, params)
    return jsonify({'success': True, 'message': 'Drying input recorded successfully.'})

@app.route('/api/drying/output', methods=['POST'])
@login_required
def create_drying_output():
    data = request.get_json()
    data = normalize_keys(data)
    if any(data.get(key) not in (None, '') for key in (
        'drying_batch_id', 'output_date', 'produced_at', 'output_unit', 'moisture_percent'
    )):
        batch_ref = data.get('drying_batch_id') or data.get('batch_code') or data.get('batch_id')
        if batch_ref in (None, ''):
            return jsonify({'success': False, 'message': 'drying_batch_id or batch_code is required'}), 400
        data['drying_batch_id'] = batch_ref
        return add_canonical_drying_output(batch_ref)
    required = ['batch_id', 'dried_produced']
    if any(field not in data for field in required):
        return jsonify({'success': False, 'message': 'Missing required fields'}), 400

    try:
        # Fetch the wet weight from drying_input to calculate ratio and yield
        input_query = "SELECT SUM(wet_placed_for_drying_kg) as total_wet FROM drying_input WHERE batch_id = %s"
        input_result = db.fetch_one(input_query, (data['batch_id'],))
        total_wet_weight = input_result['total_wet'] if input_result and input_result['total_wet'] else 0

        dried_produced = float(data['dried_produced'])
        actual_ratio = f"{total_wet_weight}:{dried_produced}" if dried_produced > 0 else "N/A"
        yield_percentage = (dried_produced / total_wet_weight) * 100 if total_wet_weight > 0 else 0

        query = """INSERT INTO drying_output (batch_id, dried_produced_kg, solar_drying_taken_kg, stored_in_silo_bag_kg, sold_kg, actual_ratio, yield_percentage, notes, recorded_by) 
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"""
        params = (
            data['batch_id'],
            dried_produced,
            data.get('solar_drying_taken'),
            data.get('silo_bag_stored'),
            data.get('dried_sold'),
            actual_ratio,
            yield_percentage,
            data.get('notes'),
            current_user.username
        )
        db.execute_query(query, params)
        logger.info(f"Drying output recorded for batch {data['batch_id']}")
        return jsonify({'success': True, 'message': 'Drying output recorded successfully', 'actual_ratio': actual_ratio, 'yield_percentage': yield_percentage}), 201
    except Exception as e:
        logger.error(f"Error in create_drying_output: {e}")
        return jsonify({'success': False, 'message': 'An error occurred'}), 500

@app.route('/api/drying/qc', methods=['POST'])
@login_required
def create_drying_qc():
    data = request.get_json()
    data = normalize_keys(data)
    if any(data.get(key) not in (None, '') for key in (
        'drying_batch_id', 'check_status', 'moisture_percent'
    )):
        return _canonical_quality_check_response(data)
    required = ['batch_id', 'qc_date', 'sand_removal', 'color_quality', 'moisture_level', 'qc_personnel']
    if any(field not in data for field in required):
        return jsonify({'success': False, 'message': 'Missing required fields'}), 400

    # Handle multiple selection for contaminants
    contaminants = data.get('contaminants_found', [])
    contaminants_str = ','.join(contaminants) if isinstance(contaminants, list) else contaminants

    query = """INSERT INTO drying_quality_control (batch_id, qc_date, sand_removal, contaminants_found, color_quality, moisture_level, qc_personnel, notes, recorded_by) 
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"""
    params = (data['batch_id'], data['qc_date'], data['sand_removal'], contaminants_str, data['color_quality'], data['moisture_level'], data['qc_personnel'], data.get('notes'), current_user.username)
    db.execute_query(query, params)
    return jsonify({'success': True, 'message': 'Drying QC recorded successfully.'})

@app.route('/api/drying/quality-control', methods=['POST'])
@login_required
def deprecated_create_drying_quality_control():
    # This is a deprecated route name, redirecting logic to the new one.
    return create_drying_qc()

@app.route('/api/drying/remarks', methods=['POST'])
@login_required
def create_drying_remarks():
    # This route seems to be unused based on frontend JS.
    # If it were to be used, it would likely add remarks to an existing batch.
    return jsonify({'success': False, 'message': 'This route is not implemented.'}), 404

@app.route('/api/drying/review', methods=['POST'])
@login_required
def create_drying_review():
    data = request.get_json()
    data = normalize_keys(data)
    if any(data.get(key) not in (None, '') for key in (
        'quality_check_id', 'check_id', 'drying_batch_id', 'decision'
    )):
        return create_canonical_drying_quality_approval()
    required = ['batch_id', 'reviewed_by', 'review_date', 'approval_status']
    if any(field not in data for field in required):
        return jsonify({'success': False, 'message': 'Missing required fields'}), 400

    query = """INSERT INTO drying_review_approval (batch_id, reviewed_by, review_date, approval_status, comments, recorded_by) 
               VALUES (%s, %s, %s, %s, %s, %s)"""
    params = (data['batch_id'], data['reviewed_by'], data['review_date'], data['approval_status'], data.get('comments'), current_user.username)
    db.execute_query(query, params)
    return jsonify({'success': True, 'message': 'Drying review recorded successfully.'})

# --- GET ALL (for potential future table views) ---
@app.route('/api/waste-sourcing/all', methods=['GET'])
@login_required
def get_all_waste_sourcing():
    query = "SELECT * FROM waste_sourcing ORDER BY collection_date DESC"
    records = db.fetch_all(query)
    return jsonify({'records': records, 'success': True})

@app.route('/api/drying/input/all', methods=['GET'])
@login_required
def get_all_drying_input():
    query = """
        SELECT di.*, db.id AS drying_batch_id_internal,
               db.business_id AS drying_batch_business_id
        FROM drying_input di
        LEFT JOIN drying_batches db ON db.batch_id = di.batch_id
        ORDER BY di.created_at DESC
    """
    records = db.fetch_all(query)
    return jsonify({'records': records, 'success': True})

@app.route('/api/drying/output/all', methods=['GET'])
@login_required
def get_all_drying_output():
    query = """
        SELECT dout.*, db.id AS drying_batch_id_internal,
               db.business_id AS drying_batch_business_id
        FROM drying_output dout
        LEFT JOIN drying_batches db ON db.batch_id = dout.batch_id
        ORDER BY dout.created_at DESC
    """
    records = db.fetch_all(query)
    return jsonify({'records': records, 'success': True})

@app.route('/api/drying/qc/all', methods=['GET'])
@login_required
def get_all_drying_qc():
    query = "SELECT * FROM drying_quality_control ORDER BY qc_date DESC"
    records = db.fetch_all(query)
    return jsonify({'records': records, 'success': True})

@app.route('/api/drying/remarks/all', methods=['GET'])
@login_required
def get_all_drying_remarks():
    return jsonify({'records': [], 'success': True})

@app.route('/api/drying/review/all', methods=['GET'])
@login_required
def get_all_drying_review():
    query = "SELECT * FROM drying_review_approval ORDER BY review_date DESC"
    records = db.fetch_all(query)
    return jsonify({'records': records, 'success': True})

@app.route('/api/feeding/harvest/all', methods=['GET'])
@login_required
def get_all_feeding_harvest():
    records = _harvest_report_rows()
    return jsonify({'records': records, 'success': True})

# --- Analytics GET Endpoints ---
@app.route('/api/analytics/waste-sourcing', methods=['GET'])
@login_required
def analytics_waste_sourcing():
    records = db.fetch_all("SELECT * FROM waste_sourcing ORDER BY collection_date DESC")
    return jsonify({'records': serialize_records(records), 'success': True})

@app.route('/api/analytics/storage-records', methods=['GET'])
@login_required
def analytics_storage_records():
    records = db.fetch_all("SELECT * FROM storage_records ORDER BY storage_date DESC")
    return jsonify({'records': records, 'success': True})

@app.route('/api/analytics/processing-records', methods=['GET'])
@login_required
def analytics_processing_records():
    records = db.fetch_all("SELECT * FROM processing_records ORDER BY processing_date DESC")
    return jsonify({'records': records, 'success': True})

@app.route('/api/analytics/waste-monitoring', methods=['GET'])
@app.route('/api/analytics/waste-env-monitoring', methods=['GET'])
@login_required
def analytics_waste_monitoring():
    records = db.fetch_all("SELECT * FROM waste_monitoring ORDER BY monitoring_date DESC")
    return jsonify({'records': serialize_records(records), 'success': True})

@app.route('/api/analytics/hatchery-batches', methods=['GET'])
@login_required
def analytics_hatchery_batches():
    records = db.fetch_all("SELECT * FROM hatchery_batches ORDER BY batch_date DESC")
    return jsonify({'records': records, 'success': True})

@app.route('/api/analytics/hatchery-feeding', methods=['GET'])
@login_required
def analytics_hatchery_feeding():
    records = db.fetch_all("SELECT * FROM hatchery_feeding ORDER BY feeding_date DESC")
    return jsonify({'records': records, 'success': True})

@app.route('/api/analytics/hatchery-monitoring', methods=['GET'])
@login_required
def analytics_hatchery_monitoring():
    records = db.fetch_all("SELECT * FROM hatchery_monitoring ORDER BY monitoring_date DESC")
    return jsonify({'records': records, 'success': True})

@app.route('/api/analytics/larvae-env-monitoring', methods=['GET'])
@login_required
def analytics_larvae_env_monitoring():
    records = db.fetch_all("SELECT * FROM environmental_monitoring_larvaefeeding ORDER BY monitoring_date DESC")
    return jsonify({'records': serialize_records(records), 'success': True})

@app.route('/api/analytics/substrate-preparation', methods=['GET'])
@login_required
def analytics_substrate_preparation():
    records = db.fetch_all("SELECT * FROM substrate_preparation ORDER BY prep_date DESC")
    return jsonify({'records': records, 'success': True})

@app.route('/api/analytics/health-intervention', methods=['GET'])
@login_required
def analytics_health_intervention():
    records = db.fetch_all("SELECT * FROM health_intervention ORDER BY health_date DESC")
    return jsonify({'records': records, 'success': True})

@app.route('/api/analytics/harvest-yield', methods=['GET'])
@login_required
def analytics_harvest_yield():
    records = _harvest_report_rows()
    return jsonify({'records': records, 'success': True})

@app.route('/api/analytics/feeding-schedule', methods=['GET'])
@login_required
def analytics_feeding_schedule():
    records = db.fetch_all("SELECT * FROM feeding_schedule ORDER BY feeding_date DESC")
    return jsonify({'records': records, 'success': True})

@app.route('/api/analytics/cage-monitoring', methods=['GET'])
@login_required
def analytics_cage_monitoring():
    records = db.fetch_all("SELECT * FROM cage_monitoring ORDER BY monitoring_date DESC")
    return jsonify({'records': records, 'success': True})

@app.route('/api/analytics/facility-maintenance', methods=['GET'])
@login_required
def analytics_facility_maintenance():
    records = db.fetch_all("SELECT * FROM facility_maintenance ORDER BY maintenance_date DESC")
    return jsonify({'records': records, 'success': True})

@app.route('/api/analytics/pupae-transition', methods=['GET'])
@login_required
def analytics_pupae_transition():
    records = db.fetch_all("SELECT * FROM pupae_transition ORDER BY transition_date DESC")
    return jsonify({'records': records, 'success': True})

@app.route('/api/analytics/egg-collection', methods=['GET'])
@login_required
def analytics_egg_collection():
    records = db.fetch_all("SELECT * FROM egg_collection ORDER BY collection_date DESC")
    return jsonify({'records': records, 'success': True})

@app.route('/api/analytics/bait-preparation', methods=['GET'])
@login_required
def analytics_bait_preparation():
    records = db.fetch_all("SELECT * FROM bait_preparation ORDER BY start_date DESC")
    return jsonify({'records': records, 'success': True})

@app.route('/api/analytics/drying-batches', methods=['GET'])
@login_required
def analytics_drying_batches():
    records = db.fetch_all("SELECT * FROM drying_batches ORDER BY drying_date DESC")
    return jsonify({'records': records, 'success': True})

@app.route('/api/analytics/customers', methods=['GET'])
@login_required
def analytics_customers():
    records = db.fetch_all("SELECT * FROM customers ORDER BY name")
    return jsonify({'records': records, 'success': True})

@app.route('/api/analytics/sales', methods=['GET'])
@login_required
def analytics_sales():
    records = db.fetch_all("SELECT s.*, c.name as customer_name FROM sales s JOIN customers c ON s.customer_id = c.id ORDER BY s.date DESC")
    return jsonify({'records': records, 'success': True})

@app.route('/api/analytics/deliveries', methods=['GET'])
@login_required
def analytics_deliveries():
    records = db.fetch_all("SELECT d.*, c.name as customer_name FROM deliveries d JOIN customers c ON d.customer_id = c.id ORDER BY d.date DESC")
    return jsonify({'records': records, 'success': True})

@app.route('/api/analytics/feedback', methods=['GET'])
@login_required
def analytics_feedback():
    records = db.fetch_all("SELECT f.*, c.name as customer_name FROM customer_feedback f JOIN customers c ON f.customer_id = c.id ORDER BY f.date DESC")
    return jsonify({'records': records, 'success': True})


# --- Feeding Section ---
@app.route('/api/feeding/environmental-monitoring', methods=['POST'])
@login_required
def create_feeding_environmental_monitoring():
    try:
        result = _create_monitoring_event(normalize_keys(request.get_json() or {}))
        return jsonify({
            'success': True,
            'message': 'Environmental monitoring data saved successfully',
            **result,
        }), 201
    except ProductionEventPermissionError as e:
        return jsonify({'success': False, 'message': str(e)}), 403
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        logger.error(f"Error saving larval env monitoring data: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500

@app.route('/api/feeding/health-intervention', methods=['POST'])
@login_required
def create_feeding_health_intervention():
    try:
        result = _create_health_event(normalize_keys(request.get_json() or {}))
        return jsonify({
            'success': True,
            'message': 'Health intervention data saved successfully',
            **result,
        }), 201
    except ProductionEventPermissionError as e:
        return jsonify({'success': False, 'message': str(e)}), 403
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        logger.error(f"Error saving health intervention data: {e}")
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500

@app.route('/api/feeding/harvest-yield', methods=['POST'])
@login_required
def create_feeding_harvest_yield():
    try:
        result = _create_harvest_event(normalize_keys(request.get_json() or {}))
        return jsonify({
            'success': True,
            'message': 'Harvest recorded',
            **result,
        }), 201
    except ProductionEventPermissionError as e:
        return jsonify({'success': False, 'message': str(e)}), 403
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        logger.error(f"Error saving harvest/yield data: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500

@app.route('/api/feeding/schedule', methods=['POST'])
@login_required
def create_feeding_schedule():
    try:
        result = _create_feeding_event(normalize_keys(request.get_json() or {}))
        return jsonify({
            'success': True,
            'message': 'Feeding schedule saved successfully',
            **result,
        }), 201
    except ProductionEventPermissionError as e:
        return jsonify({'success': False, 'message': str(e)}), 403
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        logger.error(f"Error saving feeding schedule: {e}")
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500

# --- Fly Facility Section ---
@app.route('/api/facility/cage-monitoring', methods=['POST'])
@login_required
def create_cage_monitoring():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'Invalid JSON format'}), 400

    data = normalize_keys(data)
    
    required_fields = ['date', 'cage_id', 'temperature', 'humidity', 'lighting_hours', 'ventilation_ok', 'cage_cleaned', 'cage_damage']
    if any(field not in data for field in required_fields):
        return jsonify({'success': False, 'message': 'Missing required fields'}), 400

    try:
        query = """
            INSERT INTO cage_monitoring (
                monitoring_date, cage_id, temperature, humidity, lighting_hours, ventilation_ok, 
                cage_cleaned, cage_damage, damage_notes, additional_notes, cages_damaged_list, recorded_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (
            data['date'], data['cage_id'], data['temperature'], data['humidity'], data['lighting_hours'],
            data['ventilation_ok'], data['cage_cleaned'], data['cage_damage'],
            data.get('damage_notes'), data.get('additional_notes'), data.get('cages_damaged_list'), current_user.username
        )
        db.execute_query(query, params)
        logger.info(f"Cage monitoring recorded for {data['cage_id']}")
        return jsonify({'success': True, 'message': 'Cage monitoring data saved successfully'}), 201
    except Exception as e:
        logger.error(f"Error saving cage monitoring data: {e}")
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500

@app.route('/api/facility/maintenance', methods=['POST'])
@login_required
def create_facility_maintenance():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'Invalid JSON format'}), 400
    
    data = normalize_keys(data)

    required_fields = ['date', 'moat_check', 'ants_present', 'rodents_present', 'bird_net_ok', 'trench_refilled', 'maintenance_notes']
    if any(field not in data for field in required_fields):
        return jsonify({'success': False, 'message': 'Missing required fields'}), 400

    try:
        query = """
            INSERT INTO facility_maintenance (
                maintenance_date, moat_check, ants_present, rodents_present, bird_net_ok, 
                trench_refilled, maintenance_notes, recorded_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (
            data['date'], data['moat_check'], data['ants_present'], data['rodents_present'],
            data['bird_net_ok'], data['trench_refilled'], data['maintenance_notes'], current_user.username
        )
        db.execute_query(query, params)
        logger.info(f"Facility maintenance recorded for {data['date']}")
        return jsonify({'success': True, 'message': 'Facility maintenance data saved successfully'}), 201
    except Exception as e:
        logger.error(f"Error saving facility maintenance data: {e}")
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500

@app.route('/api/facility/pupae-transition', methods=['POST'])
@login_required
def create_pupae_transition():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'Invalid JSON format'}), 400

    data = normalize_keys(data)
    
    required_fields = ['date', 'love_cage_id', 'pupae_weight_added_kg', 'old_pupae_removed_kg', 'dead_flies_removed', 'water_points_checked', 'new_egg_crates_installed']
    if any(field not in data for field in required_fields):
        return jsonify({'success': False, 'message': 'Missing required fields'}), 400

    try:
        query = """
            INSERT INTO pupae_transition (
                transition_date, love_cage_id, pupae_weight_added, old_pupae_removed, dead_flies_removed, 
                water_points_checked, new_egg_crates_installed, number_of_crates, notes, recorded_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (
            data['date'], data['love_cage_id'],
            data['pupae_weight_added_kg'], data['old_pupae_removed_kg'],
            data['dead_flies_removed'], data['water_points_checked'], data['new_egg_crates_installed'],
            data.get('number_of_crates'), data.get('notes'), current_user.username
        )
        db.execute_query(query, params)
        logger.info(f"Pupae transition recorded for {data['love_cage_id']}")
        return jsonify({'success': True, 'message': 'Pupae transition data saved successfully'}), 201
    except Exception as e:
        logger.error(f"Error saving pupae transition data: {e}")
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500

@app.route('/api/facility/egg-collection', methods=['POST'])
@login_required
def create_egg_collection():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'Invalid JSON format'}), 400

    data = normalize_keys(data)

    required_fields = ['date', 'time', 'cage_id', 'eggs_collected', 'bait_replaced', 'eggs_intact', 'collector_name', 'collection_method']
    if any(field not in data for field in required_fields):
        return jsonify({'success': False, 'message': 'Missing required fields'}), 400

    try:
        query = """
            INSERT INTO egg_collection (
                collection_date, collection_time, cage_id, eggs_collected, bait_replaced, 
                eggs_intact, collector_name, collection_method, notes, recorded_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (
            data['date'], data['time'], data['cage_id'], data['eggs_collected'], data['bait_replaced'],
            data['eggs_intact'], data['collector_name'], data['collection_method'], data.get('notes'), current_user.username
        )
        db.execute_query(query, params)
        logger.info(f"Egg collection recorded for {data['cage_id']}")
        return jsonify({'success': True, 'message': 'Egg collection data saved successfully'}), 201
    except Exception as e:
        logger.error(f"Error saving egg collection data: {e}")
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500

@app.route('/api/facility/bait-preparation', methods=['POST'])
@login_required
def create_bait_preparation():
    data = request.get_json()
    normalized_data = normalize_keys(data)
    required_fields = ['barrel_id', 'bait_type', 'ingredients_added', 'start_date', 'ready_date']
    
    missing_fields = [field for field in required_fields if field not in normalized_data or not normalized_data.get(field)]
    if missing_fields:
        return jsonify({'success': False, 'message': f'Missing or empty required fields: {", ".join(missing_fields)}'}), 400
        
    query = """
        INSERT INTO bait_preparation (barrel_id, bait_type, ingredients_added, start_date, ready_date, used_in_cage_ids, notes, recorded_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """
    params = (
        normalized_data.get('barrel_id'),
        normalized_data.get('bait_type'),
        normalized_data.get('ingredients_added'),
        normalized_data.get('start_date'),
        normalized_data.get('ready_date'),
        normalized_data.get('used_in_cage_ids'),
        normalized_data.get('notes'),
        current_user.username
    )
    
    try:
        db.execute_query(query, params)
        logger.info(f"Bait preparation data saved for barrel {normalized_data.get('barrel_id')}")
        return jsonify({'success': True, 'message': 'Bait preparation record created successfully'})
    except Exception as e:
        logger.error(f"Error creating bait preparation record: {e}")
        return jsonify({'success': False, 'message': 'Failed to create bait preparation record'}), 500

@app.route('/api/records', methods=['GET'])
@login_required
def get_records_by_date_and_section():
    target_date_str = request.args.get('date')
    section = request.args.get('section')

    if not target_date_str:
        return jsonify({'success': False, 'message': 'Date parameter is required'}), 400

    try:
        target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'success': False, 'message': 'Invalid date format. Please use YYYY-MM-DD.'}), 400

    # Map sections to tables and their respective date columns
    section_tables = {
        'waste': {
            'Waste Sourcing': ('waste_sourcing', 'collection_date'),
            'Storage Records': ('storage_records', 'storage_date'),
            'Processing Records': ('processing_records', 'processing_date'),
            'Waste Monitoring': ('waste_monitoring', 'monitoring_date'),
        },
        'hatchery': {
            'Batch Information': ('hatchery_batches', 'batch_date'),
            'Feeding Records': ('hatchery_feeding', 'feeding_date'),
            'Environmental Monitoring': ('hatchery_monitoring', 'monitoring_date'),
            'Cleaning & Sanitation': ('hatchery_cleaning', 'cleaning_date'),
            'Problems & Solutions': ('hatchery_problems', 'problem_date'),
        },
        'feeding': {
            'Environmental Monitoring': ('environmental_monitoring_larvaefeeding', 'monitoring_date'),
            'Health & Intervention': ('health_intervention', 'health_date'),
            'Harvest & Yield': ('harvest_yield', 'harvest_date'),
            'Feeding Schedule': ('feeding_schedule', 'feeding_date'),
        },
        'drying': {
            'Batch Information': ('drying_batches', 'drying_date'),
            'Input Records': ('drying_input', 'created_at'),
            'Output Records': ('drying_output', 'created_at'),
            'Quality Control': ('drying_quality_control', 'qc_date'),
            'Review & Approval': ('drying_review_approval', 'review_date'),
        },
        'facility': {
            'Cage Monitoring': ('cage_monitoring', 'monitoring_date'),
            'Facility Maintenance': ('facility_maintenance', 'maintenance_date'),
            'Pupae Transition': ('pupae_transition', 'transition_date'),
            'Egg Collection': ('egg_collection', 'collection_date'),
            'Bait Preparation': ('bait_preparation', 'start_date'),
        }
    }

    tables_to_query = {}
    if section == 'all':
        for sec in section_tables:
            tables_to_query.update(section_tables[sec])
    elif section in section_tables:
        tables_to_query = section_tables[section]
    else:
        return jsonify({'success': False, 'message': 'Invalid section specified'}), 400

    all_records = {}
    try:
        for display_name, (table_name, date_col) in tables_to_query.items():
            # The DATE() function is used to ignore the time part of datetime columns
            query = f"SELECT * FROM {table_name} WHERE DATE({date_col}) = %s"
            records = db.fetch_all(query, (target_date,))
            if records:
                # Convert datetime and timedelta objects to strings for JSON serialization
                for record in records:
                    for key, value in record.items():
                        if isinstance(value, (datetime, timedelta)):
                            record[key] = str(value)
                all_records[display_name] = records
        
        return jsonify({'success': True, 'records': all_records})

    except Exception as e:
        logger.error(f"Error fetching records for date {target_date_str} and section {section}: {e}")
        return jsonify({'success': False, 'message': 'An error occurred while fetching records.'}), 500

# --- Hatchery Routes ---

@app.route('/api/hatchery/batch', methods=['POST'])
@login_required
def create_hatchery_batch():
    try:
        data = request.get_json()
        required_fields = [
            'batch_date', 'egg_incubation_date',
            'total_eggs_grams', 'expected_hatch_date', 'supervisor_name'
        ]
        if any(f not in data for f in required_fields):
            return jsonify({'error': 'Missing required fields'}), 400
        
        query = '''INSERT INTO hatchery_batches (
            batch_number, batch_date, egg_incubation_date, total_eggs_grams,
            expected_hatch_date, actual_hatch_date, hatch_days, supervisor_name, notes
        ) VALUES (COALESCE(%s, ('HAT-' || to_char(CURRENT_DATE, 'YYYY') || '-' ||
                                lpad(nextval('phase_one_hatchery_batch_seq')::text, 5, '0'))),
                  %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id, batch_number'''
        params = (
            data.get('batch_number'), data['batch_date'], data['egg_incubation_date'],
            float(data['total_eggs_grams']), data['expected_hatch_date'],
            data.get('actual_hatch_date'), data.get('hatch_days'),
            data['supervisor_name'], data.get('notes')
        )
        record = db.execute_returning(query, params)
        return jsonify({
            'success': True,
            'message': 'Batch information saved successfully',
            'record': record,
            'id': record['id'],
            'business_id': record['batch_number'],
        }), 201
    except Exception as e:
        logger.error(f'Error saving hatchery batch: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/hatchery/next-batch-id', methods=['GET'])
@login_required
def get_next_hatchery_batch_id():
    try:
        record = db.execute_returning("""
            SELECT 'HAT-' || to_char(CURRENT_DATE, 'YYYY') || '-' ||
                   lpad(nextval('phase_one_hatchery_batch_seq')::text, 5, '0') AS next_batch_id
        """)
        return jsonify({'next_batch_id': record['next_batch_id']}), 200
    except Exception as e:
        logger.error(f'Error getting next hatchery batch ID: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/hatchery/feeding', methods=['POST'])
@login_required
def create_hatchery_feeding():
    try:
        data = request.get_json()
        required_fields = [
            'batch_id', 'feeding_date', 'feed_per_5g_eggs_grams',
            'total_feed_used_grams', 'days_to_utilize', 'feed_type', 'distribution_method'
        ]
        if any(f not in data for f in required_fields):
            return jsonify({'error': 'Missing required fields'}), 400

        query = '''INSERT INTO hatchery_feeding (
            batch_id, feeding_date, feed_per_5g_eggs_grams, total_feed_used_grams,
            days_to_utilize, feed_type, distribution_method, notes
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)'''
        params = (
            data['batch_id'], data['feeding_date'], float(data['feed_per_5g_eggs_grams']),
            float(data['total_feed_used_grams']), int(data['days_to_utilize']),
            data['feed_type'], data['distribution_method'], data.get('notes')
        )
        db.execute_query(query, params)
        return jsonify({'message': 'Feeding record saved successfully'}), 201
    except Exception as e:
        logger.error(f'Error saving feeding record: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/hatchery/monitoring', methods=['POST'])
@login_required
def create_hatchery_monitoring():
    try:
        data = request.get_json()
        required_fields = ['monitoring_date', 'temperature_c', 'humidity_percent']
        if any(f not in data for f in required_fields):
            return jsonify({'error': 'Missing required fields'}), 400

        query = '''INSERT INTO hatchery_monitoring (
            monitoring_date, temperature_c, humidity_percent, adjustments_made
        ) VALUES (%s, %s, %s, %s)'''
        params = (
            data['monitoring_date'], float(data['temperature_c']), float(data['humidity_percent']), data.get('adjustments_made')
        )
        db.execute_query(query, params)
        return jsonify({'message': 'Monitoring record saved successfully'}), 201
    except Exception as e:
        logger.error(f'Error saving monitoring record: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/hatchery/cleaning', methods=['POST'])
@login_required
def create_hatchery_cleaning():
    try:
        data = request.get_json()
        required_fields = ['cleaning_date', 'areas_cleaned', 'cleaning_materials', 'cleaning_personnel']
        if any(f not in data for f in required_fields):
            return jsonify({'error': 'Missing required fields'}), 400

        query = '''INSERT INTO hatchery_cleaning (
            cleaning_date, areas_cleaned, cleaning_materials, cleaning_personnel, remarks
        ) VALUES (%s, %s, %s, %s, %s)'''
        params = (
            data['cleaning_date'], data['areas_cleaned'], data['cleaning_materials'], data['cleaning_personnel'], data.get('remarks')
        )
        db.execute_query(query, params)
        return jsonify({'message': 'Cleaning record saved successfully'}), 201
    except Exception as e:
        logger.error(f'Error saving cleaning record: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/hatchery/problems', methods=['POST'])
@login_required
def create_hatchery_problem():
    try:
        data = request.get_json()
        required_fields = ['problem_date', 'problem_identified', 'proposed_solution', 'responsible_person']
        if any(f not in data for f in required_fields):
            return jsonify({'error': 'Missing required fields'}), 400

        query = '''INSERT INTO hatchery_problems (
            problem_date, problem_identified, proposed_solution, responsible_person,
            days_to_implement, resolution_status, additional_comments
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)'''
        params = (
            data['problem_date'], data['problem_identified'], data['proposed_solution'],
            data['responsible_person'], data.get('days_to_implement'), data.get('resolution_status'), data.get('additional_comments')
        )
        db.execute_query(query, params)
        return jsonify({'message': 'Problem record saved successfully'}), 201
    except Exception as e:
        logger.error(f'Error saving problem record: {e}')
        return jsonify({'error': str(e)}), 500

# Add missing hatchery endpoints that frontend is calling
@app.route('/api/hatchery/health', methods=['POST'])
@login_required
def create_hatchery_health():
    try:
        # Debug: Check if request has JSON content
        if not request.is_json:
            logger.error(f"Request is not JSON. Content-Type: {request.content_type}")
            return jsonify({'error': 'Request must be JSON'}), 400
        
        data = request.get_json()
        if data is None:
            logger.error("Failed to parse JSON data")
            return jsonify({'error': 'Invalid JSON data'}), 400
            
        required_fields = ['health_date', 'health_issue', 'severity', 'action_taken']
        if any(f not in data for f in required_fields):
            return jsonify({'error': 'Missing required fields'}), 400

        query = '''INSERT INTO hatchery_health_interventions (
            health_date, health_issue, severity, action_taken, follow_up_date, resolved, comments
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)'''
        params = (
            data['health_date'], data['health_issue'], data['severity'], data['action_taken'],
            data.get('follow_up_date'), data.get('resolved'), data.get('comments')
        )
        db.execute_query(query, params)
        return jsonify({'message': 'Health intervention record saved successfully'}), 201
    except Exception as e:
        logger.error(f'Error saving health intervention record: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/hatchery/batch-information', methods=['POST'])
@login_required
def create_hatchery_batch_information():
    # Alias for the existing batch endpoint
    return create_hatchery_batch()

@app.route('/api/hatchery/feeding-records', methods=['POST'])
@login_required
def create_hatchery_feeding_records():
    # Alias for the existing feeding endpoint
    return create_hatchery_feeding()

@app.route('/api/hatchery/environmental-monitoring', methods=['POST'])
@login_required
def create_hatchery_environmental_monitoring():
    # Alias for the existing monitoring endpoint
    return create_hatchery_monitoring()

# --- Customers CRUD ---
@app.route('/api/customers', methods=['GET'])
@login_required
def get_customers():
    customers = db.fetch_all("SELECT * FROM customers")
    return jsonify(customers)

@app.route('/api/customers', methods=['POST'])
@login_required
def add_customer():
    data = request.get_json()
    # Check for existing customer with same name and email
    existing = db.fetch_one("SELECT id FROM customers WHERE name=%s AND email=%s", (data['name'], data.get('email')))
    if existing:
        return jsonify({'success': False, 'error': 'Customer with this name and email already exists.'}), 409
    query = "INSERT INTO customers (name, contact, email, address) VALUES (%s, %s, %s, %s)"
    customer_id = db.execute_query(query, (data['name'], data.get('contact'), data.get('email'), data.get('address')))
    return jsonify({'success': True, 'id': customer_id})

@app.route('/api/customers/<int:customer_id>', methods=['PUT'])
@login_required
def edit_customer(customer_id):
    data = request.get_json()
    query = "UPDATE customers SET name=%s, contact=%s, email=%s, address=%s WHERE id=%s"
    db.execute_query(query, (data['name'], data.get('contact'), data.get('email'), data.get('address'), customer_id))
    return jsonify({'success': True})

# --- Sales CRUD ---
@app.route('/api/sales', methods=['GET'])
@login_required
def get_sales():
    sales = db.fetch_all("SELECT s.*, c.name as customer_name FROM sales s JOIN customers c ON s.customer_id = c.id")
    return jsonify(sales)

@app.route('/api/sales', methods=['POST'])
@login_required
def add_sale():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400
    customer_id = data.get('customer_id') or data.get('customer')
    if not customer_id:
        return jsonify({'success': False, 'error': 'customer_id is required'}), 400
    if not data.get('date') or not data.get('amount'):
        return jsonify({'success': False, 'error': 'date and amount are required'}), 400
    query = "INSERT INTO sales (date, customer_id, product, quantity, amount) VALUES (%s, %s, %s, %s, %s)"
    sale_id = db.execute_query(query, (data['date'], customer_id, data.get('product'), data.get('quantity'), data['amount']))
    # Send email notification for sale
    customer = db.fetch_one("SELECT name, email, address FROM customers WHERE id=%s", (customer_id,))
    print("[DEBUG] Customer fetched from DB (sale):", customer)
    if customer and customer.get('email'):
        subject = f"Sale Confirmation for {customer['name']}"
        body = (
            f"Dear {customer['name']},\n\n"
            f"Thank you for your purchase! Here are your sale details:\n"
            f"Date: {data['date']}\n"
            f"Product/Service: {data.get('product', '')}\n"
            f"Quantity: {data.get('quantity', '')}\n"
            f"Amount: {data.get('amount', '')}\n"
            f"Delivery Address: {customer.get('address', '')}\n\n"
            f"Best regards,\nBSF Farm Manager"
        )
        send_email(subject, body, [customer['email'], ADMIN_EMAIL])
    return jsonify({'success': True, 'id': sale_id})

@app.route('/api/sales/<int:sale_id>', methods=['PUT'])
@login_required
def edit_sale(sale_id):
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400
    customer_id = data.get('customer_id') or data.get('customer')
    if not customer_id:
        return jsonify({'success': False, 'error': 'customer_id is required'}), 400
    query = "UPDATE sales SET date=%s, customer_id=%s, product=%s, quantity=%s, amount=%s WHERE id=%s"
    db.execute_query(query, (data['date'], customer_id, data.get('product'), data.get('quantity'), data['amount'], sale_id))
    return jsonify({'success': True})

# --- Deliveries CRUD ---
@app.route('/api/deliveries', methods=['GET'])
@login_required
def get_deliveries():
    deliveries = db.fetch_all("SELECT d.*, c.name as customer_name FROM deliveries d JOIN customers c ON d.customer_id = c.id")
    return jsonify(deliveries)

@app.route('/api/deliveries', methods=['POST'])
@login_required
def add_delivery():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400
    customer_id = data.get('customer_id') or data.get('customer')
    if not customer_id:
        return jsonify({'success': False, 'error': 'customer_id is required'}), 400
    if not data.get('date') or not data.get('status'):
        return jsonify({'success': False, 'error': 'date and status are required'}), 400
    query = "INSERT INTO deliveries (date, customer_id, product, quantity, status, notes) VALUES (%s, %s, %s, %s, %s, %s)"
    delivery_id = db.execute_query(query, (data['date'], customer_id, data.get('product'), data.get('quantity'), data['status'], data.get('notes')))
    # Send email for any status
    customer = db.fetch_one("SELECT name, email, address FROM customers WHERE id=%s", (customer_id,))
    print("[DEBUG] Customer fetched from DB (delivery):", customer)
    if customer and customer.get('email'):
        subject = f"Delivery Update for {customer['name']}"
        body = (
            f"Dear {customer['name']},\n\n"
            f"Your delivery status is now: {data['status']}\n"
            f"Date of Delivery: {data['date']}\n"
            f"Product/Service: {data.get('product', '')}\n"
            f"Quantity: {data.get('quantity', '')}\n"
            f"Delivery Address: {customer.get('address', '')}\n\n"
            f"Best regards,\nBSF Farm Manager"
        )
        send_email(subject, body, [customer['email'], ADMIN_EMAIL])
    return jsonify({'success': True, 'id': delivery_id})

@app.route('/api/deliveries/<int:delivery_id>', methods=['PUT'])
@login_required
def edit_delivery(delivery_id):
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400
    customer_id = data.get('customer_id') or data.get('customer')
    if not customer_id:
        return jsonify({'success': False, 'error': 'customer_id is required'}), 400
    # Fetch previous status
    prev = db.fetch_one("SELECT status FROM deliveries WHERE id=%s", (delivery_id,))
    prev_status = prev['status'] if prev else None
    query = "UPDATE deliveries SET date=%s, customer_id=%s, product=%s, quantity=%s, status=%s, notes=%s WHERE id=%s"
    db.execute_query(query, (data['date'], customer_id, data.get('product'), data.get('quantity'), data['status'], data.get('notes'), delivery_id))
    # Send email if status is Delivered and was not previously Delivered
    if data['status'].strip().lower() == 'delivered' and (not prev_status or prev_status.strip().lower() != 'delivered'):
        customer = db.fetch_one("SELECT name, email, address FROM customers WHERE id=%s", (customer_id,))
        if customer and customer.get('email'):
            subject = f"Delivery Confirmation for {customer['name']}"
            body = (
                f"Dear {customer['name']},\n\n"
                f"Your delivery has been completed. Here are your delivery details:\n"
                f"Date of Delivery: {data['date']}\n"
                f"Product/Service: {data.get('product', '')}\n"
                f"Quantity: {data.get('quantity', '')}\n"
                f"Delivery Address: {customer.get('address', '')}\n\n"
                f"Best regards,\nBSF Farm Manager"
            )
            send_email(subject, body, [customer['email'], ADMIN_EMAIL])
    return jsonify({'success': True})

# --- Customer Feedback CRUD ---
@app.route('/api/feedback', methods=['GET'])
@login_required
def get_feedback():
    feedback = db.fetch_all("SELECT f.*, c.name as customer_name FROM customer_feedback f JOIN customers c ON f.customer_id = c.id")
    return jsonify(feedback)

@app.route('/api/feedback', methods=['POST'])
@login_required
def add_feedback():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400
    required = ['date', 'customer_id', 'feedback', 'rating']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({'success': False, 'error': f'Missing required fields: {", ".join(missing)}'}), 400
    try:
        query = "INSERT INTO customer_feedback (date, customer_id, feedback, rating) VALUES (%s, %s, %s, %s)"
        feedback_id = db.execute_query(query, (data['date'], data['customer_id'], data['feedback'], data['rating']))
        return jsonify({'success': True, 'id': feedback_id})
    except Exception as e:
        logger.error(f"Error saving feedback: {e}")
        return jsonify({'success': False, 'error': 'Failed to save feedback'}), 500

@app.route('/api/feedback/<int:feedback_id>', methods=['PUT'])
@login_required
def edit_feedback(feedback_id):
    data = request.get_json()
    query = "UPDATE customer_feedback SET date=%s, customer_id=%s, feedback=%s, rating=%s WHERE id=%s"
    db.execute_query(query, (data['date'], data['customer_id'], data['feedback'], data['rating'], feedback_id))
    return jsonify({'success': True})

# ---- Operational reports ------------------------------------------------------
#
# Each report reads the Phase One tables, is limited to the caller's
# locations (facility access for operations, farm access for commercial and
# farm-level figures) and returns typed columns so the browser can show it
# and export it to Excel/PDF; CSV is produced here.

REPORT_ROW_LIMIT = 5000
KG_SQL = "CASE WHEN {unit} = 'g' THEN {qty} / 1000 ELSE {qty} END"


class _ReportQuery:
    """Collects WHERE clauses and parameters for one report."""

    def __init__(self, filters, *, scope_alias, commercial=False):
        self.filters = filters
        self.clauses = []
        self.params = []
        visibility, params = (
            _farm_visibility_clause(scope_alias) if commercial
            else _scope_visibility_clause(scope_alias)
        )
        self.add(visibility, *params)
        if filters['farm_id']:
            self.add(f'{scope_alias}.farm_id = %s', filters['farm_id'])
        if filters['facility_id'] and not commercial:
            self.add(f'{scope_alias}.facility_id = %s', filters['facility_id'])

    def add(self, clause, *params):
        self.clauses.append(clause)
        self.params.extend(params)

    def dates(self, column):
        if self.filters['date_from']:
            self.add(f'({column})::date >= %s', self.filters['date_from'])
        if self.filters['date_to']:
            self.add(f'({column})::date <= %s', self.filters['date_to'])

    @property
    def where(self):
        return 'WHERE ' + ' AND '.join(self.clauses)


def _report_waste(cursor, f):
    q = _ReportQuery(f, scope_alias='wl')
    q.dates('wl.collection_date')
    if f['status']:
        q.add('UPPER(wl.status) = %s', f['status'])
    cursor.execute(
        f"""
        SELECT wl.collection_date AS date, wl.business_id AS waste_lot,
               wl.source_type, wl.source_name, wl.waste_type,
               wl.quantity AS received_kg, COALESCE(u.used, 0) AS used_kg,
               wl.quantity - COALESCE(u.used, 0) AS remaining_kg,
               wl.quality_status, UPPER(wl.status) AS status,
               f.name AS farm, fa.name AS facility
        FROM waste_lots AS wl
        LEFT JOIN (SELECT waste_lot_id, SUM(quantity_used) AS used
                   FROM substrate_batch_inputs GROUP BY waste_lot_id) AS u ON u.waste_lot_id = wl.id
        LEFT JOIN farms AS f ON f.id = wl.farm_id
        LEFT JOIN facilities AS fa ON fa.id = wl.facility_id
        {q.where}
        ORDER BY wl.collection_date DESC, wl.id DESC
        """,
        q.params,
    )
    return cursor.fetchall()


def _report_substrate(cursor, f):
    q = _ReportQuery(f, scope_alias='sb')
    q.dates('sb.preparation_date')
    cursor.execute(
        f"""
        SELECT sb.preparation_date AS date, sb.business_id AS substrate_batch,
               fa.name AS facility,
               (SELECT COUNT(*) FROM substrate_batch_inputs WHERE substrate_batch_id = sb.id) AS waste_lots,
               sb.total_input_weight_kg AS input_kg,
               COALESCE((SELECT SUM(quantity_issued) FROM production_batch_inputs
                         WHERE substrate_batch_id = sb.id), 0) AS issued_kg,
               COALESCE(sb.output_weight_kg, sb.total_input_weight_kg, 0) - COALESCE((
                   SELECT SUM(quantity_issued) FROM production_batch_inputs
                   WHERE substrate_batch_id = sb.id), 0) AS available_kg,
               sb.particle_size, sb.recorded_by
        FROM substrate_batches AS sb
        LEFT JOIN facilities AS fa ON fa.id = sb.facility_id
        {q.where}
        ORDER BY sb.preparation_date DESC, sb.id DESC
        """,
        q.params,
    )
    return cursor.fetchall()


def _report_production(cursor, f):
    q = _ReportQuery(f, scope_alias='pb')
    q.dates('pb.start_date')
    if f['status']:
        q.add('UPPER(pb.status) = %s', f['status'])
    cursor.execute(
        f"""
        SELECT pb.business_id AS production_batch, fa.name AS facility,
               pb.start_date, UPPER(pb.status) AS status, pb.current_stage AS stage,
               pb.expected_harvest_at::date AS expected_harvest,
               GREATEST(CURRENT_DATE - pb.start_date, 0) AS age_days,
               COALESCE(i.issued, 0) AS substrate_kg, COALESCE(h.harvested, 0) AS harvested_kg,
               CASE WHEN COALESCE(i.issued, 0) > 0 AND h.harvested IS NOT NULL
                    THEN ROUND(h.harvested / i.issued * 100, 1) END AS harvest_per_substrate_pct
        FROM production_batches AS pb
        LEFT JOIN facilities AS fa ON fa.id = pb.facility_id
        LEFT JOIN (SELECT production_batch_id, SUM(quantity_issued) AS issued
                   FROM production_batch_inputs GROUP BY 1) AS i ON i.production_batch_id = pb.id
        LEFT JOIN (SELECT production_batch_id, SUM(quantity) AS harvested
                   FROM production_events WHERE event_type = 'harvest' AND status = 'recorded'
                   GROUP BY 1) AS h ON h.production_batch_id = pb.id
        {q.where}
        ORDER BY pb.start_date DESC, pb.id DESC
        """,
        q.params,
    )
    return cursor.fetchall()


def _report_feeding(cursor, f):
    q = _ReportQuery(f, scope_alias='pe')
    q.add("pe.event_type = 'feeding' AND pe.status = 'recorded'")
    q.dates('pe.occurred_at')
    cursor.execute(
        f"""
        SELECT pe.occurred_at::date AS date, pb.business_id AS production_batch,
               fe.feed_type,
               {KG_SQL.format(unit='fe.offered_unit', qty='fe.quantity_offered')} AS offered_kg,
               {KG_SQL.format(unit='fe.consumed_unit', qty='fe.quantity_consumed')} AS consumed_kg,
               {KG_SQL.format(unit='fe.biomass_unit', qty='fe.larvae_biomass')} AS larvae_biomass_kg,
               fe.larvae_age_days, pe.actor AS recorded_by, fa.name AS facility
        FROM production_events AS pe
        JOIN feeding_events AS fe ON fe.production_event_id = pe.id
        JOIN production_batches AS pb ON pb.id = pe.production_batch_id
        LEFT JOIN facilities AS fa ON fa.id = pe.facility_id
        {q.where}
        ORDER BY pe.occurred_at DESC, pe.id DESC
        """,
        q.params,
    )
    return cursor.fetchall()


def _report_harvest(cursor, f):
    q = _ReportQuery(f, scope_alias='pe')
    q.add("pe.event_type = 'harvest' AND pe.status = 'recorded'")
    q.dates('pe.occurred_at')
    cursor.execute(
        f"""
        SELECT pe.occurred_at::date AS date, h.harvest_code AS harvest,
               pb.business_id AS production_batch, pe.quantity AS wet_kg,
               h.harvest_stage AS stage, h.operator, h.location, fa.name AS facility,
               COALESCE((SELECT SUM({KG_SQL.format(unit='di.unit', qty='di.quantity')})
                         FROM drying_inputs AS di WHERE di.harvest_id = h.id), 0) AS sent_to_drying_kg
        FROM harvests AS h
        JOIN production_events AS pe ON pe.id = h.production_event_id
        JOIN production_batches AS pb ON pb.id = pe.production_batch_id
        LEFT JOIN facilities AS fa ON fa.id = pe.facility_id
        {q.where}
        ORDER BY pe.occurred_at DESC, h.id DESC
        """,
        q.params,
    )
    return cursor.fetchall()


def _report_drying(cursor, f):
    q = _ReportQuery(f, scope_alias='db')
    q.add('db.farm_id IS NOT NULL')
    q.dates('db.drying_date')
    if f['status']:
        q.add('UPPER(db.status) = %s', f['status'])
    cursor.execute(
        f"""
        SELECT COALESCE(db.business_id, db.batch_code) AS drying_batch, db.drying_date AS date,
               db.drying_method AS method, UPPER(db.status) AS status, fa.name AS facility,
               COALESCE(i.wet, 0) AS wet_in_kg, COALESCE(o.dry, 0) AS dry_out_kg,
               CASE WHEN COALESCE(i.wet, 0) > 0 AND o.dry IS NOT NULL
                    THEN ROUND(o.dry / i.wet * 100, 1) END AS yield_pct,
               o.moisture AS moisture_pct,
               (SELECT string_agg(DISTINCT pb.business_id, ', ')
                FROM drying_inputs AS di
                JOIN harvests AS h ON h.id = di.harvest_id
                JOIN production_events AS pe ON pe.id = h.production_event_id
                JOIN production_batches AS pb ON pb.id = pe.production_batch_id
                WHERE di.drying_batch_id = db.id) AS production_batches
        FROM drying_batches AS db
        LEFT JOIN facilities AS fa ON fa.id = db.facility_id
        LEFT JOIN (SELECT drying_batch_id,
                          SUM({KG_SQL.format(unit='unit', qty='quantity')}) AS wet
                   FROM drying_inputs GROUP BY 1) AS i ON i.drying_batch_id = db.id
        LEFT JOIN (SELECT drying_batch_id,
                          SUM({KG_SQL.format(unit='unit', qty='quantity')}) AS dry,
                          (array_agg(moisture_percent ORDER BY line_no DESC))[1] AS moisture
                   FROM drying_outputs GROUP BY 1) AS o ON o.drying_batch_id = db.id
        {q.where}
        ORDER BY db.drying_date DESC, db.id DESC
        """,
        q.params,
    )
    return cursor.fetchall()


def _report_quality(cursor, f):
    q = _ReportQuery(f, scope_alias='db')
    q.dates('COALESCE(qc.checked_at, qc.created_at)')
    if f['status']:
        q.add('UPPER(qc.status) = %s', f['status'])
    cursor.execute(
        f"""
        SELECT COALESCE(qc.checked_at, qc.created_at)::date AS date, qc.check_code AS quality_check,
               COALESCE(db.business_id, db.batch_code) AS drying_batch,
               UPPER(qc.status) AS result, qc.moisture_percent AS moisture_pct, qc.inspector,
               UPPER(a.decision) AS decision, a.approver, a.decided_at::date AS decided_on,
               fa.name AS facility
        FROM quality_checks AS qc
        JOIN drying_batches AS db ON db.id = qc.drying_batch_id
        LEFT JOIN facilities AS fa ON fa.id = db.facility_id
        LEFT JOIN LATERAL (
            SELECT decision, approver, decided_at FROM quality_approvals
            WHERE quality_check_id = qc.id ORDER BY id DESC LIMIT 1
        ) AS a ON TRUE
        {q.where}
        ORDER BY qc.id DESC
        """,
        q.params,
    )
    return cursor.fetchall()


def _report_inventory(cursor, f):
    q = _ReportQuery(f, scope_alias='il')
    if f['product_type']:
        q.add('LOWER(pl.product_type) = LOWER(%s)', f['product_type'])
    cursor.execute(
        f"""
        WITH {INVENTORY_LEDGER_CTE}, {ALLOCATION_STATE_CTE},
        balances AS (
            SELECT product_lot_id, location_id, SUM(delta) AS on_hand
            FROM ledger GROUP BY 1, 2 HAVING SUM(delta) <> 0
        )
        SELECT pl.product_type AS product, pl.business_id AS product_lot,
               pl.production_date, il.name || ' (' || il.location_code || ')' AS location,
               fa.name AS facility, b.on_hand AS on_hand_kg,
               COALESCE((SELECT SUM(s.quantity_kg - s.released_kg - s.dispatched_kg)
                         FROM allocation_state AS s
                         WHERE s.product_lot_id = pl.id AND s.location_id = il.id), 0) AS reserved_kg,
               CASE WHEN {PRODUCT_LOT_RELEASABLE_SQL} THEN 'AVAILABLE' ELSE 'BLOCKED' END AS lot_status
        FROM balances AS b
        JOIN product_lots AS pl ON pl.id = b.product_lot_id
        JOIN inventory_locations AS il ON il.id = b.location_id
        JOIN facilities AS fa ON fa.id = il.facility_id
        {q.where}
        ORDER BY pl.product_type, pl.production_date, pl.business_id, il.name
        """,
        q.params,
    )
    rows = [dict(row) for row in cursor.fetchall()]
    for row in rows:
        row['free_kg'] = Decimal(str(row['on_hand_kg'])) - Decimal(str(row['reserved_kg']))
    return rows


def _report_sales(cursor, f):
    q = _ReportQuery(f, scope_alias='o', commercial=True)
    q.dates('o.order_date')
    if f['status']:
        q.add('o.status = %s', f['status'])
    if f['product_type']:
        q.add(
            'EXISTS (SELECT 1 FROM customer_order_lines AS l WHERE l.order_id = o.id '
            'AND LOWER(l.product_type) = LOWER(%s))',
            f['product_type'],
        )
    cursor.execute(
        f"""
        WITH {ALLOCATION_STATE_CTE}
        SELECT o.business_id AS order_ref, o.order_date AS date, c.name AS customer,
               o.customer_reference, fm.name AS farm, o.status,
               o.requested_delivery_date AS requested,
               (SELECT string_agg(DISTINCT l.product_type, ', ') FROM customer_order_lines AS l
                 WHERE l.order_id = o.id) AS products,
               (SELECT SUM(l.quantity_kg) FROM customer_order_lines AS l WHERE l.order_id = o.id) AS ordered_kg,
               COALESCE((SELECT SUM(s.dispatched_kg) FROM allocation_state AS s
                         JOIN customer_order_lines AS l ON l.id = s.order_line_id
                         WHERE l.order_id = o.id), 0) AS dispatched_kg,
               COALESCE((SELECT SUM(dl.quantity_kg) FROM customer_delivery_lines AS dl
                         JOIN customer_deliveries AS d ON d.id = dl.delivery_id
                         WHERE d.order_id = o.id AND d.status = 'DELIVERED'), 0) AS delivered_kg
        FROM customer_orders AS o
        JOIN customers AS c ON c.id = o.customer_id
        JOIN farms AS fm ON fm.id = o.farm_id
        {q.where}
        ORDER BY o.order_date DESC, o.id DESC
        """,
        q.params,
    )
    return cursor.fetchall()


def _report_deliveries(cursor, f):
    q = _ReportQuery(f, scope_alias='o', commercial=True)
    q.dates('d.dispatched_at')
    if f['status']:
        q.add('d.status = %s', f['status'])
    cursor.execute(
        f"""
        SELECT d.business_id AS delivery, o.business_id AS order_ref, c.name AS customer,
               d.status, d.dispatched_at, d.delivered_at, d.received_by, d.vehicle, d.driver,
               (SELECT SUM(quantity_kg) FROM customer_delivery_lines WHERE delivery_id = d.id) AS quantity_kg,
               (SELECT string_agg(pl.business_id, ', ' ORDER BY pl.business_id)
                FROM customer_delivery_lines AS dl
                JOIN order_allocations AS a ON a.id = dl.allocation_id
                JOIN product_lots AS pl ON pl.id = a.product_lot_id
                WHERE dl.delivery_id = d.id) AS product_lots
        FROM customer_deliveries AS d
        JOIN customer_orders AS o ON o.id = d.order_id
        JOIN customers AS c ON c.id = o.customer_id
        {q.where}
        ORDER BY d.dispatched_at DESC, d.id DESC
        """,
        q.params,
    )
    return cursor.fetchall()


def _report_traceability(cursor, f):
    q = _ReportQuery(f, scope_alias='batch')
    q.dates('pl.production_date')
    if f['product_type']:
        q.add('LOWER(pl.product_type) = LOWER(%s)', f['product_type'])
    commercial_visible = _farm_visibility_clause('pl')
    cursor.execute(
        f"""
        WITH chain AS (
            SELECT di.drying_batch_id, h.harvest_code, pb.business_id AS production_batch,
                   sb.business_id AS substrate_batch, wl.business_id AS waste_lot,
                   wl.source_name
            FROM drying_inputs AS di
            JOIN harvests AS h ON h.id = di.harvest_id
            JOIN production_events AS pe ON pe.id = h.production_event_id
            JOIN production_batches AS pb ON pb.id = pe.production_batch_id
            LEFT JOIN production_batch_inputs AS pbi ON pbi.production_batch_id = pb.id
            LEFT JOIN substrate_batches AS sb ON sb.id = pbi.substrate_batch_id
            LEFT JOIN substrate_batch_inputs AS sbi ON sbi.substrate_batch_id = sb.id
            LEFT JOIN waste_lots AS wl ON wl.id = sbi.waste_lot_id
        )
        SELECT pl.business_id AS product_lot, pl.product_type AS product, pl.production_date,
               pl.quantity_kg, COALESCE(batch.business_id, batch.batch_code) AS drying_batch,
               (SELECT string_agg(DISTINCT harvest_code, ', ') FROM chain
                 WHERE drying_batch_id = batch.id) AS harvests,
               (SELECT string_agg(DISTINCT production_batch, ', ') FROM chain
                 WHERE drying_batch_id = batch.id) AS production_batches,
               (SELECT string_agg(DISTINCT substrate_batch, ', ') FROM chain
                 WHERE drying_batch_id = batch.id) AS substrate_batches,
               (SELECT string_agg(DISTINCT waste_lot, ', ') FROM chain
                 WHERE drying_batch_id = batch.id) AS waste_lots,
               (SELECT string_agg(DISTINCT source_name, ', ') FROM chain
                 WHERE drying_batch_id = batch.id) AS waste_sources,
               CASE WHEN {commercial_visible[0]} THEN (
                   SELECT string_agg(DISTINCT c.name, ', ')
                   FROM order_allocations AS a
                   JOIN customer_order_lines AS l ON l.id = a.order_line_id
                   JOIN customer_orders AS o ON o.id = l.order_id
                   JOIN customers AS c ON c.id = o.customer_id
                   WHERE a.product_lot_id = pl.id
               ) ELSE 'restricted' END AS customers
        FROM product_lots AS pl
        JOIN drying_outputs AS output ON output.id = pl.drying_output_id
        JOIN drying_batches AS batch ON batch.id = output.drying_batch_id
        {q.where}
        ORDER BY pl.production_date DESC, pl.id DESC
        """,
        (*commercial_visible[1], *q.params),
    )
    return cursor.fetchall()


def _report_farm_performance(cursor, f):
    q = _ReportQuery(f, scope_alias='fm', commercial=True)
    period = []
    period_params = []
    for column, op, value in (('{c}', '>=', f['date_from']), ('{c}', '<=', f['date_to'])):
        if value:
            period.append(f"({column})::date {op} %s")
            period_params.append(value)

    def within(column):
        if not period:
            return 'TRUE', []
        return ' AND '.join(p.format(c=column) for p in period), list(period_params)

    parts = []
    params = []
    for name, sql, column in (
        ('waste_received_kg', 'SELECT COALESCE(SUM(quantity), 0) FROM waste_lots WHERE farm_id = fm.farm_id AND {w}', 'collection_date'),
        ('substrate_kg', 'SELECT COALESCE(SUM(total_input_weight_kg), 0) FROM substrate_batches WHERE farm_id = fm.farm_id AND {w}', 'preparation_date'),
        ('batches_started', 'SELECT COUNT(*) FROM production_batches WHERE farm_id = fm.farm_id AND {w}', 'start_date'),
        ('harvested_kg', "SELECT COALESCE(SUM(quantity), 0) FROM production_events WHERE farm_id = fm.farm_id AND event_type = 'harvest' AND status = 'recorded' AND {w}", 'occurred_at'),
        ('dried_in_kg', f"SELECT COALESCE(SUM({KG_SQL.format(unit='di.unit', qty='di.quantity')}), 0) FROM drying_inputs AS di JOIN drying_batches AS db ON db.id = di.drying_batch_id WHERE db.farm_id = fm.farm_id AND {{w}}", 'db.drying_date'),
        ('dried_out_kg', f"SELECT COALESCE(SUM({KG_SQL.format(unit='o.unit', qty='o.quantity')}), 0) FROM drying_outputs AS o JOIN drying_batches AS db ON db.id = o.drying_batch_id WHERE db.farm_id = fm.farm_id AND {{w}}", 'db.drying_date'),
        ('released_kg', 'SELECT COALESCE(SUM(quantity_kg), 0) FROM product_lots WHERE farm_id = fm.farm_id AND drying_output_id IS NOT NULL AND {w}', 'production_date'),
        ('dispatched_kg', "SELECT COALESCE(SUM(quantity_kg), 0) FROM inventory_movements WHERE farm_id = fm.farm_id AND movement_type = 'DISPATCH' AND status = 'posted' AND {w}", 'occurred_at'),
    ):
        clause, clause_params = within(column)
        parts.append(f"({sql.format(w=clause)}) AS {name}")
        params.extend(clause_params)
    cursor.execute(
        f"""
        SELECT fm.name AS farm, {', '.join(parts)},
               (SELECT COUNT(*) FROM operational_alerts AS a
                 WHERE a.farm_id = fm.farm_id AND a.status = 'OPEN') AS open_alerts
        FROM (SELECT id AS farm_id, name FROM farms WHERE status = 'active') AS fm
        {q.where}
        ORDER BY fm.name
        """,
        (*params, *q.params),
    )
    rows = [dict(row) for row in cursor.fetchall()]
    for row in rows:
        substrate, harvested = Decimal(str(row['substrate_kg'])), Decimal(str(row['harvested_kg']))
        dried_in, dried_out = Decimal(str(row['dried_in_kg'])), Decimal(str(row['dried_out_kg']))
        row['harvest_per_substrate_pct'] = _ratio_percent(harvested, substrate) if harvested else None
        row['drying_yield_pct'] = _ratio_percent(dried_out, dried_in) if dried_out else None
    return rows


def _col(key, label, kind='text'):
    return {'key': key, 'label': label, 'type': kind}


# Report catalogue: builder, columns, filters it accepts, and totals to sum.
REPORTS = {
    'waste_received': {
        'title': 'Waste received', 'group': 'Production', 'builder': _report_waste,
        'filters': ['dates', 'farm', 'facility', 'status'],
        'statuses': ['AVAILABLE', 'QUARANTINED', 'REJECTED', 'CONSUMED'],
        'columns': [_col('date', 'Date', 'date'), _col('waste_lot', 'Waste lot'), _col('source_type', 'Source type'),
                    _col('source_name', 'Source'), _col('waste_type', 'Waste type'),
                    _col('received_kg', 'Received kg', 'kg'), _col('used_kg', 'Used kg', 'kg'),
                    _col('remaining_kg', 'Remaining kg', 'kg'), _col('quality_status', 'Quality'),
                    _col('status', 'Status'), _col('facility', 'Facility')],
        'totals': ['received_kg', 'used_kg', 'remaining_kg'],
    },
    'substrate': {
        'title': 'Substrate preparation', 'group': 'Production', 'builder': _report_substrate,
        'filters': ['dates', 'farm', 'facility'],
        'columns': [_col('date', 'Date', 'date'), _col('substrate_batch', 'Substrate batch'), _col('facility', 'Facility'),
                    _col('waste_lots', 'Waste lots', 'number'), _col('input_kg', 'Input kg', 'kg'),
                    _col('issued_kg', 'Issued kg', 'kg'), _col('available_kg', 'Available kg', 'kg'),
                    _col('particle_size', 'Particle size'), _col('recorded_by', 'Recorded by')],
        'totals': ['input_kg', 'issued_kg', 'available_kg'],
    },
    'production_batches': {
        'title': 'Production batches', 'group': 'Production', 'builder': _report_production,
        'filters': ['dates', 'farm', 'facility', 'status'],
        'statuses': sorted(PRODUCTION_BATCH_STATUSES),
        'columns': [_col('production_batch', 'Batch'), _col('facility', 'Facility'), _col('start_date', 'Started', 'date'),
                    _col('status', 'Status'), _col('stage', 'Stage'), _col('expected_harvest', 'Expected harvest', 'date'),
                    _col('age_days', 'Age (days)', 'number'), _col('substrate_kg', 'Substrate kg', 'kg'),
                    _col('harvested_kg', 'Harvested kg', 'kg'), _col('harvest_per_substrate_pct', 'Harvest / substrate %', 'percent')],
        'totals': ['substrate_kg', 'harvested_kg'],
    },
    'feeding': {
        'title': 'Feeding activity', 'group': 'Production', 'builder': _report_feeding,
        'filters': ['dates', 'farm', 'facility'],
        'columns': [_col('date', 'Date', 'date'), _col('production_batch', 'Batch'), _col('feed_type', 'Feed'),
                    _col('offered_kg', 'Offered kg', 'kg'), _col('consumed_kg', 'Consumed kg', 'kg'),
                    _col('larvae_biomass_kg', 'Biomass kg', 'kg'), _col('larvae_age_days', 'Larvae age', 'number'),
                    _col('recorded_by', 'Recorded by'), _col('facility', 'Facility')],
        'totals': ['offered_kg', 'consumed_kg'],
    },
    'harvest': {
        'title': 'Harvest', 'group': 'Production', 'builder': _report_harvest,
        'filters': ['dates', 'farm', 'facility'],
        'columns': [_col('date', 'Date', 'date'), _col('harvest', 'Harvest'), _col('production_batch', 'Batch'),
                    _col('wet_kg', 'Wet kg', 'kg'), _col('sent_to_drying_kg', 'Sent to drying kg', 'kg'),
                    _col('stage', 'Stage'), _col('operator', 'Operator'), _col('location', 'Location'),
                    _col('facility', 'Facility')],
        'totals': ['wet_kg', 'sent_to_drying_kg'],
    },
    'drying': {
        'title': 'Drying', 'group': 'Processing', 'builder': _report_drying,
        'filters': ['dates', 'farm', 'facility', 'status'],
        'statuses': sorted(DRYING_BATCH_STATUSES),
        'columns': [_col('drying_batch', 'Drying batch'), _col('date', 'Date', 'date'), _col('method', 'Method'),
                    _col('status', 'Status'), _col('facility', 'Facility'), _col('wet_in_kg', 'Wet in kg', 'kg'),
                    _col('dry_out_kg', 'Dry out kg', 'kg'), _col('yield_pct', 'Yield %', 'percent'),
                    _col('moisture_pct', 'Moisture %', 'percent'), _col('production_batches', 'From batches')],
        'totals': ['wet_in_kg', 'dry_out_kg'],
    },
    'quality': {
        'title': 'Quality control', 'group': 'Processing', 'builder': _report_quality,
        'filters': ['dates', 'farm', 'facility', 'status'],
        'statuses': ['PASSED', 'FAILED', 'SUBMITTED', 'DRAFT', 'SUPERSEDED'],
        'columns': [_col('date', 'Date', 'date'), _col('quality_check', 'Check'), _col('drying_batch', 'Drying batch'),
                    _col('result', 'Result'), _col('moisture_pct', 'Moisture %', 'percent'), _col('inspector', 'Inspector'),
                    _col('decision', 'Decision'), _col('approver', 'Approver'), _col('decided_on', 'Decided', 'date'),
                    _col('facility', 'Facility')],
        'totals': [],
    },
    'inventory': {
        'title': 'Current stock', 'group': 'Stock & sales', 'builder': _report_inventory,
        'filters': ['farm', 'facility', 'product'],
        'columns': [_col('product', 'Product'), _col('product_lot', 'Product lot'),
                    _col('production_date', 'Produced', 'date'), _col('location', 'Location'), _col('facility', 'Facility'),
                    _col('on_hand_kg', 'On hand kg', 'kg'), _col('reserved_kg', 'Reserved kg', 'kg'),
                    _col('free_kg', 'Free kg', 'kg'), _col('lot_status', 'Lot status')],
        'totals': ['on_hand_kg', 'reserved_kg', 'free_kg'],
    },
    'sales': {
        'title': 'Customer orders', 'group': 'Stock & sales', 'builder': _report_sales,
        'filters': ['dates', 'farm', 'status', 'product'], 'commercial': True,
        'statuses': ['OPEN', 'FULFILLED', 'CANCELLED'],
        'columns': [_col('order_ref', 'Order'), _col('date', 'Date', 'date'), _col('customer', 'Customer'),
                    _col('customer_reference', 'Customer ref'), _col('status', 'Status'),
                    _col('requested', 'Requested', 'date'), _col('products', 'Products'),
                    _col('ordered_kg', 'Ordered kg', 'kg'), _col('dispatched_kg', 'Dispatched kg', 'kg'),
                    _col('delivered_kg', 'Delivered kg', 'kg'), _col('farm', 'Farm')],
        'totals': ['ordered_kg', 'dispatched_kg', 'delivered_kg'],
    },
    'deliveries': {
        'title': 'Deliveries', 'group': 'Stock & sales', 'builder': _report_deliveries,
        'filters': ['dates', 'farm', 'status'], 'commercial': True,
        'statuses': ['DISPATCHED', 'DELIVERED'],
        'columns': [_col('delivery', 'Delivery'), _col('order_ref', 'Order'), _col('customer', 'Customer'),
                    _col('status', 'Status'), _col('dispatched_at', 'Dispatched', 'datetime'),
                    _col('delivered_at', 'Delivered', 'datetime'), _col('received_by', 'Received by'),
                    _col('quantity_kg', 'Quantity kg', 'kg'), _col('product_lots', 'Product lots'),
                    _col('vehicle', 'Vehicle'), _col('driver', 'Driver')],
        'totals': ['quantity_kg'],
    },
    'traceability': {
        'title': 'Product lineage', 'group': 'Traceability', 'builder': _report_traceability,
        'filters': ['dates', 'farm', 'facility', 'product'],
        'columns': [_col('product_lot', 'Product lot'), _col('product', 'Product'),
                    _col('production_date', 'Produced', 'date'), _col('quantity_kg', 'Released kg', 'kg'),
                    _col('drying_batch', 'Drying batch'), _col('harvests', 'Harvests'),
                    _col('production_batches', 'Production batches'), _col('substrate_batches', 'Substrate'),
                    _col('waste_lots', 'Waste lots'), _col('waste_sources', 'Waste sources'),
                    _col('customers', 'Customers')],
        'totals': ['quantity_kg'],
    },
    'farm_performance': {
        'title': 'Farm performance', 'group': 'Overview', 'builder': _report_farm_performance,
        'filters': ['dates', 'farm'], 'commercial': True,
        'columns': [_col('farm', 'Farm'), _col('waste_received_kg', 'Waste received kg', 'kg'),
                    _col('substrate_kg', 'Substrate kg', 'kg'), _col('batches_started', 'Batches started', 'number'),
                    _col('harvested_kg', 'Harvested kg', 'kg'),
                    _col('harvest_per_substrate_pct', 'Harvest / substrate %', 'percent'),
                    _col('dried_in_kg', 'Into drying kg', 'kg'), _col('dried_out_kg', 'Dried kg', 'kg'),
                    _col('drying_yield_pct', 'Drying yield %', 'percent'), _col('released_kg', 'Released kg', 'kg'),
                    _col('dispatched_kg', 'Dispatched kg', 'kg'), _col('open_alerts', 'Open alerts', 'number')],
        'totals': ['waste_received_kg', 'substrate_kg', 'batches_started', 'harvested_kg',
                   'dried_in_kg', 'dried_out_kg', 'released_kg', 'dispatched_kg', 'open_alerts'],
    },
}


def _report_filters(spec):
    args = request.args

    def day(name):
        value = args.get(name)
        if value in (None, ''):
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            raise ValueError(f'{name} must be a date (YYYY-MM-DD)')

    filters = {
        'date_from': day('date_from') if 'dates' in spec['filters'] else None,
        'date_to': day('date_to') if 'dates' in spec['filters'] else None,
        'farm_id': None, 'facility_id': None, 'status': None, 'product_type': None,
    }
    if filters['date_from'] and filters['date_to'] and filters['date_from'] > filters['date_to']:
        raise ValueError('date_from must be on or before date_to')
    for name in ('farm_id', 'facility_id'):
        if args.get(name) not in (None, '') and name.split('_')[0] in spec['filters']:
            filters[name] = _parse_positive_integer(args[name], name)
    status = str(args.get('status') or '').strip().upper()
    if status and 'status' in spec['filters']:
        if status not in spec.get('statuses', []):
            raise ValueError('Unknown status for this report')
        filters['status'] = status
    product = str(args.get('product_type') or '').strip()
    if product and 'product' in spec['filters']:
        filters['product_type'] = product[:50]
    return filters


def _csv_cell(value):
    """Plain text for CSV; neutralise spreadsheet formulas from user data."""
    if value is None:
        return ''
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    text = str(value)
    if text and text[0] in ('=', '+', '-', '@', '\t', '\r') and not _looks_numeric(text):
        return "'" + text
    return text


def _looks_numeric(text):
    try:
        Decimal(text)
        return True
    except (InvalidOperation, ValueError):
        return False


@app.route('/api/reports', methods=['GET'])
@login_required
def list_reports():
    return jsonify({'success': True, 'data': [
        {'key': key, 'title': spec['title'], 'group': spec['group'], 'filters': spec['filters'],
         'statuses': spec.get('statuses', []), 'commercial': spec.get('commercial', False),
         'columns': spec['columns']}
        for key, spec in REPORTS.items()
    ]})


@app.route('/api/reports/<string:report_key>', methods=['GET'])
@login_required
def run_report(report_key):
    spec = REPORTS.get(report_key)
    if not spec:
        return jsonify({'success': False, 'message': 'Unknown report'}), 404
    try:
        filters = _report_filters(spec)
        with db.transaction() as cursor:
            rows = [dict(row) for row in spec['builder'](cursor, filters)]
        truncated = len(rows) > REPORT_ROW_LIMIT
        rows = rows[:REPORT_ROW_LIMIT]
        totals = {
            key: sum((Decimal(str(row[key])) for row in rows if row.get(key) is not None), Decimal('0'))
            for key in spec['totals']
        }
        if request.args.get('format') == 'csv':
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow([column['label'] for column in spec['columns']])
            for row in rows:
                writer.writerow([_csv_cell(row.get(column['key'])) for column in spec['columns']])
            stamp = date.today().isoformat()
            return Response(
                '﻿' + buffer.getvalue(),  # BOM so Excel opens UTF-8 correctly
                mimetype='text/csv',
                headers={'Content-Disposition': f'attachment; filename=zehunger-{report_key}-{stamp}.csv'},
            )
        return jsonify({
            'success': True,
            'report': {'key': report_key, 'title': spec['title'], 'columns': spec['columns']},
            'filters': _jsonable(filters),
            'data': _jsonable(rows),
            'totals': totals,
            'row_count': len(rows),
            'truncated': truncated,
        }), 200
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception:
        logger.exception('Error running report %s', report_key)
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


# ---- Operations dashboard ------------------------------------------------------
#
# Live figures from the Phase One tables for the caller's locations.  Same
# scoping as the reports: operations follow facility access; order and
# delivery figures need farm-level access and are omitted (restricted)
# otherwise.  Nothing here is stored or estimated.

DASHBOARD_PERIODS = (7, 30, 90)
ACTIVE_BATCH_STATUSES = ('ACTIVE', 'MONITORING', 'READY_FOR_HARVEST', 'PAUSED', 'HEALTH_ALERT')


def _dashboard_value(cursor, sql, params):
    cursor.execute(sql, params)
    row = cursor.fetchone()
    return row[next(iter(row))] if row else None


def _dashboard_buckets(start, end, weekly):
    buckets = []
    day = start - timedelta(days=start.weekday()) if weekly else start
    step = timedelta(days=7 if weekly else 1)
    while day <= end:
        buckets.append(day)
        day += step
    return buckets


def _dashboard_series(cursor, sql, params, buckets, weekly):
    unit = 'week' if weekly else 'day'
    cursor.execute(sql.format(unit=unit), params)
    values = {row['bucket']: Decimal(str(row['kg'])) for row in cursor.fetchall()}
    return [values.get(bucket, Decimal('0')) for bucket in buckets]


def _operations_dashboard(cursor, days, farm_id, facility_id):
    today = date.today()
    start = today - timedelta(days=days - 1)
    filters = {
        'date_from': start, 'date_to': today, 'farm_id': farm_id, 'facility_id': facility_id,
        'status': None, 'product_type': None,
    }

    def scoped(alias, date_column=None, commercial=False):
        q = _ReportQuery(filters, scope_alias=alias, commercial=commercial)
        if date_column:
            q.dates(date_column)
        return q

    # Production pipeline (current state, not period bound).
    q = scoped('pb')
    q.add("UPPER(pb.status) NOT IN ('COMPLETED', 'CANCELLED')")
    cursor.execute(
        f"SELECT UPPER(pb.status) AS status, COUNT(*) AS n FROM production_batches AS pb {q.where} GROUP BY 1",
        q.params,
    )
    pipeline = {row['status']: row['n'] for row in cursor.fetchall()}

    q = scoped('sb')
    available_sql = (
        "COALESCE(sb.output_weight_kg, sb.total_input_weight_kg, 0) - COALESCE(("
        "SELECT SUM(quantity_issued) FROM production_batch_inputs WHERE substrate_batch_id = sb.id), 0)"
    )
    cursor.execute(
        f"""
        SELECT COALESCE(SUM(GREATEST({available_sql}, 0)), 0) AS kg,
               COUNT(*) FILTER (WHERE {available_sql} > 0) AS batches
        FROM substrate_batches AS sb {q.where}
        """,
        q.params,
    )
    substrate = cursor.fetchone()

    q = scoped('db')
    cursor.execute(
        f"""
        SELECT COUNT(*) FILTER (WHERE UPPER(db.status) IN ('DRAFT', 'RECEIVED', 'DRYING')) AS drying,
               COUNT(*) FILTER (WHERE UPPER(db.status) = 'QC_PENDING') AS qc_pending
        FROM drying_batches AS db {q.where} AND db.farm_id IS NOT NULL
        """,
        q.params,
    )
    drying_now = cursor.fetchone()

    # Stock (current): free = QC-released on hand minus outstanding reservations.
    q = scoped('il')
    cursor.execute(
        f"""
        WITH {INVENTORY_LEDGER_CTE}, {ALLOCATION_STATE_CTE},
        balances AS (SELECT product_lot_id, location_id, SUM(delta) AS kg FROM ledger GROUP BY 1, 2)
        SELECT COALESCE(SUM(b.kg), 0) AS on_hand,
               COALESCE(SUM(b.kg) FILTER (WHERE NOT {PRODUCT_LOT_RELEASABLE_SQL}), 0) AS blocked,
               COALESCE(SUM((SELECT COALESCE(SUM(s.quantity_kg - s.released_kg - s.dispatched_kg), 0)
                             FROM allocation_state AS s
                             WHERE s.product_lot_id = b.product_lot_id AND s.location_id = b.location_id)), 0)
                   AS reserved
        FROM balances AS b
        JOIN product_lots AS pl ON pl.id = b.product_lot_id
        JOIN inventory_locations AS il ON il.id = b.location_id
        {q.where}
        """,
        q.params,
    )
    stock = cursor.fetchone()
    on_hand, blocked, reserved = (Decimal(str(stock[k])) for k in ('on_hand', 'blocked', 'reserved'))

    # Material flow over the period, in kg.
    flow = []
    for label, sql, alias, column in (
        ('Waste received', 'SELECT COALESCE(SUM(wl.quantity), 0) FROM waste_lots AS wl {w}', 'wl', 'wl.collection_date'),
        ('Substrate prepared', 'SELECT COALESCE(SUM(sb.total_input_weight_kg), 0) FROM substrate_batches AS sb {w}',
         'sb', 'sb.preparation_date'),
        ('Harvested (wet)', "SELECT COALESCE(SUM(pe.quantity), 0) FROM production_events AS pe {w} "
                            "AND pe.event_type = 'harvest' AND pe.status = 'recorded'", 'pe', 'pe.occurred_at'),
        ('Dried', f"SELECT COALESCE(SUM({KG_SQL.format(unit='o.unit', qty='o.quantity')}), 0) "
                  "FROM drying_outputs AS o JOIN drying_batches AS db ON db.id = o.drying_batch_id {w}",
         'db', 'o.output_date'),
        ('Released to stock', 'SELECT COALESCE(SUM(pl.quantity_kg), 0) FROM product_lots AS pl '
                              'JOIN drying_outputs AS o ON o.id = pl.drying_output_id '
                              'JOIN drying_batches AS batch ON batch.id = o.drying_batch_id {w}',
         'batch', 'pl.production_date'),
        ('Dispatched', "SELECT COALESCE(SUM(im.quantity_kg), 0) FROM inventory_movements AS im "
                       "JOIN inventory_locations AS il ON il.id = im.from_location_id {w} "
                       "AND im.movement_type = 'DISPATCH' AND im.status = 'posted'", 'il', 'im.occurred_at'),
    ):
        q = scoped(alias, column)
        flow.append({'stage': label, 'kg': Decimal(str(_dashboard_value(cursor, sql.format(w=q.where), q.params)))})

    # Output trend: daily up to a month, weekly beyond.
    weekly = days > 31
    buckets = _dashboard_buckets(start, today, weekly)
    trend = {'buckets': buckets, 'weekly': weekly, 'series': []}
    for label, sql, alias, column in (
        ('Harvested (wet)', "SELECT date_trunc('{unit}', pe.occurred_at)::date AS bucket, SUM(pe.quantity) AS kg "
                            "FROM production_events AS pe {w} AND pe.event_type = 'harvest' "
                            "AND pe.status = 'recorded' GROUP BY 1", 'pe', 'pe.occurred_at'),
        ('Dried', f"SELECT date_trunc('{{unit}}', o.output_date)::date AS bucket, "
                  f"SUM({KG_SQL.format(unit='o.unit', qty='o.quantity')}) AS kg "
                  "FROM drying_outputs AS o JOIN drying_batches AS db ON db.id = o.drying_batch_id {w} "
                  "GROUP BY 1", 'db', 'o.output_date'),
        ('Dispatched', "SELECT date_trunc('{unit}', im.occurred_at)::date AS bucket, SUM(im.quantity_kg) AS kg "
                       "FROM inventory_movements AS im JOIN inventory_locations AS il ON il.id = im.from_location_id "
                       "{w} AND im.movement_type = 'DISPATCH' AND im.status = 'posted' GROUP BY 1",
         'il', 'im.occurred_at'),
    ):
        q = scoped(alias, column)
        sql = sql.replace('{w}', q.where)
        trend['series'].append({
            'name': label,
            'values': _dashboard_series(cursor, sql, q.params, buckets, weekly),
        })

    # Commercial figures only for farm-level users.
    farms_visible, farms_params = _farm_visibility_clause('fm')
    cursor.execute(
        f"SELECT EXISTS (SELECT 1 FROM (SELECT id AS farm_id FROM farms) AS fm WHERE {farms_visible}) AS ok",
        farms_params,
    )
    commercial = None
    if cursor.fetchone()['ok']:
        q = scoped('o', commercial=True)
        cursor.execute(
            f"""
            WITH {ALLOCATION_STATE_CTE}
            SELECT COUNT(*) FILTER (WHERE o.status = 'OPEN') AS open_orders,
                   COUNT(*) FILTER (WHERE o.status = 'OPEN' AND o.requested_delivery_date < CURRENT_DATE)
                       AS overdue_orders,
                   COALESCE(SUM(CASE WHEN o.status = 'OPEN' THEN
                       (SELECT SUM(l.quantity_kg) FROM customer_order_lines AS l WHERE l.order_id = o.id)
                       - COALESCE((SELECT SUM(s.dispatched_kg) FROM allocation_state AS s
                                   JOIN customer_order_lines AS l ON l.id = s.order_line_id
                                   WHERE l.order_id = o.id), 0) END), 0) AS outstanding_kg
            FROM customer_orders AS o {q.where}
            """,
            q.params,
        )
        commercial = dict(cursor.fetchone())
        commercial['in_transit'] = _dashboard_value(
            cursor,
            f"""
            SELECT COUNT(*) FROM customer_deliveries AS d
            JOIN customer_orders AS o ON o.id = d.order_id
            {q.where} AND d.status = 'DISPATCHED'
            """,
            q.params,
        )
        q = scoped('o', 'd.delivered_at', commercial=True)
        commercial['delivered_kg'] = _dashboard_value(
            cursor,
            f"""
            SELECT COALESCE(SUM(dl.quantity_kg), 0) FROM customer_delivery_lines AS dl
            JOIN customer_deliveries AS d ON d.id = dl.delivery_id
            JOIN customer_orders AS o ON o.id = d.order_id
            {q.where} AND d.status = 'DELIVERED'
            """,
            q.params,
        )

    # Alerts needing attention (visible to this user).
    visibility, params = _alert_visibility_clause()
    alert_filters = [visibility, "a.status = 'OPEN'"]
    alert_params = list(params)
    if farm_id:
        alert_filters.append('a.farm_id = %s')
        alert_params.append(farm_id)
    if facility_id:
        alert_filters.append('(a.facility_id = %s OR a.facility_id IS NULL)')
        alert_params.append(facility_id)
    cursor.execute(
        f"""
        SELECT a.id, a.severity, a.title, a.message, a.href, a.first_detected_at
        FROM operational_alerts AS a
        WHERE {' AND '.join(alert_filters)}
        ORDER BY CASE a.severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
                 a.first_detected_at DESC
        """,
        alert_params,
    )
    open_alerts = [dict(row) for row in cursor.fetchall()]

    harvested = next(item['kg'] for item in flow if item['stage'] == 'Harvested (wet)')
    dried = next(item['kg'] for item in flow if item['stage'] == 'Dried')
    return _jsonable({
        'period': {'days': days, 'from': start, 'to': today},
        'kpis': {
            'active_batches': sum(pipeline.get(s, 0) for s in ACTIVE_BATCH_STATUSES),
            'planned_batches': pipeline.get('PLANNED', 0),
            'ready_for_harvest': pipeline.get('READY_FOR_HARVEST', 0),
            'health_alert_batches': pipeline.get('HEALTH_ALERT', 0),
            'substrate_available_kg': substrate['kg'],
            'substrate_batches_available': substrate['batches'],
            'harvested_kg': harvested,
            'dried_kg': dried,
            'drying_in_progress': drying_now['drying'],
            'qc_pending': drying_now['qc_pending'],
            'released_kg': next(item['kg'] for item in flow if item['stage'] == 'Released to stock'),
            'stock_on_hand_kg': on_hand,
            'stock_available_kg': on_hand - blocked - reserved,
            'stock_reserved_kg': reserved,
            'stock_blocked_kg': blocked,
        },
        'pipeline': [
            {'status': status, 'count': pipeline.get(status, 0)}
            for status in ('PLANNED', 'ACTIVE', 'MONITORING', 'READY_FOR_HARVEST', 'HARVESTED',
                           'PAUSED', 'HEALTH_ALERT')
        ],
        'flow': flow,
        'trend': trend,
        'commercial': commercial,
        'alerts': {
            'critical': sum(1 for a in open_alerts if a['severity'] == 'critical'),
            'warning': sum(1 for a in open_alerts if a['severity'] == 'warning'),
            'info': sum(1 for a in open_alerts if a['severity'] == 'info'),
            'top': open_alerts[:6],
        },
    })


@app.route('/api/dashboard', methods=['GET'])
@login_required
def operations_dashboard_data():
    try:
        days = int(request.args.get('days', 30))
    except ValueError:
        days = 0
    if days not in DASHBOARD_PERIODS:
        return jsonify({'success': False, 'message': 'days must be 7, 30 or 90'}), 400
    try:
        farm_id = _parse_positive_integer(request.args['farm_id'], 'farm_id') \
            if request.args.get('farm_id') else None
        facility_id = _parse_positive_integer(request.args['facility_id'], 'facility_id') \
            if request.args.get('facility_id') else None
        try:
            _sync_alerts()
        except Exception:
            logger.exception('Alert sync failed while loading the dashboard')
        with db.transaction() as cursor:
            data = _operations_dashboard(cursor, days, farm_id, facility_id)
        return jsonify({'success': True, 'data': data}), 200
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception:
        logger.exception('Error building operations dashboard')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/operations')
@login_required
def operations_page():
    return render_template('operations.html')


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


@app.route('/api/me', methods=['GET'])
@login_required
def current_user_profile():
    """Basic profile of the signed-in user (no secrets)."""
    if not getattr(current_user, 'is_authenticated', False):
        return jsonify({'success': False, 'message': 'Not signed in'}), 401
    return jsonify({'success': True, 'data': {
        'username': current_user.username,
        'full_name': getattr(current_user, 'full_name', None),
        'role': current_user.role,
    }})


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


@app.errorhandler(400)
def bad_request(e):
    # Custom error response for 400
    return jsonify(error=str(e), success=False), 400

@app.errorhandler(404)
def not_found(e):
    # Custom error response for 404
    return jsonify(error="Resource not found", success=False), 404
    
@app.errorhandler(409)
def conflict(e):
    # Custom error response for 409
    return jsonify(error=str(e), success=False), 409

@app.errorhandler(500)
def internal_server_error(e):
    # Custom error response for 500
    logger.error(f"Internal Server Error: {e}")
    return jsonify(error="Internal server error", success=False), 500

@app.errorhandler(Exception)
def handle_general_exception(e):
    # This will catch any exception not already handled.  Deliberate HTTP
    # errors such as abort(403) keep their status instead of becoming a 500.
    if isinstance(e, HTTPException):
        return jsonify(error=e.name, success=False), e.code
    logger.error(f"An unhandled exception occurred: {e}")
    return jsonify(error="An unexpected error occurred", success=False), 500

def send_email(subject, body, to_emails):
    print(f"[DEBUG] Preparing to send email to: {to_emails}")
    msg = MIMEMultipart()
    msg['From'] = EMAIL_HOST_USER
    msg['To'] = ', '.join(to_emails) if isinstance(to_emails, list) else to_emails
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))
    try:
        server = smtplib.SMTP(EMAIL_HOST, EMAIL_PORT)
        server.starttls()
        server.login(EMAIL_HOST_USER, EMAIL_HOST_PASSWORD)
        print("[DEBUG] Logged in to SMTP server.")
        server.sendmail(EMAIL_HOST_USER, to_emails, msg.as_string())
        print("[DEBUG] Email sent successfully.")
        server.quit()
        logger.info(f"Email sent to {to_emails}")
    except Exception as e:
        print(f"[DEBUG] Failed to send email: {e}")
        logger.error(f"Failed to send email: {e}")

@app.route('/api/send-harvest-report', methods=['POST'])
@login_required
def send_harvest_report():
    # Perform the same analysis as /api/statistics/harvest-efficiency
    try:
        # Query to get harvest yield data with correct column names
        query = "SELECT tray_batch_id, harvest_date, larvae_collected, processing_method, storage_temp FROM harvest_yield ORDER BY harvest_date DESC"
        data = db.fetch_all(query)
        if not data:
            summary = "No harvest yield records found."
        else:
            summary = f"Harvest Yield Report ({datetime.now().date()}):\n\n"
            for item in data:
                summary += (
                    f"Tray/Batch ID: {item.get('tray_batch_id', '')}, "
                    f"Date: {item.get('harvest_date', '')}, "
                    f"Larvae Collected: {item.get('larvae_collected', '')} kg, "
                    f"Processing Method: {item.get('processing_method', '')}, "
                    f"Storage Temp: {item.get('storage_temp', 'N/A')}°C\n"
                )
        subject = f"Harvest Yield Report ({datetime.now().date()})"
        send_email(subject, summary, ADMIN_EMAIL)
        return jsonify({'success': True, 'message': 'Harvest report sent to admin.'})
    except Exception as e:
        print(f"[DEBUG] Failed to send harvest report: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True) 
