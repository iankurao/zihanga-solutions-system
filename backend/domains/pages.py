"""Plain page routes that are not owned by a single domain."""

from flask import render_template, send_from_directory
from flask_login import login_required

from backend.core.web import app
from backend.core.security import super_admin_required


@app.route('/')
def index():
    """Serve the main landing page"""
    return send_from_directory(app.static_folder, 'main.html')

@app.route('/dashboard')
@login_required
def dashboard():
    """Serve the main dashboard page"""
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/waste-collection')
@login_required
def waste_collection_page():
    """Record a waste collection (creates a waste lot)."""
    return send_from_directory(app.static_folder, 'waste_collection.html')


@app.route('/analytics')
@login_required
def analytics():
    """Serve the analytics dashboard page"""
    return send_from_directory(app.static_folder, 'analytics.html')


@app.route('/setup')
@login_required
@super_admin_required
def setup_page():
    return render_template('setup.html')


@app.route('/design-system')
@login_required
def design_system_page():
    """Reference page for the shared UI components (frontend/css/erp.css)."""
    return send_from_directory(app.static_folder, 'design_system.html')
