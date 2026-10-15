# BSF Farm Management System

A Black Soldier Fly (BSF) farm management application built with Flask (Python) and PostgreSQL, developed by **Zehunger Solutions**.

---

## Project Structure

```
.
├── backend/
│   ├── __init__.py                  # Python package marker (required for module imports)
│   ├── app.py                       # Main Flask application — all routes, blueprints, auth
│   ├── config.py                    # Configuration (DB URL, secret key, email, API endpoints)
│   ├── database.py                  # PostgreSQL connection pool (psycopg2 ThreadedConnectionPool)
│   ├── init_db.py                   # Database schema initialisation & auto-migrations on startup
│   ├── waste_management_routes.py   # Blueprint: /api/waste-* routes
│   ├── fly_facility_routes.py       # Blueprint: /api/fly-facility/* routes
│   ├── migrations/                  # Historical SQL migration scripts (audit trail)
│   └── requirements.txt             # Python dependencies
├── frontend/
│   ├── css/
│   │   ├── auth.css                 # Login & register page styles
│   │   └── styles.css               # Main dashboard styles
│   ├── images/
│   │   ├── logo.png                 # Zehunger Solutions logo
│   │   └── larvae.jpg               # Background image for auth pages
│   ├── js/
│   │   ├── scripts.js               # Core UI logic, form handlers, section navigation
│   │   ├── dataManager.js           # localStorage CRUD for offline form records
│   │   ├── notificationManager.js   # In-app toast notification system
│   │   ├── analyticsManager.js      # Analytics panels & Chart.js charts
│   │   └── exportManager.js         # Excel (SheetJS) and PDF (jsPDF) export
│   ├── main.html                    # Landing page — Admin vs Farmer portal selection
│   ├── index.html                   # Main dashboard (waste, hatchery, feeding, drying, facility)
│   ├── analytics.html               # Analytics & reporting page
│   ├── login.html                   # Login page
│   └── register.html                # Registration page
├── run.sh                           # Startup script: kill stale processes → init DB → start Gunicorn
└── pyproject.toml                   # Python project & dependency manifest (uv)
```

---

## Quick Start (Replit)

The **BSF Farm Server** workflow handles everything automatically:

1. Kills any lingering Gunicorn processes that may hold port 5000
2. Initialises the database schema via `python -m backend.init_db`
3. Starts Gunicorn on port 5000

Just press **Run**. The app will be available in the Replit preview pane.

### Phase One business identifiers

Phase One production records keep their existing integer primary keys for
relationships and backward compatibility, but expose stable business IDs to
users and APIs:

| Record | Format |
|---|---|
| Waste Lot | `WL-YYYY-00001` |
| Substrate Batch | `SUB-YYYY-00001` |
| Production Batch | `BSF-YYYY-00001` |
| Harvest | `HRV-YYYY-00001` |
| Drying Batch | `DRY-YYYY-00001` |
| Product Lot | `LOT-YYYY-00001` |
| Inventory Movement | `MOV-YYYY-00001` |

The migration in `backend/migrations/phase_one_business_identifiers.sql`
creates one PostgreSQL sequence per entity and uses `nextval()` in the column
default. This is atomic under concurrent requests and deliberately does not
use `SELECT MAX(...) + 1`. Existing rows are backfilled from their preserved
primary keys; legacy fields such as `batch_no`, `batch_id`, `batch_code`, and
`lot_code` remain unchanged. Create responses return both the internal `id` and
the canonical `business_id`, while list and analytics responses include the
business ID for display.

---

## Local Setup

### Prerequisites

- Python 3.11+
- PostgreSQL 13+

### 1. Clone the Repository

```bash
git clone <your-repo-url>
cd <repo-folder>
```

### 2. Install Dependencies

Using `uv` (recommended):
```bash
pip install uv
uv sync
```

Or using pip with a virtual environment:
```bash
python -m venv venv
source venv/bin/activate        # macOS/Linux
.\venv\Scripts\activate         # Windows
pip install -r backend/requirements.txt
```

### 3. Configure Environment Variables

```bash
export DATABASE_URL=postgresql://postgres:yourpassword@localhost:5432/bsf_farm
export PGHOST=localhost
export PGPORT=5432
export PGUSER=postgres
export PGPASSWORD=yourpassword
export PGDATABASE=bsf_farm
export SECRET_KEY=your-secret-key-here
```

### 4. Initialise the Database

```bash
python -m backend.init_db
```

### 5. Run the Application

**Development:**
```bash
python -m flask --app backend.app run --host 0.0.0.0 --port 5000
```

**Production (Gunicorn):**
```bash
bash run.sh
```

The app will be at: **http://127.0.0.1:5000**

---

## First Login

