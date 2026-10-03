"""
jobs.py — Durable background jobs backed by the primary database.

Why the database (not an in-process task): jobs survive API restarts, can be
executed by any number of separate worker processes/hosts, and are claimed
atomically (``FOR UPDATE SKIP LOCKED`` on PostgreSQL), so two workers never run
the same job.  A worker that dies mid-job stops heart-beating; its job is
re-queued after ``JOB_VISIBILITY_TIMEOUT_SECONDS`` and retried up to
``max_attempts`` times.

Execution modes (``JOB_EXECUTION_MODE``):
* ``worker`` (required in production): the API only enqueues; ``python worker.py``
  processes execute.  Request handlers optionally wait a bounded time for the
  result and otherwise return ``202`` with a ``job_id`` the client polls.
* ``inline`` (development/tests): the API thread that enqueued the job claims
  and runs it immediately (still recorded durably, still off the event loop).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import random
import socket
import threading
import time
import traceback
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy import text

from core import jsonsafe
from core.db import SessionLocal, engine, is_postgres
from core.models import Job

logger = logging.getLogger("datapilot.jobs")

PRODUCTION_ENVS = {"production", "prod"}
TERMINAL = {"succeeded", "failed"}


class PermanentJobError(Exception):
    """Job failed for a reason retrying cannot fix (bad input, quota, etc.)."""


@dataclass
class JobContext:
    job_id: str
    job_type: str
    workspace_id: str | None
    user_id: str | None
    attempt: int


Handler = Callable[[dict, JobContext], dict | None]
_HANDLERS: dict[str, Handler] = {}
_FAILURE_HOOKS: dict[str, Callable[[dict, JobContext, str], None]] = {}


def register(job_type: str, on_failure: Callable[[dict, JobContext, str], None] | None = None):
    def deco(fn: Handler) -> Handler:
        _HANDLERS[job_type] = fn
        if on_failure:
            _FAILURE_HOOKS[job_type] = on_failure
        return fn

    return deco


def _now() -> dt.datetime:
    return dt.datetime.utcnow()


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def execution_mode() -> str:
    raw = os.getenv("JOB_EXECUTION_MODE")
    if raw:
        return raw.strip().lower()
    app_env = os.getenv("APP_ENV", "development").strip().lower()
    return "worker" if app_env in PRODUCTION_ENVS else "inline"


def worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{threading.get_ident()}"


# ── Enqueue / inspect ─────────────────────────────────────────────────────────

def enqueue(
    job_type: str,
    payload: dict,
    *,
    workspace_id: str | None,
    user_id: str | None,
    max_attempts: int = 3,
) -> str:
    if job_type not in _HANDLERS:
        _ensure_handlers_loaded()
    if job_type not in _HANDLERS:
        raise ValueError(f"Unknown job type '{job_type}'")
    job_id = uuid.uuid4().hex
    now = _now()
    db = SessionLocal()
    try:
        db.add(Job(
            id=job_id,
            job_type=job_type,
            status="queued",
            workspace_id=workspace_id,
            user_id=user_id,
            payload_json=jsonsafe.dumps(payload),
            attempts=0,
            max_attempts=max_attempts,
            run_after=now,
            created_at=now,
            updated_at=now,
        ))
        db.commit()
    finally:
        db.close()
    try:
        from core.observability import JOBS_ENQUEUED
        JOBS_ENQUEUED.labels(job_type).inc()
    except Exception:
        pass
    return job_id


def job_to_dict(job: Job) -> dict[str, Any]:
    result = None
    if job.result_json:
        try:
            result = json.loads(job.result_json)
        except Exception:
            result = None
    return {
        "job_id": job.id,
        "job_type": job.job_type,
        "status": job.status,
        "error": job.error,
        "result": result,
        "has_download": bool(job.result_key),
        "attempts": job.attempts,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


def get_job(job_id: str, workspace_id: str | None = None) -> dict | None:
    db = SessionLocal()
    try:
        q = db.query(Job).filter(Job.id == job_id)
        if workspace_id is not None:
            q = q.filter(Job.workspace_id == workspace_id)
        job = q.first()
        return job_to_dict(job) if job else None
    finally:
        db.close()


def get_job_result_key(job_id: str, workspace_id: str) -> str | None:
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id, Job.workspace_id == workspace_id).first()
        return job.result_key if job and job.status == "succeeded" else None
    finally:
        db.close()


# ── Claiming ──────────────────────────────────────────────────────────────────

def _claim_specific(job_id: str, owner: str) -> bool:
    now = _now()
    with engine.begin() as conn:
        res = conn.execute(
            text(
                "UPDATE jobs SET status='running', locked_by=:owner, heartbeat_at=:now, "
                "attempts=attempts+1, updated_at=:now WHERE id=:id AND status='queued'"
            ),
            {"owner": owner, "now": now, "id": job_id},
        )
        return res.rowcount == 1


def claim_next(owner: str, job_types: list[str] | None = None) -> str | None:
    now = _now()
    type_filter = ""
    params: dict[str, Any] = {"now": now, "owner": owner}
    if job_types:
        names = []
        for i, jt in enumerate(job_types):
            params[f"t{i}"] = jt
            names.append(f":t{i}")
        type_filter = f" AND job_type IN ({', '.join(names)})"
    with engine.begin() as conn:
        if is_postgres:
            row = conn.execute(
                text(
                    "UPDATE jobs SET status='running', locked_by=:owner, heartbeat_at=:now, "
                    "attempts=attempts+1, updated_at=:now "
                    "WHERE id = (SELECT id FROM jobs WHERE status='queued' AND run_after <= :now"
                    f"{type_filter} ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING id"
                ),
                params,
            ).first()
            return row[0] if row else None
        candidate = conn.execute(
            text(
                "SELECT id FROM jobs WHERE status='queued' AND run_after <= :now"
                f"{type_filter} ORDER BY created_at LIMIT 1"
            ),
            params,
        ).first()
        if not candidate:
            return None
        res = conn.execute(
            text(
                "UPDATE jobs SET status='running', locked_by=:owner, heartbeat_at=:now, "
                "attempts=attempts+1, updated_at=:now WHERE id=:id AND status='queued'"
            ),
            {"owner": owner, "now": now, "id": candidate[0]},
        )
        return candidate[0] if res.rowcount == 1 else None


def requeue_stale(visibility_timeout: int | None = None) -> int:
    """Return jobs whose worker stopped heart-beating to the queue (or fail them)."""
    timeout = visibility_timeout or _int_env("JOB_VISIBILITY_TIMEOUT_SECONDS", 300)
    cutoff = _now() - dt.timedelta(seconds=timeout)
    now = _now()
    with engine.begin() as conn:
        failed = conn.execute(
            text(
                "UPDATE jobs SET status='failed', error='Worker stopped responding; retry limit reached.', "
                "finished_at=:now, updated_at=:now "
                "WHERE status='running' AND heartbeat_at < :cutoff AND attempts >= max_attempts"
            ),
            {"now": now, "cutoff": cutoff},
        ).rowcount
        requeued = conn.execute(
            text(
                "UPDATE jobs SET status='queued', locked_by=NULL, run_after=:now, updated_at=:now "
                "WHERE status='running' AND heartbeat_at < :cutoff AND attempts < max_attempts"
            ),
            {"now": now, "cutoff": cutoff},
        ).rowcount
    if failed or requeued:
        logger.warning("Recovered stale jobs: requeued=%s failed=%s", requeued, failed)
    return requeued + failed


# ── Execution ─────────────────────────────────────────────────────────────────

def _ensure_handlers_loaded() -> None:
    # Importing the module registers every handler.
    import core.job_handlers  # noqa: F401


def _heartbeat(job_id: str, stop: threading.Event) -> None:
    interval = _int_env("JOB_HEARTBEAT_SECONDS", 15)
    while not stop.wait(interval):
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("UPDATE jobs SET heartbeat_at=:now WHERE id=:id AND status='running'"),
                    {"now": _now(), "id": job_id},
                )
        except Exception as exc:  # pragma: no cover - transient DB errors
            logger.warning("Job heartbeat failed for %s: %s", job_id, exc)


def run_claimed(job_id: str) -> dict:
    """Execute a job already marked running by this process."""
    _ensure_handlers_loaded()
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job is None:
            raise LookupError(job_id)
        job_type = job.job_type
        payload = json.loads(job.payload_json or "{}")
        ctx = JobContext(job.id, job.job_type, job.workspace_id, job.user_id, job.attempts)
        max_attempts = job.max_attempts
    finally:
        db.close()

    handler = _HANDLERS.get(job_type)
    stop = threading.Event()
    hb = threading.Thread(target=_heartbeat, args=(job_id, stop), daemon=True)
    hb.start()
    started = time.monotonic()
    status, error, result, result_key = "succeeded", None, None, None
    try:
        if handler is None:
            raise PermanentJobError(f"No handler registered for job type '{job_type}'")
        output = handler(payload, ctx) or {}
        result_key = output.pop("_result_key", None) if isinstance(output, dict) else None
        result = output
    except PermanentJobError as exc:
        status, error = "failed", str(exc)
    except Exception as exc:
        logger.error("Job %s (%s) attempt %s failed: %s\n%s", job_id, job_type, ctx.attempt, exc, traceback.format_exc())
        status, error = ("queued" if ctx.attempt < max_attempts else "failed"), str(exc)
    finally:
        stop.set()

    now = _now()
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        job.status = status
        job.error = error
        job.updated_at = now
        if status == "queued":
            backoff = min(300, (2 ** ctx.attempt) * 5) + random.uniform(0, 3)
            job.run_after = now + dt.timedelta(seconds=backoff)
            job.locked_by = None
        else:
            job.finished_at = now
            if result is not None:
                job.result_json = jsonsafe.dumps(result)
            job.result_key = result_key
        db.commit()
    finally:
        db.close()

    try:
        from core.observability import JOB_DURATION, JOBS_FINISHED
        JOBS_FINISHED.labels(job_type, status).inc()
        JOB_DURATION.labels(job_type).observe(time.monotonic() - started)
    except Exception:
        pass

    if status == "failed" and job_type in _FAILURE_HOOKS:
        try:
            _FAILURE_HOOKS[job_type](payload, ctx, error or "failed")
        except Exception as exc:  # pragma: no cover
            logger.error("Failure hook for job %s raised: %s", job_id, exc)

    return {"status": status, "error": error, "result": result}


def run_inline(job_id: str) -> dict:
    """Claim and run *job_id* in the current (non-event-loop) thread."""
    if not _claim_specific(job_id, worker_id()):
        return get_job(job_id) or {"status": "failed", "error": "job not found"}
    out = run_claimed(job_id)
    # Inline mode retries immediately (bounded) instead of waiting for a worker.
    attempts = 1
    while out["status"] == "queued" and attempts < 3:
        attempts += 1
        if not _claim_specific(job_id, worker_id()):
            break
        out = run_claimed(job_id)
    return get_job(job_id) or out


def wait_for_job(job_id: str, timeout_seconds: float, poll_seconds: float = 0.25) -> dict | None:
    """Blocking wait (call only from threadpool/worker threads, never the event loop)."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        job = get_job(job_id)
        if job is None or job["status"] in TERMINAL:
            return job
        if time.monotonic() >= deadline:
            return job
        time.sleep(poll_seconds)


