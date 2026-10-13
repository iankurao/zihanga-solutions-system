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
                cursor.execute("DELETE FROM facilities WHERE id = %s", (self.facility_id,))
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
            patch("flask_login.utils.current_user", user),
        ]

    def __enter__(self):
        for item in self._patches:
            item.__enter__()
        return self

    def __exit__(self, *exc):
        for item in reversed(self._patches):
            item.__exit__(*exc)
