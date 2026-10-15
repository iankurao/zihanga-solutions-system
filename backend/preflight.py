"""Deployment readiness check.

    python -m backend.preflight            # settings + database
    python -m backend.preflight --strict   # warnings fail too (CI / release gate)

Prints one line per check (PASS / WARN / FAIL) and exits 1 when anything
fails. Run it with the same environment as the web service before every
deployment and after restoring a backup.

The settings checks are also applied when the web app starts with
APP_ENV=production: a failing setting stops the app from starting rather than
running it insecurely (see backend/core/web.py).
"""
import argparse
import os
import sys
from urllib.parse import urlsplit

PASS, WARN, FAIL = 'PASS', 'WARN', 'FAIL'

# Tables the current code needs; missing ones mean init_db has not been run
# against this database since the last upgrade.
REQUIRED_TABLES = (
    'users', 'flask_sessions', 'audit_log', 'schema_markers', 'auth_login_attempts',
    'organizations', 'farms', 'sites', 'facilities', 'production_units',
    'waste_lots', 'substrate_batches', 'production_batches', 'production_events', 'harvests',
    'drying_batches', 'quality_checks', 'product_lots', 'inventory_locations', 'inventory_movements',
    'customers', 'customer_orders', 'customer_deliveries', 'operational_alerts', 'notification_outbox',
)
REQUIRED_MARKERS = ('rbac_roles_v1',)
# Tables whose changes must reach the audit log (one trigger each at least).
AUDITED_TABLES = ('users', 'production_batches', 'product_lots', 'inventory_movements', 'customer_orders')

_PLACEHOLDER_SECRETS = ('change-me', 'changeme', 'replace-me', 'your-secret', 'dev-only', 'test-only')
_TRUE = ('1', 'true', 'yes', 'on')
_LOCAL_HOSTS = ('localhost', '127.0.0.1', '::1', '')

# Rough connections one web worker can hold: the psycopg2 pool plus the
# SQLAlchemy session pool (5 + 10 overflow).
SESSION_POOL_CONNECTIONS = 15


def _on(env, name):
    return (env.get(name) or '').strip().lower() in _TRUE


def _secret(env):
    return env.get('SECRET_KEY') or env.get('SESSION_SECRET') or ''


