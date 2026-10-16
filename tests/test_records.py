"""Records by date, the harvest report email, and the retired tables.

Every form that wrote a record without a farm, site and facility is retired:
hatchery, fly facility and waste-handling logs moved to /api/farm-operations
(test_farm_operations.py), drying to the scoped drying API, sales to customer
orders, and the larval forms record production events on the batch. Here: the
retired routes are really gone, records by date are for super admins only and
read the current tables, and the old tables are dropped once empty.
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
        # Larval forms now post to /api/production/batches/<ref>/events/<type>.
        "/api/feeding/schedule", "/api/feeding/environmental-monitoring",
        "/api/feeding/health-intervention", "/api/feeding/harvest-yield",
        # The record-links tool wrote a side table nothing read.
        "/api/locations/record-links",
    )
] + [("PUT", f"/api/{name}/1") for name in ("sales", "deliveries", "feedback")] + [
    ("GET", "/api/hatchery/next-batch-id"),
] + [("GET", url) for url in (
    # Statistics and analytics read only the old tables; operational reports replace them.
    "/api/statistics/waste-processing", "/api/statistics/environmental", "/api/statistics/larval-growth",
    "/api/statistics/system-efficiency", "/api/statistics/daily-report", "/api/statistics/harvest-efficiency",
    "/api/waste-sourcing/all", "/api/drying/input/all", "/api/drying/output/all", "/api/drying/qc/all",
    "/api/drying/remarks/all", "/api/drying/review/all", "/api/feeding/harvest/all",
    "/api/analytics/waste-sourcing", "/api/analytics/hatchery-batches", "/api/analytics/sales",
    "/api/analytics/harvest-yield", "/api/analytics/drying-batches",
    "/api/sales", "/api/deliveries", "/api/feedback",
    "/api/waste-sourcing", "/api/storage-records", "/api/processing-records", "/api/environmental-monitoring",
)]

# Every record of one day, by area (super admins).
RECORD_READS = [f"/api/records?date=2026-09-20&section={section}"
                for section in ("all", "waste", "hatchery", "feeding", "drying", "facility", "sales")]


@requires_database
class RecordsTest(ScenarioTestCase):

    def setUp(self):
        super().setUp()
        place = self.place = self.make_farm()
        self.operator = self.make_user("operator", access=[("farm", place["farm"]["id"])])
        self.viewer = self.make_user("viewer", access=[("farm", place["farm"]["id"])])
        last_id = db.fetch_one("SELECT COALESCE(MAX(id), 0) AS id FROM waste_monitoring")["id"]
        self.addCleanup(db.execute_query, "DELETE FROM waste_monitoring WHERE id > %s", (last_id,))

    def test_retired_write_routes_are_gone(self):
        for method, url in RETIRED:
            with self.subTest(method=method, url=url):
                response = self.admin.client.open(url, method=method, json={}, base_url="https://localhost")
                self.assertIn(response.status_code, (404, 405), (method, url, response.status_code))

    def test_harvest_report_email_is_admin_only(self):
        from unittest.mock import patch

        configured = {"EMAIL_HOST_USER": "alerts@example.com", "EMAIL_HOST_PASSWORD": "x",
                      "ADMIN_EMAIL": "admin@example.com"}
        with patch.multiple("backend.domains.records", **configured), \
                patch("backend.domains.records.send_email", return_value=True) as send:
            self.assertEqual(self.operator.post("/api/send-harvest-report").status_code, 403)
            sent = self.admin.post("/api/send-harvest-report")
        self.assertEqual(sent.status_code, 200, sent.get_json())
        send.assert_called_once()
        subject, body, recipient = send.call_args.args
        self.assertIn("Harvest Report", subject)
        self.assertEqual(recipient, "admin@example.com")
        # It says so when nothing was sent instead of claiming success.
        with patch.multiple("backend.domains.records", EMAIL_HOST_USER="", EMAIL_HOST_PASSWORD="", ADMIN_EMAIL=""):
            self.assertEqual(self.admin.post("/api/send-harvest-report").status_code, 503)
        with patch.multiple("backend.domains.records", **configured), \
                patch("backend.domains.records.send_email", return_value=False):
            self.assertEqual(self.admin.post("/api/send-harvest-report").status_code, 502)

    def test_records_by_date_are_super_admin_only(self):
        for url in RECORD_READS:
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

    def test_customers_are_kept_tidy(self):
        name = f"{self.marker} customer"
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

    def test_larval_forms_record_events_shown_in_records_by_date(self):
        place = self.make_farm()
        scope = self.scope(place, place["facilities"][0])
        operator = self.make_user("operator", access=[("farm", place["farm"]["id"])])
        source = f"{self.marker} records source"
        self.waste_sources.append(source)
        lot = self.ok(operator.post("/api/waste-sourcing", {
            **scope, "collection_date": D, "collection_time": "07:00", "source_type": "market",
            "source_name": source, "waste_type": "vegetable", "waste_weight": "5", "segregation_status": "organic",
            "collection_personnel": "x", "lot_status": "available", "contaminants_found": []}), 201)["waste_lot"]
        substrate = self.ok(operator.post("/api/substrate-preparation", {
            **scope, "batch_no": f"rc-{uuid4().hex[:8]}", "prep_date": D, "moisture_consistency": "moist",
            "waste_particle_size": "fine", "foreign_matter": "no", "handler_operator": "x",
            "inputs": [{"waste_lot_id": lot["id"], "quantity_used": "4"}]}), 201)
        self.assertIn("preparation_record_id", substrate["record"])
        batch = self.ok(operator.post("/api/production/batches", {
            **scope, "start_date": D, "current_stage": "STARTING",
            "inputs": [{"substrate_batch_id": substrate["id"], "quantity_issued": "3"}]}), 201)["record"]
        ref = batch["business_id"]
        self.ok(operator.post(f"/api/production/batches/{ref}/status", {"status": "ACTIVE"}))
        # Field names exactly as the data-entry page sends them.
        base = f"/api/production/batches/{ref}/events"
        self.ok(operator.post(f"{base}/feeding", {
            "production_batch_id": ref, "feeding_date": D, "tray_reference": "T-04", "larvae_age_days": "6",
            "larvae_weight_g": "40", "feed_type": "mash", "feed_quantity_kg": "1", "start_weight_kg": "7.25",
            "end_weight_kg": "6.5", "consumption_g": "750", "operator": "x"}), 201)
        self.ok(operator.post(f"{base}/monitoring", {
            "production_batch_id": ref, "monitoring_date": D, "monitoring_time": "09:00",
            "tray_facility_id": "T-04", "temperature": "28", "humidity": "60", "ammonia_odor": "no",
            "notes": "steady"}), 201)
        self.ok(operator.post(f"{base}/health", {
            "production_batch_id": ref, "health_date": D, "observed_issue": "slow growth", "severity": "low",
            "follow_up_date": "2026-09-22", "resolved": "no", "action_taken": "more feed",
            "comments": "watch"}), 201)
        events = self.ok(operator.get(f"/api/production/batches/{ref}"))["data"]["events"]
        self.assertEqual(sorted(e["event_type"] for e in events), ["feeding", "health", "monitoring"])
        self.assertEqual(self.viewer.post(f"{base}/feeding", {"production_batch_id": ref}).status_code, 403)
        day = self.ok(self.admin.get(f"/api/records?date={D}&section=feeding"))["records"]
        self.assertEqual(sorted(e["event_type"] for e in day["Production Events"] if e["production_batch"] == ref),
                         ["feeding", "health", "monitoring"])

    def test_retired_tables_are_dropped_once_empty(self):
        """retire() keeps a retired table that holds rows and drops it once
        empty; run inside a transaction that is rolled back."""
        import psycopg2

        from backend.config import DB_CONFIG
        from backend.preflight import database_checks
        from backend.retired_tables import EVENT_COPIES, RETIRED_TABLES, remaining, retire

        checks = {name: level for level, name, _ in database_checks(db)}
        self.assertEqual(checks["retired_tables"], "WARN" if remaining(db) else "PASS")

        connection = psycopg2.connect(**DB_CONFIG)
        try:
            cursor = connection.cursor()
            cursor.execute("DROP TABLE IF EXISTS sales")
            cursor.execute("CREATE TABLE sales (id SERIAL PRIMARY KEY, note TEXT)")
            cursor.execute("INSERT INTO sales (note) VALUES ('kept')")
            kept = retire(cursor)
            self.assertIn("sales", kept)
            cursor.execute("DELETE FROM sales")
            kept = retire(cursor, clear_copies=True)
            self.assertNotIn("sales", kept)
            # Only rows that are not copies of a recorded event can keep a table.
            for table in EVENT_COPIES:
                if table in kept:
                    cursor.execute(f"SELECT count(*) FROM {table} WHERE production_event_id IS NULL")
                    self.assertEqual(cursor.fetchone()[0], kept[table])
            cursor.execute("SELECT count(*) FROM unnest(%s::text[]) AS t(name) WHERE to_regclass(name) IS NOT NULL",
                           (list(RETIRED_TABLES),))
            self.assertEqual(cursor.fetchone()[0], len(kept))
        finally:
            connection.rollback()
            connection.close()
