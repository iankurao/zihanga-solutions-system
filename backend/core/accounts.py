"""User accounts: loading, creation, sign-in throttling and sessions."""

import re
import secrets

from datetime import timedelta
from flask import jsonify, redirect, request, url_for
from flask_login import UserMixin, login_user
from werkzeug.security import check_password_hash, generate_password_hash

from backend.roles import ASSIGNABLE_ROLES
from backend.core.web import _client_ip, app, db, login_manager
from backend.core.audit import audit_event


# User class for Flask-Login
class User(UserMixin):
    def __init__(self, user_id, username, email, password_hash, full_name=None, last_login=None, is_active=True, role='viewer', auth_version=1):
        self.id = user_id
        self.username = username
        self.email = email
        self.password_hash = password_hash
        self.full_name = full_name
        self.last_login = last_login
        self._is_active = is_active
        self.role = role
        self.auth_version = auth_version

    @property
    def is_active(self):
        return self._is_active

    @property
    def is_super_admin(self):
        return self.role == 'super_admin'

    def get_id(self):
        # The version invalidates sessions after a password reset, role change
        # or deactivation (see load_user).
        return f'{self.id}:{self.auth_version}'

# Database helper functions
def get_user_by_email(email):
    """Get user by email from database"""
    result = db.fetch_one("""
        SELECT user_id, username, email, password_hash, full_name, last_login, is_active, role, auth_version
        FROM users WHERE email = %s
    """, (email,))
    return _user_from_row(result)


def _user_from_row(result):
    if not result:
        return None
    return User(
        user_id=result['user_id'],
        username=result['username'],
        email=result['email'],
        password_hash=result['password_hash'],
        full_name=result['full_name'],
        last_login=result['last_login'],
        is_active=result['is_active'],
        role=result.get('role') or 'viewer',
        auth_version=result.get('auth_version') or 1,
    )

def get_user_by_id(user_id):
    """Get user by ID from database"""
    result = db.fetch_one("""
        SELECT user_id, username, email, password_hash, full_name, last_login, is_active, role, auth_version
        FROM users WHERE user_id = %s
    """, (user_id,))
    return _user_from_row(result)

def create_user(username, full_name, email, password, role='viewer'):
    """Create a new user in the database"""
    if role not in ASSIGNABLE_ROLES:
        raise ValueError('Unknown role')
    password_hash = generate_password_hash(password)

    query = """
        INSERT INTO users (username, full_name, email, password_hash, role, created_at)
        VALUES (%s, %s, %s, %s, %s, NOW())
        RETURNING user_id
    """
    return db.execute_returning(query, (username, full_name, email, password_hash, role))['user_id']


_EMAIL_PATTERN = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _account_field_problem(username, full_name, email):
    if not re.fullmatch(r'[A-Za-z0-9_.-]{3,50}', username or ''):
        return 'Username must be 3-50 letters, numbers, dots, dashes or underscores'
    if not 2 <= len(full_name or '') <= 100:
        return 'Full name must be between 2 and 100 characters'
    if len(email or '') > 100 or not _EMAIL_PATTERN.match(email or ''):
        return 'Enter a valid email address'
    return None


# ---- Login throttling ---------------------------------------------------------------

LOGIN_WINDOW_MINUTES = 15
LOGIN_MAX_FAILURES_PER_ACCOUNT = 5
LOGIN_MAX_FAILURES_PER_IP = 30
# Compared against when the email is unknown, so response time does not reveal
# which addresses have accounts.
_DUMMY_PASSWORD_HASH = generate_password_hash(secrets.token_hex(16))


def _login_blocked(email):
    row = db.fetch_one(
        """
        SELECT
            COUNT(*) FILTER (WHERE email = %s) AS account_failures,
            COUNT(*) FILTER (WHERE ip_address = %s) AS ip_failures
        FROM auth_login_attempts
        WHERE NOT succeeded AND attempted_at > now() - make_interval(mins => %s)
          AND (email = %s OR ip_address = %s)
        """,
        (email, _client_ip(), LOGIN_WINDOW_MINUTES, email, _client_ip()),
    )
    return (
        int(row['account_failures']) >= LOGIN_MAX_FAILURES_PER_ACCOUNT
        or int(row['ip_failures']) >= LOGIN_MAX_FAILURES_PER_IP
    )


def _record_login_attempt(email, succeeded):
    db.execute_query(
        "INSERT INTO auth_login_attempts (email, ip_address, succeeded) VALUES (%s, %s, %s)",
        (email[:255], _client_ip(), succeeded),
    )


class LoginThrottled(Exception):
    pass


def _authenticate(email, password):
    """Return the active user for these credentials, or None.

    Raises LoginThrottled after too many recent failures for the account or
    the client address.
    """
    email = (email or '').lower().strip()
    if _login_blocked(email):
        audit_event('auth.sign_in_throttled', 'user', entity_ref=email[:100])
        raise LoginThrottled()
    user = get_user_by_email(email) if email else None
    valid = check_password_hash(user.password_hash if user else _DUMMY_PASSWORD_HASH, password or '')
    succeeded = bool(user and valid and user.is_active)
    _record_login_attempt(email, succeeded)
    if succeeded:
        audit_event('auth.sign_in', 'user', user.id, entity_ref=user.username, user=user)
    else:
        reason = 'inactive account' if user and valid else 'wrong email or password'
        audit_event('auth.sign_in_failed', 'user', user.id if user else None,
                    entity_ref=email[:100], reason=reason)
    return user if succeeded else None


def _start_session(user, *, remember):
    """Sign ``user`` in on a fresh session id (prevents session fixation)."""
    from flask import session
    session.clear()
    regenerate = getattr(app.session_interface, 'regenerate', None)
    if regenerate:
        regenerate(session)
    session.permanent = True
    login_user(user, remember=remember, duration=timedelta(days=7), fresh=True)
    update_last_login(user.id)

def update_last_login(user_id):
    """Update user's last login time"""
    db.execute_query("""
        UPDATE users SET last_login = NOW()
        WHERE user_id = %s
    """, (user_id,))

@login_manager.user_loader
def load_user(user_id):
    # Sessions from before Step 22 store the bare id and count as version 1.
    raw_id, _, raw_version = str(user_id).partition(':')
    try:
        user = get_user_by_id(int(raw_id))
        version = int(raw_version or 1)
    except (TypeError, ValueError):
        return None
    if not user or not user.is_active or user.auth_version != version:
        return None
    return user


@login_manager.unauthorized_handler
def _unauthorized():
    if request.path.startswith('/api/'):
        return jsonify({'success': False, 'message': 'Please sign in'}), 401
    return redirect(url_for('login', next=request.full_path.rstrip('?')))

