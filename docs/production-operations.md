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
- Workers heartbeat every `JOB_HEARTBEAT_SECONDS` (15) while running jobs. Each worker sweeps for stale jobs every `JOB_REQUEUE_SWEEP_SECONDS` (15), and a job whose worker stopped heart-beating is requeued after `JOB_VISIBILITY_TIMEOUT_SECONDS` (90). Recovery therefore takes about 90 to 105 s plus the job's own run time. Completion is fenced on the lease (`locked_by`): a worker presumed dead cannot overwrite the result of the newer attempt. Maintenance also removes expired guest data, staged transforms, and old job rows.
- Request handlers never hold a pooled DB connection while waiting on a job, streaming an upload, or hashing a password. The caller identity is resolved, detached, and its read transaction ended before the route body runs (`core.db.release_connection`). Size the pool for concurrent *active* queries, not for concurrent waiting requests.
- Schema migrations run once per deploy (`alembic upgrade head`). They do not run on API start (`RUN_MIGRATIONS_ON_STARTUP` is rejected in production), and the API refuses to start if the schema is not at head.

## Docker Compose

`docker-compose.yml` defines postgres, redis, minio, a one-shot `migrate`, `backend` (API), `worker`, and `frontend`. Only the frontend port is published; the API, MinIO, and Ollama are reachable only on the compose network.

Before starting, set: `POSTGRES_PASSWORD`, `JWT_SECRET`, `ENCRYPTION_KEY`, `LLM_PROVIDER` (plus its key), `SMTP_HOST`, `APP_URL`, `ALLOWED_ORIGINS`, `VITE_PUBLIC_SITE_URL`, `S3_ACCESS_KEY_ID`, and `S3_SECRET_ACCESS_KEY`.

`APP_URL` is the public `https://` URL of the web app. It is used in email-verification and password-reset links, and Stripe return URLs fall back to it. The API and worker refuse to start in production when it is missing, not `https`, or points at localhost.

Scale the services with `docker compose up -d --scale worker=3`, and set `WEB_CONCURRENCY` to change the number of uvicorn processes per API container.

### Reverse proxy and client IPs

- nginx overwrites `X-Forwarded-For` with `$remote_addr`, so clients cannot spoof the per-IP limits on auth endpoints. Uvicorn trusts forwarding headers only from `FORWARDED_ALLOW_IPS`.
- If a cloud load balancer sits in front of nginx, configure `set_real_ip_from <LB CIDR>` and `real_ip_header X-Forwarded-For` in nginx. Do not trust the header blindly.
- `client_max_body_size` is 55 MB (the API enforces `MAX_UPLOAD_BYTES`, 50 MB by default). `/api/chat/stream` has buffering disabled and a 300 s read timeout; the API sends keep-alives every 10 s.
- Cookies are host-only with `Path=/`; serve the SPA and `/api` from the same site (as the compose nginx does). A cross-site API origin would need `SameSite=None` and is not supported.
- `/api/metrics` is blocked at nginx. Scrape the API on the private network with `Authorization: Bearer $METRICS_TOKEN`.

### Probes

- `/live`: the process is up.
- `/ready`: checks the database, rate limiter (Redis in production), object storage (a live `HeadBucket` with a 2 s timeout, cached for 5 s), AI provider configuration, encryption key, and a writable upload spool. In production the response hides dependency error strings; they are logged instead.

### Dependency failures

- Object storage: `S3_CONNECT_TIMEOUT_SECONDS` (2), `S3_READ_TIMEOUT_SECONDS` (5, per socket read), `S3_MAX_ATTEMPTS` (2). After a connectivity failure, storage calls fail immediately for `S3_CIRCUIT_SECONDS` (10). Requests answer `503 STORAGE_UNAVAILABLE` with `Retry-After` and the request id. In the staging drill the first request on a replica failed in 15 to 20 s; later ones failed immediately (before: up to about 120 s, then a gateway timeout).
- Database unavailable or pool timeout: `503 DATABASE_UNAVAILABLE`. Stripe connectivity or API errors: `502 BILLING_PROVIDER_*`. AI provider errors: `502 AI_PROVIDER_ERROR`. Stripe calls time out after `STRIPE_TIMEOUT_SECONDS` (20).
- Every error response carries `request_id` (also in `X-Request-ID`, including unhandled 500s). Exception text is never returned in production, even with `DEBUG=true`.

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
DATABASE_URL=postgresql://... STORAGE_PROVIDER=s3 S3_BUCKET=... scripts/backup-postgres.sh --dir ./backups --with-objects
scripts/restore-postgres.sh ./backups/datapilot-YYYYMMDD-HHMMSS.dump --verify-only
DATABASE_URL=postgresql://... scripts/restore-postgres.sh ./backups/datapilot-YYYYMMDD-HHMMSS.dump \
  --objects-dir ./backups/objects-YYYYMMDD-HHMMSS --yes
