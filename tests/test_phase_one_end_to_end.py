"""Phase One end to end: Waste Lot -> Substrate -> Production -> Harvest ->
Drying -> QC -> Product Lot -> Inventory -> Order -> Delivery.

Everything goes through the public API with real sign-in, and each step is
done by the role that does it on a farm:

  super admin        sets up the farm, facilities, stores, a bio-pod and accounts
  operator (farmer)  receives waste, prepares substrate, runs the batch, harvests, dries
  QC officer         checks and approves the dried output, releases the product lot
                     (access to the drying facility only)
  inventory officer  moves the lot to the warehouse
  sales officer      creates the customer and order, reserves, dispatches, confirms
  manager            follows the alert, reads Batch 360, reports and the dashboard

Afterwards the chain is checked as a whole: traceability both ways, mass
balance, stock ledger, Batch 360, reports, dashboard, notifications, the
audit trail, label scanning, and that nobody saw or did more than their role
and locations allow.
"""
import json
from datetime import date, timedelta
from uuid import uuid4

from support import ScenarioTestCase, db, requires_database

TODAY = date.today()


def day(offset=0):
    return (TODAY + timedelta(days=offset)).isoformat()


@requires_database
class PhaseOneEndToEndTest(ScenarioTestCase):

    def setUp(self):
        super().setUp()
        self.place = self.make_farm(facilities=("production", "drying", "warehouse"))
        self.production, self.drying, self.warehouse = self.place["facilities"]
        farm_id = self.place["farm"]["id"]
        self.dry_store = self.ok(self.admin.post("/api/inventory/locations", {
            **self.scope(self.place, self.drying), "location_code": "DRY-STORE", "name": "Dry store"}), 201)["data"]
        self.bay = self.ok(self.admin.post("/api/inventory/locations", {
            **self.scope(self.place, self.warehouse), "location_code": "BAY-1", "name": "Warehouse bay 1"}), 201)["data"]
        self.pod = self.ok(self.admin.post("/api/production/units", {
            **self.scope(self.place, self.production), "unit_code": f"POD-{uuid4().hex[:4]}",
            "name": "Bio-pod 1", "unit_type": "bio_pod", "capacity_kg": "50"}), 201)["data"]

        farm = [("farm", farm_id)]
        self.operator = self.make_user("operator", access=farm, full_name="Faith Farmer")
        self.qc = self.make_user("qc_officer", access=[("facility", self.drying["id"])])
        self.stock = self.make_user("inventory_officer", access=farm)
        self.sales = self.make_user("sales_officer", access=farm)
        self.manager = self.make_user("manager", access=farm)
        other = self.make_farm()
        self.outsider = self.make_user("manager", access=[("farm", other["farm"]["id"])])

    # ---- chain steps (each by its own role) --------------------------------------------

    def _receive_waste(self):
        source = f"{self.marker} market"
        self.waste_sources.append(source)
        body = self.ok(self.operator.post("/api/waste-sourcing", {
            **self.scope(self.place, self.production),
            "collection_date": day(-12), "collection_time": "07:30", "source_type": "market",
            "source_name": source, "waste_type": "vegetable", "waste_weight": "10.000",
            "segregation_status": "organic", "collection_personnel": "Faith", "lot_status": "available",
            "contaminants_found": [],
        }), 201)
        return body["waste_lot"]

    def _prepare_substrate(self, waste_lot):
        body = self.ok(self.operator.post("/api/substrate-preparation", {
            **self.scope(self.place, self.production),
            "batch_no": f"sub-{uuid4().hex[:10]}", "prep_date": day(-11),
            "moisture_consistency": "moist", "waste_particle_size": "medium", "foreign_matter": "no",
            "handler_operator": "Faith", "inputs": [{"waste_lot_id": waste_lot["id"], "quantity_used": "8.000"}],
        }), 201)
        return body["id"]

    def _run_production(self, substrate_id):
        batch = self.ok(self.operator.post("/api/production/batches", {
            **self.scope(self.place, self.production),
            "start_date": day(-10), "current_stage": "STARTING", "harvest_limit_kg": "3.000",
            "unit_ids": [self.pod["id"]],
            "inputs": [{"substrate_batch_id": substrate_id, "quantity_issued": "6.000"}],
        }), 201)["record"]
        ref = batch["business_id"]
        base = f"/api/production/batches/{ref}"
        self.ok(self.operator.post(f"{base}/status", {"status": "ACTIVE"}))
        self.ok(self.operator.post(f"{base}/events/feeding", {
            "occurred_at": f"{day(-9)}T08:00:00+00:00", "feed_type": "vegetable mash",
            "quantity_offered": "1.500", "offered_unit": "kg", "operator": "Faith"}), 201)
        self.ok(self.operator.post(f"{base}/events/monitoring", {
            "monitoring_date": day(-8), "monitoring_time": "09:00", "asset_reference": self.pod["unit_code"],
            "temperature": 29.5, "humidity": 65}), 201)
        self.ok(self.operator.post(f"{base}/events/health", {
            "occurred_at": f"{day(-7)}T10:00:00+00:00", "observed_issue": "Larvae climbing out",
            "severity": "critical", "action_taken": "Reduced moisture"}), 201)
        for status in ("MONITORING", "READY_FOR_HARVEST"):
            self.ok(self.operator.post(f"{base}/status", {"status": status}))
        harvest = self.ok(self.operator.post(f"{base}/events/harvest", {
            "harvest_date": day(-5), "event_time": "11:00", "wet_weight": "2.500", "unit": "kg",
            "harvest_stage": "prepupae", "operator": "Faith", "location": self.production["name"]}), 201)["harvest"]
        # Partial harvests are allowed, so the operator closes the batch explicitly.
        self.ok(self.operator.post(f"{base}/status", {"status": "HARVESTED"}))
        return batch, harvest

    def _dry(self, harvest):
        drying = self.ok(self.operator.post("/api/drying/batches", {
            **self.scope(self.place, self.drying),
            "batch_code": f"dry-{uuid4().hex[:10]}", "drying_date": day(-4), "drying_method": "sun_drying",
            "personnel": "Faith",
            "inputs": [{"harvest_id": harvest["id"], "quantity": "2.000", "unit": "kg"}],
        }), 201)["data"]
        ref = drying["business_id"]
        for status in ("RECEIVED", "DRYING"):
            self.ok(self.operator.post(f"/api/drying/batches/{ref}/status", {"status": status}))
        output = self.ok(self.operator.post(f"/api/drying/batches/{ref}/outputs", {
            "quantity": "0.800", "unit": "kg", "moisture_percent": "9.5", "output_date": day(-3),
            "operator": "Faith"}), 201)["output"]
        self.ok(self.operator.post(f"/api/drying/batches/{ref}/status", {"status": "QC_PENDING"}))
        return drying, output

    def _release(self, drying, output):
        check = self.ok(self.qc.post(f"/api/drying/outputs/{output['id']}/quality-checks", {
            "status": "passed", "inspector": "QC officer", "moisture_percent": "9.5"}), 201)["data"]
        self.ok(self.qc.post(f"/api/drying/batches/{drying['business_id']}/quality-approvals", {
            "quality_check_id": check["id"], "decision": "approved", "approver": "QC officer"}), 201)
        return self.ok(self.qc.post("/api/product-lots", {
            "drying_output_id": output["id"], "product_type": "dried_larvae",
            "inventory_location_id": self.dry_store["id"], "storage_location": "Dry store",
            "lot_number": f"fin-{uuid4().hex[:8]}"}), 201)["data"]

    def _move_to_warehouse(self, lot):
        return self.ok(self.stock.post("/api/inventory/movements", {
            "product_lot_id": lot["business_id"], "movement_type": "TRANSFER", "quantity_kg": "0.800",
            "unit": "kg", "from_location_id": self.dry_store["id"], "to_location_id": self.bay["id"]}), 201)

    def _sell(self, lot):
        name = f"{self.marker} Poultry Feeds Ltd"
        self.customer_names.append(name)
        customer = self.ok(self.sales.post("/api/customers", {
            "name": name, "contact": "+254 700 000000", "email": f"{self.marker}@example.com"}), 201)
        listed = self.sales.get("/api/customers").get_json()
        self.assertIn(customer["id"], [c["id"] for c in listed])
        self.assertEqual(self.operator.get("/api/customers").status_code, 403)
        order = self.ok(self.sales.post("/api/orders", {
            "customer_id": customer["id"], "farm_id": self.place["farm"]["id"],
            "requested_delivery_date": day(7), "customer_reference": "PO-1001",
            "lines": [{"product_type": "dried_larvae", "quantity_kg": "0.500"}]}), 201)["data"]
        ref = order["business_id"]
        stock = self.ok(self.sales.get(f"/api/orders/{ref}/available-stock?line_id={order['lines'][0]['id']}"))["data"]
        offer = next(r for r in stock if r["product_lot_id"] == lot["id"])
        self.assertAlmostEqual(offer["free_kg"], 0.8)
        order = self.ok(self.sales.post(f"/api/orders/{ref}/allocations", {
            "order_line_id": order["lines"][0]["id"], "product_lot_id": lot["id"],
            "location_id": self.bay["id"], "quantity_kg": "0.500"}), 201)["data"]
        dispatched = self.ok(self.sales.post(f"/api/orders/{ref}/deliveries", {
            "lines": [{"allocation_id": order["allocations"][0]["id"], "quantity_kg": "0.500"}],
            "vehicle": "KDA 123A", "driver": "John"}), 201)["data"]
        delivery_ref = dispatched["created_delivery"]
        confirmed = self.ok(self.sales.post(f"/api/deliveries/{delivery_ref}/confirm",
                                            {"received_by": "Store keeper"}))["data"]
        return customer, confirmed, delivery_ref

    # ---- the scenario ----------------------------------------------------------------

    def test_waste_to_delivery_by_role(self):
        waste_lot = self._receive_waste()
        substrate_id = self._prepare_substrate(waste_lot)
        batch, harvest = self._run_production(substrate_id)

        # The health issue raised an alert: the manager is told and handles it.
        alerts = self._alerts_for(self.manager)
        health = [a for a in alerts if a["rule"] == "health_issue_open"]
        self.assertEqual(len(health), 1, alerts)
        self.assertEqual(health[0]["severity"], "critical")
        self.ok(self.manager.post(f"/api/alerts/{health[0]['id']}/acknowledge", {"note": "Moisture reduced"}))
        manager_inbox = self.ok(self.manager.get("/api/notifications"))["data"]
        self.assertTrue(any("Larvae climbing out" in (n["body"] or "") for n in manager_inbox), manager_inbox)
        # Alerts reach everyone with access to that location, and nobody else.
        notified = {r["user_id"] for r in db.fetch_all(
            "SELECT DISTINCT user_id FROM notifications WHERE alert_id = %s", (health[0]["id"],))}
        self.assertTrue({self.operator.id, self.manager.id} <= notified)
        self.assertNotIn(self.outsider.id, notified)
        self.assertNotIn(self.qc.id, notified)  # drying facility only; the batch is in production

        drying, output = self._dry(harvest)
        lot = self._release(drying, output)
        self._move_to_warehouse(lot)
        customer, order, delivery_ref = self._sell(lot)

        self._check_roles_were_enforced(batch, output, lot, order)
        self._check_traceability(waste_lot, batch, harvest, drying, lot, order, delivery_ref)
        self._check_quantities_and_ledger(waste_lot, batch, harvest, lot, order)
        self._check_batch_360(batch, lot, order)
        self._check_reports_and_dashboard(batch, lot, order, delivery_ref)
        self._check_audit_trail(batch, lot, order, delivery_ref)
        self._check_outsiders_see_nothing(batch, lot, delivery_ref)

    # ---- checks ----------------------------------------------------------------------

    def _alerts_for(self, session):
        db.execute_query("UPDATE operational_alert_sync SET last_run_at = NULL")
        return self.ok(session.get(f"/api/alerts?status=all&farm_id={self.place['farm']['id']}"))["data"]

    def _check_roles_were_enforced(self, batch, output, lot, order):
        base = f"/api/production/batches/{batch['business_id']}"
        refused = [
            (self.operator, "/api/drying/quality-approvals", {"quality_check_id": 1, "decision": "approved"}),
            (self.operator, "/api/orders", {}),
            (self.qc, f"{base}/events/feeding", {}),
            (self.qc, "/api/orders", {}),
            (self.stock, "/api/inventory/movements", {
                "product_lot_id": lot["business_id"], "movement_type": "WASTAGE", "quantity_kg": "0.1",
                "from_location_id": self.bay["id"], "reason": "write-off attempt"}),
            (self.sales, f"{base}/events/feeding", {}),
            (self.sales, "/api/product-lots", {}),
            (self.manager, "/api/inventory/locations", {}),
        ]
        for session, url, body in refused:
            with self.subTest(role=session.role, url=url):
                self.assertEqual(session.post(url, body).status_code, 403)
        # The wastage attempt above was refused by role, not merely by validation.
        self.assertEqual(db.fetch_one(
            "SELECT COUNT(*) AS n FROM inventory_movements WHERE product_lot_id = %s AND movement_type = 'WASTAGE'",
            (lot["id"],))["n"], 0)
        # Operators see production but not customers or orders.
        self.assertEqual(self.operator.get("/api/orders").status_code, 403)
        self.assertEqual(self.operator.get(f"/api/orders/{order['business_id']}").status_code, 403)

    def _check_traceability(self, waste_lot, batch, harvest, drying, lot, order, delivery_ref):
        def nodes(session, ref, direction):
            data = self.ok(session.get(f"/api/traceability?ref={ref}"))["data"]
            return {(n["type"], n.get("id")): n for s in data["stages"] for n in s["nodes"]
                    if n.get("direction") == direction}, data

        upstream, _ = nodes(self.sales, delivery_ref, "upstream")
        for key in [("waste_lot", waste_lot["id"]), ("production_batch", batch["id"]),
                    ("harvest", harvest["id"]), ("drying_batch", drying["id"]),
                    ("product_lot", lot["id"]), ("customer_order", order["id"])]:
            self.assertIn(key, upstream)
            self.assertFalse(upstream[key]["restricted"], key)

        downstream, _ = nodes(self.manager, waste_lot["business_id"], "downstream")
        self.assertIn(("customer_order", order["id"]), downstream)
        self.assertTrue(any(kind == "delivery" for kind, _ in downstream))

        # Facility isolation: the QC officer only works in the drying facility, so the
        # production records behind the lot are shown as restricted placeholders.
        qc_upstream, qc_trace = nodes(self.qc, lot["business_id"], "upstream")
        self.assertTrue(qc_upstream[("drying_batch", drying["id"])]["restricted"] is False)
        hidden = [n for n in qc_upstream.values() if n["restricted"]]
        self.assertTrue(hidden)
        self.assertTrue(all("ref" not in n for n in hidden))
        self.assertGreaterEqual(qc_trace["counts"]["restricted"], 1)

        # Scanning the lot's QR label opens its page for a permitted user.
        scanned = self.sales.get(f"/scan/product_lot/{lot['business_id']}")
        self.assertEqual(scanned.status_code, 302)
        self.assertTrue(scanned.headers["Location"].endswith(f"/product-lot?ref={lot['business_id']}"))

    def _check_quantities_and_ledger(self, waste_lot, batch, harvest, lot, order):
        lot_detail = self.ok(self.manager.get(f"/api/product-lots/{lot['business_id']}"))["data"]
        self.assertAlmostEqual(float(lot_detail["quantity"]), 0.8)
        self.assertEqual(lot_detail["source_chain"][0]["waste_lot_business_id"], waste_lot["business_id"])
        inventory = lot_detail["inventory"]
        self.assertEqual([m["movement_type"] for m in inventory["movements"]], ["RECEIPT", "TRANSFER", "DISPATCH"])
        self.assertAlmostEqual(float(inventory["on_hand_kg"]), 0.3)
        balances = {b["location_id"]: b for b in inventory["balances"]}
        self.assertEqual(set(balances), {self.bay["id"]})
        self.assertAlmostEqual(float(balances[self.bay["id"]]["free_kg"]), 0.3)
        # Who recorded each movement.
        recorded_by = {m["movement_type"]: m["recorded_by"] for m in inventory["movements"]}
        self.assertEqual(recorded_by["TRANSFER"], self.stock.username)
        self.assertEqual(recorded_by["DISPATCH"], self.sales.username)

        # Mass balance down the chain: nothing appears from nowhere.
        detail = self.ok(self.manager.get(f"/api/production/batches/{batch['business_id']}"))["data"]
        self.assertAlmostEqual(float(detail["total_harvested_kg"]), 2.5)
        self.assertLessEqual(float(detail["total_harvested_kg"]), float(detail["harvest_limit_kg"]))
        self.assertEqual(detail["status"], "HARVESTED")
        self.assertEqual([u for u in detail["units"] if not u["released_at"]], [])  # bio-pod freed
        self.assertEqual(order["status"], "FULFILLED")
        self.assertAlmostEqual(order["totals"]["delivered_kg"], 0.5)
        used = db.fetch_one(
            "SELECT l.quantity, SUM(i.quantity_used) AS used FROM waste_lots l "
            "JOIN substrate_batch_inputs i ON i.waste_lot_id = l.id WHERE l.id = %s GROUP BY l.quantity",
            (waste_lot["id"],))
        self.assertAlmostEqual(float(used["used"]), 8.0)
        self.assertLessEqual(float(used["used"]), float(used["quantity"]))

    def _check_batch_360(self, batch, lot, order):
        data = self.ok(self.manager.get(f"/api/production/batches/{batch['business_id']}/360"))["data"]
        done = {s["key"]: s["done"] for s in data["stages"]}
        for key in ("source", "production", "harvest", "processing", "quality", "product", "inventory"):
            self.assertTrue(done[key], (key, done))
        self.assertIn(order["business_id"], json.dumps(data["traceability"]["downstream"]["commercial"]))
        # The operator sees the same batch without the commercial section.
        operator_view = self.ok(self.operator.get(f"/api/production/batches/{batch['business_id']}/360"))["data"]
        self.assertTrue(operator_view["traceability"]["downstream"]["commercial"]["restricted"])

    def _check_reports_and_dashboard(self, batch, lot, order, delivery_ref):
        farm = self.place["farm"]["id"]
        window = f"farm_id={farm}&date_from={day(-30)}&date_to={day(1)}"
        expected = {
            "waste_received": None, "substrate": None, "production_batches": batch["business_id"],
            "harvest": batch["business_id"], "drying": None, "quality": None,
            "inventory": lot["business_id"], "sales": order["business_id"], "deliveries": delivery_ref,
            "traceability": lot["business_id"],
        }
        for key, must_contain in expected.items():
            with self.subTest(report=key):
                report = self.ok(self.manager.get(f"/api/reports/{key}?{window}"))
                self.assertTrue(report["data"], key)
                if must_contain:
                    self.assertIn(must_contain, json.dumps(report["data"]))
                csv = self.manager.get(f"/api/reports/{key}?{window}&format=csv")
                self.assertEqual(csv.status_code, 200)
                self.assertIn("text/csv", csv.headers["Content-Type"])
        # The operator gets production reports but not sales ones.
        self.assertEqual(self.operator.get(f"/api/reports/harvest?{window}").status_code, 200)
        self.assertEqual(self.operator.get(f"/api/reports/sales?{window}").status_code, 403)

        dashboard = self.ok(self.manager.get(f"/api/dashboard?days=30&farm_id={farm}"))["data"]
        self.assertGreaterEqual(dashboard["commercial"]["delivered_kg"], 0.5)
        self.assertIsNone(self.ok(self.operator.get(f"/api/dashboard?days=30&farm_id={farm}"))["data"]["commercial"])

    def _check_audit_trail(self, batch, lot, order, delivery_ref):
        def actors(ref):
            rows = self.ok(self.admin.get(f"/api/audit?record={ref}"))["data"]
            return {(r["action"], r["actor_username"]) for r in rows}

        batch_audit = actors(batch["business_id"])
        self.assertIn(("production_batches.created", self.operator.username), batch_audit)
        self.assertIn(("production_batches.status_changed", self.operator.username), batch_audit)
        self.assertIn(("product_lots.created", self.qc.username), actors(lot["business_id"]))
        self.assertIn(("customer_orders.created", self.sales.username), actors(order["business_id"]))
        self.assertIn(("customer_deliveries.created", self.sales.username), actors(delivery_ref))
        sign_ins = self.ok(self.admin.get(f"/api/audit?action=auth.sign_in&actor={self.qc.username}"))["data"]
        self.assertTrue(sign_ins)
        # Only super admins read the audit log.
        self.assertEqual(self.manager.get("/api/audit").status_code, 403)

    def _check_outsiders_see_nothing(self, batch, lot, delivery_ref):
        outsider = self.outsider
        self.assertIn(outsider.get(f"/api/production/batches/{batch['business_id']}").status_code, (403, 404))
        self.assertIn(outsider.get(f"/api/product-lots/{lot['business_id']}").status_code, (403, 404))
        self.assertEqual(outsider.get(f"/api/traceability?ref={delivery_ref}").status_code, 404)
        listed = self.ok(outsider.get("/api/production/batches"))["data"]
        self.assertNotIn(batch["business_id"], [b["business_id"] for b in listed])
        orders = self.ok(outsider.get("/api/orders"))["data"]
        self.assertNotIn(delivery_ref, json.dumps(orders))
        self.assertEqual(outsider.get(f"/scan/product_lot/{lot['business_id']}").status_code, 404)
        self.assertFalse(db.fetch_all("SELECT 1 FROM notifications WHERE user_id = %s", (outsider.id,)))
