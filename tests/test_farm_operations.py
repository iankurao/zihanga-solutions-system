"""Farm operation logs (hatchery, fly facility, waste handling) and the drying
lists behind the data-entry forms: every record belongs to a farm, site and
facility, only people with access there may record or see it, and the
database refuses rows without a location.
"""
from datetime import date, timedelta
from uuid import uuid4

import psycopg2

from support import ScenarioTestCase, db, requires_database

D = "2026-09-20"

# kind -> (table, valid fields as the data-entry form sends them)
VALID = {
    "waste-storage": ("storage_records", {
        "storageDate": D, "storageMethod": "covered bins", "storageConditions": "shaded",
        "storageDuration": "2", "plannedUtilization": "substrate"}),
    "waste-processing": ("processing_records", {
        "processingDate": D, "processingType": "shredding", "processingMethod": "manual",
        "wasteProcessed": "12.5", "wasteReduction": "20"}),
    "waste-monitoring": ("waste_monitoring", {
        "monitoring_date": D, "monitoring_time": "08:00", "temperature": "31", "water_consistency": "moist",
        "odor_level": "low", "pest_presence": "none"}),
    "hatchery-batch": ("hatchery_batches", {
        "batch_date": D, "egg_incubation_date": D, "total_eggs_grams": "25",
        "expected_hatch_date": "2026-09-24", "supervisor_name": "Faith"}),
    "hatchery-monitoring": ("hatchery_monitoring", {
        "monitoring_date": D, "temperature_c": "30", "humidity_percent": "70"}),
    "hatchery-cleaning": ("hatchery_cleaning", {
        "cleaning_date": D, "areas_cleaned": "trays", "cleaning_materials": "water", "cleaning_personnel": "Faith"}),
    "hatchery-problem": ("hatchery_problems", {
        "problem_date": D, "problem_identified": "mites", "proposed_solution": "clean trays",
        "responsible_person": "Faith", "days_to_implement": "2"}),
    "cage-monitoring": ("cage_monitoring", {
        "date": D, "cageId": "CAGE-1", "temperature": 28, "humidity": 65, "lightingHours": "12",
        "ventilationOk": "yes", "cageCleaned": "yes", "cageDamage": "no"}),
    "facility-maintenance": ("facility_maintenance", {
        "date": D, "moatCheck": "ok", "antsPresent": "no", "rodentsPresent": "no", "birdNetOk": "yes",
        "trenchRefilled": "yes", "maintenanceNotes": "routine"}),
    "pupae-transition": ("pupae_transition", {
        "date": D, "love_cage_id": "LC-1", "pupae_weight_added_kg": 1.5, "old_pupae_removed_kg": 0.5,
        "dead_flies_removed": "yes", "water_points_checked": "yes", "new_egg_crates_installed": "yes",
        "number_of_crates": 3}),
    "egg-collection": ("egg_collection", {
        "date": D, "time": "morning", "cageId": "CAGE-1", "eggsCollected": 12.5, "baitReplaced": "yes",
        "eggsIntact": "yes", "collectorName": "Faith", "collectionMethod": "crates"}),
    "bait-preparation": ("bait_preparation", {
        "barrelId": "B-1", "baitType": "fruit", "ingredientsAdded": "mango peel", "startDate": D,
        "readyDate": "2026-09-23"}),
}
LOG_TABLES = sorted({table for table, _ in VALID.values()} | {"hatchery_feeding"})


