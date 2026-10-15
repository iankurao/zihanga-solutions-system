"""Legacy (pre-traceability) record forms and reads.

These endpoints predate the location-scoped chain but are still live on the
data-entry dashboard. Each form must refuse roles that cannot record, answer
an empty submission with a 400 (never a 500), and store a valid record. The
legacy reads are for super admins only.
"""
from uuid import uuid4

from support import ScenarioTestCase, db, requires_database

D = "2026-09-20"

# endpoint, table written, valid payload
FORMS = [
    ("/api/waste-monitoring", "waste_monitoring", {
        "monitoring_date": D, "monitoring_time": "08:00", "temperature": "31", "water_consistency": "moist",
        "odor_level": "low", "pest_presence": "none"}),
    ("/api/storage-records", "storage_records", {
        "storage_date": D, "storage_method": "covered bins", "storage_conditions": "shaded",
        "storage_duration": "2", "planned_utilization": "substrate"}),
    ("/api/processing-records", "processing_records", {
        "processing_date": D, "processing_type": "shredding", "processing_method": "manual",
        "waste_processed": "12.5"}),
    ("/api/facility/cage-monitoring", "cage_monitoring", {
        "date": D, "cage_id": "CAGE-1", "temperature": 28, "humidity": 65, "lighting_hours": 12,
        "ventilation_ok": "yes", "cage_cleaned": "yes", "cage_damage": "no"}),
    ("/api/facility/maintenance", "facility_maintenance", {
        "date": D, "moat_check": "ok", "ants_present": "no", "rodents_present": "no", "bird_net_ok": "yes",
        "trench_refilled": "yes", "maintenance_notes": "routine"}),
    ("/api/facility/pupae-transition", "pupae_transition", {
        "date": D, "love_cage_id": "LC-1", "pupae_weight_added_kg": 1.5, "old_pupae_removed_kg": 0.5,
        "dead_flies_removed": "yes", "water_points_checked": "yes", "new_egg_crates_installed": "yes",
        "number_of_crates": 3}),
    ("/api/facility/egg-collection", "egg_collection", {
        "date": D, "time": "07:00", "cage_id": "CAGE-1", "eggs_collected": 12.5, "bait_replaced": "yes",
        "eggs_intact": "yes", "collector_name": "Faith", "collection_method": "crates"}),
    ("/api/facility/bait-preparation", "bait_preparation", {
        "barrel_id": "B-1", "bait_type": "fruit", "ingredients_added": "mango peel", "start_date": D,
        "ready_date": "2026-09-23"}),
    ("/api/fly-facility/cage-monitoring", "cage_monitoring", {
        "date": D, "cageId": "CAGE-2", "temperature": 28, "humidity": 60, "lightingHours": 12,
        "ventilationOk": "yes", "cageCleaned": "yes", "deadFliesRemoved": "yes", "cageDamage": "no"}),
    ("/api/fly-facility/maintenance", "facility_maintenance", {
        "date": D, "moatCheck": "ok", "antsPresent": "no", "rodentsPresent": "no", "birdNetOk": "yes",
        "trenchRefilled": "yes", "maintenanceNotes": "routine"}),
    ("/api/fly-facility/pupae-transition", "pupae_transition", {
        "date": D, "loveCageId": "LC-2", "pupaeWeightAdded": 1.0, "oldPupaeRemoved": 0.2,
        "deadFliesRemoved": "yes", "waterPointsChecked": "yes", "newEggCratesInstalled": "yes"}),
    ("/api/fly-facility/egg-collection", "egg_collection", {
        "date": D, "time": "07:30", "cageId": "CAGE-2", "eggsCollected": 9, "baitReplaced": "yes",
        "eggsIntact": "yes", "collectorName": "Faith", "collectionMethod": "crates"}),
    ("/api/fly-facility/bait-preparation", "bait_preparation", {
        "barrelId": "B-2", "baitType": "fruit", "ingredientsAdded": "banana", "startDate": D,
        "readyDate": "2026-09-23"}),
    ("/api/hatchery/batch", "hatchery_batches", {
        "batch_date": D, "egg_incubation_date": D, "total_eggs_grams": 25, "expected_hatch_date": "2026-09-24",
        "supervisor_name": "Faith"}),
    ("/api/hatchery/batch-information", "hatchery_batches", {
        "batch_date": D, "egg_incubation_date": D, "total_eggs_grams": 20, "expected_hatch_date": "2026-09-24",
        "supervisor_name": "Faith"}),
    ("/api/hatchery/feeding", "hatchery_feeding", {
        "batch_id": "HB-TEST", "feeding_date": D, "feed_per_5g_eggs_grams": 50, "total_feed_used_grams": 250,
        "days_to_utilize": 4, "feed_type": "chick mash", "distribution_method": "spread"}),
    ("/api/hatchery/feeding-records", "hatchery_feeding", {
        "batch_id": "HB-TEST", "feeding_date": D, "feed_per_5g_eggs_grams": 50, "total_feed_used_grams": 200,
        "days_to_utilize": 3, "feed_type": "chick mash", "distribution_method": "spread"}),
    ("/api/hatchery/monitoring", "hatchery_monitoring", {
        "monitoring_date": D, "temperature_c": 30, "humidity_percent": 70}),
    ("/api/hatchery/environmental-monitoring", "hatchery_monitoring", {
        "monitoring_date": D, "temperature_c": 29, "humidity_percent": 68}),
    ("/api/hatchery/cleaning", "hatchery_cleaning", {
        "cleaning_date": D, "areas_cleaned": "trays", "cleaning_materials": "water", "cleaning_personnel": "Faith"}),
    ("/api/hatchery/problems", "hatchery_problems", {
        "problem_date": D, "problem_identified": "mites", "proposed_solution": "clean trays",
        "responsible_person": "Faith"}),
    ("/api/hatchery/health", "hatchery_health_interventions", {
        "health_date": D, "health_issue": "low hatch", "severity": "low", "action_taken": "raise humidity"}),
    ("/api/drying/input", "drying_input", {
        "batch_id": "LEGACY-DRY-1", "wet_harvested": 10, "wet_placed": 9, "dried_by_personnel": 2, "sand_used": 1}),
    ("/api/drying/output", "drying_output", {"batch_id": "LEGACY-DRY-1", "dried_produced": 2.2}),
]

