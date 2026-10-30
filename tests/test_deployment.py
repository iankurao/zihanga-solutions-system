"""Deployment readiness: settings checks, production start-up guard, database
configuration, health endpoints, the readiness command, backup / restore
scripts and the deployment files.
"""
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
from unittest import mock

from backend import preflight
from tests.support import HTTPS, app, db, requires_database

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
BASH = shutil.which("bash")

GOOD = {
    "APP_ENV": "production",
    "SECRET_KEY": "k" * 24 + "Q7pZr2Lm9xWv4Ns8Jt3B",
    "DATABASE_URL": "postgresql://zehunger:pw@localhost:5432/zehunger",
    "PUBLIC_BASE_URL": "https://erp.example.com",
    "EMAIL_HOST_USER": "alerts@example.com",
    "EMAIL_HOST_PASSWORD": "app-password",
}


def levels(env):
    return {name: level for level, name, _ in preflight.settings_checks(env)}


class SettingsChecksTest(unittest.TestCase):
    def test_a_complete_production_configuration_passes(self):
        results = preflight.settings_checks(GOOD)
        self.assertEqual([r for r in results if r[0] != preflight.PASS], [])
        self.assertEqual(preflight.fatal_settings(GOOD), [])

    def test_unsafe_settings_fail(self):
        cases = {
            "secret_key": [{"SECRET_KEY": ""}, {"SECRET_KEY": "short"},
                           {"SECRET_KEY": "dev-only-not-secret-but-quite-long-enough-0123"},
                           {"SECRET_KEY": "please-change-me-before-going-live-0123456789"}],
            "database_url": [{"DATABASE_URL": ""}, {"DATABASE_URL": "mysql://u@h/db"}],
            "cookies": [{"SESSION_COOKIE_SECURE": "0"}, {"SESSION_COOKIE_SECURE": "false"}],
            "cors": [{"CORS_ORIGINS": "*"}, {"CORS_ORIGINS": "https://ok.example, http://plain.example"}],
            "proxy": [{"TRUSTED_PROXY_COUNT": "one"}],
        }
        for name, variants in cases.items():
            for change in variants:
                with self.subTest(name=name, change=change):
                    env = {**GOOD, **change}
                    self.assertEqual(levels(env)[name], preflight.FAIL)
                    self.assertTrue(preflight.fatal_settings(env))
        # SESSION_SECRET is an accepted name for the key.
        env = {k: v for k, v in GOOD.items() if k != "SECRET_KEY"}
        env["SESSION_SECRET"] = GOOD["SECRET_KEY"]
        self.assertEqual(levels(env)["secret_key"], preflight.PASS)

    def test_risky_but_workable_settings_warn(self):
        cases = {
            "database_url": {"DATABASE_URL": "postgresql://u:p@db.example.net/zehunger"},
            "public_base_url": {"PUBLIC_BASE_URL": "http://erp.example.com"},
            "email": {"EMAIL_HOST_PASSWORD": ""},
            "demo_guest": {"DEMO_GUEST_ACCESS": "1"},
            "app_env": {"APP_ENV": "development"},
            "proxy": {"TRUSTED_PROXY_COUNT": "0"},
        }
        for name, change in cases.items():
            with self.subTest(name=name):
                env = {**GOOD, **change}
                self.assertEqual(levels(env)[name], preflight.WARN)
                self.assertEqual(preflight.fatal_settings(env), [])
        remote_tls = {**GOOD, "DATABASE_URL": "postgresql://u:p@db.example.net/zehunger?sslmode=require"}
        self.assertEqual(levels(remote_tls)["database_url"], preflight.PASS)
        unset = {k: v for k, v in GOOD.items() if k != "PUBLIC_BASE_URL"}
        self.assertEqual(levels(unset)["public_base_url"], preflight.WARN)


def run_python(code, **env):
    return subprocess.run([sys.executable, "-c", code], cwd=ROOT, env={**os.environ, **env},
                          capture_output=True, text=True, timeout=120)


