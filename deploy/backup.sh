#!/usr/bin/env bash
# Back up the Zehunger ERP database to one verified, timestamped file.
#
#   DATABASE_URL=postgresql://... BACKUP_DIR=/var/backups/zehunger deploy/backup.sh
#
# Writes zehunger-<UTC time>.dump (pg_dump custom format: compressed, restores
# with pg_restore, tables can be restored one by one). The file is checked
# with pg_restore --list before it replaces nothing and counts as a backup;
# a partial or unreadable dump is removed and the script exits non-zero, so
# the systemd timer shows the failure. Backups older than BACKUP_KEEP_DAYS
# (default 14) are deleted only after a new backup succeeded.
#
# Sign-in sessions (flask_sessions) are left out: they hold no business data
# and would sign restored users back in.
set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL is not set}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/zehunger}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"

umask 077
mkdir -p "$BACKUP_DIR"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
final="$BACKUP_DIR/zehunger-$stamp.dump"
partial="$final.partial"
trap 'rm -f "$partial"' EXIT

pg_dump --dbname="$DATABASE_URL" --format=custom --compress=6 \
  --exclude-table-data=flask_sessions --file="$partial"

# A usable dump lists the audit log and the core records.
listing="$(pg_restore --list "$partial")"
for table in users audit_log production_batches product_lots inventory_movements customer_orders; do
  if ! grep -q "TABLE DATA [^ ]* $table " <<<"$listing"; then
    echo "Backup check failed: no data section for $table in $partial" >&2
    exit 1
  fi
done

mv "$partial" "$final"
trap - EXIT
echo "Backup written: $final ($(du -h "$final" | cut -f1))"

find "$BACKUP_DIR" -maxdepth 1 -name 'zehunger-*.dump' -type f -mtime +"$KEEP_DAYS" -print -delete \
  | sed 's/^/Removed old backup: /'