```

Windows (PowerShell, same semantics):

```powershell
.\scripts\backup-postgres.ps1 -BackupDir .\backups -WithObjects
.\scripts\restore-postgres.ps1 -BackupFile .\backups\datapilot-YYYYMMDD-HHMMSS.dump -VerifyOnly
.\scripts\restore-postgres.ps1 -BackupFile .\backups\datapilot-YYYYMMDD-HHMMSS.dump -ObjectsDir .\backups\objects-YYYYMMDD-HHMMSS -Yes
```

- `--with-objects` / `-WithObjects` copies the dataset store next to the dump: `aws s3 sync` for `STORAGE_PROVIDER=s3|r2|minio` (AWS CLI required; `S3_ENDPOINT_URL` honoured), or a copy of `LOCAL_STORAGE_DIR/objects` for local storage.
- Without it, the backup still succeeds but warns, and the manifest says `"objects": {"included": false}`.
- Every backup writes `datapilot-<stamp>.manifest.json` (database file plus SHA-256, and object store location and file count).
- Restores require `--yes` / `-Yes`, run in a single transaction, and accept SQLAlchemy-style `postgresql+psycopg2://` URLs.

- Enable bucket versioning plus a lifecycle rule, or cross-region replication, on the dataset bucket.
- After a restore, run `alembic upgrade head` and then start the API and workers.
- `backend/test_backup_scripts.py` drills backup, wipe, restore and tamper detection for both the bash and the PowerShell scripts, with local storage and with an S3 endpoint. CI runs it on the Postgres job. Locally it was run with PowerShell 7.4 on Linux, PostgreSQL 16 and an S3 emulator. A drill on Windows PowerShell 5.1 and against the real production database and bucket is still required.

Recommended targets: RPO 24 h (tighten for paid tiers), RTO 4 h, 14 daily backups with encrypted offsite copies.

## Security

- Browser sessions are cookie-only: the 15-minute access token (`dp_access`) and the 7-day refresh token (`dp_refresh`) are HttpOnly, `SameSite=Strict` cookies (`Secure` in production). JavaScript never sees either; auth responses to the SPA (`X-Session-Mode: cookie`) and every cookie-based refresh return `null` token fields.
- CSRF: unsafe requests authenticated by the cookie must send `X-CSRF-Token` equal to the readable `dp_csrf` cookie (double-submit, constant-time compare); otherwise 403 `CSRF_FAILED`. Bearer-header API clients are unaffected and need no CSRF token.
- Multi-tab: refreshes are serialised across tabs (Web Locks + a session epoch in localStorage); a racing tab gets 409 and retries with the already-rotated cookie.
- Rotation detects reuse: replaying a rotated token after a short grace window (`REFRESH_REUSE_GRACE_SECONDS`, for parallel tabs) revokes every session of that user.
- Password reset and password change revoke all sessions.
- OAuth accounts are linked by provider subject. Microsoft sign-in never auto-links to an existing password account.
- The DuckDB SQL sandbox runs each query on a fresh connection with external access disabled. It accepts a single read-only statement with a row cap and timeout, and only the caller's workspace tables are registered.
- AI provider and keys are chosen per user and stored encrypted. The server `.env` is never written at runtime.
- Plan, quota, and feature checks are status-aware: a canceled or expired subscription falls back to free. Quota consumption is an atomic conditional update and is released when no result is produced.

## CI/CD

`.github/workflows/production-readiness.yml` runs:

- Backend on SQLite and PostgreSQL: compile, migration upgrade/downgrade/upgrade, pytest, `pip-audit --strict`.
- Frontend: rules-of-hooks lint, tests, production build, loopback-origin bundle scan, entry-chunk size budget (450 kB), and `npm audit --omit=dev` (blocking for shipped dependencies).
- An audit of the build tooling also runs but is informational only. Its one known finding is `braces` <= 3.0.3 (GHSA-vfj7-8cjw-p6xm) through tailwindcss 3: no patched `braces` exists, and the only fix is the tailwind 4 major migration. It runs only at build time over the repository's own globs.
- Backend also runs `ruff` (undefined names, unused variables).
- Docker image builds, `docker compose config`, and a gitleaks secret scan.

## Observability

