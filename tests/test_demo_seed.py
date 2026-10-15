"""Demonstration dataset (python -m backend.demo): what it builds and where it refuses to run.

Each test runs the real command in a subprocess against its own throwaway
database, so the shared test database is never marked as a demo.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from tests.support import ScenarioTestCase, requires_database

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:  # pragma: no cover
    psycopg2 = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# Signs in as the demo guest and reports the tour's links and what the trace
# of the tour's sold lot hides from the guest.
GUEST_TOUR_SCRIPT = """
import json
from backend.app import app

client = app.test_client()
https = {'base_url': 'https://localhost'}
assert client.post('/api/demo/guest', json={}, **https).status_code == 200
tour = client.get('/api/demo/tour', **https).get_json()['data']
chapters = {c['key']: c['url'] for c in tour['chapters']}
lot = chapters['trace'].split('ref=')[1].split('&')[0]
trace = client.get('/api/traceability?type=product_lot&ref=' + lot, **https).get_json()['data']
nodes = [n for stage in trace['stages'] for n in stage['nodes']]
hidden = sorted({n.get('restricted_reason') for n in nodes if n.get('restricted')})
print(json.dumps({'chapters': chapters, 'hidden': hidden}))
"""


def _server_dsn(database):
    url = os.getenv("DATABASE_URL") or "postgresql://"
    parts = urlsplit(url)
    return urlunsplit((parts.scheme or "postgresql", parts.netloc, "/" + database, parts.query, ""))


@requires_database
class DemoSeedTest(unittest.TestCase):
    def make_database(self):
        name = f"zehunger_demo_test_{uuid4().hex[:8]}"
        admin = psycopg2.connect(_server_dsn("postgres"))
        admin.autocommit = True
        with admin.cursor() as cursor:
            cursor.execute(f'CREATE DATABASE "{name}"')
        admin.close()
        self.addCleanup(self._drop, name)
        return name

    @staticmethod
    def _drop(name):
        admin = psycopg2.connect(_server_dsn("postgres"))
        admin.autocommit = True
        with admin.cursor() as cursor:
            cursor.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        admin.close()

    def run_python(self, database, *args, **extra_env):
        env = dict(os.environ, DATABASE_URL=_server_dsn(database), PGDATABASE=database, **extra_env)
        return subprocess.run([sys.executable, *args], cwd=ROOT, env=env, capture_output=True,
                              text=True, timeout=600)

    def demo(self, database, *args):
        return self.run_python(database, "-m", "backend.demo", *args)

    def query(self, database, sql, params=()):
        with psycopg2.connect(_server_dsn(database)) as conn, conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()

    def test_seed_builds_a_linked_marked_dataset_and_rebuilds_only_on_request(self):
        database = self.make_database()
        self.assertIn("not marked", self.demo(database, "status").stdout)
        with tempfile.TemporaryDirectory() as folder:
            accounts = os.path.join(folder, "accounts.txt")
            result = self.demo(database, "seed", "--accounts-file", accounts)
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])
            with open(accounts, encoding="utf-8") as handle:
                listed = [line for line in handle if "@demo.example.com" in line]
        roles = {line.split()[-3] for line in listed}
        self.assertEqual(roles, {"super_admin", "manager", "operator", "qc_officer", "inventory_officer",
                                 "sales_officer", "viewer"})
        self.assertIn("demo dataset loaded", self.demo(database, "status").stdout)

        # Every stage of the chain is represented, in the states a demo needs.
        statuses = {r["status"] for r in self.query(database, "SELECT status FROM production_batches")}
        self.assertTrue({"PLANNED", "ACTIVE", "MONITORING", "READY_FOR_HARVEST", "HARVESTED"} <= statuses)
        self.assertEqual({r["status"] for r in self.query(database, "SELECT status FROM customer_deliveries")},
                         {"DELIVERED", "DISPATCHED"})
        self.assertEqual({r["status"] for r in self.query(database, "SELECT status FROM customer_orders")},
                         {"OPEN", "FULFILLED", "CANCELLED"})
        rules = {r["rule"] for r in self.query(database, "SELECT rule FROM operational_alerts")}
        self.assertEqual(rules, {"harvest_overdue", "harvest_due", "health_issue_open", "qc_failed",
                                 "low_stock", "order_overdue"})
        # History is spread over about three months, not stamped today.
        span = self.query(database, "SELECT min(occurred_at)::date AS first, max(occurred_at)::date AS last "
                                    "FROM production_events")[0]
        self.assertGreaterEqual((span["last"] - span["first"]).days, 70)
        # Stock comes only from the ledger and never goes negative.
        negative = self.query(database, """
            SELECT lot, location, SUM(kg) AS kg FROM (
                SELECT product_lot_id AS lot, to_location_id AS location, quantity_kg AS kg
                FROM inventory_movements WHERE status = 'posted' AND to_location_id IS NOT NULL
                UNION ALL
                SELECT product_lot_id, from_location_id, -quantity_kg
                FROM inventory_movements WHERE status = 'posted' AND from_location_id IS NOT NULL
            ) ledger GROUP BY 1, 2 HAVING SUM(kg) < 0""")
        self.assertGreater(self.query(database, "SELECT count(*) AS n FROM inventory_movements")[0]["n"], 8)
        self.assertEqual(negative, [])
        # Changes were made by the demo people and are in the audit log.
        actors = self.query(database, "SELECT DISTINCT actor_username FROM audit_log WHERE actor_username IS NOT NULL")
        self.assertGreaterEqual(len(actors), 6)
        # No customer or staff address can reach a real mailbox.
        emails = self.query(database, "SELECT email FROM users UNION ALL SELECT email FROM customers")
        self.assertTrue(all(r["email"].endswith("example.com") for r in emails))

        refused = self.demo(database, "seed")
        self.assertEqual(refused.returncode, 2)
        self.assertIn("already loaded", refused.stderr)

        rebuilt = self.demo(database, "seed", "--reset", "--accounts-file", os.devnull)
        self.assertEqual(rebuilt.returncode, 0, rebuilt.stderr[-2000:])
        self.assertEqual(self.query(database, "SELECT count(*) AS n FROM production_batches")[0]["n"], 11)
        self.assertEqual(self.query(database, "SELECT count(*) AS n FROM organizations")[0]["n"], 1)

        # The investor tour opens real records, and the guest sees the sale
        # only as a link it lacks sales access for.
        tour = self.run_python(database, "-c", GUEST_TOUR_SCRIPT, DEMO_GUEST_ACCESS="1")
        self.assertEqual(tour.returncode, 0, tour.stderr[-2000:])
        result = json.loads(tour.stdout.strip().splitlines()[-1])
        chapters = result["chapters"]
        self.assertRegex(chapters["batch"], r"^/batch-360\?ref=BSF-")
        self.assertRegex(chapters["trace"], r"^/traceability\?ref=LOT-.*&type=product_lot$")
        self.assertRegex(chapters["quality"], r"^/traceability\?ref=DRY-.*&type=drying_batch$")
        self.assertRegex(chapters["stock"], r"^/product-lot\?ref=LOT-")
        self.assertNotIn("orders", chapters)
        self.assertEqual(result["hidden"], ["sales"])

        # No email leaves a demo database, even with a mail channel configured.
        sent = self.run_python(database, "-c", (
            "from backend.app import db\n"
            "from backend import notifications\n"
            "class Channel:\n"
            "    configured = True\n"
            "    def send(self, *a, **k): raise SystemExit('email sent from a demo database')\n"
            "db.execute_query(\"INSERT INTO notification_outbox (recipient, subject, body) "
            "VALUES ('x@demo.example.com', 's', 'b')\")\n"
            "print(notifications.deliver_pending(db, channel=Channel()))\n"))
        self.assertEqual(sent.returncode, 0, sent.stderr[-2000:])
        self.assertIn("'skipped_demo': True", sent.stdout)

    def test_seed_refuses_a_database_with_real_records(self):
        database = self.make_database()
        prepared = self.run_python(database, "-c", "from backend.init_db import init_database; init_database()")
        self.assertEqual(prepared.returncode, 0, prepared.stderr[-2000:])
        self.query(database, "INSERT INTO organizations (organization_code, name) VALUES ('REAL', 'Real farm co') "
                             "RETURNING id")
        self.assertIn("Real database", self.demo(database, "status").stdout)
        for args in (("seed",), ("seed", "--reset")):
            result = self.demo(database, *args)
            self.assertEqual(result.returncode, 2, result.stdout[-2000:])
            self.assertIn("not a demo database", result.stderr)
        self.assertEqual(self.query(database, "SELECT name FROM organizations"), [{"name": "Real farm co"}])
        self.assertEqual(self.query(database, "SELECT name FROM schema_markers WHERE name LIKE 'demo%%'"), [])


@requires_database
class DemoMarkerTest(ScenarioTestCase):
    def test_profile_says_whether_this_is_a_demo_database(self):
        viewer = self.make_user("viewer")
        self.assertFalse(viewer.get("/api/me").get_json()["data"]["demo"])
        with mock.patch("backend.domains.auth.is_demo_database", return_value=True):
            self.assertTrue(viewer.get("/api/me").get_json()["data"]["demo"])
