"""Location isolation at every level, administration, location setup, the
HTML sign-in and registration forms, and the page routes - with real sessions.
"""
import json
from uuid import uuid4

from support import HTTPS, ScenarioTestCase, app, db, requires_database


@requires_database
class AccessIsolationTest(ScenarioTestCase):
    """Who sees what: facility, site, farm and organization access."""

    def setUp(self):
        super().setUp()
        self.place = self.make_farm(facilities=("production", "production"))
        self.a, self.b = self.place["facilities"]
        # A second site on the same farm with its own facility.
        tag = uuid4().hex[:5]
        self.site2 = self.ok(self.admin.post("/api/locations/sites", {
            "farm_id": self.place["farm"]["id"], "site_code": f"S2{tag}", "name": f"{self.marker} site 2"}), 201)["data"]
        self.c = self.ok(self.admin.post("/api/locations/facilities", {
            "site_id": self.site2["id"], "facility_code": f"C{tag}", "name": f"{self.marker} facility C",
            "facility_type": "production"}), 201)["data"]
        self.batch_a = self.make_batch(self.admin, self.place, self.a)
        self.batch_b = self.make_batch(self.admin, self.place, self.b)
        self.batch_c = self.make_batch(self.admin, self.place, self.c, self.site2)

    def _visible(self, session):
        listed = self.ok(session.get("/api/production/batches"))["data"]
        return {b["business_id"] for b in listed} & {
            self.batch_a["business_id"], self.batch_b["business_id"], self.batch_c["business_id"]}

    def test_access_level_decides_what_each_user_sees_and_records(self):
        a, b, c = (self.batch_a["business_id"], self.batch_b["business_id"], self.batch_c["business_id"])
        users = {
            "facility A operator": (self.make_user("operator", access=[("facility", self.a["id"])]), {a}),
            "site 1 operator": (self.make_user("operator", access=[("site", self.place["site"]["id"])]), {a, b}),
            "farm manager": (self.make_user("manager", access=[("farm", self.place["farm"]["id"])]), {a, b, c}),
            "organization manager": (self.make_user(
                "manager", access=[("organization", self.place["organization"]["id"])]), {a, b, c}),
            "other farm manager": (self.make_user(
                "manager", access=[("farm", self.make_farm()["farm"]["id"])]), set()),
            "no access viewer": (self.make_user("viewer"), set()),
        }
        feeding = {"occurred_at": "2026-09-21T08:00:00+00:00", "feed_type": "mash",
                   "quantity_offered": "1", "offered_unit": "kg", "operator": "test"}
        for label, (session, expected) in users.items():
            with self.subTest(user=label):
                self.assertEqual(self._visible(session), expected)
                for ref in (a, b, c):
                    detail = session.get(f"/api/production/batches/{ref}")
                    trace = session.get(f"/api/traceability?ref={ref}")
                    if ref in expected:
                        self.assertEqual(detail.status_code, 200)
                        self.assertEqual(trace.status_code, 200)
                    else:
                        self.assertIn(detail.status_code, (403, 404))
                        self.assertEqual(trace.status_code, 404)
                if session.role == "operator":
                    self.ok(session.post(f"/api/production/batches/{a}/status", {"status": "ACTIVE"})
                            if label == "facility A operator" else
                            session.post(f"/api/production/batches/{b}/status", {"status": "ACTIVE"}))
                    outside = c
                    self.assertEqual(session.post(f"/api/production/batches/{outside}/events/feeding",
                                                  feeding).status_code, 403)

        # Commercial data needs farm or organization access as well as a sales role.
        site_manager = self.make_user("manager", access=[("site", self.place["site"]["id"])])
        farm_manager = users["farm manager"][0]
        order_body = {"customer_id": self._customer(), "farm_id": self.place["farm"]["id"],
                      "lines": [{"product_type": "dried_larvae", "quantity_kg": "1"}]}
        self.assertEqual(site_manager.post("/api/orders", order_body).status_code, 403)
        self.ok(farm_manager.post("/api/orders", order_body), 201)
        self.assertEqual(self.ok(site_manager.get("/api/orders"))["data"], [])
        self.assertEqual(len(self.ok(farm_manager.get("/api/orders"))["data"]), 1)

    def test_scoped_lists_follow_the_same_rules(self):
        operator = self.make_user("operator", access=[("facility", self.a["id"])])
        hierarchy = self.ok(operator.get("/api/locations/hierarchy"))["data"]
        self.assertEqual({r["facility_id"] for r in hierarchy if r.get("facility_id")}, {self.a["id"]})
        self.assertTrue(self.ok(operator.get(f"/api/locations/access/check?facility_id={self.a['id']}"))["allowed"])
        self.assertFalse(self.ok(operator.get(f"/api/locations/access/check?facility_id={self.b['id']}"))["allowed"])
        self.assertEqual(operator.get("/api/locations/access/check?facility_id=0").status_code, 404)
        self.assertEqual(operator.get("/api/locations/access/check").status_code, 400)
        lots = self.ok(operator.get("/api/waste-lots"))
        facilities = {row.get("facility_id") for row in (lots.get("data") or lots.get("lots") or [])}
        self.assertTrue(facilities <= {self.a["id"]}, facilities)
        report = self.ok(operator.get("/api/reports/production_batches?date_from=2026-09-01&date_to=2026-09-30"))
        self.assertIn(self.batch_a["business_id"], json.dumps(report["data"]))
        self.assertNotIn(self.batch_b["business_id"], json.dumps(report["data"]))

    def _customer(self):
        name = f"{self.marker} customer"
        self.customer_names.append(name)
        return db.execute_returning("INSERT INTO customers (name) VALUES (%s) RETURNING id", (name,))["id"]


