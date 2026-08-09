# DataPilot Production Operations

## Required Services

Production requires:

- PostgreSQL via `DATABASE_URL`; SQLite is rejected when `APP_ENV=production`.
- Redis via `REDIS_URL`; production rate limiting must use `RATE_LIMITER_BACKEND=redis`.
- S3-compatible object storage via `STORAGE_PROVIDER=s3`, `S3_BUCKET`, and optional `S3_ENDPOINT_URL` for R2 or MinIO.
- HTTPS frontend origin in `ALLOWED_ORIGINS`.
- A strong `JWT_SECRET` of at least 32 characters.

Run `python backend/scripts/validate_env.py` before every deploy.

## Docker

`docker-compose.yml` includes PostgreSQL, Redis, MinIO, backend, and frontend. Set these before starting:

- `POSTGRES_PASSWORD`
- `JWT_SECRET`
- `ALLOWED_ORIGINS`
- `VITE_PUBLIC_SITE_URL`
- `S3_ACCESS_KEY_ID`
- `S3_SECRET_ACCESS_KEY`

The backend `/ready` probe checks database, writable upload/cache path, JWT secret, Redis rate limiter, and storage.

## Storage

Production uploads use keys shaped as:

`workspace/{workspace_id}/datasets/{dataset_id}/{filename}`

Supported object stores:

- AWS S3
- Cloudflare R2
- MinIO

Local storage is for development only. `ALLOW_LOCAL_STORAGE_IN_PRODUCTION=true` is an explicit single-node beta exception and should not be used for public multi-node production.

## Backups And Restore

Use PostgreSQL custom-format backups:

```powershell
.\scripts\backup-postgres.ps1 -DatabaseUrl $env:DATABASE_URL -BackupDir .\backups -RetentionDays 14
```

Verify a backup:

```powershell
.\scripts\restore-postgres.ps1 -BackupFile .\backups\datapilot-YYYYMMDD-HHMMSS.dump -DatabaseUrl $env:DATABASE_URL -VerifyOnly
```

Restore to a target database:

```powershell
.\scripts\restore-postgres.ps1 -BackupFile .\backups\datapilot-YYYYMMDD-HHMMSS.dump -DatabaseUrl $env:DATABASE_URL
```

Recommended beta targets:

- RPO: 24 hours until paid production usage requires tighter recovery.
- RTO: 4 hours for private beta.
- Retention: 14 daily backups minimum, with encrypted offsite copies.

Object storage backup should use bucket versioning and lifecycle retention in the cloud provider.

## Security

Frontend Nginx sets:

- `Content-Security-Policy`
- `Strict-Transport-Security`
- `X-Content-Type-Options`
- `X-Frame-Options`
- `Referrer-Policy`
- `Permissions-Policy`

Refresh tokens are stored in tab-scoped session storage and migrated out of legacy local storage. A later cookie-auth migration should add HttpOnly Secure refresh cookies and CSRF protection.

## CI/CD

`.github/workflows/production-readiness.yml` runs:

- Backend dependency install, compile, migrations, tests, `pip-audit`.
- Frontend install, tests, production build, production API bundle scan, `npm audit`.
- Backend and frontend Docker builds.
- `docker compose config`.
- Secret scanning.

Deployment should run migrations once before rolling out multiple backend replicas.

## Observability

Current built-ins:

- `/live`
- `/ready`
- `/health`
- Rotating backend logs
- DB-backed error log table

Production operators should add centralized logs, Sentry or equivalent error reporting, OpenTelemetry/Prometheus metrics, and alerts for 5xx rate, p95 latency, Redis failures, DB connection failures, storage failures, Stripe webhook failures, and disk usage.

## Supported Upload Limits

Current application limit is 50 MB per request/file. Supported formats are CSV, XLSX, and XLS. CSV parsing uses chunked reads for files above 5 MB, but transformed data is still held in memory after parsing. Large XLSX files remain a risk and should be moved to background jobs before broad public launch.

## Known Limitations

- Long-running upload, analysis, forecast, export, and report work still runs in request workers.
- No durable job queue is implemented yet.
- Browser tests are available locally but are not yet installed as a guaranteed CI browser environment.
- Production restore was scripted but not executed here because no live PostgreSQL service was available in this workspace.
