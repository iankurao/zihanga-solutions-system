"""Location access: which organizations, farms, sites and facilities a user may see."""

from flask import request
from flask_login import current_user

from backend.core.web import app
from backend.core.http import ProductionEventPermissionError, _parse_positive_integer
from backend.core.security import _can


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


# ---- Farm-level access (commercial records) -------------------------------
#
# Commercial records are farm-scoped and visible only to users with farm or
# organization access and a role that may see sales data (or super admins);
# facility-only operators do not see customers or order quantities.

def _farm_access_allowed(cursor, farm_id, permission='sales.read'):
    """Farm/organization access for ``farm_id`` plus, by default, the right to
    see commercial data. Pass ``permission=None`` for farm-level records that
    are not commercial (stock thresholds, farm alerts)."""
    if permission and not _can(permission):
        return False
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


def _farm_visibility_clause(alias, permission='sales.read'):
    if permission and not _can(permission):
        return 'FALSE', ()
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