@requires_database
class AdministrationTest(ScenarioTestCase):
    """Super-admin portal API and location setup."""

    def test_admin_portal_api(self):
        place = self.make_farm()
        farmer = self.make_user("operator", access=[("farm", place["farm"]["id"])], full_name="Grace Grower")
        for url in ("/api/admin/overview", "/api/admin/overview?days=30", "/api/admin/farmers",
                    "/api/admin/activity", "/api/admin/inactive-farmers?days=1", "/api/admin/me",
                    "/api/admin/roles", f"/api/admin/farmer/{farmer.username}/stats"):
            with self.subTest(url=url):
                self.assertEqual(self.admin.get(url).status_code, 200, url)
                self.assertEqual(farmer.get(url).status_code, 403, url)
        self.assertEqual(self.admin.get("/api/admin/farmer/nobody-here/stats").status_code, 404)
        farmers = self.ok(self.admin.get("/api/admin/farmers"))["data"]
        self.assertIn(farmer.username, [f["username"] for f in farmers])
        self.assertNotIn(self.admin.username, [f["username"] for f in farmers])  # super admins are not listed
        export = self.admin.get("/api/admin/farmers/export")
        self.assertEqual(export.status_code, 200)
        self.assertIn(farmer.username, export.get_data(as_text=True))

        # Deactivating ends the session and blocks sign-in; reactivating restores it.
        toggled = self.ok(self.admin.post(f"/api/admin/users/{farmer.id}/toggle"))
        self.assertFalse(toggled["is_active"])
        self.assertEqual(farmer.get("/api/me").status_code, 401)
        blocked = farmer.client.post("/api/auth/login", json={"username": farmer.email, "password": farmer.password}, **HTTPS)
        self.assertEqual(blocked.status_code, 401)
        self.assertTrue(self.ok(self.admin.post(f"/api/admin/users/{farmer.id}/toggle"))["is_active"])
        farmer.sign_in()
        self.assertEqual(farmer.get("/api/me").status_code, 200)

        # Super admins cannot be toggled, edited or deleted through the portal.
        for call in (lambda: self.admin.post(f"/api/admin/users/{self.admin.id}/toggle"),
                     lambda: self.admin.delete(f"/api/admin/users/{self.admin.id}")):
            self.assertEqual(call().status_code, 404)
        deleted = self.admin.delete(f"/api/admin/users/{farmer.id}")
        self.assertEqual(deleted.status_code, 200, deleted.get_json())
        self.assertIsNone(db.fetch_one("SELECT 1 FROM users WHERE user_id = %s", (farmer.id,)))

    def test_low_stock_minimums(self):
        place = self.make_farm()
        manager = self.make_user("manager", access=[("farm", place["farm"]["id"])])
        outsider = self.make_user("manager", access=[("farm", self.make_farm()["farm"]["id"])])
        body = {"farm_id": place["farm"]["id"], "product_type": "dried_larvae", "minimum_kg": "25"}
        self.assertEqual(manager.put("/api/alerts/thresholds", body).status_code, 403)
        self.ok(self.admin.put("/api/alerts/thresholds", body))
        mine = self.ok(manager.get("/api/alerts/thresholds"))["data"]
        self.assertEqual([(t["product_type"], float(t["minimum_kg"])) for t in mine], [("dried_larvae", 25.0)])
        self.assertEqual(self.ok(outsider.get("/api/alerts/thresholds"))["data"], [])
        self.assertEqual(manager.delete(f"/api/alerts/thresholds/{mine[0]['id']}").status_code, 403)
        self.ok(self.admin.delete(f"/api/alerts/thresholds/{mine[0]['id']}"))
        self.assertEqual(self.ok(manager.get("/api/alerts/thresholds"))["data"], [])
        self.assertEqual(self.admin.delete(f"/api/alerts/thresholds/{mine[0]['id']}").status_code, 404)

    def test_location_setup_status_and_grants(self):
        place = self.make_farm()
        facility = place["facilities"][0]
        manager = self.make_user("manager")
        self.assertEqual(manager.post("/api/locations/organizations", {"organization_code": "X", "name": "X"})
                         .status_code, 403)
        duplicate = self.admin.post("/api/locations/organizations", {
            "organization_code": place["organization"]["organization_code"], "name": "again"})
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(self.admin.post("/api/locations/farms", {"organization_id": "x", "farm_code": "A",
                                                                   "name": "A"}).status_code, 400)
        self.assertEqual(self.admin.post("/api/locations/facilities", {"site_id": 0, "facility_code": "A",
                                                                        "name": "A", "facility_type": "production"})
                         .status_code, 404)

        self.ok(self.admin.post("/api/locations/access", {
            "user_id": manager.id, "scope": "facility", "scope_id": facility["id"]}), 201)
        access = self.ok(self.admin.get(f"/api/locations/users/{manager.id}/access"))["data"]
        self.assertEqual([f["id"] for f in access["facility"]], [facility["id"]])
        self.assertEqual(manager.get(f"/api/locations/users/{manager.id}/access").status_code, 403)
        revoke = self.admin.delete("/api/locations/access", {
            "user_id": manager.id, "scope": "facility", "scope_id": facility["id"]})
        self.assertEqual(revoke.status_code, 200)
        self.assertEqual(self.ok(self.admin.get(f"/api/locations/users/{manager.id}/access"))["data"]["facility"], [])

        # Deactivated facilities stop taking new work; their records are kept.
        self.ok(self.admin.post(f"/api/locations/facility/{facility['id']}/status", {"status": "inactive"}))
        refused = self.admin.post("/api/waste-sourcing", {
            **self.scope(place, facility), "collection_date": "2026-09-20", "collection_time": "07:00",
            "source_type": "market", "source_name": "x", "waste_type": "vegetable", "waste_weight": "1",
            "segregation_status": "organic", "collection_personnel": "x", "lot_status": "available",
            "contaminants_found": []})
        self.assertEqual(refused.status_code, 400, refused.get_json())
        self.assertEqual(self.admin.post(f"/api/locations/facility/{facility['id']}/status", {"status": "gone"})
                         .status_code, 400)
        self.assertEqual(self.admin.post("/api/locations/planet/1/status", {"status": "active"}).status_code, 400)


