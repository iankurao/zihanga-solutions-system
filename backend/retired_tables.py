"""Tables from before the traceability chain, and their retirement.

    python -m backend.retired_tables                 # report what is left
    python -m backend.retired_tables --clear-copies  # remove the duplicate copies, then drop

init_db calls retire() on every start: details only the old copies held are
moved onto feeding_events and health_events, and every retired table that is empty is
dropped. A table that still holds rows is kept, and the readiness check
(python -m backend.preflight) says so; nothing is deleted without --clear-copies.
"""
import argparse
import sys

# Copies written next to each canonical production event until October 2026.
# Every row with a production_event_id duplicates that event.
EVENT_COPIES = {
    'feeding_schedule': 'feeding_events',
    'environmental_monitoring_larvaefeeding': 'monitoring_events',
    'health_intervention': 'health_events',
}

# Old tables that nothing writes or reads any more.
RETIRED_TABLES = tuple(EVENT_COPIES) + (
    'harvest_yield', 'waste_collection_items', 'hatchery_health_interventions',
    'drying_input', 'drying_output', 'drying_quality_control', 'drying_review_approval',
    'sales', 'deliveries', 'customer_feedback',
    'operational_location_links',
)

# The old copies kept the tray (and for feeding the tray weights, start in g,
# end in kg). A tray equal to the batch's own ID was filled in by the app.
_FEEDING_BACKFILL = """
UPDATE feeding_events AS fe
SET tray_reference = COALESCE(fe.tray_reference, NULLIF(btrim(fs.tray_batch_id), '')),
    start_weight_kg = COALESCE(fe.start_weight_kg,
                               CASE WHEN fs.start_weight >= 0 THEN fs.start_weight / 1000 END),
    end_weight_kg = COALESCE(fe.end_weight_kg, CASE WHEN fs.end_weight >= 0 THEN fs.end_weight END)
FROM feeding_schedule AS fs
JOIN production_events AS pe ON pe.id = fs.production_event_id
JOIN production_batches AS pb ON pb.id = pe.production_batch_id
WHERE fs.production_event_id = fe.production_event_id
  AND (fe.tray_reference IS NULL OR fe.start_weight_kg IS NULL OR fe.end_weight_kg IS NULL)
  AND (
      (fs.start_weight IS NOT NULL OR fs.end_weight IS NOT NULL)
      OR btrim(fs.tray_batch_id) NOT IN (COALESCE(pb.business_id, ''), COALESCE(pb.batch_code, ''))
  )
"""

_HEALTH_BACKFILL = """
UPDATE health_events AS he
SET tray_reference = NULLIF(btrim(hi.tray_batch_id), '')
FROM health_intervention AS hi
JOIN production_events AS pe ON pe.id = hi.production_event_id
JOIN production_batches AS pb ON pb.id = pe.production_batch_id
WHERE hi.production_event_id = he.production_event_id
  AND he.tray_reference IS NULL
  AND btrim(hi.tray_batch_id) NOT IN (COALESCE(pb.business_id, ''), COALESCE(pb.batch_code, ''))
"""


def _scalar(cursor):
    row = cursor.fetchone()
    return next(iter(row.values())) if isinstance(row, dict) else row[0]


def _exists(cursor, table):
    cursor.execute("SELECT to_regclass(%s) IS NOT NULL", (table,))
    return _scalar(cursor)


def _count(cursor, table):
    cursor.execute(f'SELECT count(*) FROM {table}')  # noqa: S608 - fixed table names
    return _scalar(cursor)


def retire(cursor, clear_copies=False):
    """Move the last details over, then drop each retired table that is empty.
    Returns {table: rows} for the tables that were kept."""
    if _exists(cursor, 'feeding_schedule'):
        cursor.execute(_FEEDING_BACKFILL)
    if _exists(cursor, 'health_intervention'):
        cursor.execute(_HEALTH_BACKFILL)
    if clear_copies:
        for table, canonical in EVENT_COPIES.items():
            if _exists(cursor, table):
                cursor.execute(
                    f'DELETE FROM {table} AS c WHERE EXISTS ('  # noqa: S608
                    f'SELECT 1 FROM {canonical} AS e WHERE e.production_event_id = c.production_event_id)')
    kept = {}
    for table in RETIRED_TABLES:
        if not _exists(cursor, table):
            continue
        rows = _count(cursor, table)
        if rows:
            kept[table] = rows
        else:
            cursor.execute(f'DROP TABLE {table}')
    return kept


def remaining(db):
    """{table: rows} for retired tables still in the database (readiness check)."""
    left = {}
    for table in RETIRED_TABLES:
        if db.fetch_one("SELECT to_regclass(%s) IS NOT NULL AS ok", (table,))['ok']:
            left[table] = db.fetch_one(f'SELECT count(*) AS n FROM {table}')['n']  # noqa: S608
    return left


def main(argv=None):
    parser = argparse.ArgumentParser(description='Retire the tables from before the traceability chain.')
    parser.add_argument('--clear-copies', action='store_true',
                        help='delete old copies of recorded production events (the events themselves stay), '
                             'then drop the emptied tables')
    args = parser.parse_args(argv)
    from backend.database import DatabaseConnection

    db = DatabaseConnection()
    with db.transaction() as cursor:
        kept = retire(cursor, clear_copies=args.clear_copies)
    if not kept:
        print('All retired tables are gone.')
        return 0
    for table, rows in kept.items():
        note = ' (copies of recorded events: --clear-copies removes them)' if table in EVENT_COPIES else ''
        print(f'{table}: {rows} row(s) kept{note}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