@requires_database
class FarmOperationsTest(ScenarioTestCase):
    def setUp(self):
        super().setUp()
        self.place = self.make_farm(facilities=("production", "warehouse"))
        self.where = self.scope(self.place, self.place["facilities"][0])
        self.operator = self.make_user("operator", access=[("farm", self.place["farm"]["id"])])
        self.viewer = self.make_user("viewer", access=[("farm", self.place["farm"]["id"])])
        other = self.make_farm()
        self.outsider = self.make_user("operator", access=[("farm", other["farm"]["id"])])
        before = {t: db.fetch_one(f"SELECT COALESCE(MAX(id), 0) AS id FROM {t}")["id"] for t in LOG_TABLES}
        # Log rows reference the farm; remove them before the farm cleanup runs.
        for table, last_id in before.items():
            self.addCleanup(db.execute_query, f"DELETE FROM {table} WHERE id > %s", (last_id,))

    def record(self, session, kind, body, where=None):
        return session.post(f"/api/farm-operations/{kind}", {**(self.where if where is None else where), **body})

    def test_every_kind_needs_a_location_and_access_and_stores_it(self):
        kinds = {k["key"] for k in self.ok(self.operator.get("/api/farm-operations"))["data"]}
        self.assertEqual(kinds, set(VALID) | {"hatchery-feeding"})
        for kind, (table, body) in VALID.items():
            with self.subTest(kind=kind):
                self.assertEqual(self.record(self.viewer, kind, body).status_code, 403)
                self.assertEqual(self.record(self.outsider, kind, body).status_code, 403)
                no_place = self.operator.post(f"/api/farm-operations/{kind}", body)
                self.assertEqual(no_place.status_code, 400)
                self.assertIn("farm_id, site_id, and facility_id are required", no_place.get_json()["message"])
                empty = self.record(self.operator, kind, {})
                self.assertEqual(empty.status_code, 400)
                self.assertIn("Missing", empty.get_json()["message"])

                saved = self.record(self.operator, kind, body)
                self.assertEqual(saved.status_code, 201, saved.get_json())
                row = saved.get_json()["data"]
                self.assertEqual((row["farm_id"], row["site_id"], row["facility_id"]),
                                 (self.where["farm_id"], self.where["site_id"], self.where["facility_id"]))
                self.assertEqual(row["recorded_by_user_id"], self.operator.id)
                audit = db.fetch_one(
                    "SELECT actor_user_id FROM audit_log WHERE action = %s AND entity_id = %s",
                    (f"{table}.created", str(row["id"])))
                self.assertEqual(audit["actor_user_id"], self.operator.id, table)

                listed = self.ok(self.operator.get(f"/api/farm-operations/{kind}"))["data"]
                self.assertIn(row["id"], [r["id"] for r in listed])
                self.assertEqual(listed[0]["facility_name"], self.place["facilities"][0]["name"])
                hidden = self.ok(self.outsider.get(f"/api/farm-operations/{kind}"))["data"]
                self.assertNotIn(row["id"], [r["id"] for r in hidden])
                self.assertIn(row["id"], [r["id"] for r in self.ok(self.admin.get(f"/api/farm-operations/{kind}"))["data"]])

    def test_values_are_checked_before_anything_is_stored(self):
        tomorrow_plus = (date.today() + timedelta(days=3)).isoformat()
        cases = [
            ("hatchery-monitoring", {**VALID["hatchery-monitoring"][1], "humidity_percent": "120"}, "at most 100"),
            ("waste-processing", {**VALID["waste-processing"][1], "wasteProcessed": "-1"}, "at least 0"),
            ("waste-storage", {**VALID["waste-storage"][1], "storageDuration": "2.5"}, "whole number"),
            ("waste-storage", {**VALID["waste-storage"][1], "storageDate": "20/09/2026"}, "YYYY-MM-DD"),
            ("waste-storage", {**VALID["waste-storage"][1], "storageDate": tomorrow_plus}, "future"),
            ("waste-monitoring", {**VALID["waste-monitoring"][1], "monitoring_time": "25:99"}, "HH:MM"),
            ("hatchery-cleaning", {**VALID["hatchery-cleaning"][1], "cleaning_personnel": "x" * 101}, "at most 100"),
            ("bait-preparation", {**VALID["bait-preparation"][1], "readyDate": "2026-09-19"}, "before the start"),
            ("cage-monitoring", {**VALID["cage-monitoring"][1], "temperature": "warm"}, "must be a number"),
        ]
        count = db.fetch_one("SELECT COUNT(*) AS n FROM storage_records")["n"]
        for kind, body, message in cases:
            with self.subTest(kind=kind, message=message):
                response = self.record(self.operator, kind, body)
                self.assertEqual(response.status_code, 400, response.get_json())
                self.assertIn(message, response.get_json()["message"])
        self.assertEqual(db.fetch_one("SELECT COUNT(*) AS n FROM storage_records")["n"], count)
        # Planned dates may lie ahead.
        planned = {**VALID["bait-preparation"][1], "readyDate": tomorrow_plus}
        self.assertEqual(self.record(self.operator, "bait-preparation", planned).status_code, 201)
        # A location whose facility is on another farm is refused.
        other = self.make_farm()
        mixed = {**self.where, "facility_id": other["facilities"][0]["id"]}
        self.assertEqual(self.record(self.admin, "waste-storage", VALID["waste-storage"][1], mixed).status_code, 400)
        self.assertEqual(self.admin.get("/api/farm-operations/nope").status_code, 404)
        self.assertEqual(self.admin.get("/api/farm-operations/waste-storage?date_from=yesterday").status_code, 400)
        self.assertEqual(self.admin.get("/api/farm-operations/waste-storage?limit=lots").status_code, 400)

    def test_hatchery_batches_are_numbered_and_feeding_needs_a_real_batch(self):
        first = self.ok(self.record(self.operator, "hatchery-batch", VALID["hatchery-batch"][1]), 201)["data"]
        self.assertRegex(first["batch_number"], r"^HAT-\d{4}-\d{5}$")
        named = {**VALID["hatchery-batch"][1], "batch_number": f"H-{uuid4().hex[:6]}"}
        self.ok(self.record(self.operator, "hatchery-batch", named), 201)
        again = self.record(self.operator, "hatchery-batch", named)
        self.assertEqual(again.status_code, 400)
        self.assertIn("already exists", again.get_json()["message"])

        feeding = {"feeding_date": D, "feed_per_5g_eggs_grams": "50", "total_feed_used_grams": "250",
                   "days_to_utilize": "4", "feedType": "chick mash", "distribution_method": "spread"}
        unknown = self.record(self.operator, "hatchery-feeding", {**feeding, "batch_id": "HAT-0000-99999"})
        self.assertEqual(unknown.status_code, 400)
        self.assertIn("No hatchery batch", unknown.get_json()["message"])
        fed = self.ok(self.record(self.operator, "hatchery-feeding", {**feeding, "batch_id": first["batch_number"]}), 201)
        self.assertEqual((fed["data"]["batch_id"], fed["data"]["feed_type"]), (first["batch_number"], "chick mash"))
        # A batch from another farm cannot be fed here.
        other = self.make_farm()
        elsewhere = self.ok(self.admin.post("/api/farm-operations/hatchery-batch", {
            **self.scope(other, other["facilities"][0]), **VALID["hatchery-batch"][1]}), 201)["data"]
        foreign = self.record(self.operator, "hatchery-feeding", {**feeding, "batch_id": elsewhere["batch_number"]})
        self.assertEqual(foreign.status_code, 400)

    def test_the_database_refuses_new_rows_without_a_location(self):
        with self.assertRaises(psycopg2.errors.CheckViolation):
            db.execute_query(
                "INSERT INTO storage_records (storage_date, storage_method, storage_conditions, storage_duration, "
                "planned_utilization) VALUES (%s, 'bins', 'shade', 1, 'substrate')", (D,))
        with self.assertRaises(psycopg2.errors.CheckViolation):
            db.execute_query(
                "INSERT INTO egg_collection (collection_date, collection_time, cage_id, eggs_collected, bait_replaced, "
                "eggs_intact, collector_name, collection_method, farm_id) "
                "VALUES (%s, 'am', 'C', 1, 'y', 'y', 'F', 'c', %s)", (D, self.where["farm_id"]))


