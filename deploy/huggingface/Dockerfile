# DataPilot test deployment for a Hugging Face Docker Space (free CPU tier).
#
# One container runs everything: nginx serves the built frontend on :7860 and
# proxies /api to uvicorn on 127.0.0.1:8000. SQLite, local file storage,
# in-memory rate limiting and inline background jobs replace Postgres, S3,
# Redis and the worker. Data is wiped whenever the Space restarts or redeploys,
# so this is for testing only, not production.
#
# The deploy workflow (.github/workflows/deploy-huggingface.yml) copies this
# file to the Space root and replaces __SPACE_URL__ with the Space's public URL.

FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
ARG VITE_PUBLIC_SITE_URL=__SPACE_URL__
ENV VITE_PUBLIC_SITE_URL=$VITE_PUBLIC_SITE_URL \
    VITE_API_URL=/api
RUN npm run build

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends nginx curl \
    && rm -rf /var/lib/apt/lists/*

# Hugging Face runs Spaces as uid 1000.
RUN useradd -m -u 1000 user

WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

COPY --chown=user backend/ /app/
COPY --chown=user --from=web /web/dist /app/web
COPY --chown=user deploy/huggingface/nginx.conf /app/nginx.conf
COPY --chown=user deploy/huggingface/start.sh /app/start.sh

RUN rm -f /app/.env \
    && mkdir -p /app/uploads /app/logs /tmp/nginx \
    && chown -R user:user /app /tmp/nginx \
    && chmod +x /app/start.sh

USER user

ENV APP_ENV=staging \
    DEBUG=false \
    APP_URL=__SPACE_URL__ \
    FRONTEND_URL=__SPACE_URL__ \
    ALLOWED_ORIGINS=__SPACE_URL__ \
    COOKIE_SECURE=true \
    STORAGE_PROVIDER=local \
    RATE_LIMITER_BACKEND=memory \
    RATE_LIMITER_FAIL_OPEN=false \
    JOB_EXECUTION_MODE=inline \
    RUN_MIGRATIONS_ON_STARTUP=false \
    PHONE_OTP_ENABLED=false \
    PHONE_OTP_DEV_MODE=false \
    STRIPE_BILLING_ENABLED=false \
    LLM_PROVIDER=gemini \
    GEMINI_MODEL=models/gemini-2.5-flash \
    LOG_FORMAT=json

EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD curl -fsS http://127.0.0.1:7860/api/live || exit 1

CMD ["/app/start.sh"]
