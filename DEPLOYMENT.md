# Deploying the Zehunger ERP

This guide puts the ERP on one Ubuntu 22.04/24.04 server: nginx (HTTPS) in
front of gunicorn, PostgreSQL 14+, a background jobs worker and nightly
backups. The ready-made files are in [`deploy/`](deploy) and
[`.env.example`](.env.example).

```
browser ──HTTPS──> nginx :443 ──> gunicorn 127.0.0.1:8000 (zehunger-web) ──> PostgreSQL
                                   python -m backend.jobs  (zehunger-jobs)  ──┘
                                   deploy/backup.sh nightly (zehunger-backup.timer)
```

HTTPS is not optional: sign-in cookies are only sent over HTTPS, so over
plain HTTP nobody can stay signed in.

## 1. Before you start

- [ ] A domain name pointing at the server (e.g. `erp.example.com`).
- [ ] Ubuntu with `python3-venv`, `postgresql`, `postgresql-client`, `nginx`, `certbot`.
- [ ] Somewhere off the server to copy backups to (another machine, object storage).
- [ ] An SMTP account if alerts should also go out by email (optional).

```bash
sudo apt update
sudo apt install -y python3 python3-venv postgresql postgresql-client nginx certbot python3-certbot-nginx git
```

## 2. Database

```bash
sudo -u postgres createuser --pwprompt zehunger        # choose a long random password
sudo -u postgres createdb --owner zehunger zehunger
```

Keep PostgreSQL listening on localhost only (the Ubuntu default). If it runs
on another machine, use `?sslmode=require` in `DATABASE_URL`.

## 3. Application

```bash
sudo useradd --system --home /opt/zehunger --shell /usr/sbin/nologin zehunger
sudo mkdir -p /opt/zehunger /etc/zehunger /var/backups/zehunger
sudo git clone <repository-url> /opt/zehunger/app       # or unpack a release zip there
sudo python3 -m venv /opt/zehunger/venv
sudo /opt/zehunger/venv/bin/pip install -r /opt/zehunger/app/backend/requirements.txt
sudo chown -R root:root /opt/zehunger/app /opt/zehunger/venv      # the app cannot rewrite its own code
sudo chown zehunger:zehunger /var/backups/zehunger && sudo chmod 700 /var/backups/zehunger
```

## 4. Settings

```bash
sudo cp /opt/zehunger/app/.env.example /etc/zehunger/zehunger.env
sudo chown root:zehunger /etc/zehunger/zehunger.env && sudo chmod 640 /etc/zehunger/zehunger.env
sudo nano /etc/zehunger/zehunger.env
```

Fill in at least `SECRET_KEY` (`python3 -c "import secrets; print(secrets.token_urlsafe(48))"`),
`DATABASE_URL` and `PUBLIC_BASE_URL`. With `APP_ENV=production` the app
refuses to start with a missing or weak secret key, plain-HTTP cookies or
non-HTTPS cross-origin access.

Commands run by hand use [`deploy/zrun`](deploy/zrun): it runs them as the
`zehunger` user with these settings, from the app folder.

```bash
sudo ln -s /opt/zehunger/app/deploy/zrun /usr/local/bin/zrun
sudo zrun python -m backend.preflight
```

## 5. Schema, first administrator, readiness

```bash
sudo zrun python -m backend.init_db                # creates / upgrades the schema (safe to repeat)
sudo zrun python -m backend.create_super_admin     # first super admin (asks for name, email, password)
sudo zrun python -m backend.preflight              # every line PASS or an understood WARN
```

## 6. Services

```bash
sudo cp /opt/zehunger/app/deploy/systemd/zehunger-*.service /opt/zehunger/app/deploy/systemd/zehunger-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now zehunger-web zehunger-jobs zehunger-backup.timer
curl -fsS http://127.0.0.1:8000/readyz        # {"status":"ok"}
```

- `zehunger-web` applies migrations (`init_db`) and starts gunicorn
  ([`deploy/gunicorn.conf.py`](deploy/gunicorn.conf.py)).
- `zehunger-jobs` evaluates alerts, sends queued email and trims old sign-in
  attempts every 5 minutes. Without it alerts are only refreshed when someone
  opens the app and no email is sent.
- `zehunger-backup.timer` runs [`deploy/backup.sh`](deploy/backup.sh) at 02:30.

## 7. nginx and HTTPS

The site file expects the certificate to exist, so the first time:

