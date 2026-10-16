"""Shared harness for scenario tests that run with real sign-in.

Unlike the older chain tests (LOGIN_DISABLED, super-user by default), these
build everything through the public API as the people who would do it: a
super admin sets up locations and accounts, then each user signs in through
/api/auth/login and works with their own session and role.
"""
import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch
from uuid import uuid4

try:
    import psycopg2
except ImportError:  # pragma: no cover - dependency supplied by the app
    psycopg2 = None

from backend.database import DatabaseConnection

with patch.object(DatabaseConnection, "_initialize_pool", new=classmethod(lambda cls: None)):
    from backend.app import app, db

DB_CONFIGURED = psycopg2 is not None and bool(os.getenv("DATABASE_URL") or os.getenv("PGHOST"))
requires_database = unittest.skipUnless(DB_CONFIGURED, "PostgreSQL connection is not configured")

HTTPS = {"base_url": "https://localhost"}


class Session:
    """A signed-in user with their own cookie jar."""

    def __init__(self, user_id, username, email, password, role):
        self.id, self.username, self.email, self.password, self.role = user_id, username, email, password, role
        self.client = app.test_client()

    def sign_in(self):
        response = self.client.post(
            "/api/auth/login", json={"username": self.email, "password": self.password}, **HTTPS
        )
        assert response.status_code == 200, (self.email, response.get_json())
        return response

    def get(self, url, **kwargs):
        return self.client.get(url, **HTTPS, **kwargs)

    def post(self, url, body=None, **kwargs):
        return self.client.post(url, json=body if body is not None else {}, **HTTPS, **kwargs)

    def put(self, url, body=None, **kwargs):
        return self.client.put(url, json=body if body is not None else {}, **HTTPS, **kwargs)

    def delete(self, url, body=None, **kwargs):
        return self.client.delete(url, json=body if body is not None else {}, **HTTPS, **kwargs)