- Logs: JSON to stdout in production (`LOG_FORMAT=json`), with `request_id`, `user_id`, and `workspace_id` on every line. Every error response carries `request_id`.
- Metrics: Prometheus, from `/metrics` on the API (bearer `METRICS_TOKEN`) and `WORKER_METRICS_PORT` on workers. Covered: HTTP rate, latency, and in-flight requests; rate-limit rejections; limiter backend errors; jobs enqueued, finished, and duration; LLM calls, latency, and tokens; and chat-persistence failures.
- Alerts: `ops/prometheus/alerts.yml`. It covers the API being down, 5xx rate, p95 latency, Redis limiter errors, no workers, job failure rate and duration, LLM error rate, and token spikes.
- Errors: Sentry when `SENTRY_DSN` is set (PII disabled). Pin `sentry-sdk==2.71.0` or later. 2.19.2 with FastAPI 0.141 added a wrapper per request to router-included routes, and after about 960 requests per process those routes failed permanently with RecursionError. `test_staging_blockers.py` sends 2,600 routed requests with Sentry enabled.
- Stripe: `stripe==16.0.0` (the version under test). Since stripe-python 13, `StripeObject` is not a `dict`; webhook payloads and API objects are normalised with `to_dict()` before use. Both API shapes are handled: `current_period_*` on items, and `invoice.parent.subscription_details`.

## Supported Upload Limits And Memory

- 50 MB per file by default (`MAX_UPLOAD_BYTES`), further limited by the plan.
- Up to 250,000 rows (`MAX_DATASET_ROWS`), 500 columns (`MAX_DATASET_COLUMNS`) and 20M cells (`MAX_DATASET_CELLS`, rows x columns). The cell cap exists because memory scales with cells: 250k x 500 would need several GB. Limits are checked from the Parquet metadata before a dataset is loaded.
- CSV (encoding and delimiter detection), XLSX, and XLS. A column stays text if any value in it has a meaningful leading zero (`02134`, `0042`), so ZIP codes, account numbers and IDs are never converted to numbers. The whole column is scanned, not a sample. Plain `0` and decimals such as `0.5` do not count. Excel cells that are stored as numbers with a display format such as `00000` arrive as numbers; store them as text in the workbook. Parsing runs in a worker subprocess with a timeout.

Memory path (measured locally on a 250k x 20 CSV, 42.5 MB on disk, 208 MB as a DataFrame):

| Stage | Peak above process baseline, before | After |
|---|---|---|
| Parser subprocess (CSV) | ~400 MB (507 MB RSS) | ~160 MB (262 MB RSS) |
| Ingest, worker process | ~405 MB | ~295 MB |
| Load a version (cold cache) | ~235 MB | ~235 MB (unchanged; this is the frame itself) |
| Transform (row filter), incl. new version | ~330 MB | ~320 MB; superseded versions are no longer kept in the cache |
| Full CSV export | ~390 MB | ~265 MB, written in chunks to a temp file, then streamed to storage and to the client |

How: the parser holds CSV text as Arrow strings and frees each column's temporaries (pandas' `.str` accessor creates reference cycles that otherwise kept every column's string copies alive until a full GC); the canonical Parquet file written by the parser is uploaded as-is (no in-memory re-serialisation); versions are written and read through temp files instead of in-memory byte strings; transforms use shallow copies (every step replaces whole columns or returns a new frame); the dataset cache keeps only the current version of a dataset; CSV exports are rendered in 50k-row chunks to a temp file; job downloads are streamed from a temp file. Parser output is byte-for-byte identical to the previous parser (verified against golden fixtures and an in-test reference implementation).

Sizing rule: allow about 2x the largest in-memory dataset per concurrently running job or request. A transform holds the old and new version (measured at about 1.6x). Add `DATASET_CACHE_MAX_BYTES` (512 MB by default) per process and about 150 MB of runtime. In-memory size depends on content: the 42.5 MB CSV above is 208 MB in memory, mostly text columns. Numeric-only data is about 8 bytes per cell, so the 20M-cell cap is about 160 MB.

## Known Limitations

- Staging validation ran the stack natively on a single 2 vCPU / 7 GB host: nginx (TLS), 2 API processes, 2 workers, Postgres 16, Redis, an S3 emulator (moto), and stub LLM, SMTP and Sentry endpoints. The Docker images, managed cloud services, a real Stripe test account, and a real LLM were not part of it.
- Load test results on that host, with a realistic per-user mix (files, preview, billing, sessions, chat, CSV export) and 1 to 3 s think time:

  | Users | Requests/s | Errors (excl. intended 429) | p50 | p95 | p99 |
  |---|---|---|---|---|---|
  | 100 | 36.5 | 0 | 0.3 s | 1.8 s | 2.7 s |
  | 250 | 36.3 | 0 | 1.9 s | 15.2 s | 19.1 s |
  | 500 | 33.8 | 0 | 8.7 s | 25.2 s | 28.8 s |

  Before the fixes, 500 users produced 36% errors from pool exhaustion. Now there are no errors, no stalls, and no pool timeouts. Throughput is flat at about 35 requests/s because the single 2 vCPU host is CPU-saturated (about 90%). Above about 100 concurrent users per 2 vCPUs, latency grows linearly, so capacity has to come from more API replicas and cores, not from a larger DB pool.
- Datasets are still processed in memory per job or request (pandas). The row, column and cell caps bound them, and the sizing rule above applies. True out-of-core processing would need a DuckDB-native pipeline, which is not implemented.
