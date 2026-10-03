# DataPilot Production Operations

## Required Services

Production requires:

- PostgreSQL via `DATABASE_URL`; SQLite is rejected when `APP_ENV=production`.
- Redis via `REDIS_URL`; production rate limiting must use `RATE_LIMITER_BACKEND=redis` with `RATE_LIMITER_FAIL_OPEN=false`.
- S3-compatible object storage via `STORAGE_PROVIDER=s3`, `S3_BUCKET`, and optional `S3_ENDPOINT_URL` for R2 or MinIO. Datasets (original uploads and every Parquet version) live here, so every API and worker replica sees the same data.
- `LLM_PROVIDER` (`gemini` | `openai` | `claude` | `ollama`) plus that provider's key. `AI_PROVIDER` is not read by the application and is rejected by the validator.
- A persistent `ENCRYPTION_KEY` (Fernet). User API keys are stored encrypted with it; changing or losing it makes them unreadable.
- `SMTP_HOST` (and credentials) for verification and password-reset email. In production, without SMTP, emails are refused, never logged.
- HTTPS frontend origin in `ALLOWED_ORIGINS`.
- A strong `JWT_SECRET` of at least 32 characters.
- `JOB_EXECUTION_MODE=worker` and at least one `python worker.py` process (two or more for availability).
- Optional OAuth providers via `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` and `MICROSOFT_OAUTH_CLIENT_ID` / `MICROSOFT_OAUTH_CLIENT_SECRET`.
- Optional phone OTP via `PHONE_OTP_ENABLED=true`, `PHONE_OTP_DEV_MODE=false`, and `SMS_OTP_WEBHOOK_URL`.
- `PLATFORM_ADMIN_EMAILS` for operators allowed to manage plan definitions and grants (workspace Owners cannot).

The API and the worker both run `scripts/validate_env.py` at start and refuse to boot on errors.

## Topology

```
browser ─► nginx (frontend container, /api proxy) ─► API (uvicorn, N replicas)
                                                     │
                       PostgreSQL ◄──────────────────┼──► Redis (rate limits)
                       (registry, jobs, users)       │
                                                     └──► S3 bucket (datasets, exports)
                       worker.py (M replicas) ◄── jobs table (FOR UPDATE SKIP LOCKED)
```

- Uploads are spooled to disk, stored in S3, and parsed and profiled by a worker (`dataset_ingest`). The API waits up to `UPLOAD_WAIT_SECONDS`, otherwise it answers `202 {job_id}` and the browser polls `/jobs/{id}`.
- Full exports, report generation and export, forecasts, and long reports run as jobs. Results are downloaded from `/jobs/{id}/download`, scoped to the workspace.
- Workers heartbeat while running jobs. A job whose worker died is requeued after `JOB_VISIBILITY_TIMEOUT_SECONDS`. Maintenance also removes expired guest data, staged transforms, and old job rows.
- Schema migrations run once per deploy (`alembic upgrade head`). They do not run on API start (`RUN_MIGRATIONS_ON_STARTUP` is rejected in production), and the API refuses to start if the schema is not at head.

## Docker Compose

`docker-compose.yml` defines postgres, redis, minio, a one-shot `migrate`, `backend` (API), `worker`, and `frontend`. Only the frontend port is published; the API, MinIO, and Ollama are reachable only on the compose network.

Before starting, set: `POSTGRES_PASSWORD`, `JWT_SECRET`, `ENCRYPTION_KEY`, `LLM_PROVIDER` (plus its key), `SMTP_HOST`, `ALLOWED_ORIGINS`, `VITE_PUBLIC_SITE_URL`, `S3_ACCESS_KEY_ID`, and `S3_SECRET_ACCESS_KEY`.

Scale the services with `docker compose up -d --scale worker=3`, and set `WEB_CONCURRENCY` to change the number of uvicorn processes per API container.

### Reverse proxy and client IPs

- nginx overwrites `X-Forwarded-For` with `$remote_addr`, so clients cannot spoof the per-IP limits on auth endpoints. Uvicorn trusts forwarding headers only from `FORWARDED_ALLOW_IPS`.
- If a cloud load balancer sits in front of nginx, configure `set_real_ip_from <LB CIDR>` and `real_ip_header X-Forwarded-For` in nginx. Do not trust the header blindly.
- `client_max_body_size` is 55 MB (the API enforces `MAX_UPLOAD_BYTES`, 50 MB by default). `/api/chat/stream` has buffering disabled and a 300 s read timeout; the API sends keep-alives every 10 s.
- `/api/metrics` is blocked at nginx. Scrape the API on the private network with `Authorization: Bearer $METRICS_TOKEN`.

### Probes