class ProductionStartupTest(unittest.TestCase):
    def test_production_refuses_to_start_with_unsafe_settings(self):
        result = run_python("import backend.app", APP_ENV="production", SECRET_KEY="", SESSION_SECRET="",
                            SESSION_COOKIE_SECURE="0")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Refusing to start in production", result.stderr)
        self.assertIn("SECRET_KEY is not set", result.stderr)
        self.assertIn("SESSION_COOKIE_SECURE is off", result.stderr)

    def test_development_still_starts_with_the_same_settings(self):
        code = ("from unittest import mock\n"
                "from backend.database import DatabaseConnection\n"
                "with mock.patch.object(DatabaseConnection, '_initialize_pool', new=classmethod(lambda cls: None)):\n"
                "    import backend.app\n"
                "print('started')\n")
        result = run_python(code, APP_ENV="", SECRET_KEY="", SESSION_SECRET="", SESSION_COOKIE_SECURE="0")
        self.assertEqual(result.returncode, 0, result.stderr[-1500:])
        self.assertIn("started", result.stdout)

    def test_database_url_takes_priority_over_pg_variables(self):
        code = ("from backend.config import DB_CONFIG, DB_POOL_MAX\n"
                "print(sorted(DB_CONFIG), DB_POOL_MAX)\n")
        result = run_python(code, DATABASE_URL="postgresql://u:p@h:5432/real?sslmode=require",
                            PGDATABASE="other", DB_POOL_MAX="")
        self.assertEqual(result.stdout.strip(), "['dsn'] 10")
        result = run_python(code, DATABASE_URL="", PGDATABASE="other", DB_POOL_MAX="6")
        self.assertEqual(result.stdout.strip(), "['database', 'host', 'password', 'port', 'user'] 6")

    def test_no_hosting_platform_setting_can_weaken_cookies_or_framing(self):
        # EMBEDDED_PREVIEW (an old hosting-preview iframe switch) is gone: an
        # old environment file that still sets it changes nothing.
        code = """
from unittest import mock
from backend.database import DatabaseConnection
with mock.patch.object(DatabaseConnection, '_initialize_pool', new=classmethod(lambda cls: None)):
    from backend.app import app
c = app.config
r = app.test_client().get('/healthz', base_url='https://localhost')
print(c['SESSION_COOKIE_SAMESITE'], c['REMEMBER_COOKIE_SAMESITE'], c['SESSION_COOKIE_SECURE'],
      r.headers.get('X-Frame-Options'))
"""
        result = run_python(code, EMBEDDED_PREVIEW="1")
        self.assertEqual(result.returncode, 0, result.stderr[-1500:])
        self.assertEqual(result.stdout.strip().splitlines()[-1], "Lax Lax True SAMEORIGIN")

    @requires_database
    def test_the_pool_connects_to_the_database_url_even_if_pg_variables_differ(self):
        expected = db.fetch_one("SELECT current_database() AS name")["name"]
        result = run_python("from backend.database import DatabaseConnection\n"
                            "print(DatabaseConnection().fetch_one('SELECT current_database() AS n')['n'])\n",
                            PGDATABASE="no_such_database_for_this_test")
        self.assertEqual(result.returncode, 0, result.stderr[-1500:])
        self.assertEqual(result.stdout.strip().splitlines()[-1], expected)


class HealthEndpointTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_liveness_never_needs_the_database(self):
        with mock.patch.object(db, "fetch_one", side_effect=RuntimeError("database down")):
            response = self.client.get("/healthz", **HTTPS)
        self.assertEqual((response.status_code, response.get_json()), (200, {"status": "ok"}))
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_readiness_fails_closed_without_details(self):
        with mock.patch.object(db, "fetch_one", side_effect=RuntimeError("password authentication failed")):
            response = self.client.get("/readyz", **HTTPS)
        self.assertEqual((response.status_code, response.get_json()), (503, {"status": "unavailable"}))
        self.assertNotIn(b"password", response.data)

    @requires_database
    def test_readiness_checks_the_schema(self):
        response = self.client.get("/readyz", **HTTPS)
        self.assertEqual((response.status_code, response.get_json()), (200, {"status": "ok"}))
        with mock.patch("backend.domains.health.REQUIRED_TABLES", preflight.REQUIRED_TABLES + ("no_such_table",)):
            self.assertEqual(self.client.get("/readyz", **HTTPS).status_code, 503)
        with mock.patch("backend.domains.health.REQUIRED_MARKERS", ("no_such_marker",)):
            self.assertEqual(self.client.get("/readyz", **HTTPS).status_code, 503)

    def test_health_endpoints_are_public_and_read_only(self):
        for path in ("/healthz", "/readyz"):
            rule = next(r for r in app.url_map.iter_rules() if r.rule == path)
            self.assertEqual(set(rule.methods) - {"HEAD", "OPTIONS"}, {"GET"})