@requires_database
class SignInFormsAndPagesTest(ScenarioTestCase):
    """The HTML forms and page routes, as browsers use them."""

    def test_no_self_registration_and_sign_in_form_messages(self):
        client = app.test_client()
        users = db.fetch_one("SELECT COUNT(*) AS n FROM users")["n"]
        # Accounts come from an administrator; old registration links land on sign-in.
        old_link = client.get("/register", **HTTPS)
        self.assertEqual(old_link.status_code, 302)
        self.assertTrue(old_link.headers["Location"].endswith("/login"))
        self.assertEqual(client.post("/register", data={"username": "x"}, **HTTPS).status_code, 405)
        self.assertIn(client.post("/api/auth/register", json={
            "username": "selfmade", "fullName": "Self Made", "email": "selfmade@example.com",
            "password": "a long pass phrase", "confirmPassword": "a long pass phrase"}, **HTTPS).status_code,
            (404, 405))
        self.assertIn(client.get("/register.html", **HTTPS).status_code, (404,))
        self.assertEqual(db.fetch_one("SELECT COUNT(*) AS n FROM users")["n"], users)

        page = client.get("/login", **HTTPS)
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Ask your farm administrator", page.data)
        self.assertNotIn(b"Register here", page.data)

        person = self.make_user("viewer")
        wrong = client.post("/login", data={"email": person.email, "password": "not it"}, **HTTPS)
        self.assertEqual(wrong.status_code, 200)  # form shown again, with the reason
        self.assertIn(b"Invalid email or password", wrong.data)
        signed_in = client.post("/login?next=/labels", data={"email": person.email, "password": person.password},
                                **HTTPS)
        self.assertEqual(signed_in.status_code, 302)
        self.assertTrue(signed_in.headers["Location"].endswith("/labels"))
        self.assertEqual(client.get("/api/me", **HTTPS).get_json()["data"]["home"], "/operations")
        out = client.get("/logout", **HTTPS)
        self.assertEqual(out.status_code, 302)
        self.assertEqual(client.get("/api/me", **HTTPS).status_code, 401)
        self.assertIn(b"You have been logged out", client.get("/login", **HTTPS).data)

    def test_pages_and_static_files(self):
        operator = self.make_user("operator")
        anonymous = app.test_client()
        public = ["/", "/css/erp.css", "/js/ui.js", "/images/logo.png"]
        signed_in = ["/dashboard", "/operations", "/analytics", "/batch-360", "/traceability", "/labels",
                     "/product-lot", "/alerts", "/farmer", "/design-system", "/production_batch.html"]
        for url in public:
            self.assertEqual(anonymous.get(url, **HTTPS).status_code, 200, url)
        for url in signed_in:
            with self.subTest(url=url):
                self.assertEqual(operator.get(url).status_code, 200, url)
                if url != "/production_batch.html":  # static file; its data APIs need sign-in
                    redirect = anonymous.get(url, **HTTPS)
                    self.assertEqual(redirect.status_code, 302, url)
                    self.assertIn("/login?next=", redirect.headers["Location"])
        # Admin-only pages.
        self.assertEqual(operator.get("/zehunger").status_code, 302)  # sent back to their workspace
        self.assertEqual(operator.get("/setup").status_code, 403)
        self.assertEqual(operator.get("/audit").status_code, 403)
        self.assertEqual(operator.get("/orders").status_code, 200)  # page shell; data needs sales.read
        for url in ("/zehunger", "/setup", "/audit"):
            self.assertEqual(self.admin.get(url).status_code, 200, url)
        # The static route never serves files outside the frontend folder.
        for url in ("/../backend/app.py", "/%2e%2e/backend/app.py", "/..%2fbackend/config.py"):
            self.assertEqual(anonymous.get(url, **HTTPS).status_code, 404, url)
        self.assertEqual(anonymous.get("/no-such-page.html", **HTTPS).status_code, 404)
