"""Investor demo mode (/tour, guest access): only on demo databases, read only.

The shared test database is never a demo, so these tests switch the demo
check on with a patch. The tour's real records are checked against a seeded
demo database in test_demo_seed.py.
"""
import os
from unittest import mock

from backend.app import app, db
from backend.demo import GUEST_EMAIL
from tests.support import HTTPS, ScenarioTestCase, requires_database

DEMO = mock.patch("backend.domains.tour.is_demo_database", return_value=True)
GUEST_ON = mock.patch.dict(os.environ, {"DEMO_GUEST_ACCESS": "1"})


@requires_database
class DemoTourTest(ScenarioTestCase):
    def setUp(self):
        super().setUp()
        self.client = app.test_client()

    def make_guest(self, role="viewer"):
        from werkzeug.security import generate_password_hash

        db.execute_query("DELETE FROM users WHERE email = %s", (GUEST_EMAIL,))
        row = db.execute_returning(
            "INSERT INTO users (username, full_name, email, password_hash, role) "
            "VALUES ('investor.guest', 'Investor Guest', %s, %s, %s) RETURNING user_id",
            (GUEST_EMAIL, generate_password_hash(os.urandom(16).hex()), role),
        )
        self.addCleanup(db.execute_query, "DELETE FROM users WHERE user_id = %s", (row["user_id"],))
        return row["user_id"]

    def guest_sign_in(self, **kwargs):
        return self.client.post("/api/demo/guest", json={}, **HTTPS, **kwargs)

    def test_demo_routes_do_not_exist_outside_a_demo_database(self):
        self.make_guest()
        with GUEST_ON:
            info = self.client.get("/api/demo/info", **HTTPS).get_json()["data"]
            self.assertEqual(info, {"demo": False, "guest_access": False})
            self.assertEqual(self.client.get("/tour", **HTTPS).status_code, 404)
            self.assertEqual(self.guest_sign_in().status_code, 404)
        viewer = self.make_user("viewer")
        self.assertEqual(viewer.get("/api/demo/tour").status_code, 404)

    def test_guest_access_needs_the_server_switch_and_the_read_only_account(self):
        with DEMO:
            self.assertEqual(self.client.get("/tour", **HTTPS).status_code, 200)
            # No guest account yet.
            with GUEST_ON:
                self.assertFalse(self.client.get("/api/demo/info", **HTTPS).get_json()["data"]["guest_access"])
                self.assertEqual(self.guest_sign_in().status_code, 404)
            guest_id = self.make_guest()
            # Switch off (the default).
            with mock.patch.dict(os.environ, {"DEMO_GUEST_ACCESS": ""}):
                self.assertFalse(self.client.get("/api/demo/info", **HTTPS).get_json()["data"]["guest_access"])
                self.assertEqual(self.guest_sign_in().status_code, 404)
            with GUEST_ON:
                self.assertTrue(self.client.get("/api/demo/info", **HTTPS).get_json()["data"]["guest_access"])
                # A guest account given any other role is never signed in.
                db.execute_query("UPDATE users SET role = 'operator' WHERE user_id = %s", (guest_id,))
                self.assertEqual(self.guest_sign_in().status_code, 404)
                db.execute_query("UPDATE users SET role = 'viewer', is_active = false WHERE user_id = %s",
                                 (guest_id,))
                self.assertEqual(self.guest_sign_in().status_code, 404)
                self.assertEqual(self.client.get("/api/me", **HTTPS).status_code, 401)

    def test_guest_signs_in_read_only_and_is_audited(self):
        guest_id = self.make_guest()
        with DEMO, GUEST_ON:
            refused = self.guest_sign_in(headers={"Origin": "https://evil.example"})
            self.assertEqual(refused.status_code, 403)
            signed_in = self.guest_sign_in()
            self.assertEqual(signed_in.status_code, 200, signed_in.get_json())
            self.assertEqual(signed_in.get_json()["redirect"], "/tour")
            me = self.client.get("/api/me", **HTTPS).get_json()["data"]
            self.assertEqual((me["role"], me["permissions"]), ("viewer", []))

            tour = self.client.get("/api/demo/tour", **HTTPS).get_json()["data"]
            self.assertTrue(tour["read_only"])
            keys = [c["key"] for c in tour["chapters"]]
            self.assertEqual(keys, ["overview", "batch", "trace", "quality", "stock", "alerts", "labels", "reports"])
            self.assertTrue(all(c["url"].startswith("/") and c["title"] and c["text"] for c in tour["chapters"]))

        # Looking is all a guest can do.
        place = self.make_farm()
        blocked = self.client.post("/api/waste-sourcing", json={
            **self.scope(place, place["facilities"][0]), "collection_date": "2026-10-01", "source_type": "market",
            "source_name": "guest attempt", "waste_type": "vegetable", "waste_weight": "5"}, **HTTPS)
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(self.client.post("/api/customers", json={"name": "guest attempt"}, **HTTPS).status_code, 403)
        entry = db.fetch_one(
            "SELECT actor_user_id FROM audit_log WHERE action = 'auth.demo_guest_sign_in' "
            "ORDER BY id DESC LIMIT 1")
        self.assertEqual(entry["actor_user_id"], guest_id)

    def test_staff_with_sales_access_also_get_the_orders_chapter_when_there_is_a_delivery(self):
        manager = self.make_user("manager")
        with DEMO, mock.patch("backend.domains.tour._tour_records", return_value={
            "sold": {"lot": "LOT-X", "batch": "BSF-X", "order_ref": "ORD-X"}, "failed": {"drying": "DRY-X"},
            "reserved": {"lot": "LOT-Y"}, "health": {}}):
            chapters = manager.get("/api/demo/tour").get_json()["data"]["chapters"]
        urls = {c["key"]: c["url"] for c in chapters}
        self.assertEqual(urls["orders"], "/orders?ref=ORD-X")
        self.assertEqual(urls["batch"], "/batch-360?ref=BSF-X")
        self.assertEqual(urls["trace"], "/traceability?ref=LOT-X&type=product_lot")
        self.assertEqual(urls["quality"], "/traceability?ref=DRY-X&type=drying_batch")
        self.assertEqual(urls["stock"], "/product-lot?ref=LOT-Y")