class ScenarioTestCase(unittest.TestCase):
    """Base class: real sessions, unique locations per test, full cleanup."""

    @classmethod
    def setUpClass(cls):
        from backend.init_db import init_database

        init_database()
        if DatabaseConnection._pool is None:
            DatabaseConnection._initialize_pool()
        cls._login_disabled = app.config.get("LOGIN_DISABLED", False)
        app.config["LOGIN_DISABLED"] = False
        app.testing = True

    @classmethod
    def tearDownClass(cls):
        app.config["LOGIN_DISABLED"] = cls._login_disabled

    def setUp(self):
        self.marker = f"sc{uuid4().hex[:10]}"
        self.farm_ids, self.org_ids, self.customer_names, self.waste_sources = [], [], [], []
        self.addCleanup(self._purge)
        self.admin = self.make_user("super_admin")

    # ---- accounts -------------------------------------------------------------------

    def make_user(self, role, *, access=(), full_name=None):
        """Create a user with ``role`` and location ``access`` [(scope, id)], signed in."""
        from werkzeug.security import generate_password_hash

        name = f"{role[:6]}{uuid4().hex[:8]}"
        email = f"{name}@example.com"
        password = f"pass phrase {uuid4().hex[:12]}"
        if role == "super_admin":
            # Super admins are created out of band (create_super_admin script).
            row = db.execute_returning(
                "INSERT INTO users (username, full_name, email, password_hash, role) "
                "VALUES (%s, %s, %s, %s, 'super_admin') RETURNING user_id",
                (name, full_name or name, email, generate_password_hash(password)),
            )
            user_id = row["user_id"]
        else:
            created = self.admin.post("/api/admin/users", {
                "username": name, "full_name": full_name or name.title(), "email": email,
                "password": password, "role": role,
            })
            assert created.status_code == 201, created.get_json()
            user_id = db.fetch_one("SELECT user_id FROM users WHERE email = %s", (email,))["user_id"]
        self.addCleanup(db.execute_query, "DELETE FROM users WHERE user_id = %s", (user_id,))
        self.addCleanup(db.execute_query, "DELETE FROM auth_login_attempts WHERE email = %s", (email,))
        self.addCleanup(db.execute_query, "DELETE FROM notifications WHERE user_id = %s", (user_id,))
        for scope, scope_id in access:
            granted = self.admin.post("/api/locations/access", {
                "user_id": user_id, "scope": scope, "scope_id": scope_id,
            })
            assert granted.status_code == 201, granted.get_json()
        session = Session(user_id, name, email, password, role)
        session.sign_in()
        return session

    # ---- locations ------------------------------------------------------------------

    def ok(self, response, status=None):
        expected = (status,) if status else (200, 201)
        self.assertIn(response.status_code, expected, response.get_json())
        return response.get_json()

    def make_farm(self, *, facilities=("production",)):
        """Organization > farm > one site > facilities of the given types, via the API."""
        tag = uuid4().hex[:6]
        org = self.ok(self.admin.post("/api/locations/organizations", {
            "organization_code": f"O{tag}", "name": f"{self.marker} org"}), 201)["data"]
        self.org_ids.append(org["id"])
        farm = self.ok(self.admin.post("/api/locations/farms", {
            "organization_id": org["id"], "farm_code": f"F{tag}", "name": f"{self.marker} farm {tag}"}), 201)["data"]
        self.farm_ids.append(farm["id"])
        site = self.ok(self.admin.post("/api/locations/sites", {
            "farm_id": farm["id"], "site_code": f"S{tag}", "name": f"{self.marker} site"}), 201)["data"]
        made = []
        for index, kind in enumerate(facilities):
            made.append(self.ok(self.admin.post("/api/locations/facilities", {
                "site_id": site["id"], "facility_code": f"{kind[:3].upper()}{index}{tag}",
                "name": f"{self.marker} {kind} {index}", "facility_type": kind}), 201)["data"])
        return {"organization": org, "farm": farm, "site": site, "facilities": made}

    @staticmethod
    def scope(place, facility, site=None):
        return {"farm_id": place["farm"]["id"], "site_id": (site or place["site"])["id"],
                "facility_id": facility["id"]}

    def make_batch(self, session, place, facility, site=None, *, day="2026-09-20"):
        """Waste lot -> substrate -> production batch at ``facility``, through the API."""
        scope = self.scope(place, facility, site)
        source = f"{self.marker} src {uuid4().hex[:4]}"
        self.waste_sources.append(source)
        lot = self.ok(session.post("/api/waste-sourcing", {
            **scope, "collection_date": day, "collection_time": "07:00", "source_type": "market",
            "source_name": source, "waste_type": "vegetable", "waste_weight": "5", "segregation_status": "organic",
            "collection_personnel": "test", "lot_status": "available", "contaminants_found": []}), 201)["waste_lot"]
        substrate = self.ok(session.post("/api/substrate-preparation", {
            **scope, "batch_no": f"sb-{uuid4().hex[:8]}", "prep_date": day, "moisture_consistency": "moist",
            "waste_particle_size": "fine", "foreign_matter": "no", "handler_operator": "test",
            "inputs": [{"waste_lot_id": lot["id"], "quantity_used": "4"}]}), 201)["id"]
        return self.ok(session.post("/api/production/batches", {
            **scope, "start_date": day, "current_stage": "STARTING",
            "inputs": [{"substrate_batch_id": substrate, "quantity_issued": "3"}]}), 201)["record"]

    # ---- cleanup --------------------------------------------------------------------

    def _purge(self):
        for farm_id in self.farm_ids:
            purge_farm(farm_id)
        for name in self.customer_names:
            db.execute_query("DELETE FROM customers WHERE name = %s", (name,))
        for source in self.waste_sources:
            db.execute_query("DELETE FROM waste_sourcing WHERE source_name = %s", (source,))
        for org_id in self.org_ids:
            db.execute_query("DELETE FROM organizations WHERE id = %s", (org_id,))