- `/live`: the process is up.
- `/ready`: checks the database, rate limiter (Redis in production), object storage, AI provider configuration, encryption key, and a writable upload spool. In production the response hides dependency error strings; they are logged instead.

## Storage

Keys:

- `workspace/{workspace_id}/datasets/{dataset_id}/original/{filename}` (the upload)
- `workspace/{workspace_id}/datasets/{dataset_id}/versions/{n}-{uuid}.parquet` (every edit or transform; the last `DATASET_UNDO_DEPTH` are kept for undo)
- `workspace/{workspace_id}/jobs/{job_id}/{file}` (export and report outputs; purged with job rows after `JOB_RETENTION_DAYS`)

Deleting a dataset or workspace deletes its prefix. Local storage is for development only.

## Backups And Restore

Postgres holds users, billing, the dataset registry, and jobs. The bucket holds the dataset contents. Back up both, and restore them to the same point in time.

Linux and macOS:

```bash
DATABASE_URL=postgresql://... scripts/backup-postgres.sh --dir ./backups --retention-days 14 [--with-objects]
scripts/restore-postgres.sh ./backups/datapilot-YYYYMMDD-HHMMSS.dump --verify-only
DATABASE_URL=postgresql://... scripts/restore-postgres.sh ./backups/datapilot-YYYYMMDD-HHMMSS.dump --yes
```

Windows: `scripts/backup-postgres.ps1` and `scripts/restore-postgres.ps1` (same semantics).

- Enable bucket versioning plus a lifecycle rule, or cross-region replication, on the dataset bucket.
- After a restore, run `alembic upgrade head` and then start the API and workers.
- The backup, verify, restore, and tamper-detection steps were exercised against a local PostgreSQL 16. A drill against the real production database and bucket is still required.

Recommended targets: RPO 24 h (tighten for paid tiers), RTO 4 h, 14 daily backups with encrypted offsite copies.

## Security

- Refresh tokens travel only in an HttpOnly, `SameSite=Strict` cookie (`Secure` in production), not in JS-readable storage.
- Rotation detects reuse: replaying a rotated token after a short grace window (`REFRESH_REUSE_GRACE_SECONDS`, for parallel tabs) revokes every session of that user.
- Password reset and password change revoke all sessions.
- OAuth accounts are linked by provider subject. Microsoft sign-in never auto-links to an existing password account.
- The DuckDB SQL sandbox runs each query on a fresh connection with external access disabled. It accepts a single read-only statement with a row cap and timeout, and only the caller's workspace tables are registered.
- AI provider and keys are chosen per user and stored encrypted. The server `.env` is never written at runtime.
- Plan, quota, and feature checks are status-aware: a canceled or expired subscription falls back to free. Quota consumption is an atomic conditional update and is released when no result is produced.

## CI/CD

`.github/workflows/production-readiness.yml` runs:

- Backend on SQLite and PostgreSQL: compile, migration upgrade/downgrade/upgrade, pytest, `pip-audit --strict`.
- Frontend: rules-of-hooks lint, tests, production build, loopback-origin bundle scan, and `npm audit --omit=dev` (blocking for shipped dependencies). An audit of the build tooling also runs but is informational only.
- Docker image builds, `docker compose config`, and a gitleaks secret scan.

## Observability

- Logs: JSON to stdout in production (`LOG_FORMAT=json`), with `request_id`, `user_id`, and `workspace_id` on every line. Every error response carries `request_id`.
- Metrics: Prometheus, from `/metrics` on the API (bearer `METRICS_TOKEN`) and `WORKER_METRICS_PORT` on workers. Covered: HTTP rate, latency, and in-flight requests; rate-limit rejections; limiter backend errors; jobs enqueued, finished, and duration; LLM calls, latency, and tokens; and chat-persistence failures.
- Alerts: `ops/prometheus/alerts.yml`. It covers the API being down, 5xx rate, p95 latency, Redis limiter errors, no workers, job failure rate and duration, LLM error rate, and token spikes.
- Errors: Sentry when `SENTRY_DSN` is set (PII disabled).

## Supported Upload Limits

- 50 MB per file by default (`MAX_UPLOAD_BYTES`), further limited by the plan.
- Up to 250,000 rows (`MAX_DATASET_ROWS`) and 500 columns.
- CSV (encoding and delimiter detection; identifier columns with leading zeros stay text), XLSX, and XLS. Parsing runs in a worker subprocess with a timeout.

## Known Limitations

- The compose stack, images, and cloud services (S3/R2, managed Postgres and Redis, Sentry, Prometheus/Alertmanager) have not been run as a deployed system. The CI container job builds the images, but no full-stack load test has been performed.
- Datasets are processed in memory per job or request (bounded by the row/column limits and `DATASET_CACHE_MAX_BYTES`). Size worker memory to roughly 4× the largest dataset.
