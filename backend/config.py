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

# Most connections one process keeps open to PostgreSQL (per gunicorn worker).
DB_POOL_MAX = max(2, int(os.getenv('DB_POOL_MAX', '10') or 10))

# API configuration
API_BASE_URL = os.getenv('API_BASE_URL', 'http://127.0.0.1:5000')
API_DEBUG = os.getenv('API_DEBUG', 'true').lower() == 'true'
API_CONFIG = {
    'base_url': API_BASE_URL,
    'debug': API_DEBUG,
}

# API Endpoints Configuration
API_ENDPOINTS = {
    'waste_sourcing': '/api/waste-sourcing',
    'storage_records': '/api/storage-records',
    'processing_records': '/api/processing-records',
    'environmental_monitoring': '/api/environmental-monitoring-waste',
    'larvae_environmental': '/api/environmental-monitoring-larvaefeeding',
    'substrate_preparation': '/api/substrate-preparation',
    'health_intervention': '/api/health-intervention',
    'harvest_yield': '/api/harvest-yield',
    'larvae_feeding': '/api/larvae-feeding',
    'hatchery_batch': '/api/hatchery/batch-information',
    'hatchery_feeding': '/api/hatchery/feeding-records',
    'hatchery_environmental': '/api/hatchery/environmental-monitoring',
    'growth_monitoring': '/api/growth-monitoring',
    'breeding': '/api/breeding',
    'fly_facility': '/api/fly-facility',
    'cage_monitoring': '/api/fly-facility/cage-monitoring',
    'facility_maintenance': '/api/fly-facility/maintenance',
    'pupae_transition': '/api/fly-facility/pupae-transition',
    'egg_collection': '/api/fly-facility/egg-collection',
    'bait_preparation': '/api/fly-facility/bait-preparation',
}

# Table Names
TABLE_NAMES = {
    'cage_monitoring': 'cage_monitoring',
    'facility_maintenance': 'facility_maintenance',
    'pupae_transition': 'pupae_transition',
    'egg_collection': 'egg_collection',
    'bait_preparation': 'bait_preparation',
}

# Required Fields Configuration
REQUIRED_FIELDS = {
    'cage_monitoring': [
        'date', 'cageId', 'temperature', 'humidity',
        'lightingHours', 'ventilationOk', 'cageCleaned',
        'deadFliesRemoved', 'cageDamage',
    ],
    'facility_maintenance': [
        'date', 'moatCheck', 'antsPresent', 'rodentsPresent',
        'birdNetOk', 'trenchRefilled', 'maintenanceNotes',
    ],
    'pupae_transition': [
        'date', 'loveCageId', 'pupaeWeightAdded', 'oldPupaeRemoved',
        'deadFliesRemoved', 'waterPointsChecked', 'newEggCratesInstalled',
    ],
    'egg_collection': [
        'date', 'time', 'cageId', 'eggsCollected',
        'baitReplaced', 'eggsIntact', 'collectorName',
        'collectionMethod',
    ],
    'bait_preparation': [
        'barrelId', 'baitType', 'ingredientsAdded',
        'startDate', 'readyDate',
    ],
}

# Numeric Fields Configuration
NUMERIC_FIELDS = {
    'cage_monitoring': ['temperature', 'humidity', 'lightingHours'],
    'pupae_transition': ['pupaeWeightAdded', 'oldPupaeRemoved', 'numberOfCrates'],
    'egg_collection': ['eggsCollected'],
}

# Success Messages
SUCCESS_MESSAGES = {
    'cage_monitoring': 'Cage monitoring data recorded successfully',
    'facility_maintenance': 'Facility maintenance record saved successfully',
    'pupae_transition': 'Pupae transition record saved successfully',
    'egg_collection': 'Egg collection record saved successfully',
    'bait_preparation': 'Bait preparation record saved successfully',
}

# Error Messages
ERROR_MESSAGES = {
    'missing_fields': 'Missing required fields: {}',
    'invalid_numeric': '{} must be valid numbers',
    'db_error': 'Failed to save {} record. Check server logs.',
    'server_error': 'An internal server error occurred: {}',
}

# Email (Gmail SMTP) settings from environment
EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', '') 