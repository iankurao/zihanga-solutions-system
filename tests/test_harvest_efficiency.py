import sqlite3
import unittest
from datetime import datetime
from unittest.mock import patch

from backend.database import DatabaseConnection


# Import the Flask app without requiring a running PostgreSQL database. The
# endpoint's query is exercised against SQLite below using the same schema
# columns and SQL constructs.
with patch.object(
    DatabaseConnection,
    "_initialize_pool",
    new=classmethod(lambda cls: None),
):
    from backend.app import app, db


class SQLiteDryingRecords:
    def __init__(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE drying_input (
                batch_id TEXT NOT NULL,
                wet_placed_for_drying_kg REAL NOT NULL
            );
            CREATE TABLE drying_output (
                batch_id TEXT NOT NULL,
                dried_produced_kg REAL NOT NULL,
                created_at TEXT NOT NULL
            );

            INSERT INTO drying_input (batch_id, wet_placed_for_drying_kg)
            VALUES
                ('batch-1', 100),
                ('batch-1', 200),
                ('batch-without-output', 150);

            INSERT INTO drying_output (batch_id, dried_produced_kg, created_at)
            VALUES
                ('batch-1', 50, '2026-09-20 08:00:00'),
                ('batch-1', 25, '2026-09-22 10:30:00'),
                ('batch-without-input', 40, '2026-09-23 09:00:00');
            """
        )

    def fetch_all(self, query, params=None):
        rows = self.connection.execute(query, params or ()).fetchall()
        results = []
        for row in rows:
            result = dict(row)
            result["output_date"] = datetime.fromisoformat(result["output_date"])
            results.append(result)
        return results

    def close(self):
        self.connection.close()


class HarvestEfficiencyReportTest(unittest.TestCase):
    def setUp(self):
        self.records = SQLiteDryingRecords()
        self.fetch_all_patch = patch.object(db, "fetch_all", self.records.fetch_all)
        self.fetch_all_patch.start()
        self.login_disabled = app.config.get("LOGIN_DISABLED", False)
        app.config["LOGIN_DISABLED"] = True
        self.client = app.test_client()

    def tearDown(self):
        self.fetch_all_patch.stop()
        self.records.close()
        app.config["LOGIN_DISABLED"] = self.login_disabled

    def test_sums_multiple_drying_inputs_and_outputs_without_multiplying_totals(self):
        response = self.client.get("/api/statistics/harvest-efficiency")

        self.assertEqual(response.status_code, 200)
        report = response.get_json()
        self.assertTrue(report["success"])
        self.assertEqual(
            report["data"],
            [
                {
                    "batch_id": "batch-1",
                    "drying_date": "2026-09-22",
                    "wet_placed": 300.0,
                    "dried_produced": 75.0,
                    "actual_ratio": 4.0,
                    "efficiency_status": "Inefficient",
                }
            ],
        )

    def test_omits_batches_with_drying_inputs_but_no_output(self):
        response = self.client.get("/api/statistics/harvest-efficiency")

        self.assertEqual(response.status_code, 200)
        report = response.get_json()
        self.assertTrue(report["success"])
        self.assertEqual(
            [batch["batch_id"] for batch in report["data"]],
            ["batch-1"],
        )

    def test_omits_batches_with_drying_output_but_no_input(self):
        response = self.client.get("/api/statistics/harvest-efficiency")

        self.assertEqual(response.status_code, 200)
        report = response.get_json()
        self.assertTrue(report["success"])
        self.assertEqual(
            [batch["batch_id"] for batch in report["data"]],
            ["batch-1"],
        )


if __name__ == "__main__":
    unittest.main()
