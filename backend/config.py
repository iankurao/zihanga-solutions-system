import os

# Deployment environment. APP_ENV=production makes the web app refuse to start
# with unsafe settings (see backend/preflight.py); anything else is development.
APP_ENV = os.getenv('APP_ENV', 'development').strip().lower()
IS_PRODUCTION = APP_ENV == 'production'

# PostgreSQL Configuration from environment variables
DATABASE_URL = os.getenv('DATABASE_URL', '')
DB_HOST = os.getenv('PGHOST', 'localhost')
DB_USER = os.getenv('PGUSER', 'postgres')
DB_PASSWORD = os.getenv('PGPASSWORD', '')
DB_NAME = os.getenv('PGDATABASE', 'bsf_farm')
DB_PORT = os.getenv('PGPORT', '5432')

# Connection settings for psycopg2. DATABASE_URL wins when set, so the
# records and the sign-in sessions (SQLAlchemy, also DATABASE_URL) always use
# the same database, and URL options such as ?sslmode=require are honoured.
# Without it the PG* variables are used, as before.
if DATABASE_URL:
    DB_CONFIG = {'dsn': DATABASE_URL}
else:
    DB_CONFIG = {
        'host': DB_HOST,
        'user': DB_USER,
        'password': DB_PASSWORD,
        'database': DB_NAME,
        'port': DB_PORT,
    }

# Currency of order prices and revenue (ISO code shown next to amounts).
CURRENCY = (os.getenv('CURRENCY') or 'KES').strip().upper()[:3]

# Most connections one process keeps open to PostgreSQL (per gunicorn worker).
DB_POOL_MAX = max(2, int(os.getenv('DB_POOL_MAX', '10') or 10))

# Email (Gmail SMTP) settings from environment
EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
# Seconds between scheduled jobs run inside the web process; 0 = off (use the
# jobs worker). For hosts that cannot run a worker, e.g. 900.
JOBS_IN_WEB_INTERVAL = int(os.getenv('JOBS_IN_WEB_INTERVAL', '0') or 0)
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', '') 