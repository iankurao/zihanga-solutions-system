"""Gunicorn settings for the Zehunger ERP (gunicorn -c deploy/gunicorn.conf.py backend.app:app).

Tunable from the environment file; see DEPLOYMENT.md for sizing.
"""
import os

# nginx proxies to this address; never expose gunicorn directly.
bind = os.getenv('BIND', '127.0.0.1:8000')

# Each worker holds its own database pool (DB_POOL_MAX) plus the session pool,
# so workers x (DB_POOL_MAX + 15) must stay under PostgreSQL max_connections.
# `python -m backend.preflight` checks this.
workers = int(os.getenv('WEB_CONCURRENCY', '2'))
threads = int(os.getenv('GUNICORN_THREADS', '4'))
worker_class = 'gthread'

# Reports and CSV exports are the slowest requests; nothing should take a minute.
timeout = int(os.getenv('GUNICORN_TIMEOUT', '60'))
graceful_timeout = 30
keepalive = 5

# Recycle workers now and then so a slow leak cannot grow without bound.
max_requests = 2000
max_requests_jitter = 200

# Do NOT preload: the database pool opens at import, and forked workers must
# not share one set of connections.
preload_app = False

# Only nginx on this machine may set X-Forwarded-* (the app's ProxyFix also
# trusts exactly TRUSTED_PROXY_COUNT proxies).
forwarded_allow_ips = os.getenv('FORWARDED_ALLOW_IPS', '127.0.0.1')

# Logs go to stdout/stderr, collected by systemd (journalctl -u zehunger-web).
accesslog = '-'
errorlog = '-'
loglevel = os.getenv('LOG_LEVEL', 'info')
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(M)sms "%(a)s"'
capture_output = True
proc_name = 'zehunger-web'
