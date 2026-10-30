"""Application entry point (gunicorn backend.app:app).

The code lives in backend/core (shared layers) and backend/domains (one
module per business area). Importing each domain registers its routes.
"""

from backend.core.web import app, db  # noqa: F401
import backend.core.security  # noqa: F401  (guards, headers, blueprint permissions)
import backend.core.accounts  # noqa: F401  (user loader)
import backend.domains.auth  # noqa: F401
import backend.domains.admin  # noqa: F401
import backend.domains.audit  # noqa: F401
import backend.domains.waste  # noqa: F401
import backend.domains.units  # noqa: F401
import backend.domains.production  # noqa: F401
import backend.domains.drying  # noqa: F401
import backend.domains.inventory  # noqa: F401
import backend.domains.quality  # noqa: F401
import backend.domains.sales  # noqa: F401
import backend.domains.alerts  # noqa: F401
import backend.domains.batch360  # noqa: F401
import backend.domains.traceability  # noqa: F401
import backend.domains.labels  # noqa: F401
import backend.domains.reports  # noqa: F401
import backend.domains.dashboard  # noqa: F401
import backend.domains.farmer  # noqa: F401
import backend.domains.farm_operations  # noqa: F401
import backend.domains.records  # noqa: F401
import backend.domains.recent_entries  # noqa: F401
import backend.domains.frass  # noqa: F401
import backend.domains.tour  # noqa: F401
import backend.domains.health  # noqa: F401
import backend.domains.pages  # noqa: F401

# Hosts without a worker process (free web plans) run the scheduled jobs here.
from backend.config import JOBS_IN_WEB_INTERVAL

if JOBS_IN_WEB_INTERVAL:
    from backend.jobs import start_in_web

    start_in_web(JOBS_IN_WEB_INTERVAL)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True) 