@requires_database
class DatabaseChecksTest(unittest.TestCase):
    def test_the_test_database_is_ready(self):
        results = {name: (level, message) for level, name, message in preflight.database_checks(db, GOOD)}
        for name in ("database", "schema", "audit"):
            self.assertEqual(results[name][0], preflight.PASS, results[name][1])
        self.assertIn("connections", results)

    def test_a_missing_table_is_reported_with_the_fix(self):
        with mock.patch.object(preflight, "REQUIRED_TABLES", preflight.REQUIRED_TABLES + ("no_such_table",)):
            results = {name: (level, message) for level, name, message in preflight.database_checks(db, GOOD)}
        self.assertEqual(results["schema"][0], preflight.FAIL)
        self.assertIn("no_such_table", results["schema"][1])
        self.assertIn("backend.init_db", results["schema"][1])

    def test_an_unreachable_database_fails_without_leaking_the_error(self):
        broken = mock.Mock()
        broken.fetch_one.side_effect = RuntimeError("password authentication failed for user x")
        results = preflight.database_checks(broken, GOOD)
        self.assertEqual(results, [(preflight.FAIL, "database", "Cannot reach the database: RuntimeError.")])

    def test_connection_budget_is_checked_against_max_connections(self):
        results = {name: level for level, name, _ in preflight.database_checks(db, {**GOOD, "WEB_CONCURRENCY": "40"})}
        self.assertEqual(results["connections"], preflight.WARN)

    def test_command_exit_code_follows_failures(self):
        weak = subprocess.run([sys.executable, "-m", "backend.preflight"], cwd=ROOT, capture_output=True,
                              text=True, timeout=120, env={**os.environ, "SECRET_KEY": "", "SESSION_SECRET": ""})
        self.assertEqual(weak.returncode, 1)
        self.assertIn("FAIL  secret_key", weak.stdout)
        self.assertIn("Not ready to deploy.", weak.stdout)


# ---- backup / restore scripts (run with stand-in PostgreSQL tools) -------------------

STUB_PG_DUMP = """#!/usr/bin/env bash
for arg in "$@"; do case "$arg" in --file=*) out="${arg#--file=}";; esac; done
[ "${STUB_DUMP_FAIL:-}" = 1 ] && { echo "pg_dump: connection refused" >&2; exit 1; }
printf 'PGDMP fake dump\\n' > "$out"
"""
STUB_PG_RESTORE = """#!/usr/bin/env bash
if [ "$1" = "--list" ]; then
  for t in ${STUB_TABLES:-users audit_log production_batches product_lots inventory_movements customer_orders}; do
    echo "1; 0 1 TABLE DATA public $t postgres"
  done
  exit 0
fi
echo restored >> "$STUB_LOG"
"""
# Like psql builds without argument reordering (e.g. Windows): options after
# the database are ignored, so the scripts must name it with --dbname=.
STUB_PSQL = """#!/usr/bin/env bash
case "$1" in --dbname=*) ;; *) echo "psql: options after the database were ignored" >&2; exit 2;; esac
echo "${STUB_TABLE_COUNT:-0}"
"""