# Legacy drying QC forms need the QC role.
QC_FORMS = [
    ("/api/drying/qc", "drying_quality_control", {
        "batch_id": "LEGACY-DRY-1", "qc_date": D, "sand_removal": "complete", "color_quality": "golden",
        "moisture_level": "10%", "qc_personnel": "QC", "contaminants_found": ["none"]}),
    ("/api/drying/quality-control", "drying_quality_control", {
        "batch_id": "LEGACY-DRY-1", "qc_date": D, "sand_removal": "complete", "color_quality": "golden",
        "moisture_level": "11%", "qc_personnel": "QC"}),
    ("/api/drying/review", "drying_review_approval", {
        "batch_id": "LEGACY-DRY-1", "reviewed_by": "QC", "review_date": D, "approval_status": "approved"}),
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
        place = self.make_farm()
        self.operator = self.make_user("operator", access=[("farm", place["farm"]["id"])])
        self.viewer = self.make_user("viewer", access=[("farm", place["farm"]["id"])])
        tables = ({table for _url, table, _body in FORMS + QC_FORMS}
                  | {"sales", "deliveries", "customer_feedback"})
        before = {table: db.fetch_one(f"SELECT COALESCE(MAX(id), 0) AS id FROM {table}")["id"] for table in tables}
        for table, last_id in before.items():
            self.addCleanup(db.execute_query, f"DELETE FROM {table} WHERE id > %s", (last_id,))

    def _count(self, table):
        return db.fetch_one(f"SELECT COUNT(*) AS n FROM {table}")["n"]

    def test_forms_refuse_viewers_validate_and_store(self):
        for url, table, body in FORMS:
            with self.subTest(url=url):
                self.assertEqual(self.viewer.post(url, body).status_code, 403)
                empty = self.operator.post(url, {})
                self.assertEqual(empty.status_code, 400, (url, empty.get_json()))
                before = self._count(table)
                saved = self.operator.post(url, body)
                self.assertIn(saved.status_code, (200, 201), (url, saved.get_json()))
                self.assertEqual(self._count(table), before + 1, url)

    def test_legacy_drying_qc_forms_need_the_qc_role(self):
        qc = self.make_user("qc_officer")
        for url, table, body in QC_FORMS:
            with self.subTest(url=url):
                self.assertEqual(self.operator.post(url, body).status_code, 403)
                self.assertEqual(qc.post(url, {}).status_code, 400)
                before = self._count(table)
                self.assertIn(qc.post(url, body).status_code, (200, 201))
                self.assertEqual(self._count(table), before + 1)
        # The remarks route was never implemented; it says so instead of failing.
        stub = self.operator.post("/api/drying/remarks", {"batch_id": "LEGACY-DRY-1"})
        self.assertEqual(stub.status_code, 404)
        self.assertIn("not implemented", stub.get_json()["message"])

    def test_harvest_report_email_is_admin_only(self):
        from unittest.mock import patch

        with patch("backend.domains.legacy.send_email") as send:
            self.assertEqual(self.operator.post("/api/send-harvest-report").status_code, 403)
            sent = self.admin.post("/api/send-harvest-report")
        self.assertEqual(sent.status_code, 200, sent.get_json())
        send.assert_called_once()
        subject, body, recipient = send.call_args.args
        self.assertIn("Harvest Yield Report", subject)

    def test_next_hatchery_batch_id_is_offered(self):
        response = self.operator.get("/api/hatchery/next-batch-id")
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(str(response.get_json().get("next_batch_id") or response.get_json()))

    def test_legacy_reads_are_super_admin_only(self):
        for url in LEGACY_READS:
            with self.subTest(url=url):
                self.assertEqual(self.admin.get(url).status_code, 200, url)
                self.assertEqual(self.operator.get(url).status_code, 403, url)

    def test_records_lookup_validates_its_query(self):
        self.assertEqual(self.admin.get("/api/records?section=all").status_code, 400)
        self.assertEqual(self.admin.get("/api/records?date=20-09-2026&section=all").status_code, 400)
        self.assertEqual(self.admin.get("/api/records?date=2026-09-20&section=nope").status_code, 400)
        saved = self.operator.post(FORMS[0][0], FORMS[0][2])
        self.assertIn(saved.status_code, (200, 201))
        records = self.admin.get("/api/records?date=2026-09-20&section=waste").get_json()["records"]
        self.assertTrue(records.get("Waste Monitoring"))

    def test_legacy_sales_history_returns_real_ids_and_edits(self):
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

        records = {
            "/api/sales": ("sales", {"date": D, "customer_id": customer_id, "product": "dried larvae",
                                     "quantity": 2, "amount": 900}),
            "/api/deliveries": ("deliveries", {"date": D, "customer_id": customer_id, "product": "dried larvae",
                                               "quantity": 2, "status": "delivered"}),
            "/api/feedback": ("customer_feedback", {"date": D, "customer_id": customer_id,
                                                    "feedback": "good quality", "rating": 5}),
        }
        for url, (table, body) in records.items():
            with self.subTest(url=url):
                created = self.admin.post(url, body)
                self.assertEqual(created.status_code, 200, created.get_json())
                record_id = created.get_json()["id"]
                self.assertTrue(db.fetch_one(f"SELECT 1 FROM {table} WHERE id = %s", (record_id,)), record_id)
                self.assertEqual(self.admin.put(f"{url}/{record_id}", {**body, "customer_id": customer_id})
                                 .status_code, 200)
                # Legacy sales history is read-only for everyone but super admins.
                self.assertEqual(self.operator.post(url, body).status_code, 403)
                self.assertEqual(self.admin.post(url, {}).status_code, 400)

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
