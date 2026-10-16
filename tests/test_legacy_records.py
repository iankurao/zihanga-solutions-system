"""Legacy (pre-traceability) records: read-only history.

Every form that wrote a record without a farm, site and facility is retired:
hatchery, fly facility and waste-handling logs moved to /api/farm-operations
(test_farm_operations.py), drying to the scoped drying API, and sales to
customer orders. What remains here: the retired write routes are really gone,
legacy reads are for super admins only, and the larval feeding routes record
canonical production events.
"""
from uuid import uuid4

from support import ScenarioTestCase, db, requires_database

D = "2026-09-20"

# Write routes retired because their records had no farm, site and facility.
RETIRED = [
    ("POST", url) for url in (
        "/api/waste-monitoring", "/api/storage-records", "/api/processing-records",
        "/api/facility/cage-monitoring", "/api/facility/maintenance", "/api/facility/pupae-transition",
        "/api/facility/egg-collection", "/api/facility/bait-preparation",
        "/api/fly-facility/cage-monitoring", "/api/fly-facility/maintenance", "/api/fly-facility/pupae-transition",
        "/api/fly-facility/egg-collection", "/api/fly-facility/bait-preparation",
        "/api/hatchery/batch", "/api/hatchery/batch-information", "/api/hatchery/feeding",
        "/api/hatchery/feeding-records", "/api/hatchery/monitoring", "/api/hatchery/environmental-monitoring",
        "/api/hatchery/cleaning", "/api/hatchery/problems", "/api/hatchery/health",
        "/api/drying/batch", "/api/drying/input", "/api/drying/output", "/api/drying/qc",
        "/api/drying/quality-control", "/api/drying/remarks", "/api/drying/review",
        "/api/sales", "/api/deliveries", "/api/feedback",
    )
] + [("PUT", f"/api/{name}/1") for name in ("sales", "deliveries", "feedback")] + [
    ("GET", "/api/hatchery/next-batch-id"),
]

LEGACY_READS = [
    "/api/statistics/waste-processing", "/api/statistics/environmental", "/api/statistics/larval-growth",
    "/api/statistics/system-efficiency", "/api/statistics/daily-report", "/api/statistics/harvest-efficiency",
    "/api/waste-sourcing/all", "/api/drying/input/all", "/api/drying/output/all", "/api/drying/qc/all",
    "/api/drying/remarks/all", "/api/drying/review/all", "/api/feeding/harvest/all",
    "/api/records?date=2026-09-20&section=all", "/api/sales", "/api/deliveries", "/api/feedback",
    "/api/waste-sourcing", "/api/storage-records", "/api/processing-records", "/api/environmental-monitoring",
] + [f"/api/analytics/{name}" for name in (
    "waste-sourcing", "storage-records", "processing-records", "waste-monitoring", "waste-env-monitoring",
    "hatchery-batches", "hatchery-feeding", "hatchery-monitoring", "larvae-env-monitoring",
    "substrate-preparation", "health-intervention", "harvest-yield", "feeding-schedule", "cage-monitoring",
    "facility-maintenance", "pupae-transition", "egg-collection", "bait-preparation", "drying-batches",
    "customers", "sales", "deliveries", "feedback")]