@unittest.skipUnless(BASH, "bash is not installed")
class BackupScriptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        for name, body in (("pg_dump", STUB_PG_DUMP), ("pg_restore", STUB_PG_RESTORE), ("psql", STUB_PSQL)):
            path = bin_dir / name
            path.write_text(body, newline="\n")
            path.chmod(0o755)
        self.backups = self.tmp / "backups"
        self.backups.mkdir()
        self.log = self.tmp / "log.txt"
        self.env = {**os.environ, "DATABASE_URL": "postgresql://u@localhost/z", "BACKUP_DIR": self.posix(self.backups),
                    "STUB_LOG": self.posix(self.log)}
        self.path_prefix = self.posix(bin_dir)

    @staticmethod
    def posix(path):
        text = str(path).replace("\\", "/")
        return re.sub(r"^([A-Za-z]):", lambda m: "/" + m.group(1).lower(), text) if os.name == "nt" else text

    def bash(self, script, *args, **env):
        command = f'export PATH="{self.path_prefix}:$PATH"; exec bash "$0" "$@"'
        return subprocess.run([BASH, "-c", command, self.posix(DEPLOY / script), *args],
                              env={**self.env, **env}, capture_output=True, text=True, timeout=60)

    def old_backup(self, name, days):
        path = self.backups / name
        path.write_text("old")
        stamp = time.time() - days * 86400
        os.utime(path, (stamp, stamp))
        return path

    def test_backup_is_verified_named_and_old_ones_are_pruned(self):
        stale = self.old_backup("zehunger-20200101T000000Z.dump", 30)
        recent = self.old_backup("zehunger-20991231T000000Z.dump", 2)
        other = self.old_backup("keep-me.txt", 30)
        result = self.bash("backup.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        made = [p for p in self.backups.glob("zehunger-*.dump") if p not in (recent,)]
        self.assertEqual(len(made), 1)
        self.assertRegex(made[0].name, r"^zehunger-\d{8}T\d{6}Z\.dump$")
        self.assertIn("Backup written", result.stdout)
        self.assertFalse(stale.exists())
        self.assertTrue(recent.exists() and other.exists())
        self.assertEqual(list(self.backups.glob("*.partial")), [])

    def test_an_incomplete_dump_fails_and_keeps_old_backups(self):
        stale = self.old_backup("zehunger-20200101T000000Z.dump", 30)
        result = self.bash("backup.sh", STUB_TABLES="users production_batches")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Backup check failed", result.stderr)
        self.assertEqual(sorted(p.name for p in self.backups.iterdir()), [stale.name])
        failed = self.bash("backup.sh", STUB_DUMP_FAIL="1")
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(sorted(p.name for p in self.backups.iterdir()), [stale.name])

    def test_restore_drill_refuses_a_database_that_has_tables(self):
        dump = self.backups / "zehunger-20260101T000000Z.dump"
        dump.write_text("PGDMP")
        result = self.bash("restore-check.sh", self.posix(dump),
                           RESTORE_DATABASE_URL="postgresql://u@localhost/live", STUB_TABLE_COUNT="42")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Refusing", result.stderr)
        self.assertFalse(self.log.exists(), "nothing may be restored into a database with tables")
        missing = self.bash("restore-check.sh", RESTORE_DATABASE_URL="postgresql://u@localhost/x")
        self.assertNotEqual(missing.returncode, 0)

    def test_restore_drill_restores_into_an_empty_database(self):
        dump = self.backups / "zehunger-20260101T000000Z.dump"
        dump.write_text("PGDMP")
        # The readiness check at the end runs against the fake address and
        # fails; what matters here is that the restore itself happened.
        result = self.bash("restore-check.sh", self.posix(dump),
                           RESTORE_DATABASE_URL="postgresql://u@localhost/scratch", STUB_TABLE_COUNT="0")
        self.assertIn("Restored", result.stdout, result.stderr)
        self.assertEqual(self.log.read_text().split(), ["restored"])


# ---- deployment files -------------------------------------------------------------------

class DeploymentFilesTest(unittest.TestCase):
    def test_gunicorn_settings_are_safe(self):
        settings = {}
        with mock.patch.dict(os.environ, {"WEB_CONCURRENCY": "3"}):
            exec((DEPLOY / "gunicorn.conf.py").read_text(), settings)
        self.assertFalse(settings["preload_app"])
        self.assertTrue(settings["bind"].startswith("127.0.0.1:"))
        self.assertEqual(settings["workers"], 3)
        self.assertEqual(settings["forwarded_allow_ips"], "127.0.0.1")

    def test_services_use_files_that_exist(self):
        web = (DEPLOY / "systemd" / "zehunger-web.service").read_text()
        self.assertIn("-c deploy/gunicorn.conf.py backend.app:app", web)
        self.assertIn("ExecStartPre=/opt/zehunger/venv/bin/python -m backend.init_db", web)
        self.assertIn("python -m backend.jobs --loop", (DEPLOY / "systemd" / "zehunger-jobs.service").read_text())
        self.assertIn("deploy/backup.sh", (DEPLOY / "systemd" / "zehunger-backup.service").read_text())
        for text in (web, (DEPLOY / "systemd" / "zehunger-jobs.service").read_text()):
            self.assertIn("User=zehunger", text)
            self.assertIn("NoNewPrivileges=true", text)
        site = (DEPLOY / "nginx" / "zehunger.conf").read_text()
        self.assertIn("return 301 https://", site)
        self.assertIn("include /etc/nginx/zehunger-proxy.conf", site)
        self.assertIn("X-Forwarded-Proto $scheme", (DEPLOY / "nginx" / "zehunger-proxy.conf").read_text())

    def test_render_blueprint_matches_the_app(self):
        blueprint = (ROOT / "render.yaml").read_text()
        self.assertIn("python -m backend.init_db && gunicorn -c deploy/gunicorn.conf.py --bind 0.0.0.0:$PORT "
                      "backend.app:app", blueprint)
        self.assertIn("pip install -r backend/requirements.txt", blueprint)
        self.assertIn("generateValue: true", blueprint)  # SECRET_KEY is never committed
        for secret in ("DATABASE_URL", "EMAIL_HOST_PASSWORD"):
            self.assertRegex(blueprint, rf"key: {secret}[^\n]*\n\s+sync: false")
        self.assertIn("JOBS_IN_WEB_INTERVAL", blueprint)
        self.assertIn("JOBS_IN_WEB_INTERVAL=0", (ROOT / ".env.example").read_text())

    def test_jobs_can_run_inside_the_web_process(self):
        from backend import jobs

        import threading

        runs, naps = [], []
        third_nap, never = threading.Event(), threading.Event()

        def nap(seconds):
            naps.append(seconds)
            if len(naps) > 2:
                third_nap.set()
                never.wait()  # park the daemon thread for the rest of the run
        with mock.patch.object(jobs, "run_once", side_effect=lambda: runs.append(1)):
            thread = jobs.start_in_web(10, sleep=nap)
            self.assertTrue(third_nap.wait(timeout=5))
        self.assertEqual(naps[0], 60)  # never more often than once a minute
        self.assertEqual(len(runs), 2)
        self.assertTrue(thread.daemon)

    def test_env_example_covers_every_setting_preflight_reads(self):
        example = (ROOT / ".env.example").read_text()
        for name in ("APP_ENV", "SECRET_KEY", "DATABASE_URL", "PUBLIC_BASE_URL", "TRUSTED_PROXY_COUNT",
                     "WEB_CONCURRENCY", "DB_POOL_MAX", "EMAIL_HOST_USER", "EMAIL_HOST_PASSWORD",
                     "CORS_ORIGINS", "SESSION_COOKIE_SECURE", "DEMO_GUEST_ACCESS"):
            self.assertRegex(example, rf"(?m)^#? ?{name}=", name)
        # The template carries no secret values.
        self.assertRegex(example, r"(?m)^SECRET_KEY=$")
        self.assertRegex(example, r"(?m)^EMAIL_HOST_PASSWORD=$")

    def test_route_reference_matches_the_application(self):
        from backend.routes_doc import render

        committed = (ROOT / "docs" / "api-routes.md").read_text(encoding="utf-8")
        self.assertEqual(committed, render(app),
                         "docs/api-routes.md is out of date: run python -m backend.routes_doc > docs/api-routes.md")

    def test_production_requirements_match_the_project_pins(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["dependencies"]
        pinned = {}
        for spec in project:
            name, version = re.split(r"==|>=", spec)
            pinned[name.strip().lower()] = version.strip()
        pinned.pop("pytest")
        required = {}
        for line in (ROOT / "backend" / "requirements.txt").read_text().splitlines():
            if line.strip() and not line.startswith("#"):
                name, version = line.split("==")
                required[name.strip().lower()] = version.strip()
        self.assertEqual(required, pinned)
