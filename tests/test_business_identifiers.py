import os
import re
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

try:
    import psycopg2
except ImportError:  # pragma: no cover - dependency is supplied by the app
    psycopg2 = None

from backend.business_identifiers import BUSINESS_ID_SPECS, business_id_expression


class BusinessIdentifierDefinitionTest(unittest.TestCase):
    def test_all_phase_one_formats_are_canonical(self):
        expected = {
            "waste_lot": "WL",
            "substrate_batch": "SUB",
            "production_batch": "BSF",
            "harvest": "HRV",
            "drying_batch": "DRY",
            "product_lot": "LOT",
            "inventory_movement": "MOV",
        }
        self.assertEqual(
            {name: spec["prefix"] for name, spec in BUSINESS_ID_SPECS.items()},
            expected,
        )
        for entity, prefix in expected.items():
            expression = business_id_expression(entity)
            self.assertIn(f"'{prefix}-'", expression)
            self.assertIn("nextval(", expression)
            self.assertIn("lpad(", expression)

    def test_migration_does_not_use_max_plus_one_for_runtime_ids(self):
        migration = Path("backend/migrations/phase_one_business_identifiers.sql").read_text()
        self.assertNotRegex(migration, r"MAX\s*\([^)]*\)\s*\+\s*1")
        self.assertIn("CREATE SEQUENCE IF NOT EXISTS phase_one_waste_lot_seq", migration)
        self.assertIn("ALTER TABLE waste_sourcing", migration)


@unittest.skipUnless(
    psycopg2 is not None and (os.getenv("DATABASE_URL") or os.getenv("PGHOST")),
    "PostgreSQL connection is not configured",
)
class ConcurrentBusinessIdentifierTest(unittest.TestCase):
    """Integration test proving sequence-backed INSERTs stay unique concurrently."""

    @classmethod
    def setUpClass(cls):
        cls.suffix = uuid4().hex[:12]
        cls.table_name = f"phase_one_id_test_{cls.suffix}"
        cls.sequence_name = f"phase_one_id_seq_{cls.suffix}"
        cls.connection = psycopg2.connect(os.getenv("DATABASE_URL"))
        cls.connection.autocommit = True
        with cls.connection.cursor() as cursor:
            cursor.execute(f"CREATE SEQUENCE {cls.sequence_name} AS BIGINT")
            cursor.execute(
                f"""
                CREATE TABLE {cls.table_name} (
                    id SERIAL PRIMARY KEY,
                    business_id VARCHAR(30) NOT NULL DEFAULT (
                        'WL-' || to_char(CURRENT_DATE, 'YYYY') || '-' ||
                        lpad(nextval('{cls.sequence_name}')::text, 5, '0')
                    )
                )
                """
            )

    @classmethod
    def tearDownClass(cls):
        with cls.connection.cursor() as cursor:
            cursor.execute(f"DROP TABLE IF EXISTS {cls.table_name}")
            cursor.execute(f"DROP SEQUENCE IF EXISTS {cls.sequence_name}")
        cls.connection.close()

    @classmethod
    def _insert_one(cls):
        connection = psycopg2.connect(os.getenv("DATABASE_URL"))
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"INSERT INTO {cls.table_name} DEFAULT VALUES RETURNING business_id"
                )
                value = cursor.fetchone()[0]
            connection.commit()
            return value
        finally:
            connection.close()

    def test_concurrent_inserts_receive_unique_business_ids(self):
        with ThreadPoolExecutor(max_workers=8) as executor:
            values = list(executor.map(lambda _: self._insert_one(), range(40)))

        self.assertEqual(len(values), len(set(values)))
        self.assertTrue(all(re.fullmatch(r"WL-\d{4}-\d{5}", value) for value in values))