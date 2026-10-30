import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch

try:
    import psycopg2
except ImportError:  # pragma: no cover - dependency supplied by the app
    psycopg2 = None

from backend.database import DatabaseConnection

# Other endpoint tests import the app with its connection pool disabled. The
# integration suite restores a real PostgreSQL pool when database settings are
# available.
with patch.object(
    DatabaseConnection,
    "_initialize_pool",
    new=classmethod(lambda cls: None),
):
    from backend.app import app, db


@unittest.skipUnless(
    psycopg2 is not None
    and (os.getenv("DATABASE_URL") or os.getenv("PGHOST")),
    "PostgreSQL connection is not configured",
)
class WasteToSubstrateChainIntegrationTest(unittest.TestCase):
    """Exercise collection, traceability, and stock control through Flask APIs."""

    @classmethod
    def setUpClass(cls):
        from backend.init_db import init_database

        init_database()
        if DatabaseConnection._pool is None:
            DatabaseConnection._initialize_pool()
        cls.login_disabled = app.config.get("LOGIN_DISABLED", False)
        app.config["LOGIN_DISABLED"] = True
        app.testing = True

    @classmethod
    def tearDownClass(cls):
        app.config["LOGIN_DISABLED"] = cls.login_disabled

    def setUp(self):
        self.marker = f"chain-test-{uuid4().hex}"
        self.actor = f"tester-{uuid4().hex[:10]}"
        self.client = app.test_client()
        self.farm_ids = []
        self.user_ids = []
        self.scope = self._create_scope(self.marker)
        self.waste_lot = self._create_waste_lot(self.scope)
        self.batch_ids = []

    def tearDown(self):
        conn = db.get_connection()
        try:
            with conn.cursor() as cursor:
                for farm_id in self.farm_ids:
                    cursor.execute(
                        """
                        DELETE FROM substrate_batch_inputs
                        WHERE substrate_batch_id IN (
                            SELECT id FROM substrate_batches WHERE farm_id = %s
                        )
                        """,
                        (farm_id,),
                    )
                    cursor.execute(
                        """
                        DELETE FROM substrate_preparation
                        WHERE business_id IN (
                            SELECT business_id FROM substrate_batches WHERE farm_id = %s
                        )
                        """,
                        (farm_id,),
                    )
                    cursor.execute("DELETE FROM substrate_batches WHERE farm_id = %s", (farm_id,))
                cursor.execute(
                    """
                    DELETE FROM waste_lots
                    WHERE waste_sourcing_id IN (
                        SELECT id FROM waste_sourcing WHERE source_name = %s
                    )
                    """,
                    (self.marker,),
                )
                cursor.execute(
                    "DELETE FROM waste_sourcing WHERE source_name = %s",
                    (self.marker,),
                )
                for farm_id in self.farm_ids:
                    cursor.execute(
                        """
                        DELETE FROM facilities
                        WHERE site_id IN (SELECT id FROM sites WHERE farm_id = %s)
                        """,
                        (farm_id,),
                    )
                    cursor.execute("DELETE FROM sites WHERE farm_id = %s", (farm_id,))
                    cursor.execute("DELETE FROM farms WHERE id = %s", (farm_id,))
                cursor.execute(
                    "DELETE FROM organizations WHERE organization_code LIKE %s",
                    (f"{self.marker[:20]}%",),
                )
                for user_id in self.user_ids:
                    cursor.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
            conn.commit()
        finally:
            db.return_connection(conn)

    def _create_scope(self, name, *, extra_site=False):
        code = f"{self.marker[:20]}{uuid4().hex[:8]}"
        conn = db.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO organizations (organization_code, name) VALUES (%s, %s) RETURNING id",
                    (code, name),
                )
                organization_id = cursor.fetchone()[0]
                cursor.execute(
                    "INSERT INTO farms (organization_id, farm_code, name) VALUES (%s, %s, %s) RETURNING id",
                    (organization_id, code, name),
                )
                farm_id = cursor.fetchone()[0]
                sites = []
                for index in range(2 if extra_site else 1):
                    cursor.execute(
                        "INSERT INTO sites (farm_id, site_code, name) VALUES (%s, %s, %s) RETURNING id",
                        (farm_id, f"{code}-{index}", f"{name} site {index}"),
                    )
                    site_id = cursor.fetchone()[0]
                    cursor.execute(
                        """
                        INSERT INTO facilities (site_id, facility_code, name, facility_type)
                        VALUES (%s, %s, %s, 'waste_processing') RETURNING id
                        """,
                        (site_id, code, f"{name} facility {index}"),
                    )
                    sites.append({"site_id": site_id, "facility_id": cursor.fetchone()[0]})
            conn.commit()
        finally:
            db.return_connection(conn)
        self.farm_ids.append(farm_id)
        scope = {"farm_id": farm_id, **sites[0]}
        if extra_site:
            scope["other_site"] = {"farm_id": farm_id, **sites[1]}
        return scope

    def _create_user(self, role="manager"):
        name = f"u{uuid4().hex[:12]}"
        row = db.execute_returning(
            """
            INSERT INTO users (username, full_name, email, password_hash, role)
            VALUES (%s, %s, %s, 'not-a-real-hash', %s)
            RETURNING user_id
            """,
            (name, name, f"{name}@example.test", role),
        )
        self.user_ids.append(row["user_id"])
        return SimpleNamespace(
            is_authenticated=True, id=row["user_id"], role=role, username=name,
        )

    def _grant_farm(self, user, farm_id):
        db.execute_query(
            "INSERT INTO user_farm_access (user_id, farm_id) VALUES (%s, %s)",
            (user.id, farm_id),
        )

    def _as_user(self, user):
        stack = [
            patch.dict(app.config, {"LOGIN_DISABLED": False}),
            # current_user everywhere resolves through this one function.
            patch("flask_login.utils._get_user", lambda: user),
        ]

        class _Ctx:
            def __enter__(self_inner):
                for item in stack:
                    item.__enter__()

            def __exit__(self_inner, *exc):
                for item in reversed(stack):
                    item.__exit__(*exc)

        return _Ctx()

    def _waste_payload(self, scope, weight="10.000"):
        payload = {
            "collection_date": "2026-09-24",
            "collection_time": "09:30",
            "source_type": "market",
            "source_name": self.marker,
            "waste_type": "vegetable",
            "waste_weight": weight,
            "segregation_status": "organic",
            "collection_personnel": "Integration test",
            "recorded_by": self.actor,
            "lot_status": "available",
            "contaminants_found": [],
        }
        if scope:
            payload.update({k: scope[k] for k in ("farm_id", "site_id", "facility_id")})
        return payload

    def _create_waste_lot(self, scope, weight="10.000"):
        response = self.client.post("/api/waste-sourcing", json=self._waste_payload(scope, weight))
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["waste_lot"]

    def _substrate_payload(self, inputs, scope=None, batch_no=None):
        scope = scope or self.scope
        return {
            "batch_no": batch_no or f"test-{uuid4().hex[:20]}",
            "prep_date": "2026-09-24",
            "farm_id": scope["farm_id"],
            "site_id": scope["site_id"],
            "facility_id": scope["facility_id"],
            "moisture_consistency": "moist",
            "waste_particle_size": "medium",
            "foreign_matter": "no",
            "handler_operator": "Integration test",
            "recorded_by": self.actor,
            "notes": "",
            "inputs": inputs,
        }

    def _create_substrate(self, inputs, batch_no=None, scope=None):
        response = self.client.post(
            "/api/substrate-preparation",
            json=self._substrate_payload(inputs, scope=scope, batch_no=batch_no),
        )
        if response.status_code == 201:
            self.batch_ids.append(response.get_json()["id"])
        return response

    def _available_quantity(self, lot=None):
        lot = lot or self.waste_lot
        response = self.client.get("/api/waste-lots")
        self.assertEqual(response.status_code, 200)
        row = next(
            item for item in response.get_json()["data"]
            if item["id"] == lot["id"]
        )
        return float(row["available_quantity"])

    def _make_legacy(self, lot):
        db.execute_query(
            "UPDATE waste_lots SET farm_id = NULL, site_id = NULL, facility_id = NULL WHERE id = %s",
            (lot["id"],),
        )

    def test_collection_creates_lot_and_substrate_keeps_exact_lineage(self):
        self.assertRegex(self.waste_lot["business_id"], r"^WL-\d{4}-\d+$")
        self.assertEqual(self.waste_lot["farm_id"], self.scope["farm_id"])
        self.assertEqual(self.waste_lot["site_id"], self.scope["site_id"])
        self.assertEqual(self.waste_lot["facility_id"], self.scope["facility_id"])
        self.assertEqual(self.waste_lot["farm_site"], f"{self.marker} / {self.marker} site 0")
        self.assertEqual(self._available_quantity(), 10.0)

        response = self._create_substrate(
            [{"waste_lot_id": self.waste_lot["id"], "quantity_used": "4.250"}]
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        batch = response.get_json()["record"]
        self.assertEqual(batch["farm_id"], self.scope["farm_id"])
        self.assertEqual(batch["inputs"][0]["waste_lot_id"], self.waste_lot["id"])
        self.assertEqual(batch["inputs"][0]["quantity_used"], 4.25)
        self.assertEqual(self._available_quantity(), 5.75)

        detail = self.client.get(f"/api/substrate/batches/{batch['business_id']}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.get_json()["data"]["facility_id"], self.scope["facility_id"])
        self.assertEqual(
            detail.get_json()["data"]["inputs"][0]["business_id"],
            self.waste_lot["business_id"],
        )

    def test_waste_collection_page_and_its_recent_list(self):
        page = self.client.get("/waste-collection")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'id="wcForm"', page.data)

        lot = self._create_waste_lot(self.scope, "12.500")
        url = f"/api/waste-lots/recent?days=1&facility_id={self.scope['facility_id']}"
        recent = self.client.get(url)
        self.assertEqual(recent.status_code, 200, recent.get_json())
        body = recent.get_json()
        row = next(r for r in body["data"] if r["business_id"] == lot["business_id"])
        self.assertEqual((float(row["quantity"]), row["status"], str(row["collection_time"])[:5]),
                         (12.5, "available", "09:30"))
        self.assertIn({"name": self.marker, "source_type": "market"},
                      [{"name": s["name"], "source_type": s["source_type"]} for s in body["suppliers"]])
        self.assertEqual(body["max_collection_kg"], 5000)
        self.assertEqual(self.client.get("/api/waste-lots/recent?days=soon").status_code, 400)

        # One collection is one load: the form and the server share the limit.
        too_heavy = self.client.post("/api/waste-sourcing", json=self._waste_payload(self.scope, "5000.5"))
        self.assertEqual(too_heavy.status_code, 400)
        self.assertIn("more than one collection", too_heavy.get_json()["message"])

    def test_negative_and_over_available_consumption_are_rejected(self):
        negative = self._create_substrate(
            [{"waste_lot_id": self.waste_lot["id"], "quantity_used": "-0.001"}]
        )
        self.assertEqual(negative.status_code, 400)
        self.assertEqual(self._available_quantity(), 10.0)

        overdraw = self._create_substrate(
            [{"waste_lot_id": self.waste_lot["id"], "quantity_used": "10.001"}]
        )
        self.assertEqual(overdraw.status_code, 400)
        self.assertIn("available", overdraw.get_json()["message"])
        self.assertEqual(self._available_quantity(), 10.0)

    def test_concurrent_substrate_batches_cannot_overdraw_a_lot(self):
        def submit_batch(index):
            client = app.test_client()
            payload = self._substrate_payload(
                [{"waste_lot_id": self.waste_lot["id"], "quantity_used": "7"}],
                batch_no=f"race-{uuid4().hex[:20]}",
            )
            payload["handler_operator"] = f"test-{index}"
            return client.post("/api/substrate-preparation", json=payload)

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(submit_batch, range(2)))

        self.assertEqual(
            sorted(response.status_code for response in responses),
            [201, 400],
        )
        self.assertEqual(self._available_quantity(), 3.0)

    def test_waste_lot_and_substrate_require_canonical_scope(self):
        missing = self.client.post("/api/waste-sourcing", json=self._waste_payload(None))
        self.assertEqual(missing.status_code, 400, missing.get_json())
        self.assertIn("farm_id, site_id, and facility_id", missing.get_json()["message"])

        # A facility that does not belong to the supplied site is rejected.
        other = self._create_scope(f"{self.marker}-other")
        mismatched = dict(self.scope, facility_id=other["facility_id"])
        invalid = self.client.post("/api/waste-sourcing", json=self._waste_payload(mismatched))
        self.assertEqual(invalid.status_code, 400, invalid.get_json())
        self.assertIn("ownership is invalid", invalid.get_json()["message"])

        payload = self._substrate_payload(
            [{"waste_lot_id": self.waste_lot["id"], "quantity_used": "1"}]
        )
        del payload["facility_id"]
        no_scope = self.client.post("/api/substrate-preparation", json=payload)
        self.assertEqual(no_scope.status_code, 400, no_scope.get_json())
        self.assertEqual(self._available_quantity(), 10.0)

    def test_substrate_rejects_waste_from_another_site_or_farm(self):
        multi = self._create_scope(f"{self.marker}-multi", extra_site=True)
        lot = self._create_waste_lot(multi)
        other_site = self._create_substrate(
            [{"waste_lot_id": lot["id"], "quantity_used": "1"}],
            scope=multi["other_site"],
        )
        self.assertEqual(other_site.status_code, 400, other_site.get_json())
        self.assertIn("different farm/site", other_site.get_json()["message"])

        other_farm = self._create_substrate(
            [{"waste_lot_id": self.waste_lot["id"], "quantity_used": "1"}],
            scope=multi,
        )
        self.assertEqual(other_farm.status_code, 400, other_farm.get_json())
        self.assertIn("different farm/site", other_farm.get_json()["message"])
        self.assertEqual(self._available_quantity(lot), 10.0)

    def test_legacy_lot_needs_admin_assignment_before_use(self):
        self._make_legacy(self.waste_lot)
        blocked = self._create_substrate(
            [{"waste_lot_id": self.waste_lot["id"], "quantity_used": "1"}]
        )
        self.assertEqual(blocked.status_code, 400, blocked.get_json())
        self.assertIn("administrator must assign", blocked.get_json()["message"])

        location = {k: self.scope[k] for k in ("farm_id", "site_id", "facility_id")}
        endpoint = f"/api/waste-lots/{self.waste_lot['business_id']}/location"
        operator = self._create_user()
        self._grant_farm(operator, self.scope["farm_id"])
        with self._as_user(operator):
            forbidden = self.client.post(endpoint, json=location)
            hidden = self.client.get("/api/waste-lots")
        self.assertEqual(forbidden.status_code, 403)
        self.assertNotIn(
            self.waste_lot["id"], [row["id"] for row in hidden.get_json()["data"]]
        )

        admin = SimpleNamespace(
            is_authenticated=True, id=operator.id, role="super_admin", username="admin",
        )
        with self._as_user(admin):
            assigned = self.client.post(endpoint, json=location)
            again = self.client.post(endpoint, json=location)
        self.assertEqual(assigned.status_code, 200, assigned.get_json())
        self.assertEqual(assigned.get_json()["data"]["facility_id"], self.scope["facility_id"])
        self.assertEqual(assigned.get_json()["data"]["location_assigned_by_user_id"], operator.id)
        self.assertEqual(again.status_code, 409, again.get_json())

        usable = self._create_substrate(
            [{"waste_lot_id": self.waste_lot["id"], "quantity_used": "1"}]
        )
        self.assertEqual(usable.status_code, 201, usable.get_json())

    def test_reads_and_writes_are_limited_to_authorized_farms(self):
        response = self._create_substrate(
            [{"waste_lot_id": self.waste_lot["id"], "quantity_used": "2"}]
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        batch = response.get_json()["record"]

        outsider = self._create_user()
        outsider_scope = self._create_scope(f"{self.marker}-outsider")
        self._grant_farm(outsider, outsider_scope["farm_id"])
        with self._as_user(outsider):
            lots = self.client.get("/api/waste-lots")
            batches = self.client.get("/api/substrate-batches")
            detail = self.client.get(f"/api/substrate/batches/{batch['business_id']}")
            create_lot = self.client.post(
                "/api/waste-sourcing", json=self._waste_payload(self.scope)
            )
            create_batch = self.client.post(
                "/api/substrate-preparation",
                json=self._substrate_payload(
                    [{"waste_lot_id": self.waste_lot["id"], "quantity_used": "1"}]
                ),
            )
        self.assertEqual(lots.status_code, 200)
        self.assertNotIn(self.waste_lot["id"], [row["id"] for row in lots.get_json()["data"]])
        self.assertEqual(batches.status_code, 200)
        self.assertNotIn(batch["id"], [row["id"] for row in batches.get_json()["data"]])
        self.assertEqual(detail.status_code, 404)
        self.assertEqual(create_lot.status_code, 403, create_lot.get_json())
        self.assertEqual(create_batch.status_code, 403, create_batch.get_json())
        self.assertEqual(self._available_quantity(), 8.0)

        member = self._create_user()
        self._grant_farm(member, self.scope["farm_id"])
        with self._as_user(member):
            lots = self.client.get(f"/api/waste-lots?farm_id={self.scope['farm_id']}")
            detail = self.client.get(f"/api/substrate/batches/{batch['business_id']}")
        self.assertIn(self.waste_lot["id"], [row["id"] for row in lots.get_json()["data"]])
        self.assertEqual(detail.status_code, 200)

    def test_customer_history_is_protected_from_cascade_delete(self):
        rules = db.fetch_all(
            """
            SELECT conrelid::regclass::text AS table_name, confdeltype
            FROM pg_constraint
            WHERE contype = 'f' AND confrelid = 'customers'::regclass
            """
        )
        self.assertTrue(rules)
        for rule in rules:
            self.assertEqual(rule["confdeltype"], "r", rule)


if __name__ == "__main__":
    unittest.main()
