"""Front-end logic that does not need a browser: js/ui.js status tones and labels.

Runs the real script in Node (skipped when Node is not installed).
"""
import json
import pathlib
import shutil
import subprocess
import unittest

UI = pathlib.Path(__file__).resolve().parents[1] / "frontend" / "js" / "ui.js"
NODE = shutil.which("node")

HARNESS = """
global.window = {};
require(process.argv[1]);
const ui = window.ErpUI;
const cases = JSON.parse(process.argv[2]);
console.log(JSON.stringify({
  tones: cases.tones.map(s => ui.statusTone(s)),
  labels: cases.labels.map(s => ui.humanize(s)),
}));
"""


@unittest.skipUnless(NODE, "Node.js is not installed")
class UiLogicTest(unittest.TestCase):
    def run_ui(self, tones, labels):
        result = subprocess.run(
            [NODE, "-e", HARNESS, str(UI), json.dumps({"tones": tones, "labels": labels})],
            capture_output=True, text=True, timeout=30, check=True,
        )
        return json.loads(result.stdout)

    def test_status_tones_have_one_meaning_everywhere(self):
        cases = {
            "COMPLETED": "success", "APPROVED": "success", "released": "success", "Delivered": "success",
            "ACTIVE": "info", "READY_FOR_HARVEST": "info", "DISPATCHED": "info", "low": "info",
            "PLANNED": "warning", "QC_PENDING": "warning", "OPEN": "warning", "conditional": "warning",
            "CANCELLED": "danger", "HEALTH_ALERT": "danger", "rejected": "danger", "critical": "danger",
            "closed": "neutral", "consumed": "neutral", "retired": "neutral", "": "neutral",
            # Unknown values fall back on their wording, never to "done".
            "partially_rejected": "danger", "awaiting_payment": "warning", "something_new": "neutral",
        }
        result = self.run_ui(list(cases), [])
        self.assertEqual(dict(zip(cases, result["tones"])), cases)

    def test_labels_are_human_readable(self):
        result = self.run_ui([], ["READY_FOR_HARVEST", "dried_larvae", "", None])
        self.assertEqual(result["labels"], ["Ready for harvest", "Dried larvae", "", ""])
