# Production Release Checklist

## Application

- [ ] `APP_ENV=production`
- [ ] Production domain configured
- [ ] `/live` returns 200
- [ ] `/ready` returns 200 after deploy
- [ ] Smoke test upload, query, report, export

## Security

- [ ] `JWT_SECRET` generated and stored in secret manager
- [ ] `ENCRYPTION_KEY` generated and stored in secret manager
- [ ] `ALLOWED_ORIGINS` contains HTTPS production origin only
- [ ] CSP/HSTS response headers verified
- [ ] Secret scan clean
- [ ] Dependency audits have no unmitigated Critical/High runtime findings
- [ ] `AUTH_ALLOWED_REDIRECT_ORIGINS` contains HTTPS production origin only
- [ ] Google/Microsoft OAuth credentials configured or social buttons intentionally disabled by env
- [ ] Phone OTP disabled or configured with `PHONE_OTP_DEV_MODE=false` and SMS delivery webhook

## Database

- [ ] PostgreSQL `DATABASE_URL` configured
- [ ] Migration upgrade tested against staging
- [ ] Migration rollback plan reviewed
- [ ] Pool limits reviewed for hosting environment

## Storage

- [ ] `STORAGE_PROVIDER=s3`
- [ ] `S3_BUCKET` configured
- [ ] Bucket versioning or retention enabled
- [ ] Object lifecycle policy configured
- [ ] Upload/delete smoke test passed

## Redis

- [ ] `RATE_LIMITER_BACKEND=redis`
- [ ] `REDIS_URL` configured
- [ ] Redis TLS/auth configured if managed provider requires it
- [ ] Redis outage behavior verified through `/ready`

## Workers

- [ ] Durable queue selected
- [ ] Worker deployment configured
- [ ] Job retries, timeout, cancellation, and idempotency verified
- [ ] Queue-depth alert configured

## Billing

- [ ] Stripe live keys configured
- [ ] Webhook signing secret configured
- [ ] Price IDs mapped for Pro and Team monthly/annual
- [ ] Checkout, webhook, portal, cancellation smoke tests passed

## Monitoring

- [ ] Centralized logs configured
- [ ] Error reporting configured
- [ ] Metrics dashboard created
- [ ] Alerts configured for 5xx, latency, DB, Redis, storage, queue, Stripe

## Backups

- [ ] Automated PostgreSQL backups scheduled
- [ ] Backup checksum generated
- [ ] Restore verified in staging
- [ ] Offsite retention configured
- [ ] RPO/RTO accepted by owner

## CI/CD

- [ ] Production-readiness workflow green
- [ ] Docker images built and tagged
- [ ] Deployment rollback command documented
- [ ] Migrations run before app rollout

## DNS/HTTPS

- [ ] DNS points to production frontend
- [ ] TLS certificate active
- [ ] HTTP redirects to HTTPS
- [ ] HSTS reviewed for domain/subdomains

## Smoke Tests

- [ ] Guest flow
- [ ] `/try-free` starts guest mode without login/register
- [ ] Authenticated free flow
- [ ] Google/Microsoft sign-in callback flow
- [ ] Phone OTP request/verify flow
- [ ] Paid/test billing flow
- [ ] Multi-tenant isolation flow
- [ ] Provider outage flow

## Rollback

- [ ] Previous image tag available
- [ ] Database downgrade or forward-fix plan ready
- [ ] Incident owner assigned
- [ ] Customer communication draft prepared

## Owner Signoff

- [ ] Engineering
- [ ] Security
- [ ] Product
- [ ] Operations