def settings_checks(env=None):
    """Checks of the environment alone: [(level, name, message)]."""
    env = os.environ if env is None else env
    results = []

    def add(level, name, message):
        results.append((level, name, message))

    secret = _secret(env)
    if not secret:
        add(FAIL, 'secret_key', 'SECRET_KEY is not set: sessions would be signed with a random key and '
                                'everyone signed out on each restart.')
    elif len(secret) < 32 or any(p in secret.lower() for p in _PLACEHOLDER_SECRETS):
        add(FAIL, 'secret_key', 'SECRET_KEY is too short or a placeholder: use at least 32 random characters '
                                '(python -c "import secrets; print(secrets.token_urlsafe(48))").')
    else:
        add(PASS, 'secret_key', 'SECRET_KEY is set.')

    url = env.get('DATABASE_URL') or ''
    if not url:
        add(FAIL, 'database_url', 'DATABASE_URL is not set.')
    else:
        parts = urlsplit(url)
        if parts.scheme not in ('postgres', 'postgresql'):
            add(FAIL, 'database_url', 'DATABASE_URL must be a postgresql:// URL.')
        elif (parts.hostname or '') not in _LOCAL_HOSTS and 'sslmode=' not in (parts.query or ''):
            add(WARN, 'database_url', 'The database is on another host and DATABASE_URL has no sslmode: '
                                      'add ?sslmode=require unless the network is private.')
        else:
            add(PASS, 'database_url', 'DATABASE_URL is set.')

    if (env.get('SESSION_COOKIE_SECURE', '1') or '1').strip().lower() in ('0', 'false', 'no', 'off'):
        add(FAIL, 'cookies', 'SESSION_COOKIE_SECURE is off: sign-in cookies would travel over plain HTTP.')
    else:
        add(PASS, 'cookies', 'Sign-in cookies are HTTPS-only.')

    if _on(env, 'EMBEDDED_PREVIEW'):
        add(FAIL, 'embedded_preview', 'EMBEDDED_PREVIEW is on: it allows the app inside other sites\' frames '
                                      '(Replit workspace only). Remove it in production.')

    origins = [o.strip() for o in (env.get('CORS_ORIGINS') or '').split(',') if o.strip()]
    bad = [o for o in origins if o == '*' or not o.startswith('https://')]
    if bad:
        add(FAIL, 'cors', f'CORS_ORIGINS must list https:// origins only, not {", ".join(bad)}.')
    elif origins:
        add(PASS, 'cors', f'Cross-origin access limited to {len(origins)} origin(s).')

    base = env.get('PUBLIC_BASE_URL') or ''
    if not base:
        add(WARN, 'public_base_url', 'PUBLIC_BASE_URL is not set: QR labels will use whatever host name '
                                     'the label page was opened with.')
    elif not base.startswith('https://'):
        add(WARN, 'public_base_url', 'PUBLIC_BASE_URL should be an https:// address; QR labels print it.')
    else:
        add(PASS, 'public_base_url', f'QR labels point to {base.rstrip("/")}.')

    if env.get('EMAIL_HOST_USER') and env.get('EMAIL_HOST_PASSWORD'):
        add(PASS, 'email', 'Email is configured for alert notifications.')
    else:
        add(WARN, 'email', 'Email is not configured (EMAIL_HOST_USER / EMAIL_HOST_PASSWORD): alerts are '
                           'shown in the app only.')

    proxies = (env.get('TRUSTED_PROXY_COUNT') or '1').strip()
    if not proxies.isdigit():
        add(FAIL, 'proxy', 'TRUSTED_PROXY_COUNT must be a whole number (proxies in front of the app).')
    elif proxies == '0':
        add(WARN, 'proxy', 'TRUSTED_PROXY_COUNT=0: the app trusts no proxy, so behind nginx or a load '
                           'balancer it will not know requests arrived over HTTPS.')

    if _on(env, 'DEMO_GUEST_ACCESS'):
        add(WARN, 'demo_guest', 'DEMO_GUEST_ACCESS is on: anyone can sign in as the read-only guest when '
                                'this is a demo database.')
    if (env.get('APP_ENV') or '').strip().lower() != 'production':
        add(WARN, 'app_env', 'APP_ENV is not "production": unsafe settings will not stop the app starting.')
    return results


def fatal_settings(env=None):
    """Messages that must stop a production web process from starting."""
    return [message for level, _, message in settings_checks(env) if level == FAIL]


