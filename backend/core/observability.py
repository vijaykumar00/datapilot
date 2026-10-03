"""
observability.py — Structured logs, request context, Prometheus metrics, Sentry.

* ``configure_logging()``: JSON logs to stdout (``LOG_FORMAT=json``, default in
  production) carrying request_id / user_id / workspace_id from context vars.
  Containers ship stdout to the log platform; no local log files are required.
* Prometheus metrics exposed on ``/metrics`` (API, protected by
  ``METRICS_TOKEN``) and on ``WORKER_METRICS_PORT`` (worker).
* Sentry error reporting when ``SENTRY_DSN`` is set.
"""

from __future__ import annotations

import contextvars
import json
import logging
import logging.handlers
import os
import sys
import time
from pathlib import Path

from prometheus_client import Counter, Gauge, Histogram

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
user_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("user_id", default=None)
workspace_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("workspace_id", default=None)

# ── Metrics ───────────────────────────────────────────────────────────────────
HTTP_REQUESTS = Counter("datapilot_http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_LATENCY = Histogram(
    "datapilot_http_request_duration_seconds", "HTTP request latency", ["method", "route"],
    buckets=(0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
)
HTTP_IN_FLIGHT = Gauge("datapilot_http_in_flight_requests", "In-flight HTTP requests")
RATE_LIMITED = Counter("datapilot_rate_limited_total", "Requests rejected by the rate limiter", ["scope"])
RATE_LIMITER_ERRORS = Counter("datapilot_rate_limiter_backend_errors_total", "Rate limiter backend errors")
JOBS_ENQUEUED = Counter("datapilot_jobs_enqueued_total", "Jobs enqueued", ["job_type"])
JOBS_FINISHED = Counter("datapilot_jobs_finished_total", "Jobs finished", ["job_type", "status"])
JOB_DURATION = Histogram("datapilot_job_duration_seconds", "Job execution time", ["job_type"],
                         buckets=(0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600))
LLM_REQUESTS = Counter("datapilot_llm_requests_total", "LLM calls", ["provider", "outcome"])
LLM_LATENCY = Histogram("datapilot_llm_request_duration_seconds", "LLM call latency", ["provider"],
                        buckets=(0.5, 1, 2, 5, 10, 20, 40, 60, 120))
LLM_TOKENS = Counter("datapilot_llm_tokens_total", "LLM tokens consumed", ["provider"])
CHAT_PERSIST_FAILURES = Counter("datapilot_chat_persist_failures_total", "Chat messages that failed to persist")


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        record.user_id = user_id_var.get()
        record.workspace_id = workspace_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("request_id", "user_id", "workspace_id"):
            value = getattr(record, key, None)
            if value:
                payload[key] = value
        for key in ("method", "path", "status", "duration_ms", "client_ip"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


_configured = False


def configure_logging() -> None:
    global _configured
    if _configured:
        return
    _configured = True
    production = os.getenv("APP_ENV", "development").strip().lower() in {"production", "prod"}
    fmt = os.getenv("LOG_FORMAT", "json" if production else "text").lower()
    level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)

    stream = logging.StreamHandler(sys.stdout)
    try:
        stream.stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    handlers: list[logging.Handler] = [stream]
    if os.getenv("LOG_FILE_ENABLED", "false" if production else "true").lower() in {"1", "true", "yes"}:
        log_dir = Path(__file__).parent.parent / "logs"
        log_dir.mkdir(exist_ok=True)
        handlers.append(logging.handlers.RotatingFileHandler(log_dir / "datapilot.log", maxBytes=5_000_000,
                                                             backupCount=3, encoding="utf-8"))
    formatter: logging.Formatter = (
        JsonFormatter() if fmt == "json"
        else logging.Formatter("%(asctime)s [%(levelname)s] %(name)s [req=%(request_id)s]: %(message)s")
    )
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    for h in handlers:
        h.setFormatter(formatter)
        h.addFilter(ContextFilter())
        root.addHandler(h)
    root.setLevel(level)
    for noisy in ("httpx", "httpcore", "botocore", "boto3", "urllib3", "multipart"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def init_sentry(component: str) -> None:
    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        return
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=dsn,
            environment=os.getenv("APP_ENV", "development"),
            release=os.getenv("APP_RELEASE"),
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.05")),
            send_default_pii=False,
            server_name=component,
        )
    except Exception as exc:  # pragma: no cover
        logging.getLogger("datapilot.observability").warning("Sentry init failed: %s", exc)
