"""
worker.py — DataPilot background worker.

Run one or more of these alongside the API (``python worker.py``).  Workers
claim durable jobs from the database (``FOR UPDATE SKIP LOCKED`` on Postgres),
heart-beat while running, and recover jobs from crashed workers.  They also run
periodic maintenance: stale-job recovery, expired staged-transform cleanup,
expired guest-data deletion and old job-result purging.

Environment:
  WORKER_CONCURRENCY      parallel jobs per process (threads, default 2)
  WORKER_POLL_SECONDS     idle poll interval (default 1.0)
  WORKER_JOB_TYPES        optional comma-separated allowlist of job types
  WORKER_METRICS_PORT     optional Prometheus metrics port
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.env_file import load_local_env  # noqa: E402

load_local_env()  # backend/.env for local runs; real env vars win

from core.observability import configure_logging, init_sentry  # noqa: E402

configure_logging()
init_sentry("worker")
logger = logging.getLogger("datapilot.worker")

from core import jobs  # noqa: E402
from core.db import init_db  # noqa: E402
from scripts.validate_env import validate as validate_env  # noqa: E402

_stop = threading.Event()


def _handle_signal(signum, _frame):
    logger.info("Worker received signal %s; finishing current jobs then exiting.", signum)
    _stop.set()


def _loop(slot: int, job_types: list[str] | None, poll: float) -> None:
    owner = f"{jobs.worker_id()}:{slot}"
    while not _stop.is_set():
        try:
            job_id = jobs.claim_next(owner, job_types)
        except Exception as exc:
            logger.error("Job claim failed: %s", exc)
            _stop.wait(min(poll * 5, 10))
            continue
        if not job_id:
            _stop.wait(poll)
            continue
        logger.info("Running job %s", job_id)
        try:
            outcome = jobs.run_claimed(job_id)
            logger.info("Job %s finished: %s", job_id, outcome["status"])
        except Exception as exc:  # run_claimed already records failures
            logger.exception("Job %s crashed: %s", job_id, exc)


def _maintenance(interval: int = int(os.getenv("WORKER_MAINTENANCE_SECONDS", "60"))) -> None:
    from core.job_handlers import cleanup_expired_guests, cleanup_staged_transforms

    # Stale-job recovery runs on its own short cadence: with a 90 s visibility timeout a
    # 60 s sweep would add up to a minute to every crashed-job recovery.
    sweep = max(1, int(os.getenv("JOB_REQUEUE_SWEEP_SECONDS", "15")))
    last_hourly = 0.0
    last_maintenance = float("-inf")
    # Run immediately on start (recovers jobs orphaned by a crashed worker right
    # away), then every ``sweep`` seconds (other housekeeping every ``interval``).
    first = True
    while first or not _stop.wait(sweep):
        first = False
        try:
            jobs.requeue_stale()
        except Exception as exc:
            logger.error("Stale-job recovery failed: %s", exc)
        if time.monotonic() - last_maintenance < interval:
            continue
        last_maintenance = time.monotonic()
        try:
            cleanup_staged_transforms()
            if time.monotonic() - last_hourly > 3600:
                last_hourly = time.monotonic()
                removed = cleanup_expired_guests()
                purged = jobs.purge_finished(int(os.getenv("JOB_RETENTION_DAYS", "7")))
                logger.info("Maintenance: expired guests removed=%s, finished jobs purged=%s", removed, purged)
        except Exception as exc:
            logger.error("Maintenance task failed: %s", exc)


def main() -> int:
    errors = validate_env(dict(os.environ))
    if errors:
        for err in errors:
            logger.error("Environment validation: %s", err)
        return 1
    init_db()
    jobs._ensure_handlers_loaded()

    port = os.getenv("WORKER_METRICS_PORT")
    if port:
        from prometheus_client import start_http_server

        start_http_server(int(port))

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    concurrency = max(1, int(os.getenv("WORKER_CONCURRENCY", "2")))
    poll = float(os.getenv("WORKER_POLL_SECONDS", "1.0"))
    job_types = [t.strip() for t in os.getenv("WORKER_JOB_TYPES", "").split(",") if t.strip()] or None

    threads = [threading.Thread(target=_loop, args=(i, job_types, poll), daemon=True) for i in range(concurrency)]
    threads.append(threading.Thread(target=_maintenance, daemon=True))
    for t in threads:
        t.start()
    logger.info("Worker started (concurrency=%s, job_types=%s)", concurrency, job_types or "all")
    while not _stop.is_set():
        _stop.wait(1)
    for t in threads[:-1]:
        t.join(timeout=float(os.getenv("WORKER_SHUTDOWN_GRACE_SECONDS", "60")))
    logger.info("Worker stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
