#!/usr/bin/env bash
# Restore drill: load a backup into an EMPTY scratch database and check it.
#
#   RESTORE_DATABASE_URL=postgresql://.../zehunger_restore_test deploy/restore-check.sh /var/backups/zehunger/zehunger-....dump
#
# Create the scratch database first (createdb zehunger_restore_test). The
# script refuses a database that already has tables, so it can never be
# pointed at the live database by mistake. It restores the dump, prints row
# counts of the main records and runs the readiness check against the copy.
# Drop the scratch database afterwards.
set -euo pipefail

dump="${1:?usage: restore-check.sh <backup.dump>}"
: "${RESTORE_DATABASE_URL:?RESTORE_DATABASE_URL (an empty scratch database) is not set}"
[ -f "$dump" ] || { echo "No such backup: $dump" >&2; exit 1; }

# Options before the database: not every psql build accepts them after it.
tables="$(psql --dbname="$RESTORE_DATABASE_URL" -tAc "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'" | tr -d '[:space:]')"
case "$tables" in
  0) ;;
  ''|*[!0-9]*)
    echo "Refusing: could not count the tables in the target database." >&2
    exit 1 ;;
  *)
    echo "Refusing: the target database already has $tables tables. Use an empty scratch database." >&2
    exit 1 ;;
esac

pg_restore --dbname="$RESTORE_DATABASE_URL" --no-owner --no-privileges --exit-on-error "$dump"
echo "Restored $dump"

psql --dbname="$RESTORE_DATABASE_URL" -c "
  SELECT 'users' AS records, count(*) FROM users
  UNION ALL SELECT 'production batches', count(*) FROM production_batches
  UNION ALL SELECT 'product lots', count(*) FROM product_lots
  UNION ALL SELECT 'stock movements', count(*) FROM inventory_movements
  UNION ALL SELECT 'customer orders', count(*) FROM customer_orders
  UNION ALL SELECT 'audit entries', count(*) FROM audit_log"

# The copy as restored, without running migrations that could hide gaps.
# (The sessions table is in the dump, empty.)
cd "$(dirname "$0")/.."
DATABASE_URL="$RESTORE_DATABASE_URL" python -m backend.preflight
