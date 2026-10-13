import os
import unittest
from concurrent.futures import ThreadPoolExecutor
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
        self.site = self.marker
        self.actor = f"tester-{uuid4().hex[:10]}"
        self.client = app.test_client()
        response = self.client.post(
            "/api/waste-sourcing",
            json={
                "collection_date": "2026-09-24",
                "collection_time": "09:30",
                "farm_site": self.site,
                "source_type": "market",
                "source_name": self.marker,
                "waste_type": "vegetable",
                "waste_weight": "10.000",
                "segregation_status": "organic",
                "collection_personnel": "Integration test",
                "recorded_by": self.actor,
                "lot_status": "available",
                "contaminants_found": [],
            },
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        self.waste_lot = response.get_json()["waste_lot"]
        self.batch_ids = []

    def tearDown(self):
        conn = db.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM substrate_batch_inputs
                    WHERE substrate_batch_id IN (
                        SELECT id FROM substrate_batches WHERE farm_site = %s
                    )
                    """,
                    (self.site,),
                )
                cursor.execute(
                    """
                    DELETE FROM substrate_preparation
                    WHERE business_id IN (
                        SELECT business_id FROM substrate_batches WHERE farm_site = %s
                    )
                    """,
                    (self.site,),
                )
                cursor.execute(
                    "DELETE FROM substrate_batches WHERE farm_site = %s",
                    (self.site,),
                )
                cursor.execute("DELETE FROM waste_lots WHERE farm_site = %s", (self.site,))
                cursor.execute(
                    "DELETE FROM waste_sourcing WHERE source_name = %s",
                    (self.marker,),
                )
            conn.commit()
        finally:
            db.return_connection(conn)

    def _create_substrate(self, inputs, batch_no=None):
        response = self.client.post(
            "/api/substrate-preparation",
            json={
                "batch_no": batch_no or f"test-{uuid4().hex[:20]}",
                "prep_date": "2026-09-24",
                "farm_site": self.site,
                "moisture_consistency": "moist",
                "waste_particle_size": "medium",
                "foreign_matter": "no",
                "handler_operator": "Integration test",
                "recorded_by": self.actor,
                "notes": "",
                "inputs": inputs,
            },
        )
        if response.status_code == 201:
            self.batch_ids.append(response.get_json()["id"])
        return response

    def _available_quantity(self):
        response = self.client.get("/api/waste-lots")
        self.assertEqual(response.status_code, 200)
        lot = next(
            item for item in response.get_json()["data"]
            if item["id"] == self.waste_lot["id"]
        )
        return float(lot["available_quantity"])

    def test_collection_creates_lot_and_substrate_keeps_exact_lineage(self):
        self.assertRegex(self.waste_lot["business_id"], r"^WL-\d{4}-\d+$")
        self.assertEqual(self.waste_lot["farm_site"], self.site)
        self.assertEqual(self._available_quantity(), 10.0)

        response = self._create_substrate(
            [{"waste_lot_id": self.waste_lot["id"], "quantity_used": "4.250"}]
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        batch = response.get_json()["record"]
        self.assertEqual(batch["inputs"][0]["waste_lot_id"], self.waste_lot["id"])
        self.assertEqual(batch["inputs"][0]["quantity_used"], 4.25)
        self.assertEqual(self._available_quantity(), 5.75)

        detail = self.client.get(f"/api/substrate/batches/{batch['business_id']}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(
            detail.get_json()["data"]["inputs"][0]["business_id"],
            self.waste_lot["business_id"],
        )

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
            return client.post(
                "/api/substrate-preparation",
                json={
                    "batch_no": f"race-{uuid4().hex[:20]}",
                    "prep_date": "2026-09-24",
                    "farm_site": self.site,
                    "moisture_consistency": "moist",
                    "waste_particle_size": "medium",
                    "foreign_matter": "no",
                    "handler_operator": f"test-{index}",
                    "recorded_by": self.actor,
                    "inputs": [{
                        "waste_lot_id": self.waste_lot["id"],
                        "quantity_used": "7",
                    }],
                },
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(submit_batch, range(2)))

        self.assertEqual(
            sorted(response.status_code for response in responses),
            [201, 400],
        )
        self.assertEqual(self._available_quantity(), 3.0)


if __name__ == "__main__":
    unittest.main()