async def await_job(job_id: str, timeout_seconds: float, poll_seconds: float = 0.3) -> dict | None:
    """Async wait used by streaming endpoints (DB polling runs in a thread)."""
    import asyncio

    deadline = time.monotonic() + timeout_seconds
    while True:
        job = await asyncio.to_thread(get_job, job_id)
        if job is None or job["status"] in TERMINAL:
            return job
        if time.monotonic() >= deadline:
            return job
        await asyncio.sleep(poll_seconds)


def submit_and_wait(
    job_type: str,
    payload: dict,
    *,
    workspace_id: str | None,
    user_id: str | None,
    wait_seconds: float,
    max_attempts: int = 3,
) -> dict:
    """Enqueue a job and wait (bounded) for its result.  Sync: use from threadpool only."""
    job_id = enqueue(job_type, payload, workspace_id=workspace_id, user_id=user_id, max_attempts=max_attempts)
    if execution_mode() == "inline":
        return run_inline(job_id) or {"job_id": job_id, "status": "failed"}
    return wait_for_job(job_id, wait_seconds) or {"job_id": job_id, "status": "queued"}


async def submit_and_await(
    job_type: str,
    payload: dict,
    *,
    workspace_id: str | None,
    user_id: str | None,
    wait_seconds: float,
    max_attempts: int = 1,
) -> dict:
    import asyncio

    job_id = await asyncio.to_thread(
        enqueue, job_type, payload, workspace_id=workspace_id, user_id=user_id, max_attempts=max_attempts
    )
    if execution_mode() == "inline":
        return await asyncio.to_thread(run_inline, job_id)
    return await await_job(job_id, wait_seconds) or {"job_id": job_id, "status": "queued"}


def purge_finished(older_than_days: int = 7) -> int:
    cutoff = _now() - dt.timedelta(days=older_than_days)
    from core.storage import get_storage_provider

    db = SessionLocal()
    try:
        old = db.query(Job).filter(Job.status.in_(list(TERMINAL)), Job.finished_at < cutoff).limit(500).all()
        storage = None
        for job in old:
            if job.result_key:
                storage = storage or get_storage_provider()
                try:
                    storage.delete_object(job.result_key)
                except Exception:
                    pass
            db.delete(job)
        db.commit()
        return len(old)
    finally:
        db.close()