@requires_database
class LegacyRecordsTest(ScenarioTestCase):

    def setUp(self):
        super().setUp()
        place = self.place = self.make_farm()
        self.operator = self.make_user("operator", access=[("farm", place["farm"]["id"])])
        self.viewer = self.make_user("viewer", access=[("farm", place["farm"]["id"])])
        tables = {"sales", "deliveries", "customer_feedback", "waste_monitoring"}
        before = {table: db.fetch_one(f"SELECT COALESCE(MAX(id), 0) AS id FROM {table}")["id"] for table in tables}
        for table, last_id in before.items():
            self.addCleanup(db.execute_query, f"DELETE FROM {table} WHERE id > %s", (last_id,))

    def test_retired_write_routes_are_gone(self):
        for method, url in RETIRED:
            with self.subTest(method=method, url=url):
                response = self.admin.client.open(url, method=method, json={}, base_url="https://localhost")
                self.assertIn(response.status_code, (404, 405), (method, url, response.status_code))

    def test_harvest_report_email_is_admin_only(self):
        from unittest.mock import patch

        with patch("backend.domains.legacy.send_email") as send:
            self.assertEqual(self.operator.post("/api/send-harvest-report").status_code, 403)
            sent = self.admin.post("/api/send-harvest-report")
        self.assertEqual(sent.status_code, 200, sent.get_json())
        send.assert_called_once()
        subject, body, recipient = send.call_args.args
        self.assertIn("Harvest Yield Report", subject)

    def test_legacy_reads_are_super_admin_only(self):
        for url in LEGACY_READS:
            with self.subTest(url=url):
                self.assertEqual(self.admin.get(url).status_code, 200, url)
                self.assertEqual(self.operator.get(url).status_code, 403, url)

    def test_records_lookup_validates_its_query(self):
        self.assertEqual(self.admin.get("/api/records?section=all").status_code, 400)
        self.assertEqual(self.admin.get("/api/records?date=20-09-2026&section=all").status_code, 400)
        self.assertEqual(self.admin.get("/api/records?date=2026-09-20&section=nope").status_code, 400)
        saved = self.operator.post("/api/farm-operations/waste-monitoring", {
            **self.scope(self.place, self.place["facilities"][0]), "monitoring_date": D,
            "monitoring_time": "08:00", "temperature": "31", "water_consistency": "moist",
            "odor_level": "low", "pest_presence": "none"})
        self.assertEqual(saved.status_code, 201, saved.get_json())
        records = self.admin.get("/api/records?date=2026-09-20&section=waste").get_json()["records"]
        self.assertTrue(records.get("Waste Monitoring"))

    def test_legacy_sales_history_is_read_only(self):
        name = f"{self.marker} legacy customer"
        self.customer_names.append(name)
        customer = self.admin.post("/api/customers", {"name": name, "email": f"{self.marker}@example.com"})
        self.assertEqual(customer.status_code, 201, customer.get_json())
        customer_id = customer.get_json()["id"]
        self.assertTrue(db.fetch_one("SELECT 1 FROM customers WHERE id = %s", (customer_id,)))
        self.assertEqual(self.admin.post("/api/customers", {"name": name, "email": f"{self.marker}@example.com"})
                         .status_code, 409)
        self.assertEqual(self.admin.post("/api/customers", {"contact": "no name"}).status_code, 400)
        self.assertEqual(self.admin.put(f"/api/customers/{customer_id}", {"name": name, "contact": "0700"})
                         .status_code, 200)
        self.assertEqual(self.admin.put("/api/customers/999999999", {"name": name}).status_code, 404)

        # Old sales, deliveries and feedback stay readable history for super
        # admins; new ones are customer orders (/orders), so nothing can add
        # to or change the legacy tables any more.
        legacy = {
            "/api/sales": ("sales", "INSERT INTO sales (date, customer_id, product, quantity, amount) "
                                    "VALUES (%s, %s, 'dried larvae', 2, 900) RETURNING id"),
            "/api/deliveries": ("deliveries", "INSERT INTO deliveries (date, customer_id, product, quantity, status) "
                                              "VALUES (%s, %s, 'dried larvae', 2, 'delivered') RETURNING id"),
            "/api/feedback": ("customer_feedback", "INSERT INTO customer_feedback (date, customer_id, feedback, rating) "
                                                   "VALUES (%s, %s, 'good quality', 5) RETURNING id"),
        }
        for url, (table, insert) in legacy.items():
            with self.subTest(url=url):
                record_id = db.execute_returning(insert, (D, customer_id))["id"]
                history = self.admin.get(url)
                self.assertEqual(history.status_code, 200)
                self.assertIn(record_id, [row["id"] for row in history.get_json()])
                self.assertEqual(self.operator.get(url).status_code, 403)
                self.assertIn(self.admin.post(url, {"customer_id": customer_id}).status_code, (404, 405))
                self.assertIn(self.admin.put(f"{url}/{record_id}", {"customer_id": customer_id}).status_code,
                              (404, 405))

    def test_legacy_feeding_routes_write_canonical_events(self):
        place = self.make_farm()
        scope = self.scope(place, place["facilities"][0])
        operator = self.make_user("operator", access=[("farm", place["farm"]["id"])])
        source = f"{self.marker} legacy source"
        self.waste_sources.append(source)
        lot = self.ok(operator.post("/api/waste-sourcing", {
            **scope, "collection_date": D, "collection_time": "07:00", "source_type": "market",
            "source_name": source, "waste_type": "vegetable", "waste_weight": "5", "segregation_status": "organic",
            "collection_personnel": "x", "lot_status": "available", "contaminants_found": []}), 201)["waste_lot"]
        substrate = self.ok(operator.post("/api/substrate-preparation", {
            **scope, "batch_no": f"lg-{uuid4().hex[:8]}", "prep_date": D, "moisture_consistency": "moist",
            "waste_particle_size": "fine", "foreign_matter": "no", "handler_operator": "x",
            "inputs": [{"waste_lot_id": lot["id"], "quantity_used": "4"}]}), 201)["id"]
        batch = self.ok(operator.post("/api/production/batches", {
            **scope, "start_date": D, "current_stage": "STARTING",
            "inputs": [{"substrate_batch_id": substrate, "quantity_issued": "3"}]}), 201)["record"]
        self.ok(operator.post(f"/api/production/batches/{batch['business_id']}/status", {"status": "ACTIVE"}))
        ref = {"production_batch_id": batch["business_id"]}
        self.ok(operator.post("/api/feeding/schedule", {
            **ref, "feeding_date": D, "feed_type": "mash", "quantity_offered": "1", "operator": "x"}), 201)
        self.ok(operator.post("/api/feeding/environmental-monitoring", {
            **ref, "monitoring_date": D, "monitoring_time": "09:00", "asset_reference": "tray",
            "temperature": 28, "humidity": 60}), 201)
        self.ok(operator.post("/api/feeding/health-intervention", {
            **ref, "health_date": D, "observed_issue": "slow growth", "severity": "low",
            "action_taken": "more feed"}), 201)
        events = self.ok(operator.get(f"/api/production/batches/{batch['business_id']}"))["data"]["events"]
        self.assertEqual(sorted(e["event_type"] for e in events), ["feeding", "health", "monitoring"])
        self.assertEqual(self.viewer.post("/api/feeding/schedule", {**ref}).status_code, 403)
