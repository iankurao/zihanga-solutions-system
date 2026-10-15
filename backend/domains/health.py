"""Health endpoints for load balancers, uptime monitors and systemd.

/healthz  the process is up and answering (never touches the database)
/readyz   the database answers and its schema is up to date

Both are public and say only "ok" or "unavailable"; the reason for a failure
goes to the server log, never to the caller.
"""
from flask import jsonify

from backend.core.web import app, db, logger
from backend.preflight import REQUIRED_MARKERS, REQUIRED_TABLES


def _no_store(response, status):
    response.headers['Cache-Control'] = 'no-store'
    return response, status


@app.route('/healthz', methods=['GET'])
def healthz():
    return _no_store(jsonify({'status': 'ok'}), 200)


@app.route('/readyz', methods=['GET'])
def readyz():
    try:
        row = db.fetch_one(
            """
            SELECT (SELECT count(*) FROM unnest(%s::text[]) AS t(name)
                    WHERE to_regclass(t.name) IS NULL) AS missing_tables,
                   (SELECT count(*) FROM unnest(%s::text[]) AS m(name)
                    WHERE NOT EXISTS (SELECT 1 FROM schema_markers s WHERE s.name = m.name)) AS missing_markers
            """,
            (list(REQUIRED_TABLES), list(REQUIRED_MARKERS)),
        )
    except Exception:  # noqa: BLE001 - any failure means not ready
        logger.exception('Readiness check: database unavailable')
        return _no_store(jsonify({'status': 'unavailable'}), 503)
    if row['missing_tables'] or row['missing_markers']:
        logger.error('Readiness check: schema out of date (%s tables, %s markers missing); run backend.init_db',
                     row['missing_tables'], row['missing_markers'])
        return _no_store(jsonify({'status': 'unavailable'}), 503)
    return _no_store(jsonify({'status': 'ok'}), 200)
