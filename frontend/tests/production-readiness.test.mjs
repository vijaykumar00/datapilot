import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { test } from 'node:test'

function read(path) {
  return readFileSync(new URL(path, import.meta.url), 'utf8')
}

test('RC-2 Docker artifacts exist and include production health checks', () => {
  const backendDockerfile = read('../../backend/Dockerfile')
  const frontendDockerfile = read('../Dockerfile')
  const compose = read('../../docker-compose.yml')

  assert.match(backendDockerfile, /USER datapilot/)
  assert.match(backendDockerfile, /HEALTHCHECK/)
  assert.match(backendDockerfile, /\/live/)
  assert.match(frontendDockerfile, /FROM node:20-alpine AS build/)
  assert.match(frontendDockerfile, /FROM nginx:1\.27-alpine AS runtime/)
  assert.match(frontendDockerfile, /HEALTHCHECK/)
  assert.match(compose, /postgres:/)
  assert.match(compose, /redis:/)
  assert.match(compose, /minio:/)
  assert.match(compose, /condition: service_healthy/)
  assert.match(compose, /backend_uploads:/)
  assert.match(compose, /POSTGRES_PASSWORD:\?\Set POSTGRES_PASSWORD/)
})

test('RC-2 environment examples and validator document production requirements', () => {
  const backendEnv = read('../../backend/.env.example')
  const frontendEnv = read('../.env.example')
  const validator = read('../../backend/scripts/validate_env.py')

  for (const key of [
    'JWT_SECRET',
    'DATABASE_URL',
    'REDIS_URL',
    'STORAGE_PROVIDER',
    'S3_BUCKET',
    'ALLOWED_ORIGINS',
    'ENCRYPTION_KEY',
    'GEMINI_API_KEY',
    'STRIPE_WEBHOOK_SECRET',
    'GOOGLE_OAUTH_CLIENT_ID',
    'GOOGLE_OAUTH_CLIENT_SECRET',
    'PHONE_OTP_ENABLED',
    'SMS_OTP_WEBHOOK_URL',
  ]) {
    assert.match(backendEnv, new RegExp(key))
  }

  assert.match(frontendEnv, /VITE_PUBLIC_SITE_URL/)
  assert.match(validator, /DATABASE_URL must use PostgreSQL in production/)
  assert.match(validator, /RATE_LIMITER_BACKEND must be redis in production/)
  assert.match(validator, /STORAGE_PROVIDER=local is not allowed/)
  assert.match(validator, /ALLOWED_ORIGINS entry must be HTTPS/)
  assert.match(validator, /JWT_SECRET must be at least 32 characters/)
})

test('RC-2 backend exposes liveness and readiness probes', () => {
  const main = read('../../backend/main.py')

  assert.match(main, /@app\.get\("\/live"\)/)
  assert.match(main, /@app\.get\("\/ready"\)/)
  assert.match(main, /SELECT 1/)
  assert.match(main, /uploads_writable/)
  assert.match(main, /jwt_secret/)
  assert.match(main, /rate_limiter/)
  assert.match(main, /storage/)
  assert.match(main, /status_code=503/)
})

test('RC-2 production readiness report includes required audit sections and verdict', () => {
  const report = read('../../docs/production-readiness-rc2.md')

  for (const section of [
    'Current Architecture',
    'Environment Configuration Matrix',
    'Docker and Container Readiness',
    'Database Readiness',
    'Redis and Cache',
    'File Storage',
    'Background Jobs',
    'Security Audit',
    'Performance Report',
    'Observability',
    'CI/CD Readiness',
    'Disaster Recovery',
    'Scalability Assessment',
    'Technical Debt Register',
    'Production Readiness Score',
    'CONDITIONAL PASS',
  ]) {
    assert.match(report, new RegExp(section.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')))
  }
})

test('RC-2 nginx config serves SPA with baseline security headers', () => {
  const nginx = read('../nginx.conf')

  assert.ok(existsSync(new URL('../nginx.conf', import.meta.url)))
  assert.match(nginx, /try_files \$uri \$uri\/ \/index\.html/)
  assert.match(nginx, /X-Content-Type-Options/)
  assert.match(nginx, /X-Frame-Options/)
  assert.match(nginx, /Referrer-Policy/)
  assert.match(nginx, /Strict-Transport-Security/)
  assert.match(nginx, /Permissions-Policy/)
  assert.match(nginx, /Content-Security-Policy/)
  assert.match(nginx, /frame-ancestors 'none'/)
  assert.match(nginx, /Cache-Control "public, immutable"/)
})
