"""Design-system guards for the frontend (no database needed).

Every page uses css/erp.css and the shared navigation, page stylesheets do
not bring back their own palettes, page scripts render through js/ui.js
instead of retired per-page classes, the tokens meet WCAG contrast, and every
status value the database can hold has a deliberate badge colour.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"

# Pages that are not part of the signed-in app shell.
SIGNED_OUT = {"main.html", "login.html", "register.html"}


def _read(path):
    return path.read_text(encoding="utf-8")


def _luminance(hex_colour):
    value = hex_colour.lstrip("#")
    channels = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(a, b):
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


class FrontendDesignSystemTest(unittest.TestCase):
    def setUp(self):
        self.pages = {p.name: _read(p) for p in FRONTEND.glob("*.html")}
        self.tokens = dict(re.findall(r"--(erp-[\w-]+):\s*(#[0-9a-fA-F]{6})", _read(FRONTEND / "css" / "erp.css")))

    def test_every_page_loads_the_design_system(self):
        missing = [name for name, html in self.pages.items() if "/css/erp.css" not in html]
        self.assertEqual(missing, [])

    def test_signed_in_pages_use_the_shared_navigation(self):
        problems = []
        for name, html in self.pages.items():
            if name in SIGNED_OUT:
                continue
            if "data-erp-nav" not in html:
                problems.append(f"{name}: no <header data-erp-nav>")
                continue
            nav = html.find("appNav.js")
            permissions = html.find("permissions.js")
            if nav == -1 or permissions == -1 or permissions > nav:
                problems.append(f"{name}: load permissions.js before appNav.js")
        self.assertEqual(problems, [])

    def test_pages_using_erp_ui_load_it_first(self):
        problems = []
        for name, html in self.pages.items():
            scripts = re.findall(r'<script src="/?js/([\w.]+)"', html)
            users = [s for s in scripts if s != "ui.js" and "ErpUI." in _read(FRONTEND / "js" / s)]
            inline_uses = "ErpUI." in "".join(re.findall(r"<script>(.*?)</script>", html, re.S))
            if (users or inline_uses) and ("ui.js" not in scripts or any(
                    scripts.index(s) < scripts.index("ui.js") for s in users)):
                problems.append(name)
        self.assertEqual(problems, [])

    def test_page_styles_do_not_bring_back_old_palettes(self):
        retired = ["#2ecc71", "#27ae60", "#2c3e50", "#34495e", "#7f8c8d", "#cad8ce", "#16a34a", "#94a3b8"]
        found = {}
        for path in list((FRONTEND / "css").glob("*.css")) + list(FRONTEND.glob("*.html")):
            text = _read(path).lower()
            hits = [c for c in retired if c in text]
            if hits:
                found[path.name] = hits
        self.assertEqual(found, {})

    def test_scripts_do_not_use_retired_component_classes(self):
        retired = ["b360-pill", "b360-table", "b360-empty", "b360-facts", "b360-message", "b360-welcome",
                   "orders-primary", "orders-secondary", "orders-danger", "trace-form", "trace-field",
                   "farmer-primary", "farmer-secondary", "farmer-pill", "farmer-empty"]
        found = {}
        for path in list((FRONTEND / "js").glob("*.js")) + list(FRONTEND.glob("*.html")):
            text = _read(path)
            hits = [c for c in retired if re.search(r"(?<![\w-])" + re.escape(c) + r"(?![\w-])", text)]
            if hits:
                found[path.name] = hits
        self.assertEqual(found, {})

    def test_design_tokens_meet_wcag_contrast(self):
        t = self.tokens
        text_pairs = [
            ("erp-ink", "erp-page"), ("erp-ink", "erp-surface"), ("erp-muted", "erp-surface"),
            ("erp-muted", "erp-page"), ("erp-accent", "erp-surface"), ("erp-on-brand", "erp-brand"),
            ("erp-on-brand-muted", "erp-brand"), ("erp-success-ink", "erp-success-soft"),
            ("erp-info-ink", "erp-info-soft"), ("erp-warning-ink", "erp-warning-soft"),
            ("erp-danger-ink", "erp-danger-soft"), ("erp-neutral-ink", "erp-neutral-soft"),
        ]
        weak = [(a, b, round(_contrast(t[a], t[b]), 2)) for a, b in text_pairs if _contrast(t[a], t[b]) < 4.5]
        # White text on filled buttons.
        weak += [("white", b, round(_contrast("#ffffff", t[b]), 2)) for b in ("erp-accent", "erp-danger")
                 if _contrast("#ffffff", t[b]) < 4.5]
        # Control borders and the focus ring are UI components: 3:1.
        weak += [(a, "erp-surface", round(_contrast(t[a], t["erp-surface"]), 2)) for a in ("erp-control", "erp-focus")
                 if _contrast(t[a], t["erp-surface"]) < 3]
        self.assertEqual(weak, [])

    def test_every_schema_status_has_a_deliberate_badge_tone(self):
        ui = _read(FRONTEND / "js" / "ui.js")
        tones = {}
        for tone, body in re.findall(r"(success|info|warning|danger): \[([^\]]*)\]", ui):
            for value in re.findall(r"'([^']+)'", body):
                tones[value] = tone
        neutral = re.search(r"Anything else \(([^)]*)\)", ui).group(1)
        neutral_values = {v.strip() for v in neutral.replace("...", "").split(",") if v.strip()}
        schema = set()
        for sql in (ROOT / "backend" / "migrations").glob("*.sql"):
            for column, values in re.findall(r"CHECK \((status|decision|severity)\s+IN \(([^)]*)\)", _read(sql)):
                schema.update(v.lower() for v in re.findall(r"'([^']+)'", values))
        missing = sorted(v for v in schema if v not in tones and v not in neutral_values)
        self.assertEqual(missing, [], "add these to the TONES table in js/ui.js (or the neutral list)")


if __name__ == "__main__":
    unittest.main()
