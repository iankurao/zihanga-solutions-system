"""Canonical organization, farm, site, facility, and access APIs."""

from functools import wraps

from flask import Blueprint, jsonify, request, abort
from flask_login import current_user, login_required
from psycopg2 import errors

from backend.database import DatabaseConnection


locations = Blueprint("locations", __name__)
db = DatabaseConnection()

_SCOPE_TABLES = {
    "organization": (
        "organizations",
        "organization_id",
        "user_organization_access",
    ),
    "farm": ("farms", "farm_id", "user_farm_access"),
    "site": ("sites", "site_id", "user_site_access"),
    "facility": ("facilities", "facility_id", "user_facility_access"),
}

_LINKABLE_TABLES = {
    "waste_sourcing", "storage_records", "processing_records",
    "waste_monitoring", "waste_lots", "substrate_preparation",
    "substrate_batches", "feeding_schedule", "health_intervention",
    "harvest_yield", "hatchery_batches", "hatchery_feeding",
    "hatchery_monitoring", "hatchery_cleaning", "hatchery_problems",
    "hatchery_health_interventions", "cage_monitoring",
    "facility_maintenance", "pupae_transition", "egg_collection",
    "bait_preparation", "drying_batches", "drying_input", "drying_output",
    "drying_quality_control", "drying_review_approval", "production_batches",
    "product_lots", "inventory_movements", "sales", "deliveries",
}


def _admin_required(view):
    @wraps(view)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != "super_admin":
            abort(403)
        return view(*args, **kwargs)

    decorated.required_permission = "super_admin"
    return decorated


def _text(data, field, maximum=150, required=True):
    value = str(data.get(field, "") or "").strip()
    if required and not value:
        raise ValueError(f"{field} is required")
    if len(value) > maximum:
        raise ValueError(f"{field} must be at most {maximum} characters")
    return value


def _status(data):
    value = str(data.get("status", "active") or "active").strip().lower()
    if value not in {"active", "inactive"}:
        raise ValueError("status must be active or inactive")
    return value


def _created(table, fields, values):
    columns = ", ".join(fields)
    placeholders = ", ".join(["%s"] * len(values))
    return db.execute_returning(
        f"INSERT INTO {table} ({columns}) VALUES ({placeholders}) "
        "RETURNING *",
        tuple(values),
    )


@locations.route("/api/locations/hierarchy", methods=["GET"])
@login_required
def hierarchy():
    """List the canonical hierarchy visible to the current user."""
    params = []
    access_filter = ""
    if current_user.role != "super_admin":
        access_filter = """
            WHERE EXISTS (
                SELECT 1 FROM user_organization_access uoa
                WHERE uoa.user_id = %s AND uoa.organization_id = o.id
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
                WHERE uca.user_id = %s AND uca.facility_id = ft.id
            )
        """
        params = [current_user.id] * 4
    rows = db.fetch_all(
        f"""
        SELECT
            o.id AS organization_id, o.organization_code,
            o.name AS organization_name, o.status AS organization_status,
            f.id AS farm_id, f.farm_code, f.name AS farm_name,
            f.status AS farm_status,
            s.id AS site_id, s.site_code, s.name AS site_name,
            s.status AS site_status,
            ft.id AS facility_id, ft.facility_code,
            ft.name AS facility_name, ft.facility_type,
            ft.status AS facility_status
        FROM organizations o
        LEFT JOIN farms f ON f.organization_id = o.id
        LEFT JOIN sites s ON s.farm_id = f.id
        LEFT JOIN facilities ft ON ft.site_id = s.id
        {access_filter}
        ORDER BY o.name, f.name, s.name, ft.name
        """,
        params,
    )
    return jsonify({"success": True, "data": rows})


@locations.route("/api/locations/organizations", methods=["POST"])
@login_required
@_admin_required
def create_organization():
    data = request.get_json() or {}
    try:
        row = _created(
            "organizations",
            ["organization_code", "name", "description", "status"],
            [_text(data, "organization_code", 30), _text(data, "name"),
             _text(data, "description", 2000, False), _status(data)],
        )
        return jsonify({"success": True, "data": row}), 201
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    except errors.UniqueViolation:
        return jsonify({"success": False, "message": "Organization code already exists"}), 409


