FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    BACKEND_HOST=0.0.0.0 \
    BACKEND_PORT=8000

WORKDIR /app

RUN addgroup --system datapilot && adduser --system --ingroup datapilot datapilot

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/uploads /app/logs /app/data && chown -R datapilot:datapilot /app

USER datapilot

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/live || exit 1

# API process.  Only the reverse proxy may set X-Forwarded-For: FORWARDED_ALLOW_IPS
# must list the proxy's address/CIDR (never "*" unless the backend is unreachable
# except through the proxy).  The same image runs the worker
# (`python worker.py`) and the migration step (`alembic upgrade head`).
ENV FORWARDED_ALLOW_IPS=127.0.0.1 \
    WEB_CONCURRENCY=2 \
    UVICORN_TIMEOUT_KEEP_ALIVE=75

CMD ["sh", "-c", "python scripts/validate_env.py && exec uvicorn main:app --host ${BACKEND_HOST:-0.0.0.0} --port ${BACKEND_PORT:-8000} --workers ${WEB_CONCURRENCY:-2} --proxy-headers --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS}\" --timeout-keep-alive ${UVICORN_TIMEOUT_KEEP_ALIVE:-75} --no-server-header"]