1. Install the files and switch off the HTTPS block until there is a certificate:

   ```bash
   sudo cp /opt/zehunger/app/deploy/nginx/zehunger-proxy.conf /etc/nginx/zehunger-proxy.conf
   sudo cp /opt/zehunger/app/deploy/nginx/zehunger.conf /etc/nginx/sites-available/zehunger
   sudo sed -i 's/erp.example.com/YOUR.DOMAIN/g' /etc/nginx/sites-available/zehunger
   sudo ln -s /etc/nginx/sites-available/zehunger /etc/nginx/sites-enabled/zehunger
   sudo rm -f /etc/nginx/sites-enabled/default
   sudo mkdir -p /var/www/certbot
   ```

   Comment out the second `server { ... }` block (port 443), then
   `sudo nginx -t && sudo systemctl reload nginx`.

2. Get the certificate (certbot renews it automatically the same way):

   ```bash
   sudo certbot certonly --webroot -w /var/www/certbot -d YOUR.DOMAIN
   ```

3. Uncomment the 443 block and `sudo nginx -t && sudo systemctl reload nginx`.

## 8. After the first deployment

- [ ] `https://YOUR.DOMAIN/readyz` answers `{"status":"ok"}`; add it to an uptime monitor.
- [ ] Sign in as the super admin; set up the organization, farms, sites and
      facilities (Farm setup), then staff accounts with the narrowest role
      that fits and their location access.
- [ ] Print one QR label and scan it with a phone: it must open `https://YOUR.DOMAIN/...`.
- [ ] Start a backup by hand and check it: `sudo systemctl start zehunger-backup && journalctl -u zehunger-backup -n 5`.
- [ ] Copy backups off the server every day (rsync, rclone, object storage).
      A backup on the same disk does not survive the disk.
- [ ] Run a restore drill (section 10) and note the date.

## 9. Upgrading

```bash
sudo zrun python -m backend.preflight                 # before: all PASS
sudo systemctl start zehunger-backup             # fresh backup first
cd /opt/zehunger/app && sudo git fetch && sudo git checkout <release-tag>
sudo /opt/zehunger/venv/bin/pip install -r backend/requirements.txt
sudo systemctl restart zehunger-web zehunger-jobs   # migrations run on start
sudo zrun python -m backend.preflight                 # after: all PASS
curl -fsS https://YOUR.DOMAIN/readyz
```

**Rollback:** check out the previous tag and restart. Migrations are not
reversed automatically: if the release notes say the schema changed in a way
older code cannot read, or data went wrong, restore the backup taken just
before the upgrade (section 10: into a new database, then point
`DATABASE_URL` at it). Anything recorded after that backup must then be
re-entered, so keep the upgrade window short and announced.

## 10. Backups and restore

- Format: `pg_dump` custom format, one file per run in `/var/backups/zehunger`,
  kept `BACKUP_KEEP_DAYS` (14) days. Each file is checked after writing; a bad
  dump fails the timer (`systemctl status zehunger-backup`).
- The audit log is in every backup and stays append-only after a restore.

Restore drill (do it after setup and every few months) - into an empty
scratch database, never over the live one:

```bash
sudo -u postgres createdb --owner zehunger zehunger_restore_test
sudo zrun env RESTORE_DATABASE_URL=postgresql://zehunger:PASSWORD@localhost/zehunger_restore_test \
  deploy/restore-check.sh /var/backups/zehunger/zehunger-<time>.dump
sudo -u postgres dropdb zehunger_restore_test
```

It refuses a database that already has tables, restores, prints record counts
and runs the readiness check on the copy.

To recover for real: create a new database, restore into it with
`pg_restore --no-owner --dbname=<new database url> <file>`, set
`DATABASE_URL` to it and restart the services.

## 11. Day to day

| Task | Command |
|---|---|
| Readiness | `sudo zrun python -m backend.preflight` |
| Logs | `journalctl -u zehunger-web -f`, `journalctl -u zehunger-jobs -f` |
| Restart | `sudo systemctl restart zehunger-web zehunger-jobs` |
| Reload code without dropping requests | `sudo systemctl reload zehunger-web` |
| Backups | `ls -lh /var/backups/zehunger`, `systemctl list-timers zehunger-backup` |
| Health | `curl -fsS https://YOUR.DOMAIN/healthz` (process), `/readyz` (database and schema) |

## Sizing

Each gunicorn worker serves `GUNICORN_THREADS` requests at once and may hold
`DB_POOL_MAX` + 15 database connections. Keep
`WEB_CONCURRENCY x (DB_POOL_MAX + 15) + DB_POOL_MAX + 5` below about 80% of
PostgreSQL's `max_connections` (100 by default); the readiness check warns
otherwise. 2 workers x 4 threads suit a few dozen staff.

## Demo servers

A demonstration server is set up the same way with its own database, filled
by `python -m backend.demo seed` (see README, "Demonstration Data"). Never
point a demo server at the production database; the seeder refuses databases
with real records, and the readiness check flags demo databases.
