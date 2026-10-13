import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch

try:
    import psycopg2
except ImportError:  # pragma: no cover - dependency supplied by the app
    psycopg2 = None

from backend.database import DatabaseConnection
from backend import notifications

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
class ProductionBatchChainIntegrationTest(unittest.TestCase):
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
        self.marker = f"pt-{uuid4().hex[:20]}"
        self.actor = f"production-tester-{uuid4().hex[:10]}"
        self.client = app.test_client()
        self.substrate_ids = []
        self._create_scope()
        response = self.client.post(
            "/api/waste-sourcing",
            json={
                "collection_date": "2026-09-24",
                "collection_time": "09:30",
                "farm_id": self.farm_id,
                "site_id": self.site_id,
                "facility_id": self.facility_id,
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
        self.waste_lot_id = response.get_json()["waste_lot"]["id"]

    def _create_scope(self):
        conn = db.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO organizations (organization_code, name)
                    VALUES (%s, %s) RETURNING id
                    """,
                    (self.marker, self.marker),
                )
                organization_id = cursor.fetchone()[0]
                cursor.execute(
                    """
                    INSERT INTO farms (organization_id, farm_code, name)
                    VALUES (%s, %s, %s) RETURNING id
                    """,
                    (organization_id, self.marker, self.marker),
                )
                self.farm_id = cursor.fetchone()[0]
                cursor.execute(
                    """
                    INSERT INTO sites (farm_id, site_code, name)
                    VALUES (%s, %s, %s) RETURNING id
                    """,
                    (self.farm_id, self.marker, self.marker),
                )
                self.site_id = cursor.fetchone()[0]
                cursor.execute(
                    """
                    INSERT INTO facilities (site_id, facility_code, name, facility_type)
                    VALUES (%s, %s, %s, 'production') RETURNING id
                    """,
                    (self.site_id, self.marker, self.marker),
                )
                self.facility_id = cursor.fetchone()[0]
                cursor.execute(
                    """
                    INSERT INTO inventory_locations
                        (location_code, name, farm_id, site_id, facility_id)
                    VALUES ('DRY-STORE-A', 'Dry Store A', %s, %s, %s) RETURNING id
                    """,
                    (self.farm_id, self.site_id, self.facility_id),
                )
                self.inventory_location_id = cursor.fetchone()[0]
            conn.commit()
        finally:
            db.return_connection(conn)

    def _create_substrate(self, quantity="8.000"):
        response = self.client.post(
            "/api/substrate-preparation",
            json={
                "batch_no": f"substrate-{uuid4().hex[:18]}",
                "prep_date": "2026-09-24",
                "farm_id": self.farm_id,
                "site_id": self.site_id,
                "facility_id": self.facility_id,
                "moisture_consistency": "moist",
                "waste_particle_size": "medium",
                "foreign_matter": "no",
                "handler_operator": "Integration test",
                "recorded_by": self.actor,
                "inputs": [{
                    "waste_lot_id": self.waste_lot_id,
                    "quantity_used": quantity,
                }],
            },
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        substrate_id = response.get_json()["id"]
        self.substrate_ids.append(substrate_id)
        return substrate_id

    def _create_production(
        self, substrate_id, quantity="4.000", harvest_limit_kg=None
    ):
        payload = {
            "batch_code": f"production-{uuid4().hex[:18]}",
            "start_date": "2026-09-24",
            "current_stage": "STARTING",
            "farm_id": self.farm_id,
            "site_id": self.site_id,
            "facility_id": self.facility_id,
            "recorded_by": self.actor,
            "inputs": [{
                "substrate_batch_id": substrate_id,
                "quantity_issued": quantity,
            }],
        }
        if harvest_limit_kg is not None:
            payload["harvest_limit_kg"] = harvest_limit_kg
        response = self.client.post(
            "/api/production/batches",
            json=payload,
        )
        return response

    def _move_to_harvest_ready(self, batch):
        for status in ("ACTIVE", "MONITORING", "READY_FOR_HARVEST"):
            response = self.client.post(
                f"/api/production/batches/{batch['business_id']}/status",
                json={"status": status, "recorded_by": self.actor},
            )
            self.assertEqual(response.status_code, 200, response.get_json())

    def _harvest(self, batch, *, legacy_route=False, **overrides):
        payload = {
            "harvest_date": "2026-09-25",
            "event_time": "11:30",
            "wet_weight": "1.250",
            "unit": "kg",
            "harvest_stage": "late instar",
            "operator": self.actor,
            "location": "Production facility A",
            "notes": "partial harvest",
        }
        payload.update(overrides)
        endpoint = (
            "/api/feeding/harvest-yield"
            if legacy_route
            else f"/api/production/batches/{batch['business_id']}/events/harvest"
        )
        payload["production_batch_id"] = batch["business_id"]
        return self.client.post(
            endpoint, json=payload,
        )

    def tearDown(self):
        conn = db.get_connection()
        try:
            with conn.cursor() as cursor:
                for statement in (
                    """DELETE FROM customer_delivery_lines WHERE delivery_id IN (
                        SELECT d.id FROM customer_deliveries AS d
                        JOIN customer_orders AS o ON o.id = d.order_id
                        WHERE o.farm_id = %s)""",
                    """DELETE FROM customer_deliveries WHERE order_id IN (
                        SELECT id FROM customer_orders WHERE farm_id = %s)""",
                    """DELETE FROM order_allocations WHERE order_line_id IN (
                        SELECT l.id FROM customer_order_lines AS l
                        JOIN customer_orders AS o ON o.id = l.order_id
                        WHERE o.farm_id = %s)""",
                    """DELETE FROM customer_order_lines WHERE order_id IN (
                        SELECT id FROM customer_orders WHERE farm_id = %s)""",
                    "DELETE FROM customer_orders WHERE farm_id = %s",
                    "DELETE FROM operational_alerts WHERE farm_id = %s",
                    "DELETE FROM inventory_alert_thresholds WHERE farm_id = %s",
                ):
                    cursor.execute(statement, (self.farm_id,))
                cursor.execute("DELETE FROM customers WHERE name = %s", (self.marker,))
                cursor.execute(
                    "DELETE FROM inventory_movements WHERE farm_id = %s",
                    (self.farm_id,),
                )
                cursor.execute(
                    """
                    DELETE FROM product_lots
                    WHERE drying_output_id IN (
                        SELECT output.id
                        FROM drying_outputs AS output
                        JOIN drying_batches AS batch
                          ON batch.id = output.drying_batch_id
                        WHERE batch.farm_id = %s
                    )
                    """,
                    (self.farm_id,),
                )
                cursor.execute(
                    """
                    DELETE FROM quality_approvals
                    WHERE quality_check_id IN (
                        SELECT id FROM quality_checks
                        WHERE drying_batch_id IN (
                            SELECT id FROM drying_batches WHERE farm_id = %s
                        )
                    )
                    """,
                    (self.farm_id,),
                )
                cursor.execute(
                    """
                    DELETE FROM quality_checks
                    WHERE drying_batch_id IN (
                        SELECT id FROM drying_batches WHERE farm_id = %s
                    )
                    """,
                    (self.farm_id,),
                )
                cursor.execute(
                    """
                    DELETE FROM drying_outputs
                    WHERE drying_batch_id IN (
                        SELECT id FROM drying_batches WHERE farm_id = %s
                    )
                    """,
                    (self.farm_id,),
                )
                cursor.execute(
                    """
                    DELETE FROM drying_inputs
                    WHERE drying_batch_id IN (
                        SELECT id FROM drying_batches WHERE farm_id = %s
                    )
                    """,
                    (self.farm_id,),
                )
                cursor.execute(
                    """
                    DELETE FROM drying_batch_status_history
                    WHERE drying_batch_id IN (
                        SELECT id FROM drying_batches WHERE farm_id = %s
                    )
                    """,
                    (self.farm_id,),
                )
                cursor.execute(
                    "DELETE FROM drying_batches WHERE farm_id = %s",
                    (self.farm_id,),
                )
                cursor.execute(
                    """
                    DELETE FROM harvests
                    WHERE production_event_id IN (
                        SELECT id FROM production_events
                        WHERE production_batch_id IN (
                            SELECT id FROM production_batches WHERE farm_id = %s
                        )
                    )
                    """,
                    (self.farm_id,),
                )
                cursor.execute(
                    """
                    DELETE FROM feeding_schedule
                    WHERE production_batch_id IN (
                        SELECT id FROM production_batches WHERE farm_id = %s
                    )
                    """,
                    (self.farm_id,),
                )
                cursor.execute(
                    """
                    DELETE FROM environmental_monitoring_larvaefeeding
                    WHERE production_batch_id IN (
                        SELECT id FROM production_batches WHERE farm_id = %s
                    )
                    """,
                    (self.farm_id,),
                )
                cursor.execute(
                    """
                    DELETE FROM health_intervention
                    WHERE production_batch_id IN (
                        SELECT id FROM production_batches WHERE farm_id = %s
                    )
                    """,
                    (self.farm_id,),
                )
                cursor.execute(
                    """
                    DELETE FROM feeding_events
                    WHERE production_event_id IN (
                        SELECT pe.id
                        FROM production_events pe
                        JOIN production_batches pb ON pb.id = pe.production_batch_id
                        WHERE pb.farm_id = %s
                    )
                    """,
                    (self.farm_id,),
                )
                cursor.execute(
                    """
                    DELETE FROM monitoring_events
                    WHERE production_event_id IN (
                        SELECT pe.id
                        FROM production_events pe
                        JOIN production_batches pb ON pb.id = pe.production_batch_id
                        WHERE pb.farm_id = %s
                    )
                    """,
                    (self.farm_id,),
                )
                cursor.execute(
                    """
                    DELETE FROM health_events
                    WHERE production_event_id IN (
                        SELECT pe.id
                        FROM production_events pe
                        JOIN production_batches pb ON pb.id = pe.production_batch_id
                        WHERE pb.farm_id = %s
                    )
                    """,
                    (self.farm_id,),
                )
                cursor.execute(
                    """
                    DELETE FROM production_events
                    WHERE production_batch_id IN (
                        SELECT id FROM production_batches WHERE farm_id = %s
                    )
                    """,
                    (self.farm_id,),
                )
                cursor.execute(
                    """
                    DELETE FROM production_batch_status_history
                    WHERE production_batch_id IN (
                        SELECT id FROM production_batches
                        WHERE farm_id = %s
                    )
                    """,
                    (self.farm_id,),
                )
                cursor.execute(
                    """
                    DELETE FROM production_batch_inputs
                    WHERE production_batch_id IN (
                        SELECT id FROM production_batches
                        WHERE farm_id = %s
                    )
                    """,
                    (self.farm_id,),
                )
                cursor.execute(
                    "DELETE FROM production_batches WHERE farm_id = %s",
                    (self.farm_id,),
                )
                cursor.execute(
                    """
                    DELETE FROM substrate_batch_inputs
                    WHERE substrate_batch_id IN (
                        SELECT id FROM substrate_batches
                        WHERE farm_id = %s
                    )
                    """,
                    (self.farm_id,),
                )
                cursor.execute(
                    """
                    DELETE FROM substrate_preparation
                    WHERE business_id IN (
                        SELECT business_id FROM substrate_batches
                        WHERE farm_id = %s
                    )
                    """,
                    (self.farm_id,),
                )
                cursor.execute(
                    "DELETE FROM substrate_batches WHERE farm_id = %s",
                    (self.farm_id,),
                )
                cursor.execute("DELETE FROM waste_lots WHERE farm_id = %s", (self.farm_id,))
                cursor.execute(
                    "DELETE FROM waste_sourcing WHERE source_name = %s",
                    (self.marker,),
                )
                cursor.execute("DELETE FROM inventory_locations WHERE farm_id = %s", (self.farm_id,))
                cursor.execute("DELETE FROM facilities WHERE site_id = %s", (self.site_id,))
                cursor.execute("DELETE FROM sites WHERE id = %s", (self.site_id,))
                cursor.execute("DELETE FROM farms WHERE id = %s", (self.farm_id,))
                cursor.execute(
                    "DELETE FROM organizations WHERE organization_code = %s",
                    (self.marker,),
                )
            conn.commit()
        finally:
            db.return_connection(conn)

    def _create_output_for_product_lot(self, *, output_quantity="0.600"):
        substrate_id = self._create_substrate(quantity="8.000")
        created = self._create_production(
            substrate_id, quantity="4.000", harvest_limit_kg="4.000"
        )
        self.assertEqual(created.status_code, 201, created.get_json())
        production = created.get_json()["record"]
        self._move_to_harvest_ready(production)
        harvest = self._harvest(production, wet_weight="1.500", unit="kg")
        self.assertEqual(harvest.status_code, 201, harvest.get_json())

        drying_response = self.client.post(
            "/api/drying/batches",
            json={
                "batch_code": f"lot-drying-{uuid4().hex[:15]}",
                "drying_date": "2026-09-25",
                "drying_method": "sun_drying",
                "personnel": self.actor,
                "farm_id": self.farm_id,
                "site_id": self.site_id,
                "facility_id": self.facility_id,
                "inputs": [{
                    "harvest_id": harvest.get_json()["harvest"]["id"],
                    "quantity": "1.200",
                    "unit": "kg",
                }],
            },
        )
        self.assertEqual(drying_response.status_code, 201, drying_response.get_json())
        drying = drying_response.get_json()["data"]
        drying_ref = drying["business_id"] or drying["batch_id"]

        for status in ("RECEIVED", "DRYING"):
            response = self.client.post(
                f"/api/drying/batches/{drying_ref}/status",
                json={"status": status, "recorded_by": self.actor},
            )
            self.assertEqual(response.status_code, 200, response.get_json())

        output_response = self.client.post(
            f"/api/drying/batches/{drying_ref}/outputs",
            json={
                "quantity": output_quantity,
                "unit": "kg",
                "moisture_percent": "10.5",
                "output_date": "2026-09-25",
                "operator": self.actor,
            },
        )
        self.assertEqual(output_response.status_code, 201, output_response.get_json())
        output = output_response.get_json()["output"]
        pending = self.client.post(
            f"/api/drying/batches/{drying_ref}/status",
            json={"status": "QC_PENDING", "recorded_by": self.actor},
        )
        self.assertEqual(pending.status_code, 200, pending.get_json())
        return drying_ref, output

    def _create_output_quality_check(self, output, *, status="passed"):
        response = self.client.post(
            f"/api/drying/outputs/{output['id']}/quality-checks",
            json={
                "status": status,
                "inspector": self.actor,
                "moisture_percent": "10.5",
            },
        )
        return response

    def test_approved_output_creates_product_lot_with_quantity_and_full_trace(self):
        drying_ref, output = self._create_output_for_product_lot()
        check = self._create_output_quality_check(output)
        self.assertEqual(check.status_code, 201, check.get_json())
        approval = self.client.post(
            "/api/drying/quality-approvals",
            json={
                "quality_check_id": check.get_json()["data"]["id"],
                "decision": "approved",
                "approver": self.actor,
            },
        )
        self.assertEqual(approval.status_code, 201, approval.get_json())

        response = self.client.post(
            "/api/product-lots",
            json={
                "drying_output_id": output["id"],
                "product_type": "dried_larvae",
                "inventory_location_id": self.inventory_location_id,
                "lot_number": f"finished-{uuid4().hex[:12]}",
                "storage_location": "Dry Store A",
            },
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        lot = response.get_json()["data"]
        self.assertTrue(lot["business_id"].startswith("LOT-"))
        self.assertEqual(lot["status"], "AVAILABLE")
        self.assertEqual(lot["qc_status"], "passed")
        self.assertEqual(lot["approval_status"], "approved")
        self.assertEqual(lot["product_type"], "dried_larvae")
        self.assertEqual(lot["unit"], "kg")
        self.assertAlmostEqual(float(lot["quantity"]), 0.6)
        self.assertEqual(str(lot["production_date"]), "2026-09-25")
        self.assertEqual(lot["farm_name"], self.marker)
        self.assertEqual(lot["storage_location"], "Dry Store A")

        detail = self.client.get(f"/api/product-lots/{lot['business_id']}")
        self.assertEqual(detail.status_code, 200, detail.get_json())
        traced_lot = detail.get_json()["data"]
        self.assertEqual(traced_lot["source_drying_batch"]["business_id"], drying_ref)
        self.assertTrue(traced_lot["source_chain"])
        lineage = traced_lot["source_chain"][0]
        self.assertTrue(lineage["harvest_code"])
        self.assertTrue(lineage["production_batch_business_id"])
        self.assertTrue(lineage["substrate_batch_business_id"])
        self.assertTrue(lineage["waste_lot_business_id"])

    def test_failed_qc_blocks_product_lot_release(self):
        _drying_ref, output = self._create_output_for_product_lot()
        check = self._create_output_quality_check(output, status="failed")
        self.assertEqual(check.status_code, 201, check.get_json())

        response = self.client.post(
            "/api/product-lots",
            json={
                "drying_output_id": output["id"],
                "product_type": "dried_larvae",
                "inventory_location_id": self.inventory_location_id,
            },
        )
        self.assertEqual(response.status_code, 400, response.get_json())
        self.assertIn("passed QC", response.get_json()["message"])
        lot_count = db.fetch_one(
            "SELECT COUNT(*) AS count FROM product_lots WHERE drying_output_id = %s",
            (output["id"],),
        )
        self.assertEqual(lot_count["count"], 0)

    def test_passed_qc_without_approval_cannot_create_available_lot(self):
        _drying_ref, output = self._create_output_for_product_lot()
        check = self._create_output_quality_check(output)
        self.assertEqual(check.status_code, 201, check.get_json())

        response = self.client.post(
            "/api/product-lots",
            json={
                "drying_output_id": output["id"],
                "product_type": "dried_larvae",
                "inventory_location_id": self.inventory_location_id,
            },
        )
        self.assertEqual(response.status_code, 400, response.get_json())
        self.assertIn("approved decision", response.get_json()["message"])
        lot_count = db.fetch_one(
            "SELECT COUNT(*) AS count FROM product_lots WHERE drying_output_id = %s",
            (output["id"],),
        )
        self.assertEqual(lot_count["count"], 0)

    def test_unassigned_user_cannot_create_lot_or_approve_quality(self):
        _drying_ref, output = self._create_output_for_product_lot()
        check = self._create_output_quality_check(output)
        self.assertEqual(check.status_code, 201, check.get_json())
        unauthorized_user = SimpleNamespace(
            is_authenticated=True,
            id=987654321,
            role="farm_operator",
            username="unassigned-operator",
        )
        with patch.dict(app.config, {"LOGIN_DISABLED": False}), patch(
            "backend.app.current_user", unauthorized_user
        ), patch("flask_login.utils.current_user", unauthorized_user):
            lot_response = self.client.post(
                "/api/product-lots",
                json={
                    "drying_output_id": output["id"],
                    "product_type": "dried_larvae",
                    "inventory_location_id": self.inventory_location_id,
                },
            )
            approval_response = self.client.post(
                "/api/drying/quality-approvals",
                json={
                    "quality_check_id": check.get_json()["data"]["id"],
                    "decision": "approved",
                    "approver": unauthorized_user.username,
                },
            )
        self.assertEqual(lot_response.status_code, 403, lot_response.get_json())
        self.assertEqual(approval_response.status_code, 403, approval_response.get_json())

    def test_drying_trace_consumes_multiple_harvests_and_requires_qc_approval(self):
        substrate_id = self._create_substrate(quantity="8.000")
        created = self._create_production(substrate_id, quantity="4.000", harvest_limit_kg="4.000")
        self.assertEqual(created.status_code, 201, created.get_json())
        production = created.get_json()["record"]
        self._move_to_harvest_ready(production)

        first = self._harvest(production, wet_weight="1.250", unit="kg")
        second = self._harvest(production, wet_weight="750", unit="g")
        self.assertEqual(first.status_code, 201, first.get_json())
        self.assertEqual(second.status_code, 201, second.get_json())
        first_harvest = first.get_json()["harvest"]
        second_harvest = second.get_json()["harvest"]

        batch_response = self.client.post(
            "/api/drying/batches",
            json={
                "batch_code": f"drying-{uuid4().hex[:18]}",
                "drying_date": "2026-09-25",
                "drying_method": "sun_drying",
                "personnel": self.actor,
                "farm_id": self.farm_id,
                "site_id": self.site_id,
                "facility_id": self.facility_id,
            },
        )
        self.assertEqual(batch_response.status_code, 201, batch_response.get_json())
        drying = batch_response.get_json()["data"]
        drying_ref = drying["business_id"] or drying["batch_id"]
        self.assertEqual(drying["status"], "DRAFT")

        inputs = self.client.post(
            f"/api/drying/batches/{drying_ref}/inputs",
            json={
                "inputs": [
                    {"harvest_id": first_harvest["id"], "quantity": "1.000", "unit": "kg"},
                    {"harvest_id": second_harvest["id"], "quantity": "0.500", "unit": "kg"},
                ],
                "recorded_by": self.actor,
            },
        )
        self.assertEqual(inputs.status_code, 201, inputs.get_json())
        self.assertEqual(len(inputs.get_json()["data"]["inputs"]), 2)
        self.assertAlmostEqual(float(inputs.get_json()["data"]["input_quantity_kg"]), 1.5)

        received = self.client.post(
            f"/api/drying/batches/{drying_ref}/status",
            json={"status": "RECEIVED", "recorded_by": self.actor},
        )
        self.assertEqual(received.status_code, 200, received.get_json())
        drying_started = self.client.post(
            f"/api/drying/batches/{drying_ref}/status",
            json={"status": "DRYING", "recorded_by": self.actor},
        )
        self.assertEqual(drying_started.status_code, 200, drying_started.get_json())

        output = self.client.post(
            f"/api/drying/batches/{drying_ref}/outputs",
            json={
                "quantity": "0.600",
                "unit": "kg",
                "moisture_percent": "10.5",
                "output_date": "2026-09-25T15:00:00Z",
                "operator": self.actor,
            },
        )
        self.assertEqual(output.status_code, 201, output.get_json())
        output_data = output.get_json()["output"]
        self.assertAlmostEqual(float(output_data["yield_percentage"]), 40.0)
        self.assertAlmostEqual(float(output_data["yield_ratio"]), 0.4)

        pending = self.client.post(
            f"/api/drying/batches/{drying_ref}/status",
            json={"status": "QC_PENDING", "recorded_by": self.actor},
        )
        self.assertEqual(pending.status_code, 200, pending.get_json())
        blocked_completion = self.client.post(
            f"/api/drying/batches/{drying_ref}/status",
            json={"status": "COMPLETED", "recorded_by": self.actor},
        )
        self.assertEqual(blocked_completion.status_code, 400, blocked_completion.get_json())
        self.assertIn("approved", blocked_completion.get_json()["message"])
        check = self.client.post(
            f"/api/drying/batches/{drying_ref}/quality-checks",
            json={
                "status": "passed",
                "moisture_percent": "10.5",
                "inspector": self.actor,
            },
        )
        self.assertEqual(check.status_code, 201, check.get_json())
        approval = self.client.post(
            "/api/drying/quality-approvals",
            json={
                "quality_check_id": check.get_json()["data"]["id"],
                "decision": "approved",
                "approver": self.actor,
            },
        )
        self.assertEqual(approval.status_code, 201, approval.get_json())

        detail = self.client.get(f"/api/drying/batches/{drying_ref}")
        self.assertEqual(detail.status_code, 200, detail.get_json())
        data = detail.get_json()["data"]
        self.assertEqual(data["status"], "COMPLETED")
        self.assertEqual(len(data["source"]), 2)
        self.assertAlmostEqual(float(data["output_quantity_kg"]), 0.6)
        self.assertAlmostEqual(float(data["yield_percentage"]), 40.0)

        original = db.fetch_one(
            "SELECT wet_weight, unit FROM harvests WHERE id = %s",
            (first_harvest["id"],),
        )
        self.assertAlmostEqual(float(original["wet_weight"]), 1.25)
        self.assertEqual(original["unit"], "kg")

    def test_drying_rejects_overconsumption_and_impossible_output(self):
        substrate_id = self._create_substrate(quantity="8.000")
        created = self._create_production(substrate_id, quantity="4.000", harvest_limit_kg="2.000")
        self.assertEqual(created.status_code, 201, created.get_json())
        production = created.get_json()["record"]
        self._move_to_harvest_ready(production)
        harvest = self._harvest(production, wet_weight="1.000", unit="kg")
        self.assertEqual(harvest.status_code, 201, harvest.get_json())
        harvest_id = harvest.get_json()["harvest"]["id"]

        batch_response = self.client.post(
            "/api/drying/batch",
            json={
                "batch_id": f"drying-{uuid4().hex[:18]}",
                "drying_date": "2026-09-25",
                "drying_method": "sun_drying",
                "personnel": self.actor,
                "farm_id": self.farm_id,
                "site_id": self.site_id,
                "facility_id": self.facility_id,
            },
        )
        self.assertEqual(batch_response.status_code, 201, batch_response.get_json())
        drying_ref = batch_response.get_json()["business_id"]

        overdraw = self.client.post(
            f"/api/drying/batches/{drying_ref}/inputs",
            json={"harvest_id": harvest_id, "quantity": "1.001", "unit": "kg"},
        )
        self.assertEqual(overdraw.status_code, 400, overdraw.get_json())
        self.assertIn("available", overdraw.get_json()["message"])

        valid_input = self.client.post(
            f"/api/drying/batches/{drying_ref}/inputs",
            json={"harvest_id": harvest_id, "quantity": "1.000", "unit": "kg"},
        )
        self.assertEqual(valid_input.status_code, 201, valid_input.get_json())
        for status in ("RECEIVED", "DRYING"):
            response = self.client.post(
                f"/api/drying/batches/{drying_ref}/status",
                json={"status": status},
            )
            self.assertEqual(response.status_code, 200, response.get_json())

        impossible = self.client.post(
            f"/api/drying/batches/{drying_ref}/outputs",
            json={
                "quantity": "1.001",
                "unit": "kg",
                "output_date": "2026-09-25",
                "operator": self.actor,
            },
        )
        self.assertEqual(impossible.status_code, 400, impossible.get_json())
        self.assertIn("cannot exceed", impossible.get_json()["message"])

    def test_feeding_monitoring_and_health_events_are_batch_timeline_records(self):
        substrate_id = self._create_substrate()
        created = self._create_production(substrate_id)
        self.assertEqual(created.status_code, 201, created.get_json())
        batch = created.get_json()["record"]

        active = self.client.post(
            f"/api/production/batches/{batch['business_id']}/status",
            json={"status": "ACTIVE", "recorded_by": self.actor},
        )
        self.assertEqual(active.status_code, 200, active.get_json())

        feeding = self.client.post(
            "/api/feeding/schedule",
            json={
                "production_batch_id": batch["business_id"],
                "feeding_date": "2026-09-25",
                "event_time": "08:00",
                "tray_batch_id": "tray-a",
                "larvae_age_days": 5,
                "larvae_weight_g": 500,
                "feed_type": "prepared substrate",
                "feed_quantity_kg": 1.25,
                "consumption_g": 900,
                "operator": self.actor,
                "notes": "morning feed",
            },
        )
        self.assertEqual(feeding.status_code, 201, feeding.get_json())

        monitoring = self.client.post(
            "/api/feeding/environmental-monitoring",
            json={
                "production_batch_id": batch["business_id"],
                "monitoring_date": "2026-09-25",
                "monitoring_time": "09:00",
                "tray_facility_id": "tray-a",
                "temperature": 28.5,
                "humidity": 62,
                "ammonia_odor": "no",
            },
        )
        self.assertEqual(monitoring.status_code, 201, monitoring.get_json())

        health = self.client.post(
            "/api/feeding/health-intervention",
            json={
                "production_batch_id": batch["business_id"],
                "health_date": "2026-09-25",
                "event_time": "10:00",
                "tray_batch_id": "tray-a",
                "observed_issue": "slow feeding",
                "severity": "medium",
                "action_taken": "Adjusted feed distribution",
                "resolved": "no",
            },
        )
        self.assertEqual(health.status_code, 201, health.get_json())

        detail = self.client.get(
            f"/api/production/batches/{batch['business_id']}"
        )
        self.assertEqual(detail.status_code, 200, detail.get_json())
        data = detail.get_json()["data"]
        self.assertEqual(len(data["feeding_events"]), 1)
        self.assertEqual(len(data["monitoring_events"]), 1)
        self.assertEqual(len(data["health_events"]), 1)
        self.assertEqual(
            [event["event_type"] for event in data["timeline"]],
            ["feeding", "monitoring", "health"],
        )
        self.assertTrue(all(event["production_batch_id"] == batch["id"] for event in data["timeline"]))

        links = db.fetch_all(
            """
            SELECT production_batch_id, production_event_id
            FROM feeding_schedule
            WHERE production_batch_id = %s
            UNION ALL
            SELECT production_batch_id, production_event_id
            FROM environmental_monitoring_larvaefeeding
            WHERE production_batch_id = %s
            UNION ALL
            SELECT production_batch_id, production_event_id
            FROM health_intervention
            WHERE production_batch_id = %s
            """,
            (batch["id"], batch["id"], batch["id"]),
        )
        self.assertEqual(len(links), 3)
        self.assertTrue(all(row["production_event_id"] for row in links))

    def test_event_measurement_range_and_closed_batch_rules_are_enforced(self):
        substrate_id = self._create_substrate()
        created = self._create_production(substrate_id, harvest_limit_kg="4.000")
        self.assertEqual(created.status_code, 201, created.get_json())
        batch = created.get_json()["record"]

        active = self.client.post(
            f"/api/production/batches/{batch['business_id']}/status",
            json={"status": "ACTIVE", "recorded_by": self.actor},
        )
        self.assertEqual(active.status_code, 200, active.get_json())

        invalid_monitoring = self.client.post(
            f"/api/production/batches/{batch['business_id']}/events/monitoring",
            json={
                "monitoring_date": "2026-09-25",
                "monitoring_time": "09:00",
                "asset_reference": "tray-a",
                "temperature": 101,
                "humidity": 50,
            },
        )
        self.assertEqual(invalid_monitoring.status_code, 400)
        self.assertIn("temperature", invalid_monitoring.get_json()["message"])

        transitions = [
            ("MONITORING", None),
            ("READY_FOR_HARVEST", None),
        ]
        for status, reason in transitions:
            payload = {"status": status, "recorded_by": self.actor}
            if reason:
                payload["reason"] = reason
            response = self.client.post(
                f"/api/production/batches/{batch['business_id']}/status",
                json=payload,
            )
            self.assertEqual(response.status_code, 200, response.get_json())

        missing_harvest = self.client.post(
            f"/api/production/batches/{batch['business_id']}/status",
            json={"status": "HARVESTED", "recorded_by": self.actor},
        )
        self.assertEqual(missing_harvest.status_code, 400, missing_harvest.get_json())
        self.assertIn("valid harvest", missing_harvest.get_json()["message"])

        harvest = self._harvest(batch)
        self.assertEqual(harvest.status_code, 201, harvest.get_json())
        for status, reason in (("HARVESTED", None), ("COMPLETED", "test close")):
            payload = {"status": status, "recorded_by": self.actor}
            if reason:
                payload["reason"] = reason
            response = self.client.post(
                f"/api/production/batches/{batch['business_id']}/status",
                json=payload,
            )
            self.assertEqual(response.status_code, 200, response.get_json())

        blocked = self.client.post(
            f"/api/production/batches/{batch['business_id']}/events/health",
            json={
                "health_date": "2026-09-25",
                "observed_issue": "late observation",
                "severity": "low",
                "action_taken": "No action",
            },
        )
        self.assertEqual(blocked.status_code, 400, blocked.get_json())
        self.assertIn("completed", blocked.get_json()["message"])

    def test_invalid_status_transition_is_rejected_and_history_is_audited(self):
        substrate_id = self._create_substrate()
        created = self._create_production(substrate_id)
        self.assertEqual(created.status_code, 201, created.get_json())
        batch = created.get_json()["record"]

        invalid = self.client.post(
            f"/api/production/batches/{batch['business_id']}/status",
            json={"status": "MONITORING", "recorded_by": self.actor},
        )
        self.assertEqual(invalid.status_code, 400, invalid.get_json())
        self.assertIn("Invalid status transition", invalid.get_json()["message"])

        active = self.client.post(
            f"/api/production/batches/{batch['business_id']}/status",
            json={"status": "ACTIVE", "recorded_by": self.actor},
        )
        self.assertEqual(active.status_code, 200, active.get_json())

        missing_reason = self.client.post(
            f"/api/production/batches/{batch['business_id']}/status",
            json={"status": "CANCELLED", "recorded_by": self.actor},
        )
        self.assertEqual(missing_reason.status_code, 400, missing_reason.get_json())

        cancelled = self.client.post(
            f"/api/production/batches/{batch['business_id']}/status",
            json={
                "status": "CANCELLED",
                "reason": "Operational test cancellation",
                "recorded_by": self.actor,
            },
        )
        self.assertEqual(cancelled.status_code, 200, cancelled.get_json())

        history = db.fetch_all(
            """
            SELECT previous_status, new_status, actor, reason
            FROM production_batch_status_history
            WHERE production_batch_id = %s
            ORDER BY id
            """,
            (batch["id"],),
        )
        self.assertEqual(
            [(row["previous_status"], row["new_status"]) for row in history],
            [(None, "PLANNED"), ("PLANNED", "ACTIVE"), ("ACTIVE", "CANCELLED")],
        )
        self.assertEqual(history[-1]["actor"], self.actor)
        self.assertEqual(history[-1]["reason"], "Operational test cancellation")

    def test_insufficient_substrate_is_rejected_without_creating_a_batch(self):
        substrate_id = self._create_substrate()
        first = self._create_production(substrate_id, "7.000")
        self.assertEqual(first.status_code, 201, first.get_json())

        overdraw = self._create_production(substrate_id, "2.000")
        self.assertEqual(overdraw.status_code, 400, overdraw.get_json())
        self.assertIn("available", overdraw.get_json()["message"])

        remaining = db.fetch_one(
            """
            SELECT
                sb.total_input_weight_kg - COALESCE(SUM(pbi.quantity_issued), 0)
                    AS available
            FROM substrate_batches AS sb
            LEFT JOIN production_batch_inputs AS pbi
                ON pbi.substrate_batch_id = sb.id
            WHERE sb.id = %s
            GROUP BY sb.id
            """,
            (substrate_id,),
        )
        self.assertEqual(float(remaining["available"]), 1.0)

    def test_valid_partial_harvests_keep_batch_lineage_and_aggregate_in_kg(self):
        substrate_id = self._create_substrate()
        created = self._create_production(
            substrate_id, harvest_limit_kg="2.000"
        )
        self.assertEqual(created.status_code, 201, created.get_json())
        batch = created.get_json()["record"]
        self._move_to_harvest_ready(batch)

        first = self._harvest(batch, wet_weight="1.250", unit="kg")
        self.assertEqual(first.status_code, 201, first.get_json())
        self.assertTrue(first.get_json()["harvest"]["harvest_code"].startswith("HRV-"))
        self.assertEqual(
            first.get_json()["event"]["production_batch_id"], batch["id"]
        )
        second = self._harvest(
            batch, legacy_route=True, wet_weight="500", unit="g"
        )
        self.assertEqual(second.status_code, 201, second.get_json())

        detail = self.client.get(
            f"/api/production/batches/{batch['business_id']}"
        )
        self.assertEqual(detail.status_code, 200, detail.get_json())
        data = detail.get_json()["data"]
        self.assertEqual(len(data["harvests"]), 2)
        self.assertAlmostEqual(float(data["total_harvested_kg"]), 1.75)
        self.assertAlmostEqual(float(data["remaining_harvest_kg"]), 0.25)
        self.assertTrue(
            all(event["production_batch_id"] == batch["id"] for event in data["harvests"])
        )
        reports = self.client.get("/api/feeding/harvest/all").get_json()["records"]
        linked = [
            row for row in reports
            if row["record_type"] == "production_batch"
        ]
        self.assertEqual(len(linked), 2)

    def test_harvest_requires_ready_state_and_configured_limit(self):
        substrate_id = self._create_substrate()
        created = self._create_production(substrate_id)
        self.assertEqual(created.status_code, 201, created.get_json())
        batch = created.get_json()["record"]

        invalid_state = self._harvest(batch)
        self.assertEqual(invalid_state.status_code, 400, invalid_state.get_json())
        self.assertIn("READY_FOR_HARVEST", invalid_state.get_json()["message"])

        self._move_to_harvest_ready(batch)
        no_limit = self._harvest(batch)
        self.assertEqual(no_limit.status_code, 400, no_limit.get_json())
        self.assertIn("harvest_limit_kg", no_limit.get_json()["message"])

        configured = self.client.put(
            f"/api/production/batches/{batch['business_id']}/harvest-limit",
            json={"harvest_limit_kg": "1.500"},
        )
        self.assertEqual(configured.status_code, 200, configured.get_json())
        valid = self._harvest(batch, wet_weight="250", unit="g")
        self.assertEqual(valid.status_code, 201, valid.get_json())

        frozen_limit = self.client.put(
            f"/api/production/batches/{batch['business_id']}/harvest-limit",
            json={"harvest_limit_kg": "2.000"},
        )
        self.assertEqual(frozen_limit.status_code, 400, frozen_limit.get_json())
        self.assertIn("cannot be changed", frozen_limit.get_json()["message"])

    def test_excess_harvest_is_rejected_without_partial_write(self):
        substrate_id = self._create_substrate()
        created = self._create_production(
            substrate_id, harvest_limit_kg="1.000"
        )
        self.assertEqual(created.status_code, 201, created.get_json())
        batch = created.get_json()["record"]
        self._move_to_harvest_ready(batch)

        excessive = self._harvest(batch, wet_weight="1.001", unit="kg")
        self.assertEqual(excessive.status_code, 400, excessive.get_json())
        self.assertIn("batch limit", excessive.get_json()["message"])
        detail = self.client.get(
            f"/api/production/batches/{batch['business_id']}"
        ).get_json()["data"]
        self.assertEqual(detail["harvests"], [])
        self.assertEqual(float(detail["total_harvested_kg"]), 0)

    def test_harvest_requires_farm_authorization(self):
        substrate_id = self._create_substrate()
        created = self._create_production(
            substrate_id, harvest_limit_kg="2.000"
        )
        self.assertEqual(created.status_code, 201, created.get_json())
        batch = created.get_json()["record"]
        self._move_to_harvest_ready(batch)
        owner_harvest = self._harvest(batch)
        self.assertEqual(owner_harvest.status_code, 201, owner_harvest.get_json())

        unauthorized_user = SimpleNamespace(
            is_authenticated=True,
            id=987654321,
            role="farm_operator",
            username="unassigned-operator",
        )
        with patch.dict(app.config, {"LOGIN_DISABLED": False}), patch(
            "backend.app.current_user", unauthorized_user
        ), patch("flask_login.utils.current_user", unauthorized_user):
            response = self._harvest(batch)
            listing = self.client.get("/api/feeding/harvest/all")
        self.assertEqual(response.status_code, 403, response.get_json())
        self.assertIn("not authorized", response.get_json()["message"])
        self.assertEqual(listing.status_code, 200, listing.get_json())
        self.assertFalse(
            any(
                row.get("production_batch_id") == batch["id"]
                for row in listing.get_json()["records"]
            ),
            listing.get_json(),
        )
    # ---- Product Lot -> Inventory ledger -------------------------------------

    def _release_lot(self, *, output_quantity="0.600"):
        _drying_ref, output = self._create_output_for_product_lot(
            output_quantity=output_quantity
        )
        check = self._create_output_quality_check(output)
        self.assertEqual(check.status_code, 201, check.get_json())
        approval = self.client.post(
            "/api/drying/quality-approvals",
            json={
                "quality_check_id": check.get_json()["data"]["id"],
                "decision": "approved",
                "approver": self.actor,
            },
        )
        self.assertEqual(approval.status_code, 201, approval.get_json())
        response = self.client.post(
            "/api/product-lots",
            json={
                "drying_output_id": output["id"],
                "product_type": "dried_larvae",
                "inventory_location_id": self.inventory_location_id,
            },
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["data"]

    def _add_inventory_location(self, code, *, farm_id=None, site_id=None, facility_id=None):
        row = db.execute_returning(
            """
            INSERT INTO inventory_locations
                (location_code, name, farm_id, site_id, facility_id)
            VALUES (%s, %s, %s, %s, %s) RETURNING id
            """,
            (
                code, f"Store {code}", farm_id or self.farm_id,
                site_id or self.site_id, facility_id or self.facility_id,
            ),
        )
        return row["id"]

    def _move(self, lot, movement_type, quantity, **extra):
        payload = {
            "product_lot_id": lot["business_id"],
            "movement_type": movement_type,
            "quantity_kg": quantity,
            "unit": "kg",
            **extra,
        }
        return self.client.post("/api/inventory/movements", json=payload)

    def _balances(self, lot):
        detail = self.client.get(f"/api/product-lots/{lot['business_id']}")
        self.assertEqual(detail.status_code, 200, detail.get_json())
        inventory = detail.get_json()["data"]["inventory"]
        return {
            row["location_id"]: float(row["quantity_kg"]) for row in inventory["balances"]
        }, inventory

    def _create_db_user(self, *, farm_access=True):
        name = f"u{uuid4().hex[:12]}"
        row = db.execute_returning(
            """
            INSERT INTO users (username, full_name, email, password_hash, role)
            VALUES (%s, %s, %s, 'not-a-real-hash', 'viewer') RETURNING user_id
            """,
            (name, name, f"{name}@example.test"),
        )
        self.addCleanup(
            db.execute_query, "DELETE FROM users WHERE user_id = %s", (row["user_id"],)
        )
        if farm_access:
            db.execute_query(
                "INSERT INTO user_farm_access (user_id, farm_id) VALUES (%s, %s)",
                (row["user_id"], self.farm_id),
            )
        return SimpleNamespace(
            is_authenticated=True, id=row["user_id"], role="viewer", username=name,
        )

    def _as(self, user):
        return _UserContext(user)

    def test_release_posts_exactly_one_receipt_and_stock_is_ledger_derived(self):
        lot = self._release_lot()
        balances, inventory = self._balances(lot)
        self.assertEqual(balances, {self.inventory_location_id: 0.6})
        self.assertAlmostEqual(float(inventory["on_hand_kg"]), 0.6)
        self.assertEqual(len(inventory["movements"]), 1)
        receipt = inventory["movements"][0]
        self.assertEqual(receipt["movement_type"], "RECEIPT")
        self.assertRegex(receipt["business_id"], r"^MOV-\d{4}-\d+$")
        self.assertEqual(receipt["reference_type"], "quality_approval")
        self.assertEqual(lot["storage_location"], "Dry Store A")

        duplicate = self._move(
            lot, "RECEIPT", "0.600", to_location_id=self.inventory_location_id
        )
        self.assertEqual(duplicate.status_code, 409, duplicate.get_json())
        receipts = db.fetch_one(
            """
            SELECT COUNT(*) AS count FROM inventory_movements
            WHERE product_lot_id = %s AND movement_type = 'RECEIPT'
            """,
            (lot["id"],),
        )
        self.assertEqual(receipts["count"], 1)

        stock = self.client.get("/api/inventory")
        self.assertEqual(stock.status_code, 200, stock.get_json())
        rows = [row for row in stock.get_json()["data"] if row["product_lot_id"] == lot["id"]]
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(float(rows[0]["quantity_kg"]), 0.6)
        self.assertEqual(rows[0]["lot_status"], "AVAILABLE")
        self.assertEqual(rows[0]["location_code"], "DRY-STORE-A")

        lots = self.client.get(f"/api/product-lots?farm_id={self.farm_id}")
        listed = next(row for row in lots.get_json()["data"] if row["id"] == lot["id"])
        self.assertAlmostEqual(float(listed["on_hand_kg"]), 0.6)

    def test_release_requires_a_receiving_location_on_the_same_farm(self):
        _drying_ref, output = self._create_output_for_product_lot()
        check = self._create_output_quality_check(output)
        self.client.post(
            "/api/drying/quality-approvals",
            json={
                "quality_check_id": check.get_json()["data"]["id"],
                "decision": "approved",
                "approver": self.actor,
            },
        )
        payload = {"drying_output_id": output["id"], "product_type": "dried_larvae"}
        missing = self.client.post("/api/product-lots", json=payload)
        self.assertEqual(missing.status_code, 400, missing.get_json())
        self.assertIn("inventory_location_id", missing.get_json()["message"])

        other = self._create_other_farm_location()
        foreign = self.client.post(
            "/api/product-lots", json={**payload, "inventory_location_id": other}
        )
        self.assertEqual(foreign.status_code, 400, foreign.get_json())
        self.assertIn("different farm", foreign.get_json()["message"])
        lot_count = db.fetch_one(
            "SELECT COUNT(*) AS count FROM product_lots WHERE drying_output_id = %s",
            (output["id"],),
        )
        self.assertEqual(lot_count["count"], 0)

    def _create_other_farm_location(self):
        code = f"o{uuid4().hex[:20]}"
        conn = db.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO organizations (organization_code, name) VALUES (%s, %s) RETURNING id",
                    (code, code),
                )
                org_id = cursor.fetchone()[0]
                cursor.execute(
                    "INSERT INTO farms (organization_id, farm_code, name) VALUES (%s, %s, %s) RETURNING id",
                    (org_id, code, code),
                )
                farm_id = cursor.fetchone()[0]
                cursor.execute(
                    "INSERT INTO sites (farm_id, site_code, name) VALUES (%s, %s, %s) RETURNING id",
                    (farm_id, code, code),
                )
                site_id = cursor.fetchone()[0]
                cursor.execute(
                    """
                    INSERT INTO facilities (site_id, facility_code, name, facility_type)
                    VALUES (%s, %s, %s, 'warehouse') RETURNING id
                    """,
                    (site_id, code, code),
                )
                facility_id = cursor.fetchone()[0]
                cursor.execute(
                    """
                    INSERT INTO inventory_locations
                        (location_code, name, farm_id, site_id, facility_id)
                    VALUES ('FOREIGN', 'Foreign store', %s, %s, %s) RETURNING id
                    """,
                    (farm_id, site_id, facility_id),
                )
                location_id = cursor.fetchone()[0]
            conn.commit()
        finally:
            db.return_connection(conn)

        def cleanup():
            for statement, value in (
                ("DELETE FROM inventory_locations WHERE id = %s", location_id),
                ("DELETE FROM facilities WHERE id = %s", facility_id),
                ("DELETE FROM sites WHERE id = %s", site_id),
                ("DELETE FROM farms WHERE id = %s", farm_id),
                ("DELETE FROM organizations WHERE id = %s", org_id),
            ):
                db.execute_query(statement, (value,))

        self.addCleanup(cleanup)
        return location_id

    def test_transfer_adjustment_and_negative_stock_rules(self):
        lot = self._release_lot()
        store_b = self._add_inventory_location("STORE-B")

        transfer = self._move(
            lot, "TRANSFER", "0.250",
            from_location_id=self.inventory_location_id, to_location_id=store_b,
        )
        self.assertEqual(transfer.status_code, 201, transfer.get_json())
        self.assertEqual(
            self._balances(lot)[0],
            {self.inventory_location_id: 0.35, store_b: 0.25},
        )

        overdraw = self._move(
            lot, "TRANSFER", "0.251",
            from_location_id=store_b, to_location_id=self.inventory_location_id,
        )
        self.assertEqual(overdraw.status_code, 400, overdraw.get_json())
        self.assertIn("Only 0.250 kg", overdraw.get_json()["message"])

        no_reason = self._move(lot, "WASTAGE", "0.010", from_location_id=store_b)
        self.assertEqual(no_reason.status_code, 400, no_reason.get_json())
        self.assertIn("reason is required", no_reason.get_json()["message"])

        wastage = self._move(
            lot, "WASTAGE", "0.050", from_location_id=store_b, reason="Bag torn in transit",
        )
        self.assertEqual(wastage.status_code, 201, wastage.get_json())
        over_release = self._move(
            lot, "ADJUSTMENT_IN", "0.051", to_location_id=store_b, reason="Recount",
        )
        self.assertEqual(over_release.status_code, 400, over_release.get_json())
        self.assertIn("cannot exceed the released quantity", over_release.get_json()["message"])
        recount = self._move(
            lot, "ADJUSTMENT_IN", "0.050", to_location_id=store_b, reason="Recount found bag",
        )
        self.assertEqual(recount.status_code, 201, recount.get_json())
        balances, inventory = self._balances(lot)
        self.assertEqual(balances, {self.inventory_location_id: 0.35, store_b: 0.25})
        self.assertEqual(
            [row["movement_type"] for row in inventory["movements"]],
            ["RECEIPT", "TRANSFER", "WASTAGE", "ADJUSTMENT_IN"],
        )

        for bad_payload, message in (
            ({"movement_type": "SALE", "from_location_id": store_b}, "movement_type"),
            ({"movement_type": "TRANSFER", "from_location_id": store_b,
              "to_location_id": store_b}, "two different"),
            ({"movement_type": "TRANSFER", "from_location_id": store_b}, "requires a to_location_id"),
            ({"movement_type": "WASTAGE", "from_location_id": store_b,
              "to_location_id": store_b, "reason": "x"}, "must not have a to_location_id"),
            ({"movement_type": "TRANSFER", "from_location_id": store_b,
              "to_location_id": self.inventory_location_id, "unit": "g"}, "kg"),
        ):
            response = self._move(lot, quantity="0.010", **bad_payload)
            self.assertEqual(response.status_code, 400, (bad_payload, response.get_json()))
            self.assertIn(message, response.get_json()["message"])
        negative = self._move(
            lot, "TRANSFER", "-0.010",
            from_location_id=store_b, to_location_id=self.inventory_location_id,
        )
        self.assertEqual(negative.status_code, 400, negative.get_json())
        self.assertEqual(self._balances(lot)[0], {self.inventory_location_id: 0.35, store_b: 0.25})

    def test_concurrent_withdrawals_cannot_drive_stock_negative(self):
        lot = self._release_lot()

        def withdraw(index):
            return app.test_client().post(
                "/api/inventory/movements",
                json={
                    "product_lot_id": lot["business_id"],
                    "movement_type": "WASTAGE",
                    "quantity_kg": "0.400",
                    "from_location_id": self.inventory_location_id,
                    "reason": f"race {index}",
                },
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(withdraw, range(2)))
        self.assertEqual(sorted(r.status_code for r in responses), [201, 400])
        self.assertEqual(self._balances(lot)[0], {self.inventory_location_id: 0.2})

    def test_inventory_roles_and_farm_isolation(self):
        lot = self._release_lot()
        store_b = self._add_inventory_location("STORE-B")
        operator = self._create_db_user()
        with self._as(operator):
            transfer = self._move(
                lot, "TRANSFER", "0.100",
                from_location_id=self.inventory_location_id, to_location_id=store_b,
            )
            adjustment = self._move(
                lot, "ADJUSTMENT_OUT", "0.100",
                from_location_id=store_b, reason="Operator tries a write-off",
            )
            visible = self.client.get("/api/inventory")
        self.assertEqual(transfer.status_code, 201, transfer.get_json())
        self.assertEqual(adjustment.status_code, 403, adjustment.get_json())
        self.assertIn(lot["id"], [row["product_lot_id"] for row in visible.get_json()["data"]])

        outsider = self._create_db_user(farm_access=False)
        with self._as(outsider):
            moved = self._move(
                lot, "TRANSFER", "0.050",
                from_location_id=store_b, to_location_id=self.inventory_location_id,
            )
            stock = self.client.get("/api/inventory")
            lots = self.client.get("/api/product-lots")
            locations = self.client.get("/api/inventory/locations")
            batches = self.client.get("/api/production/batches")
            create_location = self.client.post(
                "/api/inventory/locations",
                json={
                    "farm_id": self.farm_id, "site_id": self.site_id,
                    "facility_id": self.facility_id,
                    "location_code": "X", "name": "Outsider store",
                },
            )
        self.assertEqual(moved.status_code, 403, moved.get_json())
        self.assertNotIn(lot["id"], [row["product_lot_id"] for row in stock.get_json()["data"]])
        self.assertNotIn(lot["id"], [row["id"] for row in lots.get_json()["data"]])
        self.assertNotIn(store_b, [row["id"] for row in locations.get_json()["data"]])
        self.assertFalse(
            any(row["farm_id"] == self.farm_id for row in batches.get_json()["data"])
        )
        self.assertEqual(create_location.status_code, 403)
        self.assertEqual(
            self._balances(lot)[0],
            {self.inventory_location_id: 0.5, store_b: 0.1},
        )

    def test_qc_blocked_lot_cannot_be_moved_but_can_be_written_off(self):
        lot = self._release_lot()
        db.execute_query(
            """
            INSERT INTO quality_approvals (quality_check_id, decision, rationale, approver)
            SELECT quality_check_id, 'revoked', 'Contamination found after release', %s
            FROM quality_approvals WHERE id = %s
            """,
            (self.actor, lot_release_approval_id(lot)),
        )
        store_b = self._add_inventory_location("STORE-B")
        blocked = self._move(
            lot, "TRANSFER", "0.100",
            from_location_id=self.inventory_location_id, to_location_id=store_b,
        )
        self.assertEqual(blocked.status_code, 400, blocked.get_json())
        self.assertIn("blocked by QC", blocked.get_json()["message"])
        stock = self.client.get("/api/inventory")
        row = next(r for r in stock.get_json()["data"] if r["product_lot_id"] == lot["id"])
        self.assertEqual(row["lot_status"], "BLOCKED")
        written_off = self._move(
            lot, "WASTAGE", "0.600",
            from_location_id=self.inventory_location_id, reason="Destroyed after QC revocation",
        )
        self.assertEqual(written_off.status_code, 201, written_off.get_json())
        self.assertEqual(self._balances(lot)[0], {})

    def test_production_batches_can_be_listed_and_filtered(self):
        substrate_id = self._create_substrate()
        created = self._create_production(substrate_id)
        self.assertEqual(created.status_code, 201, created.get_json())
        batch = created.get_json()["record"]
        listing = self.client.get(
            f"/api/production/batches?farm_id={self.farm_id}&status=planned"
        )
        self.assertEqual(listing.status_code, 200, listing.get_json())
        row = next(r for r in listing.get_json()["data"] if r["id"] == batch["id"])
        self.assertEqual(row["status"], "PLANNED")
        self.assertEqual(row["facility_name"], self.marker)
        invalid = self.client.get("/api/production/batches?status=sold")
        self.assertEqual(invalid.status_code, 400)

    # ---- Batch 360 ----------------------------------------------------------
    def _get_360(self, ref):
        return self.client.get(f"/api/production/batches/{ref}/360")

    def test_batch_360_follows_one_batch_from_waste_to_stock(self):
        lot = self._release_lot()
        detail = self.client.get(f"/api/product-lots/{lot['business_id']}").get_json()["data"]
        batch_ref = detail["source_chain"][0]["production_batch_business_id"]
        feeding = self.client.post(
            f"/api/production/batches/{batch_ref}/events/feeding",
            json={
                "occurred_at": "2026-09-25T08:00:00+00:00",
                "feed_type": "vegetable mash",
                "operator": self.actor,
                "quantity_offered": "2.000",
                "offered_unit": "kg",
                "larvae_biomass": "0.750",
                "biomass_unit": "kg",
            },
        )
        self.assertEqual(feeding.status_code, 201, feeding.get_json())

        response = self._get_360(batch_ref)
        self.assertEqual(response.status_code, 200, response.get_json())
        data = response.get_json()["data"]
        self.assertEqual(data["batch"]["business_id"], batch_ref)
        self.assertEqual(data["batch"]["farm_name"], self.marker)
        self.assertTrue(all(stage["done"] for stage in data["stages"]), data["stages"])

        self.assertAlmostEqual(data["source"]["substrate_issued_kg"], 4.0)
        waste_ids = [
            w["waste_lot_id"]
            for s in data["source"]["substrate_batches"] for w in s["waste_lots"]
        ]
        self.assertEqual(waste_ids, [self.waste_lot_id])

        self.assertEqual(data["operations"]["feeding"]["count"], 1)
        self.assertAlmostEqual(data["operations"]["feeding"]["total_offered_kg"], 2.0)
        self.assertAlmostEqual(data["harvest"]["total_wet_kg"], 1.5)
        self.assertAlmostEqual(data["harvest"]["substrate_conversion_percent"], 37.5)

        drying = data["processing"]["drying_batches"]
        self.assertEqual(len(drying), 1)
        self.assertAlmostEqual(drying[0]["input_from_this_batch_kg"], 1.2)
        self.assertAlmostEqual(drying[0]["total_output_kg"], 0.6)
        self.assertAlmostEqual(drying[0]["yield_percent"], 50.0)
        self.assertEqual(drying[0]["shared_with_other_batches"], 0)

        self.assertEqual(
            [(q["check_status"], q["decision"]) for q in data["quality"]],
            [("passed", "approved")],
        )
        self.assertEqual([p["business_id"] for p in data["product_lots"]], [lot["business_id"]])
        self.assertAlmostEqual(data["inventory"]["on_hand_kg"], 0.6)
        self.assertAlmostEqual(data["inventory"]["available_kg"], 0.6)
        self.assertEqual(
            [m["movement_type"] for m in data["inventory"]["movements"]], ["RECEIPT"]
        )
        self.assertEqual(
            [p["business_id"] for p in data["traceability"]["downstream"]["product_lots"]],
            [lot["business_id"]],
        )
        self.assertEqual(
            data["traceability"]["downstream"]["commercial"],
            {"restricted": False, "orders": [], "deliveries": []},
        )

        titles = [entry["title"] for entry in data["audit"]]
        self.assertIn("Batch created as PLANNED", titles)
        self.assertTrue(any(t.startswith("Harvest HRV-") for t in titles), titles)
        self.assertTrue(any(t.startswith("QC decision") for t in titles), titles)
        self.assertIn(f"Product Lot {lot['business_id']} released", titles)
        self.assertTrue(any(t.endswith("RECEIPT") for t in titles), titles)
        timestamps = [entry["at"] for entry in data["audit"]]
        self.assertEqual(timestamps, sorted(timestamps, key=_parse_iso))

    def test_new_batch_reports_unrecorded_stages_without_placeholders(self):
        created = self._create_production(self._create_substrate())
        self.assertEqual(created.status_code, 201, created.get_json())
        batch = created.get_json()["record"]
        data = self._get_360(batch["business_id"]).get_json()["data"]
        self.assertEqual(
            {stage["key"]: stage["done"] for stage in data["stages"]},
            {
                "source": True, "production": False, "harvest": False,
                "processing": False, "quality": False, "product": False,
                "inventory": False,
            },
        )
        self.assertEqual(data["harvest"]["count"], 0)
        self.assertIsNone(data["harvest"]["substrate_conversion_percent"])
        self.assertEqual(data["processing"]["drying_batches"], [])
        self.assertEqual(data["quality"], [])
        self.assertEqual(data["product_lots"], [])
        self.assertEqual(data["inventory"]["on_hand_kg"], 0)
        self.assertEqual([e["title"] for e in data["audit"]], ["Batch created as PLANNED"])

    def test_batch_360_is_farm_scoped(self):
        created = self._create_production(self._create_substrate())
        batch = created.get_json()["record"]
        outsider = self._create_db_user(farm_access=False)
        member = self._create_db_user()
        with self._as(outsider):
            denied = self._get_360(batch["business_id"])
        with self._as(member):
            allowed = self._get_360(batch["business_id"])
        self.assertEqual(denied.status_code, 403, denied.get_json())
        self.assertEqual(allowed.status_code, 200, allowed.get_json())
        self.assertEqual(self._get_360("BSF-0000-99999").status_code, 404)
        self.assertEqual(self.client.get("/batch-360").status_code, 200)

    def test_shared_drying_batch_is_flagged_not_split(self):
        batches, _drying = self._shared_drying()

        data = self._get_360(batches[0][0]["business_id"]).get_json()["data"]
        row = data["processing"]["drying_batches"][0]
        self.assertEqual(row["shared_with_other_batches"], 1)
        self.assertAlmostEqual(row["input_from_this_batch_kg"], 0.8)
        self.assertAlmostEqual(row["total_input_kg"], 1.2)
        self.assertTrue(data["processing"]["any_shared"])
        self.assertAlmostEqual(data["processing"]["wet_input_kg"], 0.8)

    def test_feeding_accepts_canonical_biomass_and_mirrors_it_in_grams(self):
        created = self._create_production(self._create_substrate())
        batch = created.get_json()["record"]
        payload = {
            "occurred_at": "2026-09-25T08:00:00+00:00",
            "feed_type": "vegetable mash",
            "operator": self.actor,
            "quantity_offered": "1.500",
            "offered_unit": "kg",
        }
        endpoint = f"/api/production/batches/{batch['business_id']}/events/feeding"
        with_biomass = self.client.post(
            endpoint, json={**payload, "larvae_biomass": "0.031", "biomass_unit": "kg"}
        )
        without_biomass = self.client.post(endpoint, json=payload)
        self.assertEqual(with_biomass.status_code, 201, with_biomass.get_json())
        self.assertEqual(without_biomass.status_code, 201, without_biomass.get_json())
        weights = db.fetch_all(
            "SELECT larvae_weight FROM feeding_schedule WHERE production_batch_id = %s ORDER BY id",
            (batch["id"],),
        )
        self.assertEqual([None if r["larvae_weight"] is None else float(r["larvae_weight"])
                          for r in weights], [31.0, None])

    # ---- Traceability ---------------------------------------------------------

    def _trace(self, ref, record_type=None):
        url = f"/api/traceability?ref={ref}"
        if record_type:
            url += f"&type={record_type}"
        return self.client.get(url)

    @staticmethod
    def _trace_nodes(data, direction=None):
        return {
            (node["type"], node.get("id")): node
            for stage in data["stages"] for node in stage["nodes"]
            if direction is None or node.get("direction") == direction
        }

    def _shared_drying(self):
        batches = []
        for _ in range(2):
            substrate_id = self._create_substrate(quantity="4.000")
            created = self._create_production(
                substrate_id, quantity="2.000", harvest_limit_kg="2.000"
            )
            self.assertEqual(created.status_code, 201, created.get_json())
            batch = created.get_json()["record"]
            self._move_to_harvest_ready(batch)
            harvest = self._harvest(batch, wet_weight="1.000")
            self.assertEqual(harvest.status_code, 201, harvest.get_json())
            batches.append((batch, harvest.get_json()["harvest"]["id"]))
        drying = self.client.post(
            "/api/drying/batches",
            json={
                "batch_code": f"shared-{uuid4().hex[:15]}",
                "drying_date": "2026-09-25",
                "drying_method": "sun_drying",
                "personnel": self.actor,
                "farm_id": self.farm_id,
                "site_id": self.site_id,
                "facility_id": self.facility_id,
                "inputs": [
                    {"harvest_id": batches[0][1], "quantity": "0.800", "unit": "kg"},
                    {"harvest_id": batches[1][1], "quantity": "0.400", "unit": "kg"},
                ],
            },
        )
        self.assertEqual(drying.status_code, 201, drying.get_json())
        return batches, drying.get_json()["data"]

    def test_trace_reaches_waste_from_product_and_stock_from_waste(self):
        lot = self._release_lot()
        response = self._trace(lot["business_id"].lower())
        self.assertEqual(response.status_code, 200, response.get_json())
        data = response.get_json()["data"]
        self.assertEqual((data["root"]["type"], data["root"]["id"]), ("product_lot", lot["id"]))
        upstream = self._trace_nodes(data, "upstream")
        self.assertIn(("waste_lot", self.waste_lot_id), upstream)
        self.assertEqual(
            {kind for kind, _ in upstream},
            {"waste_lot", "substrate_batch", "production_batch", "harvest", "drying_batch"},
        )
        downstream = self._trace_nodes(data, "downstream")
        self.assertEqual(list(downstream), [("inventory_location", self.inventory_location_id)])
        stock_edge = next(e for e in data["edges"] if e["to"].startswith("inventory_location:"))
        self.assertAlmostEqual(stock_edge["quantity"], 0.6)
        self.assertEqual(data["counts"]["restricted"], 0)
        self.assertTrue(data["commercial"]["linked"])

        waste_ref = db.fetch_one(
            "SELECT business_id FROM waste_lots WHERE id = %s", (self.waste_lot_id,)
        )["business_id"]
        from_waste = self._trace(waste_ref).get_json()["data"]
        self.assertEqual(from_waste["counts"]["upstream"], 0)
        downstream = self._trace_nodes(from_waste, "downstream")
        self.assertIn(("product_lot", lot["id"]), downstream)
        self.assertIn(("inventory_location", self.inventory_location_id), downstream)

    def test_trace_follows_direction_without_pulling_in_sibling_batches(self):
        batches, drying = self._shared_drying()
        (first, _), (second, _) = batches
        data = self._trace(first["business_id"]).get_json()["data"]
        nodes = self._trace_nodes(data)
        self.assertIn(("drying_batch", drying["id"]), nodes)
        self.assertNotIn(("production_batch", second["id"]), nodes)

        from_drying = self._trace(drying["business_id"], "drying_batch").get_json()["data"]
        upstream = self._trace_nodes(from_drying, "upstream")
        self.assertIn(("production_batch", first["id"]), upstream)
        self.assertIn(("production_batch", second["id"]), upstream)

    def test_trace_errors_scope_and_search(self):
        created = self._create_production(self._create_substrate())
        batch = created.get_json()["record"]
        self.assertEqual(self._trace("NOPE-0000-1").status_code, 404)
        self.assertEqual(self._trace(str(batch["id"])).status_code, 400)
        self.assertEqual(self._trace(str(batch["id"]), "production_batch").status_code, 200)
        self.assertEqual(self._trace(batch["business_id"], "warehouse").status_code, 400)
        self.assertEqual(self.client.get("/traceability").status_code, 200)

        outsider = self._create_db_user(farm_access=False)
        member = self._create_db_user()
        prefix = batch["business_id"][:9]
        with self._as(outsider):
            denied = self._trace(batch["business_id"])
            outsider_search = self.client.get(f"/api/traceability/search?q={prefix}")
        with self._as(member):
            allowed = self._trace(batch["business_id"])
            member_search = self.client.get(f"/api/traceability/search?q={prefix}")
        self.assertEqual(denied.status_code, 403, denied.get_json())
        self.assertEqual(allowed.status_code, 200, allowed.get_json())
        self.assertNotIn(batch["business_id"], [r["ref"] for r in outsider_search.get_json()["data"]])
        self.assertIn(batch["business_id"], [r["ref"] for r in member_search.get_json()["data"]])

    def test_trace_redacts_records_at_locations_the_user_cannot_access(self):
        lot = self._release_lot()
        other_facility = db.execute_returning(
            """
            INSERT INTO facilities (site_id, facility_code, name, facility_type)
            VALUES (%s, %s, 'Remote store', 'warehouse') RETURNING id
            """,
            (self.site_id, f"r{uuid4().hex[:10]}"),
        )["id"]
        remote = self._add_inventory_location("REMOTE", facility_id=other_facility)
        moved = self._move(
            lot, "TRANSFER", "0.200",
            from_location_id=self.inventory_location_id, to_location_id=remote,
        )
        self.assertEqual(moved.status_code, 201, moved.get_json())

        user = self._create_db_user(farm_access=False)
        db.execute_query(
            "INSERT INTO user_facility_access (user_id, facility_id) VALUES (%s, %s)",
            (user.id, self.facility_id),
        )
        with self._as(user):
            response = self._trace(lot["business_id"])
        self.assertEqual(response.status_code, 200, response.get_json())
        data = response.get_json()["data"]
        hidden = self._trace_nodes(data).get(("inventory_location", None))
        self.assertIsNotNone(hidden)
        self.assertTrue(hidden["restricted"])
        self.assertNotIn("ref", hidden)
        self.assertEqual(data["counts"]["restricted"], 1)
        remote_edge = next(e for e in data["edges"] if e["to"] == f"inventory_location:{remote}")
        self.assertIsNone(remote_edge["quantity"])

    # ---- Customer orders and deliveries ----------------------------------------

    def _customer(self):
        row = db.execute_returning(
            "INSERT INTO customers (name, contact) VALUES (%s, 'test') RETURNING id",
            (self.marker,),
        )
        return row["id"]

    def _order(self, *quantities, product_type="dried_larvae"):
        response = self.client.post(
            "/api/orders",
            json={
                "customer_id": self._customer(),
                "farm_id": self.farm_id,
                "requested_delivery_date": "2026-10-30",
                "lines": [
                    {"product_type": product_type, "quantity_kg": quantity}
                    for quantity in quantities
                ],
            },
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["data"]

    def _allocate(self, order, lot, quantity, *, line_index=0, location_id=None):
        return self.client.post(
            f"/api/orders/{order['business_id']}/allocations",
            json={
                "order_line_id": order["lines"][line_index]["id"],
                "product_lot_id": lot["id"],
                "location_id": location_id or self.inventory_location_id,
                "quantity_kg": quantity,
            },
        )

    def _dispatch(self, order, allocation_id, quantity):
        return self.client.post(
            f"/api/orders/{order['business_id']}/deliveries",
            json={
                "lines": [{"allocation_id": allocation_id, "quantity_kg": quantity}],
                "vehicle": "KDA 123A",
                "driver": "Test driver",
            },
        )

    def _free_and_reserved(self, lot):
        _balances, inventory = self._balances(lot)
        row = next(
            (b for b in inventory["balances"] if b["location_id"] == self.inventory_location_id),
            None,
        )
        if not row:
            return 0.0, 0.0
        return float(row["free_kg"]), float(row["reserved_kg"])

    def test_order_to_delivery_reserves_dispatches_and_traces_to_waste(self):
        lot = self._release_lot()
        order = self._order("0.500")
        self.assertRegex(order["business_id"], r"^ORD-\d{4}-\d+$")
        self.assertEqual(order["status"], "OPEN")

        stock = self.client.get(
            f"/api/orders/{order['business_id']}/available-stock?line_id={order['lines'][0]['id']}"
        )
        self.assertEqual(stock.status_code, 200, stock.get_json())
        self.assertAlmostEqual(
            next(r for r in stock.get_json()["data"] if r["product_lot_id"] == lot["id"])["free_kg"],
            0.6,
        )

        allocated = self._allocate(order, lot, "0.400")
        self.assertEqual(allocated.status_code, 201, allocated.get_json())
        order = allocated.get_json()["data"]
        allocation_id = order["allocations"][0]["id"]
        self.assertAlmostEqual(order["lines"][0]["remaining_to_allocate_kg"], 0.1)
        self.assertEqual(self._free_and_reserved(lot), (0.2, 0.4))

        # Reserved stock cannot leave by a manual movement.
        blocked = self._move(
            lot, "WASTAGE", "0.300", from_location_id=self.inventory_location_id, reason="spill",
        )
        self.assertEqual(blocked.status_code, 400, blocked.get_json())
        self.assertIn("reserved for customer orders", blocked.get_json()["message"])
        wasted = self._move(
            lot, "WASTAGE", "0.200", from_location_id=self.inventory_location_id, reason="spill",
        )
        self.assertEqual(wasted.status_code, 201, wasted.get_json())
        no_stock = self._allocate(order, lot, "0.100")
        self.assertEqual(no_stock.status_code, 400, no_stock.get_json())
        self.assertIn("free to allocate", no_stock.get_json()["message"])

        too_much = self._dispatch(order, allocation_id, "0.401")
        self.assertEqual(too_much.status_code, 400, too_much.get_json())
        first = self._dispatch(order, allocation_id, "0.250")
        self.assertEqual(first.status_code, 201, first.get_json())
        delivery_ref = first.get_json()["data"]["created_delivery"]
        self.assertRegex(delivery_ref, r"^DEL-\d{4}-\d+$")
        self.assertEqual(self._free_and_reserved(lot), (0.0, 0.15))
        second = self._dispatch(order, allocation_id, "0.150")
        self.assertEqual(second.status_code, 201, second.get_json())
        order = second.get_json()["data"]
        self.assertEqual(order["status"], "OPEN")  # 0.4 of 0.5 kg dispatched
        self.assertAlmostEqual(order["totals"]["dispatched_kg"], 0.4)
        _balances, inventory = self._balances(lot)
        self.assertEqual(inventory["balances"], [])
        self.assertEqual(
            [m["movement_type"] for m in inventory["movements"]],
            ["RECEIPT", "WASTAGE", "DISPATCH", "DISPATCH"],
        )

        confirmed = self.client.post(
            f"/api/deliveries/{delivery_ref}/confirm", json={"received_by": "Store keeper"}
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.get_json())
        delivered = next(d for d in confirmed.get_json()["data"]["deliveries"]
                         if d["business_id"] == delivery_ref)
        self.assertEqual(delivered["status"], "DELIVERED")
        again = self.client.post(
            f"/api/deliveries/{delivery_ref}/confirm", json={"received_by": "Store keeper"}
        )
        self.assertEqual(again.status_code, 409, again.get_json())

        # "Which waste lots ultimately contributed to this delivery?"
        trace = self._trace(delivery_ref).get_json()["data"]
        upstream = self._trace_nodes(trace, "upstream")
        self.assertIn(("waste_lot", self.waste_lot_id), upstream)
        self.assertIn(("product_lot", lot["id"]), upstream)
        self.assertIn(("customer_order", order["id"]), upstream)
        downstream = self._trace_nodes(self._trace(lot["business_id"]).get_json()["data"], "downstream")
        self.assertIn(("customer_order", order["id"]), downstream)
        self.assertEqual(
            sum(1 for kind, _ in downstream if kind == "delivery"), 2
        )

    def test_cancel_release_and_fulfilment_rules(self):
        lot = self._release_lot()
        cancelled = self._order("0.300")
        self.assertEqual(self._allocate(cancelled, lot, "0.300").status_code, 201)
        self.assertEqual(self._free_and_reserved(lot), (0.3, 0.3))
        no_reason = self.client.post(f"/api/orders/{cancelled['business_id']}/cancel", json={})
        self.assertEqual(no_reason.status_code, 400)
        cancel = self.client.post(
            f"/api/orders/{cancelled['business_id']}/cancel", json={"reason": "Customer withdrew"}
        )
        self.assertEqual(cancel.status_code, 200, cancel.get_json())
        self.assertEqual(cancel.get_json()["data"]["status"], "CANCELLED")
        self.assertEqual(self._free_and_reserved(lot), (0.6, 0.0))
        self.assertEqual(self._allocate(cancelled, lot, "0.100").status_code, 400)

        fulfilled = self._order("0.200")
        allocation = self._allocate(fulfilled, lot, "0.200").get_json()["data"]["allocations"][0]
        dispatched = self._dispatch(fulfilled, allocation["id"], "0.200")
        self.assertEqual(dispatched.get_json()["data"]["status"], "FULFILLED")
        late_cancel = self.client.post(
            f"/api/orders/{fulfilled['business_id']}/cancel", json={"reason": "too late"}
        )
        self.assertEqual(late_cancel.status_code, 400, late_cancel.get_json())

        partial = self._order("0.300")
        allocation = self._allocate(partial, lot, "0.300").get_json()["data"]["allocations"][0]
        self.assertEqual(self._dispatch(partial, allocation["id"], "0.100").status_code, 201)
        refused = self.client.post(
            f"/api/orders/{partial['business_id']}/cancel", json={"reason": "stop"}
        )
        self.assertEqual(refused.status_code, 400, refused.get_json())
        release = self.client.post(
            f"/api/orders/{partial['business_id']}/allocations/{allocation['id']}/release",
            json={"reason": "Short shipment agreed"},
        )
        self.assertEqual(release.status_code, 200, release.get_json())
        released = release.get_json()["data"]["allocations"][0]
        self.assertAlmostEqual(released["outstanding_kg"], 0.0)
        self.assertAlmostEqual(released["released_kg"], 0.2)
        self.assertEqual(self._free_and_reserved(lot), (0.3, 0.0))
        twice = self.client.post(
            f"/api/orders/{partial['business_id']}/allocations/{allocation['id']}/release",
            json={"reason": "again"},
        )
        self.assertEqual(twice.status_code, 400, twice.get_json())

    def test_order_validation_and_qc_blocking(self):
        lot = self._release_lot()
        missing_lines = self.client.post(
            "/api/orders", json={"customer_id": self._customer(), "farm_id": self.farm_id, "lines": []}
        )
        self.assertEqual(missing_lines.status_code, 400)
        negative = self.client.post(
            "/api/orders",
            json={"customer_id": self._customer(), "farm_id": self.farm_id,
                  "lines": [{"product_type": "dried_larvae", "quantity_kg": "-1"}]},
        )
        self.assertEqual(negative.status_code, 400)

        frass = self._order("0.100", product_type="frass")
        mismatch = self._allocate(frass, lot, "0.100")
        self.assertEqual(mismatch.status_code, 400, mismatch.get_json())
        self.assertIn("order line is for frass", mismatch.get_json()["message"])

        order = self._order("0.200")
        over_line = self._allocate(order, lot, "0.300")
        self.assertEqual(over_line.status_code, 400, over_line.get_json())
        self.assertIn("left to allocate", over_line.get_json()["message"])
        allocation = self._allocate(order, lot, "0.200").get_json()["data"]["allocations"][0]

        db.execute_query(
            """
            INSERT INTO quality_approvals (quality_check_id, decision, rationale, approver)
            SELECT quality_check_id, 'revoked', 'Recall', %s FROM quality_approvals WHERE id = %s
            """,
            (self.actor, lot_release_approval_id(lot)),
        )
        blocked = self._dispatch(order, allocation["id"], "0.100")
        self.assertEqual(blocked.status_code, 400, blocked.get_json())
        self.assertIn("blocked by QC", blocked.get_json()["message"])
        self.assertEqual(
            db.fetch_one(
                "SELECT COUNT(*) AS n FROM customer_deliveries WHERE order_id = %s", (order["id"],)
            )["n"],
            0,
        )
        another = self._order("0.100")
        self.assertEqual(self._allocate(another, lot, "0.100").status_code, 400)

    def test_orders_need_farm_level_access(self):
        lot = self._release_lot()
        order = self._order("0.100")
        allocation = self._allocate(order, lot, "0.100").get_json()["data"]["allocations"][0]
        self.assertEqual(self._dispatch(order, allocation["id"], "0.100").status_code, 201)

        facility_only = self._create_db_user(farm_access=False)
        db.execute_query(
            "INSERT INTO user_facility_access (user_id, facility_id) VALUES (%s, %s)",
            (facility_only.id, self.facility_id),
        )
        farm_user = self._create_db_user()
        with self._as(facility_only):
            detail = self.client.get(f"/api/orders/{order['business_id']}")
            listing = self.client.get("/api/orders")
            create = self.client.post(
                "/api/orders",
                json={"customer_id": self._customer(), "farm_id": self.farm_id,
                      "lines": [{"product_type": "dried_larvae", "quantity_kg": "0.1"}]},
            )
            trace = self._trace(lot["business_id"])
            batch360 = self._get_360(
                trace.get_json()["data"]["stages"][2]["nodes"][0]["ref"]
            )
        self.assertEqual(detail.status_code, 403)
        self.assertNotIn(order["id"], [row["id"] for row in listing.get_json()["data"]])
        self.assertEqual(create.status_code, 403)
        commercial = [
            node for stage in trace.get_json()["data"]["stages"]
            if stage["type"] in ("customer_order", "delivery") for node in stage["nodes"]
        ]
        self.assertTrue(commercial)
        self.assertTrue(all(node["restricted"] and "ref" not in node for node in commercial))
        self.assertTrue(batch360.get_json()["data"]["traceability"]["downstream"]["commercial"]["restricted"])

        with self._as(farm_user):
            self.assertEqual(self.client.get(f"/api/orders/{order['business_id']}").status_code, 200)
        self.assertEqual(self.client.get("/orders").status_code, 200)

    def test_concurrent_allocations_cannot_over_reserve_a_lot(self):
        lot = self._release_lot()
        orders = [self._order("0.400"), self._order("0.400")]

        def allocate(order):
            return app.test_client().post(
                f"/api/orders/{order['business_id']}/allocations",
                json={
                    "order_line_id": order["lines"][0]["id"],
                    "product_lot_id": lot["id"],
                    "location_id": self.inventory_location_id,
                    "quantity_kg": "0.400",
                },
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(allocate, orders))
        self.assertEqual(sorted(r.status_code for r in responses), [201, 400])
        self.assertEqual(self._free_and_reserved(lot), (0.2, 0.4))

    # ---- Operational alerts ------------------------------------------------------

    def _alerts(self, view="all"):
        db.execute_query("UPDATE operational_alert_sync SET last_run_at = NULL")
        response = self.client.get(f"/api/alerts?status={view}&farm_id={self.farm_id}")
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()["data"]

    @staticmethod
    def _by_rule(alerts, rule, status=None):
        return [a for a in alerts if a["rule"] == rule and (status is None or a["status"] == status)]

    def _health_event(self, batch, severity="critical"):
        response = self.client.post(
            f"/api/production/batches/{batch['business_id']}/events/health",
            json={
                "occurred_at": "2026-09-25T09:00:00+00:00",
                "observed_issue": "Larvae climbing out of trays",
                "severity": severity,
                "action_taken": "Reduced moisture",
            },
        )
        self.assertEqual(response.status_code, 201, response.get_json())

    def test_production_alerts_fire_from_records_and_resolve_when_cleared(self):
        substrate_id = self._create_substrate(quantity="8.000")
        first = self._create_production(substrate_id, quantity="2.000").get_json()["record"]
        second = self._create_production(substrate_id, quantity="2.000").get_json()["record"]
        db.execute_query(
            "UPDATE production_batches SET expected_harvest_at = now() - interval '4 days' WHERE id = %s",
            (first["id"],),
        )
        db.execute_query(
            "UPDATE production_batches SET expected_harvest_at = now() + interval '1 day' WHERE id = %s",
            (second["id"],),
        )
        self._health_event(first)
        for status in ("ACTIVE", "HEALTH_ALERT"):
            moved = self.client.post(
                f"/api/production/batches/{second['business_id']}/status",
                json={"status": status, "reason": "Mites found"},
            )
            self.assertEqual(moved.status_code, 200, moved.get_json())

        alerts = self._alerts()
        overdue = self._by_rule(alerts, "harvest_overdue")
        self.assertEqual(len(overdue), 1)
        self.assertEqual((overdue[0]["entity_id"], overdue[0]["severity"]), (first["id"], "critical"))
        self.assertEqual(overdue[0]["href"], f"/batch-360?ref={first['business_id']}")
        self.assertEqual(
            [(a["entity_id"], a["severity"]) for a in self._by_rule(alerts, "harvest_due")],
            [(second["id"], "info")],
        )
        self.assertEqual(self._by_rule(alerts, "health_issue_open")[0]["severity"], "critical")
        self.assertEqual(
            [a["entity_id"] for a in self._by_rule(alerts, "batch_health_alert")], [second["id"]]
        )

        # A second evaluation must not duplicate anything.
        self.assertEqual(len(self._alerts()), len(alerts))

        db.execute_query(
            "UPDATE production_batches SET expected_harvest_at = now() + interval '10 days' WHERE id = %s",
            (first["id"],),
        )
        alerts = self._alerts()
        resolved = self._by_rule(alerts, "harvest_overdue")
        self.assertEqual([a["status"] for a in resolved], ["RESOLVED"])
        self.assertEqual(resolved[0]["resolved_reason"], "Condition cleared")
        self.assertNotIn(
            first["id"], [a["entity_id"] for a in self._by_rule(alerts, "harvest_due", "OPEN")]
        )

        batch360 = self._get_360(second["business_id"]).get_json()["data"]
        self.assertIn("batch_health_alert", [a["rule"] for a in batch360["alerts"]])

    def test_qc_pending_turns_into_qc_failed(self):
        drying_ref, output = self._create_output_for_product_lot()
        db.execute_query(
            """
            UPDATE drying_batch_status_history SET changed_at = now() - interval '2 days'
            WHERE new_status = 'QC_PENDING' AND drying_batch_id = (
                SELECT id FROM drying_batches WHERE business_id = %s)
            """,
            (drying_ref,),
        )
        pending = self._by_rule(self._alerts(), "qc_pending", "OPEN")
        self.assertEqual(len(pending), 1)
        self.assertIn("hours", pending[0]["message"])

        failed = self._create_output_quality_check(output, status="failed")
        self.assertEqual(failed.status_code, 201, failed.get_json())
        alerts = self._alerts()
        self.assertEqual(len(self._by_rule(alerts, "qc_failed", "OPEN")), 1)
        self.assertEqual([a["status"] for a in self._by_rule(alerts, "qc_pending")], ["RESOLVED"])

    def test_stock_order_and_delivery_alerts(self):
        lot = self._release_lot()
        admin = self._create_db_user()
        admin.role = "super_admin"
        with self._as(admin):
            threshold = self.client.put(
                "/api/alerts/thresholds",
                json={"farm_id": self.farm_id, "product_type": "dried_larvae", "minimum_kg": "1.000"},
            )
        self.assertEqual(threshold.status_code, 200, threshold.get_json())
        response = self.client.post(
            "/api/orders",
            json={
                "customer_id": self._customer(), "farm_id": self.farm_id,
                "order_date": "2026-09-01", "requested_delivery_date": "2026-09-02",
                "lines": [{"product_type": "dried_larvae", "quantity_kg": "0.500"}],
            },
        )
        order = response.get_json()["data"]
        allocation = self._allocate(order, lot, "0.200").get_json()["data"]["allocations"][0]
        dispatched = self._dispatch(order, allocation["id"], "0.200")
        delivery_ref = dispatched.get_json()["data"]["created_delivery"]
        db.execute_query(
            "UPDATE customer_deliveries SET dispatched_at = now() - interval '3 days' WHERE business_id = %s",
            (delivery_ref,),
        )

        alerts = self._alerts()
        low = self._by_rule(alerts, "low_stock", "OPEN")
        self.assertEqual(len(low), 1)
        self.assertEqual(low[0]["severity"], "warning")
        self.assertIn("0.4 kg free", low[0]["message"])
        self.assertEqual(self._by_rule(alerts, "order_overdue", "OPEN")[0]["severity"], "critical")
        self.assertEqual(
            self._by_rule(alerts, "delivery_unconfirmed", "OPEN")[0]["entity_ref"], delivery_ref
        )

        db.execute_query(
            """
            INSERT INTO quality_approvals (quality_check_id, decision, rationale, approver)
            SELECT quality_check_id, 'revoked', 'Recall', %s FROM quality_approvals WHERE id = %s
            """,
            (self.actor, lot_release_approval_id(lot)),
        )
        alerts = self._alerts()
        self.assertEqual(
            [a["entity_id"] for a in self._by_rule(alerts, "quarantined_stock", "OPEN")], [lot["id"]]
        )
        self.assertEqual(self._by_rule(alerts, "low_stock", "OPEN")[0]["severity"], "critical")

        confirmed = self.client.post(
            f"/api/deliveries/{delivery_ref}/confirm", json={"received_by": "Stores"}
        )
        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(
            [a["status"] for a in self._by_rule(self._alerts(), "delivery_unconfirmed")], ["RESOLVED"]
        )

    def test_alert_acknowledge_snooze_and_escalation(self):
        response = self.client.post(
            "/api/orders",
            json={
                "customer_id": self._customer(), "farm_id": self.farm_id,
                "order_date": "2026-09-01", "requested_delivery_date": str(date.today() - timedelta(days=1)),
                "lines": [{"product_type": "dried_larvae", "quantity_kg": "1"}],
            },
        )
        order = response.get_json()["data"]
        alert = self._by_rule(self._alerts(), "order_overdue", "OPEN")[0]
        self.assertEqual(alert["severity"], "warning")

        ack = self.client.post(f"/api/alerts/{alert['id']}/acknowledge", json={"note": "Customer informed"})
        self.assertEqual(ack.status_code, 200, ack.get_json())
        self.assertEqual(
            self.client.post(f"/api/alerts/{alert['id']}/acknowledge", json={}).status_code, 409
        )
        still = self._by_rule(self._alerts(), "order_overdue")
        self.assertEqual([(a["id"], a["status"]) for a in still], [(alert["id"], "ACKNOWLEDGED")])
        self.assertEqual(still[0]["acknowledgement_note"], "Customer informed")

        db.execute_query(
            "UPDATE customer_orders SET requested_delivery_date = CURRENT_DATE - 5 WHERE id = %s",
            (order["id"],),
        )
        escalated = self._by_rule(self._alerts(), "order_overdue")[0]
        self.assertEqual((escalated["id"], escalated["status"], escalated["severity"]),
                         (alert["id"], "OPEN", "critical"))

        self.assertEqual(
            self.client.post(f"/api/alerts/{alert['id']}/snooze", json={"hours": 0}).status_code, 400
        )
        snoozed = self.client.post(f"/api/alerts/{alert['id']}/snooze", json={"hours": 24})
        self.assertEqual(snoozed.status_code, 200, snoozed.get_json())
        self.assertEqual(self._by_rule(self._alerts(), "order_overdue")[0]["status"], "SNOOZED")
        db.execute_query(
            "UPDATE operational_alerts SET snoozed_until = now() - interval '1 minute' WHERE id = %s",
            (alert["id"],),
        )
        self.assertEqual(self._by_rule(self._alerts(), "order_overdue")[0]["status"], "OPEN")

    def test_alert_visibility_and_threshold_permissions(self):
        created = self._create_production(self._create_substrate()).get_json()["record"]
        db.execute_query(
            "UPDATE production_batches SET expected_harvest_at = now() - interval '1 day' WHERE id = %s",
            (created["id"],),
        )
        self.client.post(
            "/api/orders",
            json={"customer_id": self._customer(), "farm_id": self.farm_id,
                  "order_date": "2026-09-01", "requested_delivery_date": "2026-09-02",
                  "lines": [{"product_type": "dried_larvae", "quantity_kg": "1"}]},
        )
        alerts = self._alerts("active")
        production_alert = self._by_rule(alerts, "harvest_overdue")[0]
        order_alert = self._by_rule(alerts, "order_overdue")[0]

        outsider = self._create_db_user(farm_access=False)
        facility_only = self._create_db_user(farm_access=False)
        db.execute_query(
            "INSERT INTO user_facility_access (user_id, facility_id) VALUES (%s, %s)",
            (facility_only.id, self.facility_id),
        )
        with self._as(outsider):
            outsider_ids = [a["id"] for a in self.client.get("/api/alerts").get_json()["data"]]
            outsider_ack = self.client.post(f"/api/alerts/{production_alert['id']}/acknowledge", json={})
            threshold = self.client.put(
                "/api/alerts/thresholds",
                json={"farm_id": self.farm_id, "product_type": "x", "minimum_kg": "1"},
            )
        with self._as(facility_only):
            facility_ids = [a["id"] for a in self.client.get("/api/alerts").get_json()["data"]]
            summary = self.client.get("/api/alerts/summary").get_json()["counts"]
        self.assertNotIn(production_alert["id"], outsider_ids)
        self.assertNotIn(order_alert["id"], outsider_ids)
        self.assertEqual(outsider_ack.status_code, 404)
        self.assertEqual(threshold.status_code, 403)
        self.assertIn(production_alert["id"], facility_ids)
        self.assertNotIn(order_alert["id"], facility_ids)
        self.assertGreaterEqual(summary["open"], 1)
        self.assertEqual(self.client.get("/alerts").status_code, 200)

    # ---- Notifications -----------------------------------------------------------

    def _notifications_for(self, user):
        return db.fetch_all(
            "SELECT kind, severity, title, read_at FROM notifications WHERE user_id = %s ORDER BY id",
            (user.id,),
        )

    def _overdue_batch(self, days):
        created = self._create_production(self._create_substrate()).get_json()["record"]
        self._set_expected(created, days)
        return created

    def _set_expected(self, batch, days_ago):
        db.execute_query(
            "UPDATE production_batches SET expected_harvest_at = now() - make_interval(days => %s) WHERE id = %s",
            (days_ago, batch["id"]),
        )

    def test_alert_notifications_reach_the_right_people_once(self):
        farm_user = self._create_db_user()
        facility_user = self._create_db_user(farm_access=False)
        db.execute_query(
            "INSERT INTO user_facility_access (user_id, facility_id) VALUES (%s, %s)",
            (facility_user.id, self.facility_id),
        )
        outsider = self._create_db_user(farm_access=False)
        critical_only = self._create_db_user()
        db.execute_query(
            "INSERT INTO notification_preferences (user_id, in_app_min_severity) VALUES (%s, 'critical')",
            (critical_only.id,),
        )
        batch = self._overdue_batch(1)
        self._alerts()

        self.assertEqual([n["kind"] for n in self._notifications_for(farm_user)], ["alert_opened"])
        self.assertEqual([n["severity"] for n in self._notifications_for(facility_user)], ["warning"])
        self.assertEqual(self._notifications_for(outsider), [])
        self.assertEqual(self._notifications_for(critical_only), [])

        self._set_expected(batch, 4)
        self._alerts()
        self._alerts()  # re-evaluating must not repeat notifications
        self.assertEqual(
            [(n["kind"], n["severity"]) for n in self._notifications_for(farm_user)],
            [("alert_opened", "warning"), ("alert_escalated", "critical")],
        )
        self.assertEqual(
            [n["kind"] for n in self._notifications_for(critical_only)], ["alert_escalated"]
        )

        alert = self._by_rule(self._alerts(), "harvest_overdue")[0]
        self.client.post(f"/api/alerts/{alert['id']}/snooze", json={"hours": 4})
        db.execute_query(
            "UPDATE operational_alerts SET snoozed_until = now() - interval '1 minute' WHERE id = %s",
            (alert["id"],),
        )
        self._alerts()
        self.assertEqual(self._notifications_for(farm_user)[-1]["kind"], "alert_reminder")

        with self._as(farm_user):
            inbox = self.client.get("/api/notifications").get_json()
            count = self.client.get("/api/notifications/unread-count").get_json()
            first_id = inbox["data"][0]["id"]
            read = self.client.post(f"/api/notifications/{first_id}/read")
            after = self.client.get("/api/notifications/unread-count").get_json()
            all_read = self.client.post("/api/notifications/read-all").get_json()
        self.assertEqual(inbox["unread"], 3)
        self.assertTrue(inbox["data"][0]["title"].startswith("Snooze ended"))
        self.assertEqual(inbox["data"][0]["href"], f"/batch-360?ref={batch['business_id']}")
        self.assertEqual((count["unread"], count["critical"]), (3, 2))
        self.assertEqual(read.status_code, 200)
        self.assertEqual(after["unread"], 2)
        self.assertEqual(all_read["updated"], 2)
        with self._as(outsider):
            stolen = self.client.post(f"/api/notifications/{first_id}/read")
            self.assertEqual(self.client.get("/api/notifications").get_json()["data"], [])
        self.assertEqual(stolen.status_code, 404)

    def test_email_outbox_retries_and_redacts_errors(self):
        channel = _FakeEmailChannel(fail_times=1)
        farm_user = self._create_db_user()
        db.execute_query(
            "INSERT INTO notification_preferences (user_id, email_min_severity) VALUES (%s, 'warning')",
            (farm_user.id,),
        )
        with patch.object(notifications, "channel_factory", lambda: channel), \
                patch.object(notifications, "background_delivery_enabled", False):
            self._overdue_batch(1)
            self._alerts()
            outbox = db.fetch_all(
                "SELECT id, status, recipient FROM notification_outbox WHERE user_id = %s",
                (farm_user.id,),
            )
            self.assertEqual(len(outbox), 1)
            first = notifications.deliver_pending(db, channel=channel)
            row = db.fetch_one("SELECT * FROM notification_outbox WHERE id = %s", (outbox[0]["id"],))
            self.assertEqual((first["retry"], row["status"], row["attempts"]), (1, "PENDING", 1))
            self.assertIn("temporary failure", row["last_error"])
            self.assertEqual(notifications.deliver_pending(db, channel=channel)["sent"], 0)  # backing off
            db.execute_query(
                "UPDATE notification_outbox SET next_attempt_at = now() WHERE id = %s", (outbox[0]["id"],)
            )
            self.assertEqual(notifications.deliver_pending(db, channel=channel)["sent"], 1)
        row = db.fetch_one("SELECT status, sent_at FROM notification_outbox WHERE id = %s", (outbox[0]["id"],))
        self.assertEqual(row["status"], "SENT")
        recipient, subject, body = channel.sent[-1]
        self.assertEqual(recipient, outbox[0]["recipient"])
        self.assertIn("[Zehunger WARNING]", subject)
        self.assertIn("/batch-360?ref=", body)

        broken = _FakeEmailChannel(fail_times=99, error="login failed for secret-pass-123")
        db.execute_query(
            """
            INSERT INTO notification_outbox (user_id, recipient, subject, body)
            VALUES (%s, 'nobody@example.test', 'x', 'y')
            """,
            (farm_user.id,),
        )
        with patch.object(notifications.config, "EMAIL_HOST_PASSWORD", "secret-pass-123"):
            for _ in range(notifications.EMAIL_MAX_ATTEMPTS):
                db.execute_query(
                    "UPDATE notification_outbox SET next_attempt_at = now() WHERE status = 'PENDING' AND user_id = %s",
                    (farm_user.id,),
                )
                notifications.deliver_pending(db, channel=broken)
        failed = db.fetch_one(
            "SELECT status, attempts, last_error FROM notification_outbox WHERE recipient = 'nobody@example.test'"
        )
        self.assertEqual((failed["status"], failed["attempts"]), ("FAILED", notifications.EMAIL_MAX_ATTEMPTS))
        self.assertNotIn("secret-pass-123", failed["last_error"])
        self.assertIn("***", failed["last_error"])

    def test_unconfigured_email_keeps_in_app_only(self):
        farm_user = self._create_db_user()
        db.execute_query(
            "INSERT INTO notification_preferences (user_id, email_min_severity) VALUES (%s, 'info')",
            (farm_user.id,),
        )
        unconfigured = _FakeEmailChannel(configured=False)
        with patch.object(notifications, "channel_factory", lambda: unconfigured):
            self._overdue_batch(1)
            self._alerts()
            stats = notifications.deliver_pending(db)
        self.assertEqual(len(self._notifications_for(farm_user)), 1)
        self.assertEqual(
            db.fetch_one("SELECT COUNT(*) AS n FROM notification_outbox WHERE user_id = %s", (farm_user.id,))["n"],
            0,
        )
        self.assertTrue(stats["skipped_unconfigured"])

    def test_notification_preferences_and_admin_endpoints(self):
        user = self._create_db_user()
        admin = self._create_db_user()
        admin.role = "super_admin"
        with self._as(user):
            defaults = self.client.get("/api/notifications/preferences").get_json()["data"]
            bad = self.client.put("/api/notifications/preferences",
                                  json={"in_app_min_severity": "loud", "email_min_severity": "off"})
            good = self.client.put("/api/notifications/preferences",
                                   json={"in_app_min_severity": "info", "email_min_severity": "off"})
            status_denied = self.client.get("/api/notifications/email-status")
            test_denied = self.client.post("/api/notifications/test-email")
        self.assertEqual((defaults["in_app_min_severity"], defaults["email_min_severity"]), ("warning", "critical"))
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(good.get_json()["data"]["in_app_min_severity"], "info")
        self.assertEqual((status_denied.status_code, test_denied.status_code), (403, 403))
        with self._as(admin), patch.object(
            notifications, "channel_factory", lambda: _FakeEmailChannel(configured=False)
        ):
            status = self.client.get("/api/notifications/email-status")
            test = self.client.post("/api/notifications/test-email")
        self.assertEqual(status.status_code, 200)
        self.assertFalse(status.get_json()["data"]["configured"])
        self.assertEqual(test.status_code, 400)
        self.assertIn("not configured", test.get_json()["message"])

    def test_scheduled_job_evaluates_alerts_and_sends_email(self):
        from backend import jobs

        channel = _FakeEmailChannel()
        farm_user = self._create_db_user()
        db.execute_query(
            "INSERT INTO notification_preferences (user_id, email_min_severity) VALUES (%s, 'warning')",
            (farm_user.id,),
        )
        self._overdue_batch(1)
        db.execute_query("UPDATE operational_alert_sync SET last_run_at = NULL")
        with patch.object(notifications, "channel_factory", lambda: channel), \
                patch.object(notifications, "background_delivery_enabled", False):
            ran, stats = jobs.run_once()
        self.assertTrue(ran)
        self.assertGreaterEqual(stats["sent"], 1)
        self.assertIn(farm_user.username, [r.split("@")[0] for r, _s, _b in channel.sent])

    # ---- Setup and gap fixes -----------------------------------------------------

    def _admin(self):
        admin = self._create_db_user()
        admin.role = "super_admin"
        return admin

    def _second_facility(self, kind="drying"):
        return db.execute_returning(
            """
            INSERT INTO facilities (site_id, facility_code, name, facility_type)
            VALUES (%s, %s, 'Drying Facility', %s) RETURNING id
            """,
            (self.site_id, f"d{uuid4().hex[:10]}", kind),
        )["id"]

    def _ready_harvest(self):
        substrate_id = self._create_substrate()
        batch = self._create_production(substrate_id, harvest_limit_kg="2.000").get_json()["record"]
        self._move_to_harvest_ready(batch)
        harvest = self._harvest(batch, wet_weight="1.000")
        self.assertEqual(harvest.status_code, 201, harvest.get_json())
        return harvest.get_json()["harvest"]["id"]

    def _drying_at(self, facility_id, harvest_id, farm_id=None, site_id=None):
        return self.client.post(
            "/api/drying/batches",
            json={
                "batch_code": f"dry-{uuid4().hex[:15]}",
                "drying_date": "2026-09-25",
                "drying_method": "solar",
                "personnel": self.actor,
                "farm_id": farm_id or self.farm_id,
                "site_id": site_id or self.site_id,
                "facility_id": facility_id,
                "inputs": [{"harvest_id": harvest_id, "quantity": "0.500", "unit": "kg"}],
            },
        )

    def test_drying_can_use_another_facility_on_the_same_farm_only(self):
        harvest_id = self._ready_harvest()
        drying_facility = self._second_facility()
        moved = self._drying_at(drying_facility, harvest_id)
        self.assertEqual(moved.status_code, 201, moved.get_json())

        other = self._create_other_farm_location()  # registers its own cleanup
        other_scope = db.fetch_one(
            "SELECT farm_id, site_id, facility_id FROM inventory_locations WHERE id = %s", (other,)
        )
        cross_farm = self._drying_at(
            other_scope["facility_id"], harvest_id,
            farm_id=other_scope["farm_id"], site_id=other_scope["site_id"],
        )
        self.assertEqual(cross_farm.status_code, 400, cross_farm.get_json())
        self.assertIn("same farm", cross_farm.get_json()["message"])

        dryer_only = self._create_db_user(farm_access=False)
        db.execute_query(
            "INSERT INTO user_facility_access (user_id, facility_id) VALUES (%s, %s)",
            (dryer_only.id, drying_facility),
        )
        with self._as(dryer_only):
            denied = self._drying_at(drying_facility, harvest_id)
        self.assertEqual(denied.status_code, 403, denied.get_json())

    def test_record_links_are_admin_only(self):
        member = self._create_db_user()
        payload = {"entity_table": "waste_sourcing", "entity_id": 1, "facility_id": self.facility_id}
        with self._as(member):
            self.assertEqual(self.client.post("/api/locations/record-links", json=payload).status_code, 403)
        with self._as(self._admin()):
            response = self.client.post("/api/locations/record-links", json=payload)
        self.assertIn(response.status_code, (200, 201, 404), response.get_json())

    def test_deactivation_blocks_new_work_and_protects_stock(self):
        admin = self._admin()
        member = self._create_db_user()
        lot = self._release_lot()  # issues 4 of the substrate's 8 kg
        substrate_id = self.substrate_ids[-1]
        with self._as(member):
            denied = self.client.post(
                f"/api/locations/facility/{self.facility_id}/status", json={"status": "inactive"}
            )
        self.assertEqual(denied.status_code, 403)
        with self._as(admin):
            off = self.client.post(
                f"/api/locations/facility/{self.facility_id}/status", json={"status": "inactive"}
            )
        self.assertEqual(off.get_json()["data"]["status"], "inactive")
        blocked = self._create_production(substrate_id)
        self.assertEqual(blocked.status_code, 400, blocked.get_json())
        self.assertIn("ownership is invalid", blocked.get_json()["message"])
        with self._as(admin):
            self.client.post(f"/api/locations/facility/{self.facility_id}/status", json={"status": "active"})

        listing = self.client.get(f"/api/substrate-batches?facility_id={self.facility_id}").get_json()["data"]
        self.assertAlmostEqual(next(s for s in listing if s["id"] == substrate_id)["available_kg"], 4.0)

        empty_store = self._add_inventory_location("EMPTY")
        with self._as(admin):
            in_use = self.client.post(
                f"/api/inventory/locations/{self.inventory_location_id}/status", json={"status": "inactive"}
            )
            emptied = self.client.post(
                f"/api/inventory/locations/{empty_store}/status", json={"status": "inactive"}
            )
            page = self.client.get("/setup")
        self.assertEqual(in_use.status_code, 400, in_use.get_json())
        self.assertIn("Move the stock out", in_use.get_json()["message"])
        self.assertEqual(emptied.status_code, 200, emptied.get_json())
        self.assertEqual(page.status_code, 200)
        moved = self._move(
            lot, "TRANSFER", "0.100",
            from_location_id=self.inventory_location_id, to_location_id=empty_store,
        )
        self.assertEqual(moved.status_code, 400, moved.get_json())
        self.assertIn("inactive", moved.get_json()["message"])
        with self._as(member):
            self.assertEqual(self.client.get("/setup").status_code, 403)

    # ---- Reports -----------------------------------------------------------------

    def _report(self, key, **params):
        params.setdefault("farm_id", self.farm_id)
        query = "&".join(f"{k}={v}" for k, v in params.items())
        response = self.client.get(f"/api/reports/{key}?{query}")
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def _sold_lot(self):
        lot = self._release_lot()
        order = self._order("0.300")
        allocation = self._allocate(order, lot, "0.200").get_json()["data"]["allocations"][0]
        dispatched = self._dispatch(order, allocation["id"], "0.200")
        self.assertEqual(dispatched.status_code, 201, dispatched.get_json())
        return lot, order

    def test_reports_follow_the_chain_with_consistent_totals(self):
        lot, order = self._sold_lot()
        totals = {key: self._report(key)["totals"] for key in (
            "waste_received", "substrate", "production_batches", "harvest", "drying", "inventory",
            "sales", "deliveries",
        )}
        self.assertAlmostEqual(totals["waste_received"]["received_kg"], 10.0)
        self.assertAlmostEqual(totals["waste_received"]["used_kg"], 8.0)
        self.assertAlmostEqual(totals["substrate"]["issued_kg"], 4.0)
        self.assertAlmostEqual(totals["production_batches"]["harvested_kg"], 1.5)
        self.assertAlmostEqual(totals["harvest"]["sent_to_drying_kg"], 1.2)
        self.assertAlmostEqual(totals["drying"]["dry_out_kg"], 0.6)
        self.assertAlmostEqual(totals["inventory"]["on_hand_kg"], 0.4)
        self.assertAlmostEqual(totals["sales"]["ordered_kg"], 0.3)
        self.assertAlmostEqual(totals["sales"]["dispatched_kg"], 0.2)
        self.assertAlmostEqual(totals["deliveries"]["quantity_kg"], 0.2)

        drying = self._report("drying")["data"][0]
        self.assertAlmostEqual(drying["yield_pct"], 50.0)
        quality = self._report("quality")["data"][0]
        self.assertEqual((quality["result"], quality["decision"]), ("PASSED", "APPROVED"))
        lineage = self._report("traceability")["data"][0]
        waste_ref = db.fetch_one("SELECT business_id FROM waste_lots WHERE id = %s", (self.waste_lot_id,))["business_id"]
        self.assertEqual(lineage["product_lot"], lot["business_id"])
        self.assertEqual(lineage["waste_lots"], waste_ref)
        self.assertEqual(lineage["customers"], self.marker)
        farm = self._report("farm_performance")["data"]
        self.assertEqual(len(farm), 1)
        self.assertAlmostEqual(farm[0]["harvested_kg"], 1.5)
        self.assertAlmostEqual(farm[0]["dispatched_kg"], 0.2)
        self.assertAlmostEqual(farm[0]["drying_yield_pct"], 50.0)

        empty = self._report("harvest", date_from="2000-01-01", date_to="2000-01-31")
        self.assertEqual(empty["row_count"], 0)
        planned = self._report("production_batches", status="PLANNED")
        self.assertEqual(planned["row_count"], 0)

    def test_reports_respect_location_and_commercial_access(self):
        self._sold_lot()
        outsider = self._create_db_user(farm_access=False)
        facility_only = self._create_db_user(farm_access=False)
        db.execute_query(
            "INSERT INTO user_facility_access (user_id, facility_id) VALUES (%s, %s)",
            (facility_only.id, self.facility_id),
        )
        with self._as(outsider):
            outsider_counts = {k: self._report(k)["row_count"] for k in ("harvest", "inventory", "sales", "traceability")}
        with self._as(facility_only):
            harvest = self._report("harvest")["row_count"]
            sales = self._report("sales")["row_count"]
            farm = self._report("farm_performance")["row_count"]
            lineage = self._report("traceability")["data"][0]["customers"]
        self.assertEqual(outsider_counts, {"harvest": 0, "inventory": 0, "sales": 0, "traceability": 0})
        self.assertEqual((harvest, sales, farm), (1, 0, 0))
        self.assertEqual(lineage, "restricted")

    def test_report_validation_and_safe_csv(self):
        response = self.client.post(
            "/api/waste-sourcing",
            json={**{k: v for k, v in {
                "collection_date": "2026-09-24", "collection_time": "09:30",
                "source_type": "market", "source_name": '=HYPERLINK("http://x")',
                "waste_type": "vegetable", "waste_weight": "1", "segregation_status": "organic",
                "collection_personnel": "Integration test", "lot_status": "available",
                "contaminants_found": [],
            }.items()}, "farm_id": self.farm_id, "site_id": self.site_id, "facility_id": self.facility_id},
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        self.addCleanup(db.execute_query,
                        "DELETE FROM waste_sourcing WHERE source_name = %s", ('=HYPERLINK("http://x")',))
        csv_response = self.client.get(f"/api/reports/waste_received?farm_id={self.farm_id}&format=csv")
        self.assertEqual(csv_response.status_code, 200)
        self.assertIn("attachment", csv_response.headers["Content-Disposition"])
        body = csv_response.get_data(as_text=True)
        self.assertTrue(body.startswith("﻿Date,Waste lot"))
        self.assertIn("'=HYPERLINK", body)

        bad_dates = self.client.get("/api/reports/harvest?date_from=2026-10-02&date_to=2026-10-01")
        bad_status = self.client.get("/api/reports/drying?status=BURNT")
        self.assertEqual((bad_dates.status_code, bad_status.status_code), (400, 400))
        self.assertEqual(self.client.get("/api/reports/unknown").status_code, 404)
        catalog = self.client.get("/api/reports").get_json()["data"]
        self.assertEqual(len(catalog), 12)
        self.assertEqual(self.client.get("/analytics").status_code, 200)

    # ---- Operations dashboard ----------------------------------------------------

    def _make_chain_recent(self):
        """The chain fixtures use fixed dates; move them into the last week."""
        for statement in (
            "UPDATE waste_lots SET collection_date = CURRENT_DATE - 2 WHERE farm_id = %s",
            "UPDATE substrate_batches SET preparation_date = CURRENT_DATE - 2 WHERE farm_id = %s",
            "UPDATE production_events SET occurred_at = now() - interval '1 day' WHERE farm_id = %s",
            """UPDATE drying_outputs SET output_date = now() - interval '1 day'
               WHERE drying_batch_id IN (SELECT id FROM drying_batches WHERE farm_id = %s)""",
            "UPDATE drying_batches SET drying_date = CURRENT_DATE - 1 WHERE farm_id = %s",
            "UPDATE product_lots SET production_date = CURRENT_DATE - 1 WHERE farm_id = %s",
            "UPDATE inventory_movements SET occurred_at = now() - interval '1 hour' WHERE farm_id = %s",
        ):
            db.execute_query(statement, (self.farm_id,))

    def _dashboard(self, **params):
        params.setdefault("days", 7)
        params.setdefault("farm_id", self.farm_id)
        query = "&".join(f"{k}={v}" for k, v in params.items())
        response = self.client.get(f"/api/dashboard?{query}")
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()["data"]

    def test_dashboard_reflects_the_chain(self):
        lot, order = self._sold_lot()
        self._make_chain_recent()
        data = self._dashboard()
        k = data["kpis"]
        self.assertAlmostEqual(k["harvested_kg"], 1.5)
        self.assertAlmostEqual(k["dried_kg"], 0.6)
        self.assertAlmostEqual(k["released_kg"], 0.6)
        self.assertAlmostEqual(k["stock_on_hand_kg"], 0.4)
        self.assertAlmostEqual(k["stock_available_kg"], 0.4)
        self.assertAlmostEqual(k["substrate_available_kg"], 4.0)
        self.assertEqual(k["ready_for_harvest"], 1)
        flow = {f["stage"]: f["kg"] for f in data["flow"]}
        self.assertAlmostEqual(flow["Waste received"], 10.0)
        self.assertAlmostEqual(flow["Dispatched"], 0.2)
        self.assertEqual(len(data["trend"]["buckets"]), 7)
        self.assertFalse(data["trend"]["weekly"])
        sums = {s["name"]: sum(s["values"]) for s in data["trend"]["series"]}
        self.assertAlmostEqual(sums["Harvested (wet)"], 1.5)
        self.assertAlmostEqual(sums["Dispatched"], 0.2)
        commercial = data["commercial"]
        self.assertEqual(commercial["open_orders"], 1)
        self.assertAlmostEqual(commercial["outstanding_kg"], 0.1)
        self.assertEqual(commercial["in_transit"], 1)
        self.assertTrue(self._dashboard(days=90)["trend"]["weekly"])

        by_facility = self._dashboard(days=7, facility_id=self.facility_id)
        self.assertAlmostEqual(by_facility["kpis"]["harvested_kg"], 1.5)

    def test_dashboard_scope_and_validation(self):
        self._sold_lot()
        self._make_chain_recent()
        outsider = self._create_db_user(farm_access=False)
        facility_only = self._create_db_user(farm_access=False)
        db.execute_query(
            "INSERT INTO user_facility_access (user_id, facility_id) VALUES (%s, %s)",
            (facility_only.id, self.facility_id),
        )
        with self._as(outsider):
            nothing = self._dashboard()
        with self._as(facility_only):
            ops_only = self._dashboard()
        self.assertEqual(nothing["kpis"]["harvested_kg"], 0)
        self.assertEqual(nothing["kpis"]["stock_on_hand_kg"], 0)
        self.assertIsNone(nothing["commercial"])
        self.assertAlmostEqual(ops_only["kpis"]["harvested_kg"], 1.5)
        self.assertIsNone(ops_only["commercial"])
        self.assertEqual(self.client.get("/api/dashboard?days=12").status_code, 400)
        self.assertEqual(self.client.get("/api/dashboard?farm_id=abc").status_code, 400)
        self.assertEqual(self.client.get("/operations").status_code, 200)


def lot_release_approval_id(lot):
    row = db.fetch_one(
        "SELECT release_approval_id FROM product_lots WHERE id = %s", (lot["id"],)
    )
    return row["release_approval_id"]


class _UserContext:
    """Run requests as ``user`` with real login checks enabled."""

    def __init__(self, user):
        self._patches = [
            patch.dict(app.config, {"LOGIN_DISABLED": False}),
            patch("backend.app.current_user", user),
            patch("backend.location_routes.current_user", user),
            patch("flask_login.utils.current_user", user),
        ]

    def __enter__(self):
        for item in self._patches:
            item.__enter__()
        return self

    def __exit__(self, *exc):
        for item in reversed(self._patches):
            item.__exit__(*exc)


def _parse_iso(value):
    from datetime import datetime

    return datetime.fromisoformat(value)


class _FakeEmailChannel:
    """Records sends instead of talking to SMTP; can fail a set number of times."""

    def __init__(self, *, configured=True, fail_times=0, error="temporary failure"):
        self.configured = configured
        self.fail_times = fail_times
        self.error = error
        self.sent = []

    def send(self, recipient, subject, body):
        if self.fail_times > 0:
            self.fail_times -= 1
            raise ConnectionError(self.error)
        self.sent.append((recipient, subject, body))