1. Navigate to `/` — the landing page (Admin vs Farmer portal selector).
2. Go to `/register` to create your account.
3. Log in at `/login`.
4. You will be redirected to the main dashboard at `/dashboard`.

---

## Demonstration Data

A separate database can be filled with about three months of linked,
invented records for demonstrations and training:

```bash
createdb zehunger_demo
DATABASE_URL=postgresql://user@host:5432/zehunger_demo PGDATABASE=zehunger_demo   python -m backend.demo seed --accounts-file demo-accounts.txt
python -m backend.demo status            # is this a demo database?
python -m backend.demo seed --reset      # rebuild it from scratch (demo databases only)
```

What it contains: the Zehunger Demo Co-operative with two farms (Kericho and
Nakuru), bio-pods, stores and seven staff accounts, one per role. Batches are
in every state: delivered to a customer, on the road, failed QC, in stock and
reserved, awaiting a QC decision, harvest overdue, an open health issue, ready
to harvest and just planned. Customers, orders, deliveries, stock movements,
alerts and the audit trail all come from the same records.

Safeguards:

- Seeding refuses any database that already holds farms, customers or orders
  and is not marked as a demo. `--reset` works only on a demo database.
- Everything is entered through the application's API by the matching role,
  so the demo follows every business rule.
- A demo database shows a **Demo data** badge in the app bar and never sends
  email. All addresses end in `example.com`.
- Account passwords are random on each seed and are written only to the
  `--accounts-file` (or printed). Keep that file out of version control.

### Investor demo mode

On a demo database, `/tour` is a guided tour for visitors: eight short
chapters (dashboard, one batch's life, tracing a sold product back to its
waste, the QC gate, stock, alerts, QR labels, reports), each opening the real
page at a real demo record. A tour bar with Back / Next follows the visitor
across pages. The sign-in page links to the tour, and the **Demo data** badge
opens it.

To let visitors in without an account, start the demo server with:

```bash
DEMO_GUEST_ACCESS=1
```

"Explore as a guest" then signs visitors in as the read-only *Investor
Guest* viewer: they can look at everything that role may see (no customer or
order details) and cannot change anything. Guest sign-ins are audited. The
switch is off by default, works only on a demo database, and refuses the
guest account if it has been given any role other than viewer. On a real
database `/tour` and the demo endpoints answer 404.

---

## Environment Variables Reference

| Variable              | Description                              | Default          |
|-----------------------|------------------------------------------|------------------|
| `DATABASE_URL`        | Full PostgreSQL connection URL           | Required         |
| `PGHOST`              | Database host                            | `localhost`      |
| `PGPORT`              | Database port                            | `5432`           |
| `PGUSER`              | Database user                            | `postgres`       |
| `PGPASSWORD`          | Database password                        | Required         |
| `PGDATABASE`          | Database name                            | `bsf_farm`       |
| `SECRET_KEY`          | Flask secret key (or `SESSION_SECRET`)   | Auto-generated   |
| `EMAIL_HOST`          | SMTP host for email notifications        | `smtp.gmail.com` |
| `EMAIL_PORT`          | SMTP port                                | `587`            |
| `EMAIL_HOST_USER`     | SMTP username                            | —                |
| `EMAIL_HOST_PASSWORD` | SMTP password / app password             | —                |
| `ADMIN_EMAIL`         | Admin notification email                 | —                |
| `DEMO_GUEST_ACCESS`   | `1` lets visitors explore a demo database as the read-only guest (ignored on real databases) | off |

---

## Page Routes

| Route          | Description                                        | Auth Required |
|----------------|----------------------------------------------------|---------------|
| `/`            | Landing page — portal selector (main.html)         | No            |
| `/login`       | Login form                                         | No            |
| `/register`    | Registration form                                  | No            |
| `/dashboard`   | Main farm dashboard                                | Yes           |
| `/analytics`   | Analytics & reporting dashboard                    | Yes           |
| `/logout`      | Logout and redirect to login                       | Yes           |

---

## API Endpoints

### Authentication
| Method | Endpoint               | Description |
|--------|------------------------|-------------|
| POST   | `/api/auth/login`      | JSON login  |
| POST   | `/api/auth/register`   | JSON register |