_FARM_PURGE = [
    """DELETE FROM customer_delivery_lines WHERE delivery_id IN (
        SELECT d.id FROM customer_deliveries d JOIN customer_orders o ON o.id = d.order_id WHERE o.farm_id = %(f)s)""",
    "DELETE FROM customer_deliveries WHERE order_id IN (SELECT id FROM customer_orders WHERE farm_id = %(f)s)",
    """DELETE FROM order_allocations WHERE order_line_id IN (
        SELECT l.id FROM customer_order_lines l JOIN customer_orders o ON o.id = l.order_id WHERE o.farm_id = %(f)s)""",
    "DELETE FROM customer_order_lines WHERE order_id IN (SELECT id FROM customer_orders WHERE farm_id = %(f)s)",
    "DELETE FROM customer_orders WHERE farm_id = %(f)s",
    "DELETE FROM notifications WHERE alert_id IN (SELECT id FROM operational_alerts WHERE farm_id = %(f)s)",
    "DELETE FROM operational_alerts WHERE farm_id = %(f)s",
    "DELETE FROM production_batch_units WHERE production_unit_id IN (SELECT id FROM production_units WHERE farm_id = %(f)s)",
    "DELETE FROM production_units WHERE farm_id = %(f)s",
    "DELETE FROM inventory_alert_thresholds WHERE farm_id = %(f)s",
    "DELETE FROM inventory_movements WHERE farm_id = %(f)s",
    """DELETE FROM product_lots WHERE drying_output_id IN (
        SELECT o.id FROM drying_outputs o JOIN drying_batches b ON b.id = o.drying_batch_id WHERE b.farm_id = %(f)s)""",
    """DELETE FROM quality_approvals WHERE quality_check_id IN (
        SELECT id FROM quality_checks WHERE drying_batch_id IN (SELECT id FROM drying_batches WHERE farm_id = %(f)s))""",
    "DELETE FROM quality_checks WHERE drying_batch_id IN (SELECT id FROM drying_batches WHERE farm_id = %(f)s)",
    "DELETE FROM drying_outputs WHERE drying_batch_id IN (SELECT id FROM drying_batches WHERE farm_id = %(f)s)",
    "DELETE FROM drying_inputs WHERE drying_batch_id IN (SELECT id FROM drying_batches WHERE farm_id = %(f)s)",
    "DELETE FROM drying_batch_status_history WHERE drying_batch_id IN (SELECT id FROM drying_batches WHERE farm_id = %(f)s)",
    "DELETE FROM drying_batches WHERE farm_id = %(f)s",
    """DELETE FROM harvests WHERE production_event_id IN (SELECT id FROM production_events WHERE
        production_batch_id IN (SELECT id FROM production_batches WHERE farm_id = %(f)s))""",
    # Old copies of production events, while a database still has them (backend/retired_tables.py).
    *(f"""DO $$ BEGIN IF to_regclass('{table}') IS NOT NULL THEN
        DELETE FROM {table} WHERE production_batch_id IN (SELECT id FROM production_batches WHERE farm_id = %(f)s);
        END IF; END $$""" for table in ("feeding_schedule", "environmental_monitoring_larvaefeeding",
                                         "health_intervention")),
    """DELETE FROM feeding_events WHERE production_event_id IN (SELECT pe.id FROM production_events pe
        JOIN production_batches pb ON pb.id = pe.production_batch_id WHERE pb.farm_id = %(f)s)""",
    """DELETE FROM monitoring_events WHERE production_event_id IN (SELECT pe.id FROM production_events pe
        JOIN production_batches pb ON pb.id = pe.production_batch_id WHERE pb.farm_id = %(f)s)""",
    """DELETE FROM health_events WHERE production_event_id IN (SELECT pe.id FROM production_events pe
        JOIN production_batches pb ON pb.id = pe.production_batch_id WHERE pb.farm_id = %(f)s)""",
    "DELETE FROM production_events WHERE production_batch_id IN (SELECT id FROM production_batches WHERE farm_id = %(f)s)",
    """DELETE FROM production_batch_status_history WHERE production_batch_id IN (
        SELECT id FROM production_batches WHERE farm_id = %(f)s)""",
    "DELETE FROM production_batch_inputs WHERE production_batch_id IN (SELECT id FROM production_batches WHERE farm_id = %(f)s)",
    "DELETE FROM production_batches WHERE farm_id = %(f)s",
    "DELETE FROM substrate_batch_inputs WHERE substrate_batch_id IN (SELECT id FROM substrate_batches WHERE farm_id = %(f)s)",
    """DELETE FROM substrate_preparation WHERE business_id IN (
        SELECT business_id FROM substrate_batches WHERE farm_id = %(f)s)""",
    "DELETE FROM substrate_batches WHERE farm_id = %(f)s",
    "DELETE FROM waste_lots WHERE farm_id = %(f)s",
    "DELETE FROM inventory_locations WHERE farm_id = %(f)s",
    "DELETE FROM facilities WHERE site_id IN (SELECT id FROM sites WHERE farm_id = %(f)s)",
    "DELETE FROM sites WHERE farm_id = %(f)s",
    "DELETE FROM farms WHERE id = %(f)s",
]


def purge_farm(farm_id):
    """Delete everything recorded on one test farm (audit log entries stay)."""
    with db.transaction() as cursor:
        for statement in _FARM_PURGE:
            cursor.execute(statement, {"f": farm_id})


@contextmanager
def login_enabled():
    with patch.dict(app.config, {"LOGIN_DISABLED": False}):
        yield
