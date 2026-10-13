from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, send_from_directory, abort
from flask_cors import CORS
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_session import Session
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Email, Length, EqualTo, ValidationError, Regexp
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from backend.init_db import init_database
from backend.database import DatabaseConnection
import logging
from datetime import datetime, timedelta, timezone
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
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
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
            
            next_page = request.args.get('next')
            if next_page and not next_page.startswith('/'):
                next_page = None
            return redirect(next_page or url_for('dashboard'))
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
        raise ProductionEventPermissionError('You must be signed in to record a production event')
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
            'You are not authorized for this Production Batch location'
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
                data.get('larvae_weight_g'),
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


def _production_scope_values(data):
    values = [data.get(field) for field in ('farm_id', 'site_id', 'facility_id')]
    if any(value in (None, '') for value in values):
        raise ValueError('farm_id, site_id, and facility_id are required for a Production Batch')
    return tuple(
        _parse_positive_integer(value, field)
        for value, field in zip(values, ('farm_id', 'site_id', 'facility_id'))
    )


def _assert_production_location(cursor, farm_id, site_id, facility_id):
    cursor.execute(
        """
        SELECT f.id AS farm_id, s.id AS site_id, fa.id AS facility_id
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
    if not cursor.fetchone():
        raise ValueError('The selected farm, site, and facility ownership is invalid')


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
        'collection_date', 'collection_time', 'farm_site', 'source_type',
        'source_name', 'waste_type', 'waste_weight', 'segregation_status',
        'collection_personnel'
    ]
    missing_fields = [field for field in required_fields if field not in normalized_data or not normalized_data.get(field)]
    if missing_fields:
        return jsonify({'success': False, 'message': f'Missing required fields: {", ".join(missing_fields)}'}), 400

    try:
        if not normalized_data['farm_site'].strip():
            raise ValueError('farm_site is required')
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
                    business_id, waste_sourcing_id, farm_site, source_type,
                    source_name, waste_type, collection_date, quantity, unit,
                    quality_status, status, recorded_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'kg', %s, %s, %s)
                RETURNING id, business_id, farm_site, source_name,
                          collection_date, quantity, unit, quality_status,
                          status, recorded_by, created_at
                """,
                (
                    source_record['business_id'],
                    source_record['id'],
                    normalized_data['farm_site'].strip(),
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
        'prep_date', 'farm_site', 'moisture_consistency',
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
        batch_site = normalized_data['farm_site'].strip()
        if not batch_site:
            raise ValueError('farm_site is required')
        actor = _chain_actor(normalized_data)
        scope_values = [
            normalized_data.get(field)
            for field in ('farm_id', 'site_id', 'facility_id')
        ]
        if any(value not in (None, '') for value in scope_values):
            if any(value in (None, '') for value in scope_values):
                raise ValueError(
                    'farm_id, site_id, and facility_id must be supplied together'
                )
            substrate_scope = tuple(
                _parse_positive_integer(value, field)
                for value, field in zip(
                    scope_values, ('farm_id', 'site_id', 'facility_id')
                )
            )
        else:
            substrate_scope = (None, None, None)
        total_input = Decimal('0')
        validated_inputs = []

        with db.transaction() as cursor:
            if substrate_scope[0] is not None:
                _assert_production_location(cursor, *substrate_scope)
            for requested in requested_inputs:
                cursor.execute(
                    """
                    SELECT id, business_id, farm_site, quantity, unit, status,
                           source_name
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
                if lot['farm_site'].strip().casefold() != batch_site.casefold():
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
                'preparation_date': normalized_data['prep_date'],
                'total_input_weight_kg': total_input,
                'inputs': input_details,
                'legacy_record_id': legacy_record['id'],
            },
            'id': batch['id'],
            'business_id': batch['business_id'],
        }), 201
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        logger.error(f"Error saving substrate preparation record: {e}")
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500

@app.route('/api/waste-lots', methods=['GET'])
@login_required
def get_available_waste_lots():
    try:
        records = db.fetch_all(
            """
            SELECT wl.id, wl.business_id, wl.farm_site, wl.source_type,
                   wl.source_name, wl.waste_type, wl.collection_date,
                   wl.quantity, wl.unit, wl.quality_status, wl.status,
                   wl.recorded_by, wl.created_at,
                   wl.quantity - COALESCE(SUM(sbi.quantity_used), 0)
                       AS available_quantity
            FROM waste_lots AS wl
            LEFT JOIN substrate_batch_inputs AS sbi ON sbi.waste_lot_id = wl.id
            WHERE wl.status = 'available'
            GROUP BY wl.id
            HAVING wl.quantity - COALESCE(SUM(sbi.quantity_used), 0) > 0
            ORDER BY wl.collection_date DESC, wl.id DESC
            """
        )
        return jsonify({'success': True, 'data': records}), 200
    except Exception as e:
        logger.error(f"Error fetching available Waste Lots: {e}")
        return jsonify({'success': False, 'message': 'Could not load Waste Lots'}), 500


def _substrate_batch_detail_query(where_clause='', order_clause=''):
    return f"""
        SELECT sb.id, sb.batch_code, sb.business_id, sb.preparation_date,
               sb.farm_site, sb.total_input_weight_kg, sb.particle_size,
               sb.notes, sb.recorded_by, sb.created_at,
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
        LEFT JOIN substrate_batch_inputs AS sbi
            ON sbi.substrate_batch_id = sb.id
        LEFT JOIN waste_lots AS wl ON wl.id = sbi.waste_lot_id
        {where_clause}
        GROUP BY sb.id
        {order_clause}
    """


@app.route('/api/substrate-batches', methods=['GET'])
@login_required
def get_substrate_batches():
    try:
        records = db.fetch_all(
            _substrate_batch_detail_query(
                order_clause="ORDER BY sb.preparation_date DESC, sb.id DESC"
            )
        )
        return jsonify({'success': True, 'data': records}), 200
    except Exception as e:
        logger.error(f"Error fetching Substrate Batches: {e}")
        return jsonify({'success': False, 'message': 'Could not load Substrate Batches'}), 500


@app.route('/api/substrate/batches/<string:batch_no>', methods=['GET'])
@login_required
def get_substrate_batch(batch_no):
    try:
        record = db.fetch_one(
            _substrate_batch_detail_query(
                "WHERE sb.batch_code = %s OR sb.business_id = %s"
            ),
            (batch_no, batch_no),
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


@app.route('/api/inventory/movements', methods=['POST'])
@login_required
def create_inventory_movement():
    """Post an auditable inventory movement with a database-generated MOV ID."""
    data = normalize_keys(request.get_json() or {})
    required_fields = ['product_lot_id', 'movement_type', 'quantity_kg']
    missing_fields = [field for field in required_fields if data.get(field) in (None, '')]
    if missing_fields:
        return jsonify({'success': False, 'message': f'Missing required fields: {", ".join(missing_fields)}'}), 400

    try:
        query = """
            INSERT INTO inventory_movements (
                product_lot_id, movement_type, quantity_kg, occurred_at, notes, recorded_by
            ) VALUES (%s, %s, %s, COALESCE(%s, CURRENT_TIMESTAMP), %s, %s)
            RETURNING id, business_id, product_lot_id
        """
        record = db.execute_returning(query, (
            data['product_lot_id'],
            data['movement_type'],
            data['quantity_kg'],
            data.get('occurred_at'),
            data.get('notes'),
            current_user.username,
        ))
        return jsonify({'success': True, 'record': record, 'id': record['id'],
                        'business_id': record['business_id']}), 201
    except Exception as e:
        logger.error(f"Error creating inventory movement: {e}")
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


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
        if (
            harvest['farm_id'] != batch['farm_id']
            or harvest['site_id'] != batch['site_id']
            or harvest['facility_id'] != batch['facility_id']
        ):
            raise ValueError('Harvest and Drying Batch locations must match')
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
    # This will catch any exception not already handled
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
