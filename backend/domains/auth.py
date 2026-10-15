"""Sign-in, registration, sign-out and the current user's profile."""

from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required, logout_user
from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Regexp, ValidationError

from backend.demo import is_demo_database
from backend.passwords import password_problem
from backend.roles import ROLE_LABELS
from backend.core.web import app, db, logger
from backend.core.audit import audit_event
from backend.core.security import _landing_page, _permissions_for
from backend.core.accounts import (
    LoginThrottled,
    _account_field_problem,
    _authenticate,
    _start_session,
    create_user,
    get_user_by_email,
)


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
        # Same limits as the JSON API (_account_field_problem).
        Length(min=3, max=50, message='Username must be between 3 and 50 characters'),
        Regexp(r'^[A-Za-z0-9_.-]+$', message='Username can only contain letters, numbers, dots, dashes and underscores')
    ])
    full_name = StringField('Full Name', validators=[
        DataRequired(),
        Length(min=2, max=100, message='Full name must be between 2 and 100 characters')
    ])
    email = StringField('Email', validators=[
        DataRequired(), 
        Email(message='Please enter a valid email address')
    ])
    # The password rule itself is password_problem() (backend/passwords.py), checked
    # in the view, so the form, the JSON API and admin resets all agree.
    password = PasswordField('Password', validators=[DataRequired()])
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

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    form = RegistrationForm()
    if form.validate_on_submit():
        problem = password_problem(form.password.data, email=form.email.data, username=form.username.data)
        if problem:
            flash(problem, 'danger')
            return render_template('register.html', form=form), 400
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
    from flask import session
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

@app.route('/api/auth/register', methods=['POST'])
def api_register():
    """API endpoint for AJAX registration requests"""
    data = request.get_json(silent=True) or {}
    username = str(data.get('username') or '').strip()
    full_name = str(data.get('fullName') or '').strip()
    email = str(data.get('email') or '').lower().strip()
    password = str(data.get('password') or '')
    confirm_password = str(data.get('confirmPassword') or '')

    # Simple validation
    if not all([username, full_name, email, password, confirm_password]):
        return jsonify({'success': False, 'message': 'All fields are required'}), 400
    problem = _account_field_problem(username, full_name, email)
    if problem:
        return jsonify({'success': False, 'message': problem}), 400
    if password != confirm_password:
        return jsonify({'success': False, 'message': 'Passwords do not match'}), 400
    problem = password_problem(password, email=email, username=username)
    if problem:
        return jsonify({'success': False, 'message': problem}), 400
    if db.fetch_one("SELECT 1 FROM users WHERE LOWER(username) = LOWER(%s)", (username,)):
        return jsonify({'success': False, 'message': 'Username is already taken'}), 409
        
    # Check if user already exists
    if get_user_by_email(email):
        return jsonify({'success': False, 'message': 'Email is already registered'}), 409

    try:
        create_user(username, full_name, email, password)
        return jsonify({'success': True, 'message': 'Registration successful'}), 201
    except Exception as e:
        logger.error(f"API Registration error: {e}")
        return jsonify({'success': False, 'message': 'Registration failed due to a server error'}), 500


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