@locations.route("/api/locations/farms", methods=["POST"])
@login_required
@_admin_required
def create_farm():
    data = request.get_json() or {}
    try:
        org_id = int(data.get("organization_id"))
        row = _created(
            "farms",
            ["organization_id", "farm_code", "name", "location_description", "status"],
            [org_id, _text(data, "farm_code", 30), _text(data, "name"),
             _text(data, "location_description", 2000, False), _status(data)],
        )
        return jsonify({"success": True, "data": row}), 201
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "organization_id must be a valid integer"}), 400
    except errors.ForeignKeyViolation:
        return jsonify({"success": False, "message": "Organization not found"}), 404
    except errors.UniqueViolation:
        return jsonify({"success": False, "message": "Farm code already exists in this organization"}), 409


@locations.route("/api/locations/sites", methods=["POST"])
@login_required
@_admin_required
def create_site():
    data = request.get_json() or {}
    try:
        farm_id = int(data.get("farm_id"))
        row = _created(
            "sites",
            ["farm_id", "site_code", "name", "location_description", "status"],
            [farm_id, _text(data, "site_code", 30), _text(data, "name"),
             _text(data, "location_description", 2000, False), _status(data)],
        )
        return jsonify({"success": True, "data": row}), 201
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "farm_id must be a valid integer"}), 400
    except errors.ForeignKeyViolation:
        return jsonify({"success": False, "message": "Farm not found"}), 404
    except errors.UniqueViolation:
        return jsonify({"success": False, "message": "Site code already exists in this farm"}), 409


@locations.route("/api/locations/facilities", methods=["POST"])
@login_required
@_admin_required
def create_facility():
    data = request.get_json() or {}
    try:
        site_id = int(data.get("site_id"))
        row = _created(
            "facilities",
            ["site_id", "facility_code", "name", "facility_type", "description", "status"],
            [site_id, _text(data, "facility_code", 30), _text(data, "name"),
             _text(data, "facility_type", 80), _text(data, "description", 2000, False),
             _status(data)],
        )
        return jsonify({"success": True, "data": row}), 201
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "site_id must be a valid integer"}), 400
    except errors.ForeignKeyViolation:
        return jsonify({"success": False, "message": "Site not found"}), 404
    except errors.UniqueViolation:
        return jsonify({"success": False, "message": "Facility code already exists in this site"}), 409


@locations.route("/api/locations/<string:scope>/<int:scope_id>/status", methods=["POST"])
@login_required
@_admin_required
def set_location_status(scope, scope_id):
    """Activate or deactivate a location; records are never hard-deleted."""
    if scope not in _SCOPE_TABLES:
        return jsonify({"success": False, "message": "scope must be organization, farm, site, or facility"}), 400
    try:
        status = _status(request.get_json() or {})
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    table = _SCOPE_TABLES[scope][0]
    row = db.execute_returning(
        f"UPDATE {table} SET status = %s, updated_at = CURRENT_TIMESTAMP "
        "WHERE id = %s RETURNING id, status",
        (status, scope_id),
    )
    if not row:
        return jsonify({"success": False, "message": f"{scope.title()} not found"}), 404
    return jsonify({"success": True, "data": row})