@requires_database
class DryingListsTest(ScenarioTestCase):
    """The drying pick-lists: harvests with larvae left, and batches with outputs, checks and lots."""

    def harvested(self, session, place, kg="6"):
        facility = place["facilities"][0]
        batch = self.make_batch(session, place, facility)
        ref = batch["business_id"]
        # The test batch has no harvest limit; set one as setup would.
        db.execute_query("UPDATE production_batches SET harvest_limit_kg = 50 WHERE business_id = %s", (ref,))
        for status in ("ACTIVE", "MONITORING", "READY_FOR_HARVEST"):
            self.ok(session.post(f"/api/production/batches/{ref}/status", {"status": status}))
        harvest = self.ok(session.post(f"/api/production/batches/{ref}/events/harvest", {
            "harvest_date": D, "event_time": "10:00", "wet_weight": kg, "unit": "kg", "harvest_stage": "prepupae",
            "operator": "test", "location": "tray"}), 201)["harvest"]
        return ref, harvest

    def test_available_harvests_and_batches_follow_drying(self):
        place = self.make_farm(facilities=("production", "drying"))
        operator = self.make_user("operator", access=[("farm", place["farm"]["id"])])
        outsider = self.make_user("operator", access=[("farm", self.make_farm()["farm"]["id"])])
        production_ref, harvest = self.harvested(operator, place)

        available = self.ok(operator.get(f"/api/drying/available-harvests?farm_id={place['farm']['id']}"))["data"]
        row = next(h for h in available if h["id"] == harvest["id"])
        self.assertEqual((row["production_batch"], float(row["remaining_kg"])), (production_ref, 6.0))
        self.assertNotIn(harvest["id"], [h["id"] for h in self.ok(outsider.get("/api/drying/available-harvests"))["data"]])

        dryer = self.scope(place, place["facilities"][1])
        created = self.ok(operator.post("/api/drying/batches", {
            **dryer, "batch_code": f"T-{uuid4().hex[:6]}", "drying_date": D, "drying_method": "solar_drying",
            "personnel": "test", "inputs": [{"harvest_id": harvest["id"], "quantity": "4", "unit": "kg"}]}), 201)
        drying_ref = created["data"]["business_id"]
        left = self.ok(operator.get("/api/drying/available-harvests"))["data"]
        self.assertEqual(float(next(h for h in left if h["id"] == harvest["id"])["remaining_kg"]), 2.0)

        for status in ("RECEIVED", "DRYING"):
            self.ok(operator.post(f"/api/drying/batches/{drying_ref}/status", {"status": status}))
        output = self.ok(operator.post(f"/api/drying/batches/{drying_ref}/outputs", {
            "quantity": "1.2", "unit": "kg", "output_date": D, "operator": "test"}), 201)["output"]
        self.ok(operator.post(f"/api/drying/batches/{drying_ref}/status", {"status": "QC_PENDING"}))
        qc = self.make_user("qc_officer", access=[("farm", place["farm"]["id"])])
        check = self.ok(qc.post(f"/api/drying/outputs/{output['id']}/quality-checks", {
            "status": "passed", "inspector": "qc", "moisture_percent": "9"}), 201)["data"]

        def listed(session, query=""):
            return {b["business_id"]: b for b in self.ok(session.get(f"/api/drying/batches{query}"))["data"]}

        batch = listed(operator)[drying_ref]
        self.assertEqual((batch["status"], float(batch["input_kg"])), ("QC_PENDING", 4.0))
        self.assertEqual([(o["id"], o["product_lot"]) for o in batch["outputs"]], [(output["id"], None)])
        self.assertEqual([(c["id"], c["status"], c["decision"]) for c in batch["outputs"][0]["checks"]],
                         [(check["id"], "passed", None)])
        self.assertIn(drying_ref, listed(operator, "?status=DRYING,QC_PENDING"))
        self.assertNotIn(drying_ref, listed(operator, "?status=DRYING"))
        self.assertNotIn(drying_ref, listed(operator, "?status=COMPLETED"))
        self.assertNotIn(drying_ref, listed(outsider))
        self.assertEqual(operator.get("/api/drying/batches?status=SOMEDAY").status_code, 400)

        self.ok(qc.post("/api/drying/quality-approvals", {
            "quality_check_id": check["id"], "decision": "approved", "approver": "qc"}), 201)
        self.assertEqual(listed(operator)[drying_ref]["outputs"][0]["checks"][0]["decision"], "approved")