### Farm, Site & Facility Locations
The canonical location hierarchy is additive and follows
`Organization → Farm → Site → Facility`. Existing records are not assigned a
location automatically because legacy free-text values are ambiguous.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/locations/hierarchy` | List locations visible to the signed-in user |
| POST | `/api/locations/organizations` | Create an organization (super admin) |
| POST | `/api/locations/farms` | Create a farm (super admin) |
| POST | `/api/locations/sites` | Create a site (super admin) |
| POST | `/api/locations/facilities` | Create a facility (super admin) |
| POST/DELETE | `/api/locations/access` | Grant or revoke a user's location access (super admin) |
| GET | `/api/locations/access/check` | Check access to a facility |
| POST | `/api/locations/record-links` | Link an existing operational record to a facility |

### Waste Management (`waste_management_routes.py` blueprint)
| Method | Endpoint                                      | Description                     |
|--------|-----------------------------------------------|---------------------------------|
| POST   | `/api/waste-sourcing`                         | Record waste sourcing           |
| GET    | `/api/waste-sourcing`                         | Fetch waste sourcing records    |
| POST   | `/api/storage-records`                        | Record storage                  |
| POST   | `/api/processing-records`                     | Record processing               |
| POST   | `/api/environmental-monitoring-waste`         | Waste environmental monitoring  |
| POST   | `/api/environmental-monitoring-larvaefeeding` | Larvae environmental monitoring |
| POST   | `/api/substrate-preparation`                  | Substrate preparation           |
| POST   | `/api/larvae-feeding`                         | Larvae feeding schedule         |
| POST   | `/api/health-intervention`                    | Health intervention             |
| POST   | `/api/harvest-yield`                          | Harvest yield                   |
| POST   | `/api/hatchery/batch-information`             | Hatchery batch info             |
| POST   | `/api/hatchery/feeding-records`               | Hatchery feeding records        |
| POST   | `/api/hatchery/environmental-monitoring`      | Hatchery environmental monitoring |
| GET    | `/api/growth-monitoring`                      | Growth monitoring data          |
| POST   | `/api/breeding`                               | Breeding records                |

### Fly Facility (`fly_facility_routes.py` blueprint)
| Method | Endpoint                              | Description              |
|--------|---------------------------------------|--------------------------|
| POST   | `/api/fly-facility/cage-monitoring`   | Cage monitoring          |
| POST   | `/api/fly-facility/maintenance`       | Facility maintenance     |
| POST   | `/api/fly-facility/pupae-transition`  | Pupae transition         |
| POST   | `/api/fly-facility/egg-collection`    | Egg collection           |
| POST   | `/api/fly-facility/bait-preparation`  | Bait preparation         |

---

## Static File Routing

Flask serves all frontend assets via a `/<path:filename>` catch-all route using `send_from_directory`. `app.static_folder` is set to `../frontend` (relative to `backend/app.py`).

| URL path           | File served                   |
|--------------------|-------------------------------|
| `/css/styles.css`  | `frontend/css/styles.css`     |
| `/css/auth.css`    | `frontend/css/auth.css`       |
| `/js/scripts.js`   | `frontend/js/scripts.js`      |
| `/images/logo.png` | `frontend/images/logo.png`    |

---

## Features

- **Landing Page** — Portal selector directing users to Admin or Farmer portal
- **User Authentication** — Secure login/registration with hashed passwords, server-side sessions
- **Waste Management** — Sourcing, storage, processing, and environmental monitoring
- **Hatchery Management** — Batch tracking, feeding records, environmental monitoring
- **Larval Feeding** — Feeding schedules, health interventions, harvest yields
- **Drying Process** — Batch management and quality control
- **Fly Facility** — Cage monitoring, maintenance, pupae transition, egg collection, bait preparation
- **Analytics & Reporting** — Chart.js dashboards with Excel and PDF export
- **Notification System** — In-app toast notifications for all form submissions

---

## Database Schema

All tables are created automatically by `backend/init_db.py` on first startup:

| Table                                  | Module               |
|----------------------------------------|----------------------|
| `users`                                | Auth                 |
| `flask_sessions`                       | Flask-Session        |
| `waste_sourcing`                       | Waste Management     |
| `storage_records`                      | Waste Management     |
| `processing_records`                   | Waste Management     |
| `environmental_monitoring_waste`       | Waste Management     |
| `environmental_monitoring_larvaefeeding` | Larval Feeding     |
| `substrate_preparation`                | Larval Feeding       |
| `larvae_feeding`                       | Larval Feeding       |
| `health_intervention`                  | Larval Feeding       |
| `harvest_yield`                        | Larval Feeding       |
| `hatchery_batches`                     | Hatchery             |
| `hatchery_feeding_records`             | Hatchery             |
| `hatchery_environmental_monitoring`    | Hatchery             |
| `cage_monitoring`                      | Fly Facility         |
| `facility_maintenance`                 | Fly Facility         |
| `pupae_transition`                     | Fly Facility         |
| `egg_collection`                       | Fly Facility         |
| `bait_preparation`                     | Fly Facility         |
| `drying_batches`                       | Drying Process       |
| `drying_quality_control`               | Drying Process       |
| `customers`, `sales`, `deliveries`     | Sales & CRM          |

---

## Ubuntu Server Deployment

### 1. Install System Dependencies

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv \
    postgresql postgresql-contrib nginx git
```

### 2. Set Up PostgreSQL

