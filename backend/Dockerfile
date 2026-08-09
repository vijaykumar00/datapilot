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
RUN mkdir -p /app/uploads /app/logs && chown -R datapilot:datapilot /app

USER datapilot

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/live || exit 1

CMD ["sh", "-c", "python scripts/validate_env.py && uvicorn main:app --host ${BACKEND_HOST:-0.0.0.0} --port ${BACKEND_PORT:-8000} --proxy-headers"]