@locations.route("/api/locations/access", methods=["POST", "DELETE"])
@login_required
@_admin_required
def manage_access():
    data = request.get_json() or {}
    scope = str(data.get("scope", "") or "").strip().lower()
    if scope not in _SCOPE_TABLES:
        return jsonify({"success": False, "message": "scope must be organization, farm, site, or facility"}), 400
    try:
        user_id = int(data.get("user_id"))
        scope_id = int(data.get("scope_id"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "user_id and scope_id must be valid integers"}), 400

    table, column, access_table = _SCOPE_TABLES[scope]
    target = db.fetch_one(f"SELECT id FROM {table} WHERE id = %s", (scope_id,))
    user = db.fetch_one("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
    if not target:
        return jsonify({"success": False, "message": f"{scope.title()} not found"}), 404
    if not user:
        return jsonify({"success": False, "message": "User not found"}), 404

    if request.method == "DELETE":
        db.execute_query(
            f"DELETE FROM {access_table} WHERE user_id = %s AND {column} = %s",
            (user_id, scope_id),
        )
        return jsonify({"success": True, "message": "Location access revoked"})

    db.execute_query(
        f"INSERT INTO {access_table} (user_id, {column}, granted_by) "
        "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
        (user_id, scope_id, current_user.id),
    )
    return jsonify({"success": True, "message": "Location access granted"}), 201


@locations.route("/api/locations/users/<int:user_id>/access", methods=["GET"])
@login_required
@_admin_required
def user_access(user_id):
    user = db.fetch_one("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
    if not user:
        return jsonify({"success": False, "message": "User not found"}), 404
    result = {}
    for scope, (table, column, access_table) in _SCOPE_TABLES.items():
        result[scope] = db.fetch_all(
            f"SELECT x.* FROM {table} x "
            f"JOIN {access_table} a ON a.{column} = x.id "
            "WHERE a.user_id = %s ORDER BY x.name",
            (user_id,),
        )
    return jsonify({"success": True, "data": result})


@locations.route("/api/locations/access/check", methods=["GET"])
@login_required
def check_access():
    try:
        facility_id = int(request.args["facility_id"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"success": False, "message": "facility_id must be a valid integer"}), 400
    if current_user.role == "super_admin":
        return jsonify({"success": True, "allowed": True, "reason": "super_admin"})

    allowed = db.fetch_one(
        """
        SELECT EXISTS (
            SELECT 1 FROM user_facility_access ufa
            WHERE ufa.user_id = %s AND ufa.facility_id = ft.id
        ) OR EXISTS (
            SELECT 1 FROM user_site_access usa
            WHERE usa.user_id = %s AND usa.site_id = s.id
        ) OR EXISTS (
            SELECT 1 FROM user_farm_access ufa
            WHERE ufa.user_id = %s AND ufa.farm_id = f.id
        ) OR EXISTS (
            SELECT 1 FROM user_organization_access uoa
            WHERE uoa.user_id = %s AND uoa.organization_id = o.id
        ) AS allowed
        FROM facilities ft
        JOIN sites s ON s.id = ft.site_id
        JOIN farms f ON f.id = s.farm_id
        JOIN organizations o ON o.id = f.organization_id
        WHERE ft.id = %s
        """,
        (current_user.id, current_user.id, current_user.id, current_user.id, facility_id),
    )
    if not allowed:
        return jsonify({"success": False, "message": "Facility not found"}), 404
    return jsonify({"success": True, "allowed": bool(allowed["allowed"])})


@locations.route("/api/locations/record-links", methods=["POST"])
@login_required
@_admin_required
def link_record():
    # Legacy records carry no proven owner, so assigning (or moving) their
    # location is an administrator's mapping decision, never a user claim.
    data = request.get_json() or {}
    entity_table = str(data.get("entity_table", "") or "").strip()
    if entity_table not in _LINKABLE_TABLES:
        return jsonify({"success": False, "message": "Unsupported operational table"}), 400
    try:
        entity_id = int(data.get("entity_id"))
        facility_id = int(data.get("facility_id"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "entity_id and facility_id must be valid integers"}), 400
    record = db.fetch_one(
        f"SELECT id FROM {entity_table} WHERE id = %s",
        (entity_id,),
    )
    if not record:
        return jsonify({"success": False, "message": "Operational record not found"}), 404

    location = db.fetch_one(
        """
        SELECT o.id AS organization_id, f.id AS farm_id, s.id AS site_id, ft.id AS facility_id
        FROM facilities ft
        JOIN sites s ON s.id = ft.site_id
        JOIN farms f ON f.id = s.farm_id
        JOIN organizations o ON o.id = f.organization_id
        WHERE ft.id = %s
        """,
        (facility_id,),
    )
    if not location:
        return jsonify({"success": False, "message": "Facility not found"}), 404
    row = db.execute_returning(
        """
        INSERT INTO operational_location_links
            (entity_table, entity_id, organization_id, farm_id, site_id, facility_id, recorded_by_user_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (entity_table, entity_id) DO UPDATE SET
            organization_id = EXCLUDED.organization_id,
            farm_id = EXCLUDED.farm_id,
            site_id = EXCLUDED.site_id,
            facility_id = EXCLUDED.facility_id,
            recorded_by_user_id = EXCLUDED.recorded_by_user_id,
            updated_at = CURRENT_TIMESTAMP
        RETURNING *
        """,
        (entity_table, entity_id, location["organization_id"], location["farm_id"],
         location["site_id"], location["facility_id"], current_user.id),
    )
    return jsonify({"success": True, "data": row}), 201