```bash
sudo systemctl start postgresql && sudo systemctl enable postgresql
sudo -u postgres psql <<EOF
CREATE USER bsf_user WITH PASSWORD 'your_strong_password';
CREATE DATABASE bsf_farm OWNER bsf_user;
GRANT ALL PRIVILEGES ON DATABASE bsf_farm TO bsf_user;
EOF
```

### 3. Clone & Set Up the App

```bash
cd /opt
sudo git clone <your-repo-url> bsf-farm
sudo chown -R $USER:$USER /opt/bsf-farm
cd /opt/bsf-farm
python3 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt
```

### 4. Configure Environment Variables

```bash
sudo nano /etc/bsf-farm.env
```

```env
DATABASE_URL=postgresql://bsf_user:your_strong_password@localhost:5432/bsf_farm
PGHOST=localhost
PGPORT=5432
PGUSER=bsf_user
PGPASSWORD=your_strong_password
PGDATABASE=bsf_farm
SECRET_KEY=replace-with-a-long-random-string
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=your@email.com
EMAIL_HOST_PASSWORD=your-app-password
ADMIN_EMAIL=admin@yourdomain.com
```

```bash
sudo chmod 600 /etc/bsf-farm.env
```

### 5. Initialise the Database

```bash
export $(sudo cat /etc/bsf-farm.env | xargs)
python -m backend.init_db
```

### 6. Create a systemd Service

```bash
sudo nano /etc/systemd/system/bsf-farm.service
```

```ini
[Unit]
Description=BSF Farm Management System
After=network.target postgresql.service

[Service]
User=www-data
Group=www-data
WorkingDirectory=/opt/bsf-farm
EnvironmentFile=/etc/bsf-farm.env
ExecStart=/opt/bsf-farm/venv/bin/gunicorn \
    --bind 127.0.0.1:5000 \
    --workers 2 \
    --threads 4 \
    --timeout 120 \
    --access-logfile /var/log/bsf-farm/access.log \
    --error-logfile /var/log/bsf-farm/error.log \
    backend.app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo mkdir -p /var/log/bsf-farm
sudo chown -R www-data:www-data /var/log/bsf-farm /opt/bsf-farm
sudo systemctl daemon-reload
sudo systemctl enable --now bsf-farm
sudo systemctl status bsf-farm
```

### 7. Configure Nginx

```bash
sudo nano /etc/nginx/sites-available/bsf-farm
```

```nginx
server {
    listen 80;
    server_name your-domain.com;
    client_max_body_size 20M;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/bsf-farm /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

### 8. (Optional) HTTPS with Let's Encrypt

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

### Useful Commands

| Task                   | Command                                       |
|------------------------|-----------------------------------------------|
| View app logs          | `sudo journalctl -u bsf-farm -f`              |
| Restart the app        | `sudo systemctl restart bsf-farm`             |
| Connect to the database| `psql -U bsf_user -d bsf_farm -h localhost`   |
| Check Nginx config     | `sudo nginx -t`                               |

---

## Troubleshooting

**Cannot connect to database:**
- Verify `PGPASSWORD`, `PGHOST`, and `PGDATABASE` are set correctly.
- Confirm PostgreSQL is running: `sudo systemctl status postgresql`

**Port 5000 already in use (Replit):**
- `run.sh` automatically kills stale Gunicorn processes before starting. If it still fails, restart the workflow from the Replit UI.

**Port 5000 already in use (local):**
```bash
lsof -i :5000   # find the PID
kill -9 <PID>
```

**502 Bad Gateway from Nginx:**
- Check app is running: `sudo systemctl status bsf-farm`
- Check logs: `sudo journalctl -u bsf-farm -n 50`
- Ensure Gunicorn binds to `127.0.0.1:5000`

**Module not found errors:**
- Run all commands from the project root, not from inside `backend/`.
- Ensure the virtual environment is activated.

**Fly facility API endpoints returning 404:**
- Ensure `fly_facility` blueprint is imported and registered in `backend/app.py`.
- Both lines must be present:
  ```python
  from backend.fly_facility_routes import fly_facility
  app.register_blueprint(fly_facility)
  ```

**Deployment (publish) failing with `ModuleNotFoundError` for `main`:**
- The project has no `main.py` at the root. The correct Gunicorn entry point is `backend.app:app`, not `main:app`.
- The deployment run command must be: `gunicorn --bind 0.0.0.0:5000 backend.app:app`

**Packages not found after cloning to a new Replit:**
- Install all dependencies from the project root:
  ```bash
  uv add flask flask-sqlalchemy flask-login flask-session flask-wtf flask-cors psycopg2-binary gunicorn email-validator werkzeug wtforms requests sqlalchemy
  ```
  All pinned versions are in `pyproject.toml`.
