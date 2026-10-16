"""Roles and permissions, route guards, cross-site write protection and security headers."""

from flask import abort, jsonify, request
from flask_login import current_user

from backend.roles import PERMISSION_LABELS, ROLE_PERMISSIONS
from backend.core.web import _cors_origins, app, logger
from backend.core.audit import audit_event



def _can(permission):
    """True if the signed-in user's role grants ``permission``."""
    if not getattr(current_user, 'is_authenticated', False):
        return bool(app.config.get('LOGIN_DISABLED'))
    return permission in ROLE_PERMISSIONS.get(getattr(current_user, 'role', None), ())


def _permissions_for(role):
    return sorted(ROLE_PERMISSIONS.get(role, ()))


def _landing_page(role):
    if role == 'super_admin':
        return '/zehunger'
    if role == 'operator':
        return '/farmer'
    if role == 'manager':
        return '/dashboard'
    # Read-only and specialist roles start on the live operations dashboard;
    # /dashboard is mostly data-entry forms.
    return '/operations'


def requires(permission):
    """Route guard: 401 when signed out, 403 when the role lacks ``permission``."""
    from functools import wraps

    def decorator(view):
        @wraps(view)
        def guarded(*args, **kwargs):
            if not getattr(current_user, 'is_authenticated', False) and not app.config.get('LOGIN_DISABLED'):
                return jsonify({'success': False, 'message': 'Please sign in'}), 401
            if not _can(permission):
                audit_event('security.permission_denied', 'route', request.endpoint,
                            new_value={'permission': permission, 'method': request.method})
                return jsonify({
                    'success': False,
                    'message': f'Your role does not allow this ({PERMISSION_LABELS[permission].lower()})',
                }), 403
            return view(*args, **kwargs)
        guarded.required_permission = permission
        return guarded
    return decorator


def super_admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'super_admin':
            if current_user.is_authenticated:
                audit_event('security.permission_denied', 'route', request.endpoint,
                            new_value={'permission': 'super_admin', 'method': request.method})
            abort(403)
        return f(*args, **kwargs)
    decorated_function.required_permission = 'super_admin'
    return decorated_function


# ---- Cross-site request protection and security headers --------------------------

_TRUSTED_ORIGINS = {o.rstrip('/') for o in _cors_origins}


def _same_site_url(value):
    from urllib.parse import urlsplit
    parts = urlsplit(value)
    if not parts.scheme or not parts.netloc:
        return False
    origin = f'{parts.scheme}://{parts.netloc}'
    return origin == request.host_url.rstrip('/') or origin in _TRUSTED_ORIGINS


@app.before_request
def _reject_cross_site_writes():
    """Refuse state-changing requests sent by another website (CSRF).

    Browsers always send Origin (or at least Referer) on cross-site writes, so
    a write is refused when those headers name a different site. Requests
    without either header come from non-browser clients, which do not carry
    the user's cookies by accident.
    """
    if request.method in ('GET', 'HEAD', 'OPTIONS', 'TRACE'):
        return None
    if request.headers.get('Sec-Fetch-Site') == 'cross-site':
        return _cross_site_refusal()
    origin = request.headers.get('Origin')
    if origin and origin != 'null':
        return None if _same_site_url(origin) else _cross_site_refusal()
    if origin == 'null':
        return _cross_site_refusal()
    referer = request.headers.get('Referer')
    if referer and not _same_site_url(referer):
        return _cross_site_refusal()
    return None


def _cross_site_refusal():
    logger.warning('Refused cross-site %s %s', request.method, request.path)
    audit_event('security.cross_site_refused', 'route', request.endpoint,
                new_value={'method': request.method,
                           'origin': (request.headers.get('Origin') or request.headers.get('Referer') or '')[:200]})
    return jsonify({'success': False, 'message': 'Cross-site request refused'}), 403


@app.after_request
def _security_headers(response):
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
    response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    if request.is_secure:
        response.headers.setdefault('Strict-Transport-Security', 'max-age=31536000')
    if request.path.startswith('/api/'):
        response.headers.setdefault('Cache-Control', 'no-store')
    return response
