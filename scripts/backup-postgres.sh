#!/usr/bin/env bash
# Back up the DataPilot PostgreSQL database (and optionally the dataset object store).
#
# Datasets (original uploads + Parquet versions) live in object storage, NOT in
# Postgres.  A consistent restore needs both: this database dump AND the bucket
# (enable bucket versioning / cross-region replication, or pass --with-objects
# to mirror the bucket with the AWS CLI).
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
PG_URL="${DATABASE_URL/postgresql+psycopg2:/postgresql:}"
command -v pg_dump >/dev/null || { echo "pg_dump not found on PATH" >&2; exit 1; }

mkdir -p "$BACKUP_DIR"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
FILE="$BACKUP_DIR/datapilot-$STAMP.dump"
export PGCONNECT_TIMEOUT="${PGCONNECT_TIMEOUT:-10}"

pg_dump --format=custom --no-owner --no-acl --file "$FILE" "$PG_URL"
( cd "$BACKUP_DIR" && sha256sum "$(basename "$FILE")" > "$(basename "$FILE").sha256" )
# Verify the archive is readable before declaring success.
pg_restore --list "$FILE" >/dev/null

if [[ "$WITH_OBJECTS" == 1 ]]; then
  : "${S3_BUCKET:?S3_BUCKET is required with --with-objects}"
  command -v aws >/dev/null || { echo "aws CLI not found on PATH" >&2; exit 1; }
  ENDPOINT_ARGS=()
  [[ -n "${S3_ENDPOINT_URL:-}" ]] && ENDPOINT_ARGS=(--endpoint-url "$S3_ENDPOINT_URL")
  aws "${ENDPOINT_ARGS[@]}" s3 sync "s3://$S3_BUCKET" "$BACKUP_DIR/objects-$STAMP" --only-show-errors
fi

find "$BACKUP_DIR" -maxdepth 1 -name 'datapilot-*.dump*' -mtime +"$RETENTION_DAYS" -delete
echo "Backup created: $FILE"
