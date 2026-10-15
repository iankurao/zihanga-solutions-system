"""Flask application, configuration, database handle and error pages."""

import decimal
import logging
import os
import secrets

from datetime import time as dt_time, timedelta
from flask import Flask, jsonify, request, send_from_directory
from flask.json.provider import DefaultJSONProvider
from flask_cors import CORS
from flask_login import LoginManager
from flask_session import Session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from backend.config import DATABASE_URL
from backend.database import DatabaseConnection
from backend.fly_facility_routes import fly_facility
from backend.location_routes import locations
from backend.waste_management_routes import waste_management


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CustomJSONProvider(DefaultJSONProvider):
    def default(self, obj):
        if isinstance(obj, decimal.Decimal):
            return float(obj)
        # Raw rows from TIME and INTERVAL columns (legacy tables) are not JSON types.
        if isinstance(obj, dt_time):
            return obj.isoformat()
        if isinstance(obj, timedelta):
            return str(obj)
        return super().default(obj)

# Named and rooted as backend/app.py (the entry point), so the frontend paths,
# app name and logger are the same as before the code was split into modules.
app = Flask('backend.app',
            root_path=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            static_folder='../frontend',
            template_folder='../frontend')
app.json_provider_class = CustomJSONProvider
app.json = CustomJSONProvider(app)

            
# Trust proxy headers (Replit terminates SSL at proxy level)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Cross-origin access is off unless CORS_ORIGINS lists trusted origins
# (comma-separated). The browser UI is served from this app and needs none.
_cors_origins = [o.strip() for o in os.getenv('CORS_ORIGINS', '').split(',') if o.strip()]
if _cors_origins:
    CORS(app, origins=_cors_origins, supports_credentials=True)

# Configure Flask app
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY') or os.getenv('SESSION_SECRET') or secrets.token_hex(32)
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)  # Session timeout

# SQLAlchemy configuration
# Without DATABASE_URL the app still imports (tooling, tests that skip the
# database); the placeholder never connects, so any query fails loudly.
if not DATABASE_URL:
    logger.warning('DATABASE_URL is not set; database features will not work')
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL or 'postgresql://'
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

# Session cookies: never readable by JavaScript, HTTPS-only, and SameSite=Lax
# so other sites cannot ride on a signed-in session. EMBEDDED_PREVIEW=1 relaxes
# SameSite to None for the Replit workspace preview iframe; the Origin check
# in _reject_cross_site_writes still blocks cross-site writes then.
_embedded_preview = os.getenv('EMBEDDED_PREVIEW', '').lower() in ('1', 'true', 'yes')
_cookie_samesite = 'None' if _embedded_preview else 'Lax'
_cookie_secure = os.getenv('SESSION_COOKIE_SECURE', '1').lower() not in ('0', 'false', 'no')
app.config['SESSION_COOKIE_SAMESITE'] = _cookie_samesite
app.config['SESSION_COOKIE_SECURE'] = _cookie_secure or _embedded_preview
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_DOMAIN'] = None
app.config['SESSION_COOKIE_PATH'] = '/'
app.config['SESSION_COOKIE_NAME'] = 'bsf_session'

# Flask-Login remember cookie settings
app.config['REMEMBER_COOKIE_DURATION'] = timedelta(days=7)
app.config['REMEMBER_COOKIE_SAMESITE'] = _cookie_samesite
app.config['REMEMBER_COOKIE_SECURE'] = _cookie_secure or _embedded_preview
app.config['REMEMBER_COOKIE_HTTPONLY'] = True
app.config['REMEMBER_COOKIE_NAME'] = 'bsf_remember'
# Form tokens are replaced by the Origin/Referer check for every write
# (see _reject_cross_site_writes), which also covers the JSON APIs.
app.config['WTF_CSRF_ENABLED'] = False
if not (os.getenv('SECRET_KEY') or os.getenv('SESSION_SECRET')):
    logger.warning('SECRET_KEY is not set; sessions will not survive a restart')

# Initialize Flask-Session with SQLAlchemy instance
# Server-side sessions live in PostgreSQL; with no database configured (tooling,
# database-less test runs) Flask's signed-cookie sessions are used instead.
sess = Session(app) if DATABASE_URL else None

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


def _client_ip():
    return (request.remote_addr or '')[:64]


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
