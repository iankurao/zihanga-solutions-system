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


ANALYTICS = pathlib.Path(__file__).resolve().parents[1] / "frontend" / "js" / "analyticsManager.js"

# Renders every legacy analytics panel with records whose every field holds
# HTML, the way an operator could type it into a legacy form.
ANALYTICS_HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
const payload = '<img src=x onerror=alert(1)>';
const container = { innerHTML: '', getContext: () => ({}) };
global.document = { getElementById: () => container };
global.Chart = function () { return { destroy() {} }; };
let current = [];
global.fetch = async () => ({ ok: true, json: async () => current });
vm.runInThisContext(fs.readFileSync(process.argv[1], 'utf8') + ';globalThis.AM = AnalyticsManager;');
(async () => {
  const leaks = [];
  for (const key of Object.keys(AM.SUBSECTIONS)) {
    const sub = AM.SUBSECTIONS[key];
    const record = {};
    sub.columns.forEach(c => { record[c.field] = payload; });
    current = [record, record];
    container.innerHTML = '';
    try { await AM.renderSubsectionPanel('panel', key); } catch (e) { leaks.push(key + ': ' + e.message); continue; }
    if (container.innerHTML.includes('<img')) leaks.push(key);
  }
  console.log(JSON.stringify(leaks));
})();
"""


@unittest.skipUnless(NODE, "Node.js is not installed")
class AnalyticsEscapingTest(unittest.TestCase):
    def test_legacy_analytics_tables_show_record_text_as_text(self):
        result = subprocess.run([NODE, "-e", ANALYTICS_HARNESS, str(ANALYTICS)],
                                capture_output=True, text=True, timeout=60, check=True)
        self.assertEqual(json.loads(result.stdout.strip().splitlines()[-1]), [])
