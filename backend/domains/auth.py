"""Sign-in, sign-out and the current user's profile. Accounts are created by
administrators (domains/admin.py); there is no self-registration."""

from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required, logout_user
from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Email

from backend.demo import is_demo_database
from backend.roles import ROLE_LABELS
from backend.core.web import app, db, logger
from backend.core.audit import audit_event
from backend.core.security import _landing_page, _permissions_for
from backend.core.accounts import LoginThrottled, _authenticate, _start_session


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
# Authentication routes
def _safe_next(target):
    """Return ``target`` only if it is a path on this site (no open redirect)."""
    if not target or not target.startswith('/') or target.startswith('//') or '\\' in target:
        return None
    # Never send someone who just signed in straight back out.
    if target.split('?', 1)[0].rstrip('/') == '/logout':
        return None
    return target


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(_safe_next(request.args.get('next')) or url_for('dashboard'))
    
    form = LoginForm()
    if form.validate_on_submit():
        try:
            user = _authenticate(form.email.data, form.password.data)
        except LoginThrottled:
            flash('Too many failed sign-in attempts. Try again in 15 minutes.', 'danger')
            return render_template('login.html', form=form), 429
        if user:
            _start_session(user, remember=bool(form.remember.data))
            if user.role == 'super_admin':
                return redirect(url_for('zehunger_portal'))
            return redirect(_safe_next(request.args.get('next')) or _landing_page(user.role))
        flash('Invalid email or password', 'danger')
    
    return render_template('login.html', form=form)

@app.route('/register', methods=['GET'])
def register():
    """There is no self-registration: an administrator creates each account
    with its role and locations (Admin portal). Old links land on sign-in."""
    return redirect(url_for('login'))


@app.route('/logout')
def logout():
    # No sign-in required: with an expired session, "Sign out" must still end
    # up signed out instead of asking to sign in (and then signing out).
    from flask import session
    if current_user.is_authenticated:
        audit_event('auth.sign_out', 'user', current_user.id, entity_ref=current_user.username)
    # Clear first: logout_user() leaves a note in the session that makes
    # Flask-Login delete the remember-me cookie on this response.
    session.clear()
    logout_user()
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for('login'))

# API routes for AJAX requests
@app.route('/api/auth/login', methods=['POST'])
def api_login():
    """API endpoint for AJAX login requests"""
    from flask import session, make_response
    
    data = request.get_json(silent=True) or {}
    email = str(data.get('username') or '').lower().strip()  # Frontend sends username field
    password = str(data.get('password') or '')
    remember_me = bool(data.get('rememberMe', True))

    if not email or not password:
        return jsonify({'success': False, 'message': 'Email and password are required'}), 400

    try:
        user = _authenticate(email, password)
    except LoginThrottled:
        return jsonify({
            'success': False,
            'message': 'Too many failed sign-in attempts. Try again in 15 minutes.',
        }), 429
    if not user:
        return jsonify({'success': False, 'message': 'Invalid email or password'}), 401
    _start_session(user, remember=remember_me)
    next_url = _safe_next(data.get('next')) if user.role != 'super_admin' else None
    redirect_url = next_url or _landing_page(user.role)
    logger.info('User %s signed in', user.id)
    return make_response(jsonify({'success': True, 'message': 'Login successful', 'redirect': redirect_url, 'role': user.role}))

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
        'role_label': ROLE_LABELS.get(current_user.role, current_user.role),
        'permissions': _permissions_for(current_user.role),
        'home': _landing_page(current_user.role),
        # Demonstration database (python -m backend.demo); pages show a badge.
        'demo': is_demo_database(db),
    }})
