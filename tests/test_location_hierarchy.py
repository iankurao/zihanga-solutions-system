import unittest
from pathlib import Path


class LocationHierarchyMigrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.migration = Path("backend/migrations/farm_site_facility.sql").read_text()
        cls.audit = (Path(__file__).resolve().parents[1] / "docs" / "history" / "FARM_FACILITY_CURRENT_STATE.md").read_text()

    def test_migration_defines_canonical_parent_chain(self):
        expected_tables = (
            "organizations",
            "farms",
            "sites",
            "facilities",
            "operational_location_links",
        )
        for table in expected_tables:
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", self.migration)
        self.assertIn("organization_id INTEGER NOT NULL REFERENCES organizations(id)", self.migration)
        self.assertIn("farm_id INTEGER NOT NULL REFERENCES farms(id)", self.migration)
        self.assertIn("site_id INTEGER NOT NULL REFERENCES sites(id)", self.migration)
        self.assertIn("facility_id INTEGER NOT NULL REFERENCES facilities(id)", self.migration)

    def test_migration_defines_access_at_each_scope(self):
        for table in (
            "user_organization_access",
            "user_farm_access",
            "user_site_access",
            "user_facility_access",
        ):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", self.migration)

    def test_migration_does_not_guess_legacy_locations(self):
        self.assertIn("does not backfill guessed relationships", self.audit)
        self.assertNotIn("INSERT INTO organizations", self.migration)
        self.assertNotIn("UPDATE waste_lots", self.migration)