def database_checks(db, env=None):
    """Checks against the database the app is configured for."""
    env = os.environ if env is None else env
    results = []

    def add(level, name, message):
        results.append((level, name, message))

    try:
        version = db.fetch_one("SHOW server_version")['server_version']
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        add(FAIL, 'database', f'Cannot reach the database: {type(exc).__name__}.')
        return results
    add(PASS, 'database', f'Connected to PostgreSQL {version}.')

    present = {r['name'] for r in db.fetch_all(
        "SELECT c.relname AS name FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = current_schema() AND c.relkind IN ('r', 'p') AND c.relname = ANY(%s)",
        (list(REQUIRED_TABLES),))}
    markers = set()
    if 'schema_markers' in present:
        markers = {r['name'] for r in db.fetch_all("SELECT name FROM schema_markers")}
    missing = [t for t in REQUIRED_TABLES if t not in present] + [m for m in REQUIRED_MARKERS if m not in markers]
    if missing:
        add(FAIL, 'schema', f'The schema is not up to date (missing {", ".join(missing[:6])}'
                            f'{"…" if len(missing) > 6 else ""}): run python -m backend.init_db.')
        return results
    add(PASS, 'schema', f'All {len(REQUIRED_TABLES)} required tables are present.')

    unaudited = [r['name'] for r in db.fetch_all("""
        SELECT t.name FROM unnest(%s::text[]) AS t(name)
        WHERE NOT EXISTS (
            SELECT 1 FROM pg_trigger g JOIN pg_class c ON c.oid = g.tgrelid
            WHERE c.relname = t.name AND NOT g.tgisinternal AND g.tgname LIKE 'audit%%')""",
        (list(AUDITED_TABLES),))]
    if unaudited:
        add(FAIL, 'audit', f'Audit triggers are missing on {", ".join(unaudited)}: run python -m backend.init_db.')
    else:
        add(PASS, 'audit', 'Changes are recorded in the audit log.')

    admins = db.fetch_one("SELECT count(*) AS n FROM users WHERE role = 'super_admin' AND is_active")['n']
    if admins:
        add(PASS, 'super_admin', f'{admins} active super admin account(s).')
    else:
        add(FAIL, 'super_admin', 'No active super admin: run python -m backend.create_super_admin.')

    demo = 'demo_database' in markers
    if demo:
        add(WARN, 'demo', 'This is a DEMO database (python -m backend.demo): never enter real records here.')
    elif _on(env, 'DEMO_GUEST_ACCESS'):
        add(PASS, 'demo', 'Real database: DEMO_GUEST_ACCESS has no effect here, but should be removed.')

    sync = db.fetch_one("SELECT max(last_run_at) AS at, now() - max(last_run_at) AS age "
                        "FROM operational_alert_sync") if _table(db, 'operational_alert_sync') else None
    if not sync or not sync['at']:
        add(WARN, 'jobs', 'Alerts have never been evaluated: start the jobs worker (python -m backend.jobs --loop 300).')
    elif sync['age'].total_seconds() > 30 * 60:
        add(WARN, 'jobs', f'Alerts were last evaluated {int(sync["age"].total_seconds() // 60)} min ago: '
                          'is the jobs worker running?')
    else:
        add(PASS, 'jobs', 'Alerts were evaluated in the last 30 minutes.')

    outbox = db.fetch_one("""
        SELECT count(*) FILTER (WHERE status = 'PENDING' AND created_at < now() - interval '30 minutes') AS stuck,
               count(*) FILTER (WHERE status = 'FAILED' AND created_at > now() - interval '7 days') AS failed
        FROM notification_outbox""")
    if outbox['stuck'] or outbox['failed']:
        add(WARN, 'email_queue', f'{outbox["stuck"]} email(s) waiting over 30 min, {outbox["failed"]} failed '
                                 'this week: check the email settings and the jobs worker.')
    else:
        add(PASS, 'email_queue', 'No stuck or failed email.')

    limit = int(db.fetch_one("SHOW max_connections")['max_connections'])
    from backend.config import DB_POOL_MAX

    workers = int(env.get('WEB_CONCURRENCY') or 2)
    needed = workers * (DB_POOL_MAX + SESSION_POOL_CONNECTIONS) + DB_POOL_MAX + 5
    if needed > limit * 0.8:
        add(WARN, 'connections', f'{workers} web worker(s) with DB_POOL_MAX={DB_POOL_MAX} can open about '
                                 f'{needed} connections; PostgreSQL allows {limit}. Lower DB_POOL_MAX or '
                                 'WEB_CONCURRENCY, or raise max_connections.')
    else:
        add(PASS, 'connections', f'Up to about {needed} connections of {limit} allowed.')
    return results


def _table(db, name):
    return bool(db.fetch_one("SELECT to_regclass(%s) IS NOT NULL AS ok", (name,))['ok'])


def run(*, strict=False, out=print):
    results = settings_checks()
    try:
        from backend.database import DatabaseConnection

        db = DatabaseConnection()
    except Exception as exc:  # noqa: BLE001
        results.append((FAIL, 'database', f'Cannot reach the database: {type(exc).__name__}.'))
    else:
        results += database_checks(db)
    width = max(len(name) for _, name, _ in results)
    for level, name, message in results:
        out(f'{level}  {name:<{width}}  {message}')
    failed = [r for r in results if r[0] == FAIL or (strict and r[0] == WARN)]
    counts = {level: sum(1 for r in results if r[0] == level) for level in (PASS, WARN, FAIL)}
    out(f'\n{counts[PASS]} passed, {counts[WARN]} warning(s), {counts[FAIL]} failed.'
        + (' Not ready to deploy.' if failed else ' Ready to deploy.'))
    return 1 if failed else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description='Check deployment readiness.')
    parser.add_argument('--strict', action='store_true', help='treat warnings as failures')
    args = parser.parse_args(argv)
    return run(strict=args.strict)


if __name__ == '__main__':
    sys.exit(main())
