#!/usr/bin/env bash
# Restore a DataPilot backup created by backup-postgres.sh / backup-postgres.ps1.
#
# Usage: DATABASE_URL=postgresql://... scripts/restore-postgres.sh BACKUP_FILE [--objects-dir DIR] [--verify-only] [--yes]
#   --verify-only   check checksum + archive integrity, do not touch the database
#   --objects-dir   restore the dataset object store from the backup's objects-<stamp> folder
#   --yes           required to actually restore (drops and recreates existing objects)
# Restore database and objects from the SAME backup.  Stop the API and workers
# before restoring, then run `alembic upgrade head`.
set -euo pipefail

FILE="${1:-}"; shift || true
VERIFY_ONLY=0; CONFIRMED=0; OBJECTS_DIR=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --verify-only) VERIFY_ONLY=1; shift ;;
    --yes) CONFIRMED=1; shift ;;
    --objects-dir) OBJECTS_DIR="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ -n "$FILE" && -f "$FILE" ]] || { echo "Backup file not found: $FILE" >&2; exit 1; }
command -v pg_restore >/dev/null || { echo "pg_restore not found on PATH" >&2; exit 1; }
[[ -z "$OBJECTS_DIR" || -d "$OBJECTS_DIR" ]] || { echo "Objects folder not found: $OBJECTS_DIR" >&2; exit 1; }

if [[ -f "$FILE.sha256" ]]; then
  EXPECTED="$(cut -d' ' -f1 < "$FILE.sha256" | tr '[:upper:]' '[:lower:]')"
  ACTUAL="$(sha256sum "$FILE" | cut -d' ' -f1)"
  [[ "$EXPECTED" == "$ACTUAL" ]] || { echo "Checksum mismatch for $FILE" >&2; exit 1; }
fi
pg_restore --list "$FILE" >/dev/null
echo "Backup archive verified: $FILE"
[[ "$VERIFY_ONLY" == 1 ]] && exit 0

[[ "$CONFIRMED" == 1 ]] || { echo "Refusing to restore without --yes" >&2; exit 1; }
: "${DATABASE_URL:?DATABASE_URL is required}"
PG_URL="$(printf '%s' "$DATABASE_URL" | sed -E 's#^postgresql\+[a-z0-9_]+://#postgresql://#')"
pg_restore --clean --if-exists --no-owner --no-acl --exit-on-error --single-transaction --dbname "$PG_URL" "$FILE"
echo "Database restored from: $FILE"

if [[ -n "$OBJECTS_DIR" ]]; then
  PROVIDER="$(printf '%s' "${STORAGE_PROVIDER:-local}" | tr '[:upper:]' '[:lower:]')"
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  case "$PROVIDER" in
    s3|r2|minio)
      : "${S3_BUCKET:?S3_BUCKET is required to restore objects}"
      command -v aws >/dev/null || { echo "aws CLI not found on PATH" >&2; exit 1; }
      ENDPOINT_ARGS=()
      [[ -n "${S3_ENDPOINT_URL:-}" ]] && ENDPOINT_ARGS=(--endpoint-url "$S3_ENDPOINT_URL")
      aws "${ENDPOINT_ARGS[@]}" s3 sync "$OBJECTS_DIR" "s3://$S3_BUCKET" --only-show-errors ;;
    local)
      TARGET="${LOCAL_STORAGE_DIR:-$SCRIPT_DIR/../backend/uploads}/objects"
      mkdir -p "$TARGET" && cp -a "$OBJECTS_DIR/." "$TARGET/" ;;
    *) echo "Unsupported STORAGE_PROVIDER '$PROVIDER' for object restore" >&2; exit 1 ;;
  esac
  echo "Objects restored from: $OBJECTS_DIR"
else
  echo "WARNING: only the database was restored; restore dataset objects from the same backup (--objects-dir) unless the bucket is intact." >&2
fi
echo "Next: run 'alembic upgrade head', then start the API and workers."
