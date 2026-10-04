#!/usr/bin/env bash
# Back up DataPilot: the PostgreSQL database and (with --with-objects) the dataset object store.
#
# Postgres holds users, billing, the dataset registry and jobs; the datasets
# themselves (original uploads + every Parquet version) live in object storage.
# A restorable backup needs both.  --with-objects copies the object store next
# to the dump (STORAGE_PROVIDER=s3|r2|minio: `aws s3 sync`; local: copy of
# $LOCAL_STORAGE_DIR/objects).  Without it a warning is printed and the manifest
# records that dataset contents were NOT included (rely on bucket versioning).
#
# Usage: DATABASE_URL=postgresql://... scripts/backup-postgres.sh [--dir ./backups] [--retention-days 14] [--with-objects]
set -euo pipefail

BACKUP_DIR="./backups"
RETENTION_DAYS=14
WITH_OBJECTS=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir) BACKUP_DIR="$2"; shift 2 ;;
    --retention-days) RETENTION_DAYS="$2"; shift 2 ;;
    --with-objects) WITH_OBJECTS=1; shift ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

: "${DATABASE_URL:?DATABASE_URL is required}"
# SQLAlchemy URLs carry a driver suffix that libpq does not understand.
PG_URL="$(printf '%s' "$DATABASE_URL" | sed -E 's#^postgresql\+[a-z0-9_]+://#postgresql://#')"
command -v pg_dump >/dev/null || { echo "pg_dump not found on PATH" >&2; exit 1; }
PROVIDER="$(printf '%s' "${STORAGE_PROVIDER:-local}" | tr '[:upper:]' '[:lower:]')"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$BACKUP_DIR"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
FILE="$BACKUP_DIR/datapilot-$STAMP.dump"
MANIFEST="$BACKUP_DIR/datapilot-$STAMP.manifest.json"
export PGCONNECT_TIMEOUT="${PGCONNECT_TIMEOUT:-10}"

pg_dump --format=custom --no-owner --no-acl --file "$FILE" "$PG_URL"
( cd "$BACKUP_DIR" && sha256sum "$(basename "$FILE")" > "$(basename "$FILE").sha256" )
SHA="$(cut -d' ' -f1 < "$FILE.sha256")"
# Verify the archive is readable before declaring success.
pg_restore --list "$FILE" >/dev/null

OBJ_INCLUDED=false; OBJ_LOCATION=""; OBJ_PATH=""; OBJ_FILES=0
if [[ "$WITH_OBJECTS" == 1 ]]; then
  OBJ_PATH="$BACKUP_DIR/objects-$STAMP"
  case "$PROVIDER" in
    s3|r2|minio)
      : "${S3_BUCKET:?S3_BUCKET is required with --with-objects}"
      command -v aws >/dev/null || { echo "aws CLI not found on PATH" >&2; exit 1; }
      ENDPOINT_ARGS=()
      [[ -n "${S3_ENDPOINT_URL:-}" ]] && ENDPOINT_ARGS=(--endpoint-url "$S3_ENDPOINT_URL")
      aws "${ENDPOINT_ARGS[@]}" s3 sync "s3://$S3_BUCKET" "$OBJ_PATH" --only-show-errors
      OBJ_LOCATION="s3://$S3_BUCKET" ;;
    local)
      SRC="${LOCAL_STORAGE_DIR:-$SCRIPT_DIR/../backend/uploads}/objects"
      [[ -d "$SRC" ]] || { echo "Local object store not found: $SRC" >&2; exit 1; }
      mkdir -p "$OBJ_PATH" && cp -a "$SRC/." "$OBJ_PATH/"
      OBJ_LOCATION="$SRC" ;;
    *) echo "Unsupported STORAGE_PROVIDER '$PROVIDER' for --with-objects" >&2; exit 1 ;;
  esac
  mkdir -p "$OBJ_PATH"
  OBJ_INCLUDED=true
  OBJ_FILES="$(find "$OBJ_PATH" -type f | wc -l | tr -d ' ')"
else
  echo "WARNING: dataset contents in object storage ($PROVIDER) were NOT backed up." \
       "Re-run with --with-objects, or make sure bucket versioning/replication is enabled." >&2
fi

cat > "$MANIFEST" <<JSON
{
  "created_utc": "$STAMP",
  "database": {"included": true, "file": "$(basename "$FILE")", "sha256": "$SHA"},
  "objects": {"included": $OBJ_INCLUDED, "provider": "$PROVIDER", "location": "$OBJ_LOCATION", "path": "$OBJ_PATH", "files": $OBJ_FILES}
}
JSON

find "$BACKUP_DIR" -maxdepth 1 -name 'datapilot-*' -type f -mtime +"$RETENTION_DAYS" -delete
find "$BACKUP_DIR" -maxdepth 1 -name 'objects-*' -type d -mtime +"$RETENTION_DAYS" -exec rm -rf {} +
echo "Backup created: $FILE"
echo "Manifest: $MANIFEST"
[[ "$OBJ_INCLUDED" == true ]] && echo "Objects: $OBJ_FILES file(s) in $OBJ_PATH"
exit 0
