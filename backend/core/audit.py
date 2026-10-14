"""Who-is-acting description for audit triggers, and app-level audit events."""

import json
import secrets

from flask import g, has_request_context, request
from flask_login import current_user

from backend.database import DatabaseConnection
from backend.core.web import _client_ip, db, logger


# ---- Audit trail ---------------------------------------------------------------------
#
# Row changes are recorded by database triggers (migrations/audit_log.sql).
# Every connection borrowed during a request carries this description of the
# actor, so the triggers know who made the change and from where.

def _request_id():
    if 'audit_request_id' not in g:
        g.audit_request_id = secrets.token_hex(8)
    return g.audit_request_id


def _audit_actor_json():
    if not has_request_context():
        return None
    actor = {
        'ip': _client_ip(),
        'ua': (request.headers.get('User-Agent') or '')[:200],
        'path': request.path[:200],
        'request_id': _request_id(),
    }
    # Resolving current_user may itself query the database (to load the
    # user); that inner query is recorded without a user.
    if not g.get('audit_resolving_user'):
        g.audit_resolving_user = True
        try:
            if getattr(current_user, 'is_authenticated', False):
                actor.update(
                    user_id=int(current_user.id),
                    username=current_user.username,
                    role=current_user.role,
                )
        finally:
            g.audit_resolving_user = False
    return json.dumps(actor)


DatabaseConnection.audit_actor = staticmethod(_audit_actor_json)


def audit_event(action, entity_type, entity_id=None, *, entity_ref=None, new_value=None,
                reason=None, user=None):
    """Record an event that is not a row change (sign-in, refusal, ...).

    ``user`` names the account involved when it is not the signed-in user
    (e.g. at sign-in). Failures are logged and never break the request.
    """
    try:
        actor = json.loads(_audit_actor_json() or '{}')
        if user is not None:
            actor.update(user_id=user.id, username=user.username, role=user.role)
        db.execute_query(
            """
            INSERT INTO audit_log (
                actor_user_id, actor_username, actor_role, action, entity_type, entity_id,
                entity_ref, new_value, reason, ip_address, user_agent, request_id, request_path
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s)
            """,
            (
                actor.get('user_id'),
                actor.get('username') or ('anonymous' if actor else 'system'),
                actor.get('role'), action, entity_type,
                None if entity_id is None else str(entity_id),
                entity_ref,
                json.dumps(new_value, default=str) if new_value is not None else None,
                reason, actor.get('ip'), actor.get('ua'), actor.get('request_id'), actor.get('path'),
            ),
        )
    except Exception:
        logger.exception('Could not write audit event %s', action)
