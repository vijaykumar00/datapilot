#!/usr/bin/env bash
# Restore a DataPilot PostgreSQL backup created by backup-postgres.sh.
#
# Usage: DATABASE_URL=postgresql://... scripts/restore-postgres.sh BACKUP_FILE [--verify-only] [--yes]
#   --verify-only  check checksum + archive integrity, do not touch the database
#   --yes          required to actually restore (drops and recreates existing objects)
# Stop the API and workers before restoring, then run `alembic upgrade head`.
set -euo pipefail

FILE="${1:-}"; shift || true
VERIFY_ONLY=0; CONFIRMED=0
for arg in "$@"; do
  case "$arg" in
    --verify-only) VERIFY_ONLY=1 ;;
    --yes) CONFIRMED=1 ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done
[[ -n "$FILE" && -f "$FILE" ]] || { echo "Backup file not found: $FILE" >&2; exit 1; }
command -v pg_restore >/dev/null || { echo "pg_restore not found on PATH" >&2; exit 1; }

if [[ -f "$FILE.sha256" ]]; then
  ( cd "$(dirname "$FILE")" && sha256sum --check --status "$(basename "$FILE").sha256" ) \
    || { echo "Checksum mismatch for $FILE" >&2; exit 1; }
fi
pg_restore --list "$FILE" >/dev/null
echo "Backup archive verified: $FILE"
[[ "$VERIFY_ONLY" == 1 ]] && exit 0

[[ "$CONFIRMED" == 1 ]] || { echo "Refusing to restore without --yes" >&2; exit 1; }
: "${DATABASE_URL:?DATABASE_URL is required}"
PG_URL="${DATABASE_URL/postgresql+psycopg2:/postgresql:}"
pg_restore --clean --if-exists --no-owner --no-acl --exit-on-error --single-transaction --dbname "$PG_URL" "$FILE"
echo "Restore complete. Next: run 'alembic upgrade head', then start the API and workers."
