#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

readonly DATABASE_NAME="protracklite"
readonly BACKUP_DIR="/var/backups/protracklite/daily"
readonly RETENTION_DAYS=15
readonly LOCK_FILE="/run/lock/protracklite-db-backup.lock"
readonly TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
readonly FINAL_BACKUP="${BACKUP_DIR}/${DATABASE_NAME}-${TIMESTAMP}.sql.gz"
readonly TEMP_BACKUP="${FINAL_BACKUP}.part"

mkdir -p "${BACKUP_DIR}"

exec 9>"${LOCK_FILE}"
if ! /usr/bin/flock -n 9; then
  /usr/bin/logger -t protracklite-db-backup "Skipped: another backup is already running."
  exit 0
fi

cleanup() {
  /usr/bin/rm -f "${TEMP_BACKUP}"
}
trap cleanup EXIT

/usr/bin/mysqldump \
  --single-transaction \
  --quick \
  --routines \
  --triggers \
  --events \
  --hex-blob \
  --set-gtid-purged=OFF \
  "${DATABASE_NAME}" \
  | /usr/bin/gzip -9 > "${TEMP_BACKUP}"

test -s "${TEMP_BACKUP}"
/usr/bin/gzip -t "${TEMP_BACKUP}"
/usr/bin/mv "${TEMP_BACKUP}" "${FINAL_BACKUP}"

# Keep the most recent 15 rolling days. Rotation runs only after a valid new
# backup has been written, so a failed backup never deletes an older copy.
/usr/bin/find "${BACKUP_DIR}" \
  -maxdepth 1 \
  -type f \
  -name "${DATABASE_NAME}-*.sql.gz" \
  -mtime +14 \
  -delete

trap - EXIT
/usr/bin/logger -t protracklite-db-backup \
  "Completed ${FINAL_BACKUP} ($(/usr/bin/stat -c %s "${FINAL_BACKUP}") bytes)."
/usr/bin/printf '%s\n' "${FINAL_BACKUP}"
