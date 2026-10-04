"""
main.py — FastAPI application entry point.

Architecture notes (production):
* Stateless API processes: datasets live in object storage + Postgres, jobs in
  Postgres, rate limits in Redis, AI clients are built per request.  Any number
  of API replicas/workers can serve any request.
* Handlers that do blocking work are plain ``def`` (FastAPI runs them in the
  threadpool) or offload explicitly; the event loop only does I/O.
* Heavy work (upload parsing/profiling, report generation, exports, forecast
  and report agents, large templates) runs as durable jobs on ``worker.py``.
"""

from __future__ import annotations

# Load backend/.env before any core module reads configuration at import time.
from core.env_file import load_local_env

load_local_env()

import asyncio  # noqa: E402
import datetime as dt
import json
import hmac
import logging
import os
import re
import shutil
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, List, Optional

import pandas as pd
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.background import BackgroundTask

from core.observability import (
    CHAT_PERSIST_FAILURES,
    HTTP_IN_FLIGHT,
    HTTP_LATENCY,
    HTTP_REQUESTS,
    configure_logging,
    init_sentry,
    request_id_var,
    user_id_var,
    workspace_id_var,
)

configure_logging()
init_sentry("api")
logger = logging.getLogger("datapilot.main")

import core.analysis_store as analysis_store  # noqa: E402
import core.dataset_store as dataset_store  # noqa: E402
import core.report_dto as report_dto  # noqa: E402
import core.report_store as report_store  # noqa: E402
import core.session_store as session_store  # noqa: E402
from agents.clean_agent import CleanAgent  # noqa: E402
from agents.crossfile_agent import CrossFileAgent  # noqa: E402
from agents.forecast_agent import ForecastAgent  # noqa: E402
from agents.insight_agent import InsightAgent  # noqa: E402
from agents.report_agent import ReportAgent  # noqa: E402
from agents.summary_agent import SummaryAgent  # noqa: E402
from agents.viz_agent import VizAgent  # noqa: E402
from core import jobs, jsonsafe  # noqa: E402
from core.data_store import get_store  # noqa: E402
from core.db import SessionLocal, connection_released, get_db, log_api_error, release_connection  # noqa: E402
from core.error_intelligence import IntelligentException  # noqa: E402
from core.explain_enricher import enrich_explain_metadata  # noqa: E402
from core.file_manager import (  # noqa: E402
    ColumnMappingError,
    ConcurrentModificationError,
    DatasetNotReadyError,
    get_file_manager,
    max_upload_bytes,
)
from core.llm_client import (  # noqa: E402
    PROVIDERS,
    LLMConfigError,
    LLMError,
    build_client,
    get_active_provider,
    platform_settings,
    resolve_settings_for_user,
    settings_for,
)
from core.models import StagedTransform, UserAPIKey, UserSettings  # noqa: E402
from core.rate_limiter import caller_key, check_rate_limit_async, rate_limiter_health  # noqa: E402
from core.request_identity import CallerContext, get_caller  # noqa: E402
from core.router import classify  # noqa: E402
from core.suggestion_engine import build_greeting, generate_suggestions  # noqa: E402
from core.usage import record_ai_tokens  # noqa: E402

APP_VERSION = os.getenv("APP_RELEASE", "1.1.0")


def _get_backend_host() -> str:
    return os.getenv("BACKEND_HOST", "127.0.0.1")


def _get_backend_port() -> int:
    try:
        return int(os.getenv("BACKEND_PORT", "8001"))
    except ValueError:
        return 8001


def _float_env(name: str, default: float) -> float:
    try:
        return max(0.0, float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from core.db import init_db
    from core.stripe_billing import validate_stripe_startup
    from scripts.validate_env import validate as validate_env

    env_errors = validate_env(dict(os.environ))
    if env_errors:
        raise RuntimeError("Environment validation failed: " + "; ".join(env_errors))
    await run_in_threadpool(init_db)
    validate_stripe_startup()
    jobs._ensure_handlers_loaded()
    try:
        platform = platform_settings()
        if not platform.configured:
            logger.error("Platform AI provider '%s' has no API key configured.", platform.provider)
    except LLMConfigError as exc:
        logger.error("AI provider misconfigured: %s", exc)
    logger.info("DataPilot API ready (job execution mode: %s)", jobs.execution_mode())
    yield


app = FastAPI(title="DataPilot API", description="AI data analysis assistant", version=APP_VERSION, lifespan=lifespan)

from core.auth_routes import router as auth_router  # noqa: E402
from core.billing_routes import router as billing_router  # noqa: E402
from core.guest_routes import router as guest_router  # noqa: E402
from core.user_routes import router as user_router  # noqa: E402
from core.workspace_routes import router as workspace_router  # noqa: E402

app.include_router(auth_router)
app.include_router(guest_router)
app.include_router(workspace_router)
app.include_router(user_router)
app.include_router(billing_router)


# ── Middleware ───────────────────────────────────────────────────────────────

def _allowed_origins() -> list[str]:
    raw = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:5174,http://127.0.0.1:5173")
    return [o.strip() for o in raw.split(",") if o.strip()]


def _route_label(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", None) or "unmatched"


class _BodyTooLarge(Exception):
    pass


async def _send_json(send, status_code: int, payload: dict) -> None:
    body = json.dumps(payload).encode()
    await send({"type": "http.response.start", "status": status_code,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


class CookieSessionMiddleware:
    """Browser sessions: authenticate with the HttpOnly ``dp_access`` cookie.

    When a request carries no ``Authorization`` header but has the access cookie,
    the cookie's JWT is presented to the app as ``Authorization: Bearer …`` so all
    existing auth dependencies, tenant scoping and rate limiting apply unchanged.
    Unsafe methods authenticated this way must pass the double-submit CSRF check
    (``X-CSRF-Token`` header == ``dp_csrf`` cookie).  Explicit bearer headers
    (API clients) are used as-is and need no CSRF token.
    """

    SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
    # Credential-establishing endpoints do not use the access cookie (refresh and
    # logout handle their own cookie / CSRF rules).
    EXEMPT_PATHS = ("/auth/login", "/auth/signup", "/auth/oauth/", "/auth/otp/", "/auth/refresh",
                    "/auth/forgot-password", "/auth/reset-password", "/auth/verify-email", "/guest/session")

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        if path == "/auth/logout" or path.startswith(self.EXEMPT_PATHS):
            return await self.app(scope, receive, send)
        headers = scope.get("headers") or []
        if any(k == b"authorization" for k, _ in headers):
            return await self.app(scope, receive, send)
        raw_cookie = b"; ".join(v for k, v in headers if k == b"cookie").decode("latin-1")
        if not raw_cookie:
            return await self.app(scope, receive, send)
        from starlette.requests import cookie_parser
        from core.auth_routes import ACCESS_COOKIE, CSRF_COOKIE, CSRF_HEADER

        cookies = cookie_parser(raw_cookie)
        access = cookies.get(ACCESS_COOKIE)
        if not access:
            return await self.app(scope, receive, send)
        if scope.get("method", "GET").upper() not in self.SAFE_METHODS:
            sent = next((v.decode("latin-1") for k, v in headers if k == CSRF_HEADER.encode()), "")
            expected = cookies.get(CSRF_COOKIE) or ""
            if not expected or not hmac.compare_digest(sent, expected):
                return await _send_json(send, 403, {"success": False, "error": "CSRF token missing or invalid.",
                                                    "detail": {"message": "CSRF token missing or invalid.",
                                                               "code": "CSRF_FAILED"},
                                                    "code": "CSRF_FAILED"})
        scope = dict(scope)
        scope["headers"] = list(headers) + [(b"authorization", f"Bearer {access}".encode("latin-1"))]
        return await self.app(scope, receive, send)


class BodySizeLimitMiddleware:
    """Enforce request size on the actual streamed body (Content-Length can lie or be absent)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        limit = max_upload_bytes() + 1024 * 1024 if path.startswith("/upload") else int(
            _float_env("MAX_JSON_BODY_BYTES", 10 * 1024 * 1024)
        )
        headers = dict(scope.get("headers") or [])
        declared = headers.get(b"content-length")
        if declared is not None:
            try:
                if int(declared) > limit:
                    return await _send_json(send, 413, {"success": False, "error": "Payload too large.",
                                                        "detail": f"Payload too large. Maximum request size is {limit // (1024 * 1024)}MB."})
            except ValueError:
                return await _send_json(send, 400, {"success": False, "error": "Invalid Content-Length header."})
        received = 0
        response_started = False

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _BodyTooLarge()
            return message

        async def tracking_send(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLarge:
            if not response_started:
                await _send_json(send, 413, {"success": False, "error": "Payload too large.",
                                             "detail": "Payload too large."})


@app.middleware("http")
async def rate_limiting_middleware(request: Request, call_next):
    if request.url.path in ("/health", "/live", "/ready", "/metrics") or request.method == "OPTIONS":
        return await call_next(request)
    ip = request.client.host if request.client else "unknown"
    identity = caller_key(request.headers.get("authorization"), request.headers.get("x-guest-token"), ip)
    allowed, scope = await check_rate_limit_async(identity, ip, request.url.path, request.method)
    if not allowed:
        return JSONResponse(status_code=429, headers={"Retry-After": "30"},
                            content={"success": False, "error": "Too many requests. Please try again shortly.",
                                     "detail": "Too many requests. Please try again shortly.", "scope": scope})
    return await call_next(request)


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    """Request id, structured access log and Prometheus metrics for every request."""
    rid = request.headers.get("x-request-id")
    if not rid or len(rid) > 64 or not re.fullmatch(r"[A-Za-z0-9_.:-]+", rid):
        rid = uuid.uuid4().hex
    token = request_id_var.set(rid)
    # Also kept on the request scope: the outermost 500 handler runs after this
    # middleware has reset the contextvar and must still report the same id.
    request.state.request_id = rid
    user_id_var.set(None)
    workspace_id_var.set(None)
    started = time.perf_counter()
    HTTP_IN_FLIGHT.inc()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = rid
        return response
    finally:
        HTTP_IN_FLIGHT.dec()
        elapsed = time.perf_counter() - started
        route = _route_label(request)
        HTTP_REQUESTS.labels(request.method, route, str(status_code)).inc()
        HTTP_LATENCY.labels(request.method, route).observe(elapsed)
        if request.url.path not in ("/live", "/health", "/metrics"):
            logging.getLogger("datapilot.access").info(
                "%s %s %s %.1fms", request.method, request.url.path, status_code, elapsed * 1000,
                extra={"method": request.method, "path": request.url.path, "status": status_code,
                       "duration_ms": round(elapsed * 1000, 1),
                       "client_ip": request.client.host if request.client else None},
            )
        request_id_var.reset(token)


app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(CookieSessionMiddleware)  # inside CORS, outside rate limiting / auth
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Guest-Token", "X-Workspace-ID", "X-Request-ID",
                   "X-CSRF-Token", "X-Session-Mode"],
    expose_headers=["X-Request-ID", "Content-Disposition"],
)


# ── Error handling: one shape {success:false, error:str, detail, request_id} ──

def _error_message(detail) -> str:
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict):
        return str(detail.get("message") or detail.get("error") or "Request failed")
    if isinstance(detail, list) and detail:
        first = detail[0]
        if isinstance(first, dict):
            loc = ".".join(str(p) for p in first.get("loc", [])[1:])
            return f"{loc}: {first.get('msg')}" if loc else str(first.get("msg"))
    return "Request failed"


def _request_id(request: Request | None = None) -> str | None:
    rid = request_id_var.get()
    if not rid and request is not None:
        rid = getattr(request.state, "request_id", None)
    return rid


def _error_response(status_code: int, detail, extra: dict | None = None, headers: dict | None = None,
                    request: Request | None = None) -> JSONResponse:
    rid = _request_id(request)
    body = {"success": False, "error": _error_message(detail), "detail": jsonsafe.to_jsonable(detail),
            "request_id": rid}
    if rid:
        headers = {**(headers or {}), "X-Request-ID": rid}
    if isinstance(detail, dict) and detail.get("error"):
        body["code"] = detail["error"]
    if extra:
        body.update(jsonsafe.to_jsonable(extra))
    return JSONResponse(status_code=status_code, content=body, headers=headers)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return _error_response(exc.status_code, exc.detail, headers=getattr(exc, "headers", None))


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return _error_response(422, jsonsafe.to_jsonable(exc.errors()))


@app.exception_handler(IntelligentException)
async def intelligent_exception_handler(request: Request, exc: IntelligentException):
    return _error_response(400, exc.err_dict.get("message"),
                           {"error": exc.err_dict.get("title", "Error"), "message": exc.err_dict.get("message"),
                            "intelligent_error": exc.err_dict})


@app.exception_handler(DatasetNotReadyError)
async def dataset_not_ready_handler(request: Request, exc: DatasetNotReadyError):
    if exc.status == "processing":
        return _error_response(409, "This dataset is still being processed. Please wait a moment.",
                               {"dataset_status": "processing"})
    return _error_response(422, exc.error or "This dataset could not be processed.", {"dataset_status": exc.status})


@app.exception_handler(ConcurrentModificationError)
async def concurrent_modification_handler(request: Request, exc: ConcurrentModificationError):
    return _error_response(409, str(exc), {"code": "CONCURRENT_MODIFICATION"})


@app.exception_handler(LLMConfigError)
async def llm_config_handler(request: Request, exc: LLMConfigError):
    return _error_response(400, str(exc), {"code": "AI_PROVIDER_NOT_CONFIGURED"})


@app.exception_handler(LLMError)
async def llm_error_handler(request: Request, exc: LLMError):
    # Provider error strings can contain endpoints/model names: log, never echo.
    logger.warning("AI provider error on %s: %s", request.url.path, exc)
    return _error_response(502, "The AI provider failed to respond. Please retry.", {"code": "AI_PROVIDER_ERROR"},
                           request=request)


# ── Infrastructure failures: clear, retryable 502/503 with a request id; no internals ──

def _infrastructure_status(exc: BaseException) -> tuple[int, str, str] | None:
    """Classify dependency outages.  Returns (status, code, public message) or None."""
    from sqlalchemy import exc as sa_exc
    from core.storage import StorageUnavailableError, _is_connectivity_error

    if isinstance(exc, StorageUnavailableError) or _is_connectivity_error(exc):
        return 503, "STORAGE_UNAVAILABLE", "File storage is temporarily unavailable. Please retry shortly."
    if isinstance(exc, (sa_exc.TimeoutError, sa_exc.OperationalError, sa_exc.InterfaceError,
                        sa_exc.DisconnectionError)):
        return 503, "DATABASE_UNAVAILABLE", "The service is temporarily unavailable. Please retry shortly."
    try:
        import stripe as _stripe

        if isinstance(exc, (_stripe.error.APIConnectionError, _stripe.error.RateLimitError)):
            return 502, "BILLING_PROVIDER_UNAVAILABLE", "The billing provider is temporarily unavailable. Please retry."
        if isinstance(exc, _stripe.error.StripeError):
            return 502, "BILLING_PROVIDER_ERROR", "The billing provider rejected the request. Please retry or contact support."
    except ImportError:  # pragma: no cover
        pass
    try:
        from redis.exceptions import ConnectionError as RedisConnectionError, TimeoutError as RedisTimeoutError

        if isinstance(exc, (RedisConnectionError, RedisTimeoutError)):
            return 503, "SERVICE_UNAVAILABLE", "The service is temporarily unavailable. Please retry shortly."
    except ImportError:  # pragma: no cover
        pass
    return None


def _infrastructure_response(request: Request, exc: BaseException, info: tuple[int, str, str]) -> JSONResponse:
    status_code, code, message = info
    logger.error("Dependency failure on %s [%s]: %s: %s", request.url.path, code, type(exc).__name__, exc)
    headers = {"Retry-After": "5"} if status_code == 503 else None
    return _error_response(status_code, message, {"code": code}, headers=headers, request=request)


async def infrastructure_exception_handler(request: Request, exc: Exception):
    info = _infrastructure_status(exc) or (503, "SERVICE_UNAVAILABLE",
                                           "The service is temporarily unavailable. Please retry shortly.")
    return _infrastructure_response(request, exc, info)


def _register_infrastructure_handlers() -> None:
    """Handle dependency outages inside the middleware stack (so access logs/metrics
    record the real 502/503 and the X-Request-ID header is set)."""
    from sqlalchemy import exc as sa_exc
    from core.storage import StorageUnavailableError

    classes: list[type] = [StorageUnavailableError, sa_exc.TimeoutError, sa_exc.OperationalError,
                           sa_exc.InterfaceError, sa_exc.DisconnectionError]
    try:
        import stripe as _stripe

        classes.append(_stripe.error.StripeError)
    except ImportError:  # pragma: no cover
        pass
    try:
        from botocore.exceptions import EndpointConnectionError, ConnectTimeoutError, ReadTimeoutError

        classes += [EndpointConnectionError, ConnectTimeoutError, ReadTimeoutError]
    except ImportError:  # pragma: no cover
        pass
    for cls in classes:
        app.add_exception_handler(cls, infrastructure_exception_handler)


_register_infrastructure_handlers()


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import traceback as _tb

    rid = _request_id(request)
    info = _infrastructure_status(exc)
    if info is not None:
        # Do not try to write an error_logs row: the database may be the failing dependency.
        return _infrastructure_response(request, exc, info)
    logger.error("Unhandled exception on %s: %s", request.url.path, exc, exc_info=True)
    await run_in_threadpool(
        log_api_error,
        request_id=rid,
        endpoint=str(request.url.path),
        error_type=exc.__class__.__name__,
        message=str(exc)[:2000],
        traceback=_tb.format_exc()[-8000:],
        user_id=user_id_var.get(),
        workspace_id=workspace_id_var.get(),
    )
    # Exception text is only ever echoed in local development (never in production).
    debug = os.getenv("DEBUG", "false").lower() == "true" and not _is_production_env()
    message = str(exc) if debug else "An unexpected error occurred. It has been logged."
    return _error_response(500, message, {"error": "Internal Server Error", "message": message}, request=request)


# ── Shared helpers ───────────────────────────────────────────────────────────

def _bind_caller(caller: CallerContext) -> None:
    user_id_var.set(caller.user_id if not caller.is_anonymous else None)
    try:
        workspace_id_var.set(caller.effective_workspace_id)
    except HTTPException:
        pass


def _audit_log(caller: CallerContext, event_type: str, description: str, db: Session) -> None:
    try:
        from core.models import AuditLog

        db.add(AuditLog(
            id=str(uuid.uuid4()),
            user_id=caller.user_id if caller.is_authenticated else None,
            workspace_id=caller.workspace_id if caller.is_authenticated else None,
            guest_session_id=caller.guest.guest_session_id if caller.is_guest else None,
            event_type=event_type,
            description=description,
        ))
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning("Audit log write failed [%s]: %s", event_type, e)


def _require_resource_context(caller: CallerContext) -> tuple[str, str]:
    caller.require_active_context()
    _bind_caller(caller)
    return caller.user_id, caller.effective_workspace_id


def _require_file_record(file_id: str, caller: CallerContext):
    """Fetch a dataset only if it belongs to the caller's workspace/guest namespace."""
    _, workspace_id = _require_resource_context(caller)
    record = get_file_manager().get_record(file_id, workspace_id)
    if record is None:
        raise HTTPException(404, f"File '{file_id}' not found")
    return record


def _llm_for_caller(caller: CallerContext, db: Session):
    """Build a request-scoped AI client for the caller (own key when configured)."""
    if caller.is_authenticated:
        settings = resolve_settings_for_user(caller.user_id, db)
        workspace_id = caller.workspace_id
    else:
        settings = platform_settings()
        workspace_id = None

    def _usage(_provider: str, tokens: int) -> None:
        if workspace_id:
            record_ai_tokens(workspace_id, tokens)

    return build_client(settings, _usage)


def get_agents(llm=None, workspace_id: str | None = None):
    store, files = get_store(), get_file_manager()
    return {
        "insight": InsightAgent(llm, store, files, workspace_id),
        "clean": CleanAgent(llm, store, files, workspace_id),
        "visualize": VizAgent(llm, store, files, workspace_id),
        "forecast": ForecastAgent(llm, store, files, workspace_id),
        "summary": SummaryAgent(llm, store, files, workspace_id),
        "report": ReportAgent(llm, store, files, workspace_id),
        "crossfile": CrossFileAgent(llm, store, files, workspace_id),
    }


def _safe_export_name(name: str, fallback: str) -> str:
    stem = Path(name).stem if name else fallback
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._")
    return cleaned or fallback


def _bytes_download_response(payload: bytes, media_type: str, filename: str) -> Response:
    return Response(content=payload, media_type=media_type,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


EXPORT_MEDIA = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def _job_file_response(job: dict, workspace_id: str) -> Response:
    from core.storage import get_storage_provider

    key = jobs.get_job_result_key(job["job_id"], workspace_id)
    if not key:
        raise HTTPException(404, "Export file not found or expired")
    result = job.get("result") or {}
    # Stream from a temp copy instead of holding the whole export in API memory.
    tmp_dir = tempfile.mkdtemp(prefix="dp_download_")
    local = os.path.join(tmp_dir, "result")
    try:
        get_storage_provider().download_object(key, Path(local))
    except FileNotFoundError:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(404, "Export file not found or expired")
    filename = result.get("filename", "download")
    return FileResponse(local, media_type=result.get("media_type", "application/octet-stream"),
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
                        background=BackgroundTask(shutil.rmtree, tmp_dir, ignore_errors=True))


def _job_outcome(job: dict, *, download: bool, workspace_id: str):
    """Map a job state to an HTTP response (result, file, 202 pending, or error)."""
    status_ = job.get("status")
    if status_ == "succeeded":
        if download:
            return _job_file_response(job, workspace_id)
        return job.get("result") or {}
    if status_ == "failed":
        raise HTTPException(422, job.get("error") or "Background job failed")
    return JSONResponse(status_code=202, content={
        "success": True, "status": "processing", "job_id": job.get("job_id"),
        "message": "Still processing — poll /jobs/{job_id} for the result.",
    })


def _sse(data: dict) -> str:
    return f"data: {jsonsafe.dumps(data)}\n\n"


def _df_to_bytes(df: pd.DataFrame, export_format: str) -> tuple[bytes, str, str]:
    from core.job_handlers import _df_to_bytes as convert

    fmt = export_format.lower()
    if fmt not in {"csv", "xlsx"}:
        raise HTTPException(400, "Unsupported export format. Use csv or xlsx")
    return convert(df, fmt), EXPORT_MEDIA[fmt], fmt


def _quota_payload(caller: CallerContext, action: str) -> dict:
    if caller.is_guest:
        return {"kind": "guest", "namespace": caller.guest.guest_session_id, "action": action}
    return {"kind": "workspace", "namespace": caller.workspace_id, "action": action}


# ── Request / Response models ────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str = Field(..., max_length=32000)
    file_ids: list[str] = Field(default_factory=list, max_length=10)
    conversation_history: list[dict] = Field(default_factory=list, max_length=50)
    session_id: str | None = Field(None, max_length=64)


class ExportRowsRequest(BaseModel):
    rows: list[dict] = Field(default_factory=list, max_length=50000)
    filename: str | None = None
    sql: str | None = Field(None, max_length=20000)
    file_ids: list[str] = Field(default_factory=list, max_length=10)


class ExportReportRequest(BaseModel):
    content: str = Field(..., max_length=2_000_000)
    filename: str | None = None


class CellEdit(BaseModel):
    row_index: int
    column: str
    value: str | int | float | bool | None = None


class UpdateCellsRequest(BaseModel):
    edits: list[CellEdit] = Field(..., max_length=1000)


class CreateSessionRequest(BaseModel):
    session_id: str | None = None
    name: str | None = None


class UpdateSessionRequest(BaseModel):
    name: str | None = None
    pinned: bool | None = None


class TransformPreviewRequest(BaseModel):
    query: str = Field(..., max_length=4000)


class TransformApplyRequest(BaseModel):
    transformation_id: str


class TransformPipelineRequest(BaseModel):
    pipeline: list[dict] = Field(..., max_length=100)


class ReportGenerateRequest(BaseModel):
    file_id: str
    report_type: str
    title: str
    date_range: str | None = None
    brand_colors: dict = {"primary": "#6366f1", "secondary": "#a855f7"}
    x_col: str | None = None
    y_col: str | None = None
    chart_type: str = "bar"


class ReportExportRequest(BaseModel):
    file_id: str
    format: str
    title: str
    date_range: str | None = None
    narrative: str
    kpis: list[dict] = []
    chart_type: str = "bar"
    x_col: str | None = None
    y_col: str | None = None
    brand_colors: dict = {"primary": "#6366f1", "secondary": "#a855f7"}


class TemplateCreateRequest(BaseModel):
    name: str
    description: str
    category: str
    steps: list[dict] = []
    file_id: str | None = None


class TemplateRunRequest(BaseModel):
    mapping_overrides: dict[str, str] | None = None


class SaveAnalysisRequest(BaseModel):
    session_id: str
    title: str
    query: str
    response: str
    type: str = "insight"
    chart_data: dict | None = None
    table_data: list[dict] | None = None
    metadata: dict | None = None
    file_id: str | None = None
    filename: str | None = None
    tags: list[str] = []


class UpdateAnalysisRequest(BaseModel):
    title: str | None = None
    tags: list[str] | None = None
    starred: bool | None = None


class ProviderRequest(BaseModel):
    provider: str
    api_key: str | None = Field(None, max_length=500)


class SwitchSheetRequest(BaseModel):
    sheet: str


class RenameFileRequest(BaseModel):
    filename: str = Field(..., max_length=255)


class UpdateDatasetRequest(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None


# ── Health / metrics ─────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Cheap health endpoint (no external calls, no tenant data)."""
    return {"status": "ok", "version": APP_VERSION, "provider": get_active_provider()}


@app.get("/live")
async def live():
    return {"status": "alive"}


def _is_production_env() -> bool:
    return os.getenv("APP_ENV", "development").strip().lower() in {"production", "prod"}


@app.get("/ready")
def ready():
    """Readiness: dependencies required to serve authenticated traffic."""
    checks = {"database": False, "jwt_secret": False, "rate_limiter": False, "storage": False,
              "ai_provider": False, "encryption_key": False, "upload_spool_writable": False}
    details: dict = {}
    try:
        from sqlalchemy import text
        from core.db import engine

        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception as exc:
        details["database"] = str(exc)
    checks["jwt_secret"] = len(os.getenv("JWT_SECRET", "")) >= 32
    try:
        rl = rate_limiter_health()
        checks["rate_limiter"] = bool(rl["ok"])
        details["rate_limiter"] = rl
    except Exception as exc:
        details["rate_limiter"] = str(exc)
    try:
        from core.storage import storage_health

        st = storage_health()
        checks["storage"] = bool(st["ok"])
        details["storage"] = st
    except Exception as exc:
        details["storage"] = str(exc)
    try:
        ps = platform_settings()
        checks["ai_provider"] = ps.configured
        details["ai_provider"] = {"provider": ps.provider, "configured": ps.configured}
    except LLMConfigError as exc:
        details["ai_provider"] = str(exc)
    try:
        from core.encryption import _load_master_key

        _load_master_key()
        checks["encryption_key"] = True
    except Exception as exc:
        details["encryption_key"] = str(exc)
    try:
        # Uploads are spooled to the temp dir before going to object storage.
        with tempfile.NamedTemporaryFile(prefix="dp_ready_") as probe:
            probe.write(b"ok")
        checks["upload_spool_writable"] = True
    except Exception as exc:
        details["upload_spool_writable"] = str(exc)
    ready_state = all(checks.values())
    if not ready_state:
        logger.warning("Readiness check failed: %s", jsonsafe.to_jsonable(details))
    payload = {"status": "ready" if ready_state else "not_ready", "checks": checks}
    if not _is_production_env():
        # Dependency error strings can reveal hostnames; only expose them outside production.
        payload["details"] = details
    return payload if ready_state else JSONResponse(status_code=503, content=jsonsafe.to_jsonable(payload))


@app.get("/metrics")
def metrics(request: Request):
    """Prometheus metrics. Requires METRICS_TOKEN (bearer) when set; disabled in production without it."""
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    token = os.getenv("METRICS_TOKEN", "")
    production = os.getenv("APP_ENV", "development").lower() in {"production", "prod"}
    if token:
        if request.headers.get("authorization", "") != f"Bearer {token}":
            raise HTTPException(401, "Unauthorized")
    elif production:
        raise HTTPException(404, "Not found")
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ── AI provider (per user, never global) ─────────────────────────────────────

@app.get("/provider")
def get_provider(caller: CallerContext = Depends(get_caller), db: Session = Depends(get_db)):
    """Effective AI provider for the caller (configuration only — no network calls)."""
    try:
        settings = resolve_settings_for_user(caller.user_id, db) if caller.is_authenticated else platform_settings()
        return {"provider": settings.provider, "online": settings.configured, "key_source": settings.key_source,
                "default_provider": get_active_provider()}
    except LLMConfigError as exc:
        pref = None
        if caller.is_authenticated:
            row = db.query(UserSettings).filter(UserSettings.user_id == caller.user_id).first()
            pref = row.llm_provider if row else None
        return {"provider": pref or get_active_provider(), "online": False, "error": str(exc),
                "default_provider": get_active_provider()}


@app.post("/provider")
def switch_provider(req: ProviderRequest, caller: CallerContext = Depends(get_caller), db: Session = Depends(get_db)):
    """Set the CALLER's preferred provider (optionally storing their own key, encrypted).

    Never changes the provider or keys used by any other user and never writes
    server configuration files.
    """
    if not caller.is_authenticated:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Authentication required to choose an AI provider.")
    provider = req.provider.lower()
    if provider not in PROVIDERS:
        raise HTTPException(400, f"Invalid provider. Choose from: {', '.join(PROVIDERS)}")
    if provider == "ollama" and get_active_provider() != "ollama":
        raise HTTPException(400, "Self-hosted Ollama is not available on this deployment.")

    if req.api_key:
        from core.encryption import encrypt_value

        if len(req.api_key.strip()) < 8:
            raise HTTPException(400, "API key is too short.")
        existing = db.query(UserAPIKey).filter(UserAPIKey.user_id == caller.user_id, UserAPIKey.provider == provider).first()
        encrypted = encrypt_value(req.api_key.strip())
        if existing:
            existing.encrypted_key = encrypted
            existing.updated_at = dt.datetime.utcnow()
        else:
            db.add(UserAPIKey(id=str(uuid.uuid4()), user_id=caller.user_id, provider=provider,
                              label=f"{provider.capitalize()} API Key", encrypted_key=encrypted))
    settings_row = db.query(UserSettings).filter(UserSettings.user_id == caller.user_id).first()
    if settings_row is None:
        settings_row = UserSettings(user_id=caller.user_id)
        db.add(settings_row)
    settings_row.llm_provider = provider
    db.commit()

    try:
        online = resolve_settings_for_user(caller.user_id, db).configured
    except LLMConfigError:
        online = False
    logger.info("User %s set preferred AI provider to %s", caller.user_id, provider)
    return {"success": True, "provider": provider, "online": online}


@app.get("/ollama/status")
async def ollama_status(caller: CallerContext = Depends(get_caller)):
    if get_active_provider() != "ollama":
        return {"online": False, "models": []}
    return {"online": await build_client(settings_for("ollama")).is_online(), "models": []}


# ── Jobs ──────────────────────────────────────────────────────────────────────

@app.get("/jobs/{job_id}")
def get_job_status(job_id: str, caller: CallerContext = Depends(get_caller)):
    _, workspace_id = _require_resource_context(caller)
    job = jobs.get_job(job_id, workspace_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return {"success": True, **job}


@app.get("/jobs/{job_id}/download")
def download_job_result(job_id: str, caller: CallerContext = Depends(get_caller)):
    _, workspace_id = _require_resource_context(caller)
    job = jobs.get_job(job_id, workspace_id)
    if job is None or job["status"] != "succeeded":
        raise HTTPException(404, "Export not ready")
    return _job_file_response(job, workspace_id)


# ── Upload ────────────────────────────────────────────────────────────────────

@app.post("/upload")
async def upload_file(file: UploadFile = File(...), caller: CallerContext = Depends(get_caller),
                      db: Session = Depends(get_db)):
    """Upload a CSV/Excel file. Parsing/profiling runs as a durable background job."""
    _require_resource_context(caller)
    caller.require_role("Member")
    filename = file.filename or "upload.csv"
    hard_limit = max_upload_bytes()

    # Spool to disk in chunks — never hold the whole upload in memory.
    tmp = tempfile.NamedTemporaryFile(prefix="dp_upload_", suffix=Path(filename).suffix[:10], delete=False)
    size = 0
    dataset_id = job_id = None
    try:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > hard_limit:
                tmp.close()
                return _error_response(413, f"File too large. Maximum upload size is {hard_limit // (1024 * 1024)}MB.")
            tmp.write(chunk)
        tmp.close()

        def _stage() -> tuple[str, str]:
            caller.check_upload(size, db)
            caller.consume("upload", db)
            try:
                ds_id = get_file_manager().stage_upload(
                    Path(tmp.name), filename, size,
                    workspace_id=caller.effective_workspace_id, user_id=caller.user_id,
                )
            except Exception:
                caller.release("upload", db)
                raise
            j_id = jobs.enqueue(
                "dataset_ingest",
                {"dataset_id": ds_id, "is_guest": caller.is_guest, "quota": _quota_payload(caller, "upload")},
                workspace_id=caller.effective_workspace_id, user_id=caller.user_id, max_attempts=2,
            )
            return ds_id, j_id

        def _stage_released():
            with connection_released(db):
                return _stage()

        try:
            dataset_id, job_id = await run_in_threadpool(_stage_released)
        except ValueError as exc:
            return _error_response(422, str(exc))
    finally:
        try:
            tmp.close()
        except Exception:
            pass
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)

    def _audit_and_release():
        with connection_released(db):  # do not pin a connection while the ingest job runs
            _audit_log(caller, "FILE_UPLOADED", f"File '{filename}' uploaded (id={dataset_id})", db)

    await run_in_threadpool(_audit_and_release)

    if jobs.execution_mode() == "inline":
        job = await run_in_threadpool(jobs.run_inline, job_id)
    else:
        job = await jobs.await_job(job_id, _float_env("UPLOAD_WAIT_SECONDS", 25))
    job = job or {"status": "queued", "job_id": job_id}
    if job.get("status") == "succeeded":
        return {"success": True, **(job.get("result") or {}), "job_id": job_id}
    if job.get("status") == "failed":
        return _error_response(422, job.get("error") or "File processing failed", {"file_id": dataset_id, "job_id": job_id})
    return JSONResponse(status_code=202, content={"success": True, "status": "processing", "job_id": job_id,
                                                  "file_id": dataset_id, "filename": filename})


# ── Files ─────────────────────────────────────────────────────────────────────

@app.get("/files")
def list_files(caller: CallerContext = Depends(get_caller)):
    _, workspace_id = _require_resource_context(caller)
    return {"files": get_file_manager().list_files(workspace_id=workspace_id)}


@app.get("/files/{file_id}/suggestions")
def get_file_suggestions(file_id: str, caller: CallerContext = Depends(get_caller)):
    record = _require_file_record(file_id, caller)
    try:
        suggestions = generate_suggestions(record.df, filename=record.filename, metadata=record.metadata)
        greeting = build_greeting(filename=record.filename, row_count=len(record.df),
                                  col_count=len(record.df.columns), suggestions=suggestions)
        return {"suggestions": jsonsafe.to_jsonable(suggestions), "greeting": greeting}
    except Exception as e:
        logger.warning("Suggestions failed for %s: %s", file_id, e)
        return {"suggestions": [], "greeting": ""}


@app.get("/files/{file_id}")
def get_file_preview(file_id: str, caller: CallerContext = Depends(get_caller)):
    _, workspace_id = _require_resource_context(caller)
    preview = get_file_manager().get_preview_data(file_id, workspace_id=workspace_id)
    if preview is None:
        raise HTTPException(404, f"File '{file_id}' not found")
    return {"success": True, **preview}


@app.get("/files/{file_id}/diagnostics")
def get_file_diagnostics(file_id: str, caller: CallerContext = Depends(get_caller)):
    from core.error_intelligence import diagnose_schema

    record = _require_file_record(file_id, caller)
    warnings = jsonsafe.to_jsonable(diagnose_schema(record.df, record.filename))
    return {
        "success": True,
        "file_id": file_id,
        "filename": record.filename,
        "warnings": warnings,
        "warning_count": len(warnings),
        "warning_count_by_severity": {
            sev: sum(1 for w in warnings if w.get("severity") == sev) for sev in ("critical", "warning", "info")
        },
    }


@app.patch("/files/{file_id}")
def update_file_cells(file_id: str, req: UpdateCellsRequest, caller: CallerContext = Depends(get_caller)):
    _, workspace_id = _require_resource_context(caller)
    caller.require_role("Member")
    try:
        result = get_file_manager().apply_edits(file_id, [e.model_dump() for e in req.edits], workspace_id=workspace_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if result is None:
        raise HTTPException(404, f"File '{file_id}' not found")
    return result


@app.get("/export/file/{file_id}")
def export_file_data(file_id: str, format: str = "csv", caller: CallerContext = Depends(get_caller),
                     db: Session = Depends(get_db)):
    """Export the full dataset (background job; waits briefly, else 202 + job id)."""
    record = _require_file_record(file_id, caller)
    fmt = format.lower()
    if fmt not in {"csv", "xlsx"}:
        raise HTTPException(400, "Unsupported export format. Use csv or xlsx")
    caller.consume("export", db)
    filename = f"{_safe_export_name(record.filename, 'dataset')}.{fmt}"
    release_connection(db)  # never hold a pooled connection while waiting on a job
    job = jobs.submit_and_wait(
        "data_export",
        {"file_id": file_id, "format": fmt, "filename": filename, "media_type": EXPORT_MEDIA[fmt],
         "quota": _quota_payload(caller, "export")},
        workspace_id=caller.effective_workspace_id, user_id=caller.user_id,
        wait_seconds=_float_env("EXPORT_WAIT_SECONDS", 30), max_attempts=2,
    )
    return _job_outcome(job, download=True, workspace_id=caller.effective_workspace_id)


@app.post("/export/results")
def export_result_rows(req: ExportRowsRequest, format: str = "csv", caller: CallerContext = Depends(get_caller),
                       db: Session = Depends(get_db)):
    """Export query results.  With ``sql`` + ``file_ids`` the FULL result is recomputed server-side."""
    _, workspace_id = _require_resource_context(caller)
    fmt = format.lower()
    if fmt not in {"csv", "xlsx"}:
        raise HTTPException(400, "Unsupported export format. Use csv or xlsx")
    filename = f"{_safe_export_name(req.filename or 'results', 'results')}.{fmt}"
    if req.sql and req.file_ids:
        for fid in req.file_ids:
            _require_file_record(fid, caller)
        caller.consume("export", db)
        release_connection(db)  # never hold a pooled connection while waiting on a job
        job = jobs.submit_and_wait(
            "data_export",
            {"sql": req.sql, "file_ids": req.file_ids, "format": fmt, "filename": filename,
             "media_type": EXPORT_MEDIA[fmt], "quota": _quota_payload(caller, "export")},
            workspace_id=workspace_id, user_id=caller.user_id,
            wait_seconds=_float_env("EXPORT_WAIT_SECONDS", 30), max_attempts=2,
        )
        return _job_outcome(job, download=True, workspace_id=workspace_id)
    if not req.rows:
        raise HTTPException(400, "No rows provided for export")
    caller.consume("export", db)
    payload, media_type, _ = _df_to_bytes(pd.DataFrame(req.rows), fmt)
    return _bytes_download_response(payload, media_type, filename)


@app.post("/export/report")
def export_report(req: ExportReportRequest, format: str = "md", caller: CallerContext = Depends(get_caller)):
    _require_resource_context(caller)
    export_format = format.lower()
    if export_format not in {"md", "txt"}:
        raise HTTPException(400, "Unsupported report format. Use md or txt")
    filename = f"{_safe_export_name(req.filename or 'report', 'report')}.{export_format}"
    return _bytes_download_response(req.content.encode("utf-8"), "text/plain; charset=utf-8", filename)


@app.get("/files/{file_id}/sheets")
def list_sheets(file_id: str, caller: CallerContext = Depends(get_caller)):
    record = _require_file_record(file_id, caller)
    return {"file_id": file_id, "sheets": record.metadata.get("sheet_names", []),
            "active_sheet": record.metadata.get("active_sheet")}


@app.post("/files/{file_id}/sheet")
def switch_sheet(file_id: str, req: SwitchSheetRequest, caller: CallerContext = Depends(get_caller)):
    _, workspace_id = _require_resource_context(caller)
    caller.require_role("Member")
    try:
        summary = get_file_manager().switch_sheet(file_id, req.sheet, workspace_id=workspace_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if summary is None:
        raise HTTPException(404, f"File '{file_id}' not found")
    return {"success": True, **summary}


@app.post("/files/{file_id}/rename")
def rename_file(file_id: str, req: RenameFileRequest, caller: CallerContext = Depends(get_caller)):
    _, workspace_id = _require_resource_context(caller)
    caller.require_role("Member")
    if not req.filename.strip():
        raise HTTPException(400, "Filename cannot be empty")
    if not get_file_manager().rename_file(file_id, req.filename, workspace_id=workspace_id):
        raise HTTPException(404, f"File '{file_id}' not found")
    return {"success": True, "file_id": file_id, "filename": req.filename.strip()}


@app.delete("/files/{file_id}")
def delete_file(file_id: str, caller: CallerContext = Depends(get_caller)):
    _, workspace_id = _require_resource_context(caller)
    caller.require_role("Member")
    if not get_file_manager().delete_file(file_id, workspace_id=workspace_id):
        raise HTTPException(404, f"File '{file_id}' not found")
    return {"success": True, "file_id": file_id}


# ── Sessions ──────────────────────────────────────────────────────────────────

@app.get("/sessions")
def get_sessions(limit: Optional[int] = None, offset: int = 0, q: Optional[str] = None,
                 caller: CallerContext = Depends(get_caller)):
    user_id, workspace_id = _require_resource_context(caller)
    res = session_store.get_sessions_paginated(user_id=user_id, workspace_id=workspace_id,
                                               limit=min(limit, 200) if limit else limit, offset=offset, search=q)
    return {"success": True, "sessions": res["sessions"], "total": res["total"]}


@app.post("/sessions")
def create_session(req: CreateSessionRequest, caller: CallerContext = Depends(get_caller)):
    user_id, workspace_id = _require_resource_context(caller)
    return {"success": True, "session": session_store.create_session(req.session_id, req.name, user_id=user_id,
                                                                      workspace_id=workspace_id)}


@app.put("/sessions/{session_id}")
def update_session_route(session_id: str, req: UpdateSessionRequest, caller: CallerContext = Depends(get_caller)):
    user_id, workspace_id = _require_resource_context(caller)
    if not session_store.update_session(session_id, req.name, req.pinned, user_id=user_id, workspace_id=workspace_id):
        raise HTTPException(404, f"Session '{session_id}' not found")
    return {"success": True}


@app.delete("/sessions/{session_id}")
def delete_session(session_id: str, caller: CallerContext = Depends(get_caller)):
    user_id, workspace_id = _require_resource_context(caller)
    ok = session_store.delete_session(session_id, user_id=user_id, workspace_id=workspace_id)
    return {"success": ok, "session_id": session_id}


@app.get("/sessions/{session_id}/messages")
def get_session_messages(session_id: str, caller: CallerContext = Depends(get_caller)):
    user_id, workspace_id = _require_resource_context(caller)
    return {"success": True, "messages": session_store.get_history(session_id, user_id=user_id, workspace_id=workspace_id)}


@app.delete("/session/{session_id}")
def clear_session(session_id: str, caller: CallerContext = Depends(get_caller)):
    user_id, workspace_id = _require_resource_context(caller)
    ok = session_store.clear_session(session_id, user_id=user_id, workspace_id=workspace_id)
    return {"success": ok, "session_id": session_id}


# ── Transformations ───────────────────────────────────────────────────────────

_STAGED_TTL_SECONDS = 1800


@app.post("/files/{file_id}/transform/preview")
async def transform_preview(file_id: str, req: TransformPreviewRequest, caller: CallerContext = Depends(get_caller),
                            db: Session = Depends(get_db)):
    """Plan transformations and dry-run them on a sample; the plan is stored durably for apply."""
    from core.transform_engine import execute_transform, propose_transformations

    record = await run_in_threadpool(_require_file_record, file_id, caller)
    caller.require_role("Member")
    def _llm_released():
        # Resolve the AI client and end the transaction in the same thread: the AI call
        # below can take many seconds and must not keep a pooled connection open.
        with connection_released(db):
            try:
                return _llm_for_caller(caller, db)
            except LLMConfigError:
                return None

    llm = await run_in_threadpool(_llm_released)
    try:
        proposed_actions = await propose_transformations(req.query, record.df, record.table_name, llm=llm)
    except LLMError:
        raise
    except Exception as e:
        logger.warning("Transformation proposal failed for %s: %s", file_id, e)
        raise HTTPException(400, "Could not turn that request into a transformation. Please rephrase it.")

    def _dry_run():
        df_slice = record.df.head(5000)
        df_after = df_slice
        failures = []
        for action in proposed_actions:
            try:
                df_after = execute_transform(df_after, action)
            except Exception as exc:
                failures.append({"action": action.get("action"), "error": str(exc)})
        return df_slice, df_after, failures

    df_slice, df_after, failures = await run_in_threadpool(_dry_run)
    if failures:
        raise HTTPException(400, {"error": "TRANSFORM_PREVIEW_FAILED", "message": failures[0]["error"], "failures": failures})

    def _stage() -> str:
        trans_id = uuid.uuid4().hex
        now = dt.datetime.utcnow()
        db.add(StagedTransform(id=trans_id, dataset_id=file_id, workspace_id=caller.effective_workspace_id,
                               base_version=record.version, actions_json=jsonsafe.dumps(proposed_actions),
                               created_at=now, expires_at=now + dt.timedelta(seconds=_STAGED_TTL_SECONDS)))
        db.commit()
        return trans_id

    trans_id = await run_in_threadpool(_stage)
    head_before, head_after = df_slice.head(50), df_after.head(50)
    rows_before = jsonsafe.records(head_before.astype(object).where(head_before.notna(), ""))
    rows_after = jsonsafe.records(head_after.astype(object).where(head_after.notna(), ""))
    for idx, r in enumerate(rows_before):
        r["_row_index"] = idx
    for idx, r in enumerate(rows_after):
        r["_row_index"] = idx
    sampled = len(record.df) > len(df_slice)
    return {
        "success": True,
        "transformation_id": trans_id,
        "actions": jsonsafe.to_jsonable(proposed_actions),
        "affected_rows": abs(len(df_slice) - len(df_after)),
        "affected_rows_scope": f"first {len(df_slice):,} rows (sample)" if sampled else "all rows",
        "preview_before": {"columns": list(map(str, df_slice.columns)), "rows": rows_before},
        "preview_after": {"columns": list(map(str, df_after.columns)), "rows": rows_after},
    }


@app.post("/files/{file_id}/transform/apply")
def transform_apply(file_id: str, req: TransformApplyRequest, caller: CallerContext = Depends(get_caller),
                    db: Session = Depends(get_db)):
    _, workspace_id = _require_resource_context(caller)
    caller.require_role("Member")
    staged = db.query(StagedTransform).filter(
        StagedTransform.id == req.transformation_id,
        StagedTransform.dataset_id == file_id,
        StagedTransform.workspace_id == workspace_id,
        StagedTransform.expires_at > dt.datetime.utcnow(),
    ).first()
    if staged is None:
        raise HTTPException(404, "Transformation plan not found or expired")
    actions = json.loads(staged.actions_json)
    description = "; ".join(a.get("description") or a.get("action", "step") for a in actions)[:400] or "Apply transformation"
    try:
        result = get_file_manager().apply_actions(file_id, actions, description, workspace_id,
                                                  base_version=staged.base_version)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if result is None:
        raise HTTPException(404, f"File '{file_id}' not found")
    db.delete(staged)
    db.commit()
    return {"success": True, "message": f"Successfully committed {len(actions)} transformation steps.",
            "preview": result["preview"], "history_count": result["history_count"]}


@app.post("/files/{file_id}/transform/undo")
def transform_undo(file_id: str, caller: CallerContext = Depends(get_caller)):
    _, workspace_id = _require_resource_context(caller)
    caller.require_role("Member")
    try:
        res = get_file_manager().undo_transform(file_id, workspace_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if res is None:
        raise HTTPException(404, f"File '{file_id}' not found")
    return {"success": True, "undone_description": res.get("undone_description"), "preview": res.get("preview"),
            "history_count": res.get("history_count")}


@app.post("/files/{file_id}/transform/pipeline")
def transform_pipeline(file_id: str, req: TransformPipelineRequest, caller: CallerContext = Depends(get_caller)):
    _, workspace_id = _require_resource_context(caller)
    caller.require_role("Member")
    try:
        result = get_file_manager().apply_actions(file_id, req.pipeline, f"Pipeline of {len(req.pipeline)} step(s)", workspace_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if result is None:
        raise HTTPException(404, f"File '{file_id}' not found")
    return {"success": True, "message": f"Successfully completed pipeline chain with {len(req.pipeline)} steps.",
            "preview": result["preview"], "history_count": result["history_count"]}


# ── Reports ───────────────────────────────────────────────────────────────────

@app.post("/report/generate")
def report_generate(req: ReportGenerateRequest, caller: CallerContext = Depends(get_caller),
                    db: Session = Depends(get_db)):
    """Generate a report: computed KPIs + chart + AI narrative grounded in computed facts."""
    _require_file_record(req.file_id, caller)
    caller.require_feature("can_generate_report", db, "Report generation")
    caller.check_ai_budget(db)
    caller.consume("report", db)
    release_connection(db)  # never hold a pooled connection while waiting on a job
    job = jobs.submit_and_wait(
        "report_generate",
        {**req.model_dump(), "is_guest": caller.is_guest, "quota": _quota_payload(caller, "report")},
        workspace_id=caller.effective_workspace_id, user_id=caller.user_id,
        wait_seconds=_float_env("REPORT_WAIT_SECONDS", 90), max_attempts=1,
    )
    outcome = _job_outcome(job, download=False, workspace_id=caller.effective_workspace_id)
    if isinstance(outcome, dict):
        _audit_log(caller, "REPORT_GENERATED", f"Report '{req.title}' generated (type={req.report_type})", db)
    return outcome


@app.post("/report/export")
def report_export(req: ReportExportRequest, caller: CallerContext = Depends(get_caller), db: Session = Depends(get_db)):
    _require_file_record(req.file_id, caller)
    fmt = req.format.lower()
    if fmt not in {"pdf", "docx", "pptx", "xlsx"}:
        raise HTTPException(400, f"Unsupported export format '{fmt}'")
    if fmt == "pdf":
        caller.require_feature("can_export_pdf", db, "PDF export")
    filename = f"{_safe_export_name(req.title or 'report', 'report')}.{fmt}"
    release_connection(db)  # never hold a pooled connection while waiting on a job
    job = jobs.submit_and_wait(
        "report_export",
        {**req.model_dump(), "format": fmt, "filename": filename, "media_type": EXPORT_MEDIA[fmt]},
        workspace_id=caller.effective_workspace_id, user_id=caller.user_id,
        wait_seconds=_float_env("EXPORT_WAIT_SECONDS", 60), max_attempts=2,
    )
    return _job_outcome(job, download=True, workspace_id=caller.effective_workspace_id)


# ── Templates ─────────────────────────────────────────────────────────────────

@app.get("/templates")
def get_templates_route(caller: CallerContext = Depends(get_caller)):
    from core.template_store import get_template_store

    user_id, workspace_id = _require_resource_context(caller)
    return {"success": True, "templates": get_template_store().list_templates(user_id=user_id, workspace_id=workspace_id)}


@app.post("/templates")
def create_template_route(req: TemplateCreateRequest, caller: CallerContext = Depends(get_caller)):
    from core.template_store import get_template_store

    user_id, workspace_id = _require_resource_context(caller)
    caller.require_role("Member")
    steps = req.steps
    if req.file_id:
        record = _require_file_record(req.file_id, caller)
        applied = record.metadata.get("applied_workflows", [])
        if not applied:
            raise HTTPException(400, "No active workflow pipelines have been applied to this file to save as a template.")
        steps = []
        for block in applied:
            if "steps" in block:
                steps.extend(block["steps"])
            elif "action" in block:
                steps.append(block["action"])
    if not steps:
        raise HTTPException(400, "Template must contain at least 1 pipeline step.")
    template = get_template_store().create_template(req.name, req.description, req.category, steps,
                                                    user_id=user_id, workspace_id=workspace_id)
    return {"success": True, "template": template}


@app.post("/templates/{template_id}/duplicate")
def duplicate_template_route(template_id: str, caller: CallerContext = Depends(get_caller)):
    from core.template_store import get_template_store

    user_id, workspace_id = _require_resource_context(caller)
    duplicated = get_template_store().duplicate_template(template_id, user_id=user_id, workspace_id=workspace_id)
    if not duplicated:
        raise HTTPException(404, f"Template '{template_id}' not found")
    return {"success": True, "template": duplicated}


@app.delete("/templates/{template_id}")
def delete_template_route(template_id: str, caller: CallerContext = Depends(get_caller)):
    from core.template_store import get_template_store

    user_id, workspace_id = _require_resource_context(caller)
    if not get_template_store().delete_template(template_id, user_id=user_id, workspace_id=workspace_id):
        raise HTTPException(404, f"Custom Template '{template_id}' not found or is a built-in template.")
    return {"success": True}


@app.post("/files/{file_id}/transform/template/{template_id}")
def run_template_on_file(file_id: str, template_id: str, req: TemplateRunRequest,
                         caller: CallerContext = Depends(get_caller)):
    from core.template_store import get_template_store

    user_id, workspace_id = _require_resource_context(caller)
    caller.require_role("Member")
    template = get_template_store().get_template(template_id, user_id=user_id, workspace_id=workspace_id)
    if not template:
        raise HTTPException(404, f"Template '{template_id}' not found")
    try:
        res = get_file_manager().apply_template(file_id, template_id, template["steps"], req.mapping_overrides,
                                                workspace_id=workspace_id, user_id=user_id)
    except ColumnMappingError as e:
        return JSONResponse(status_code=422, content={
            "success": False, "error": str(e), "error_type": "column_mapping_required", "message": str(e),
            "unmapped_columns": e.failed_mappings, "available_columns": e.available_columns,
        })
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if res is None:
        raise HTTPException(404, f"File '{file_id}' not found")
    return res


# ── Saved analyses ────────────────────────────────────────────────────────────

@app.post("/analyses")
def create_analysis(req: SaveAnalysisRequest, caller: CallerContext = Depends(get_caller)):
    user_id, workspace_id = _require_resource_context(caller)
    result = analysis_store.save_analysis(
        session_id=req.session_id, title=req.title, query=req.query, response=req.response, type=req.type,
        chart_data=req.chart_data, table_data=jsonsafe.to_jsonable(req.table_data), metadata=req.metadata,
        file_id=req.file_id, filename=req.filename, tags=req.tags, user_id=user_id, workspace_id=workspace_id,
    )
    return {"success": True, "analysis": result}


@app.get("/analyses")
def list_analyses_route(session_id: str | None = None, file_id: str | None = None, starred: bool = False,
                        limit: int = 100, caller: CallerContext = Depends(get_caller)):
    user_id, workspace_id = _require_resource_context(caller)
    results = analysis_store.list_analyses(session_id=session_id, file_id=file_id, starred_only=starred,
                                           limit=min(max(limit, 1), 500), user_id=user_id, workspace_id=workspace_id)
    return {"success": True, "analyses": results, "count": len(results)}


@app.get("/analyses/{analysis_id}")
def get_analysis_route(analysis_id: str, caller: CallerContext = Depends(get_caller)):
    user_id, workspace_id = _require_resource_context(caller)
    result = analysis_store.get_analysis(analysis_id, user_id=user_id, workspace_id=workspace_id)
    if result is None:
        raise HTTPException(404, f"Analysis '{analysis_id}' not found")
    return {"success": True, "analysis": result}


@app.patch("/analyses/{analysis_id}")
def update_analysis_route(analysis_id: str, req: UpdateAnalysisRequest, caller: CallerContext = Depends(get_caller)):
    user_id, workspace_id = _require_resource_context(caller)
    if not analysis_store.update_analysis(analysis_id, title=req.title, tags=req.tags, starred=req.starred,
                                          user_id=user_id, workspace_id=workspace_id):
        raise HTTPException(404, f"Analysis '{analysis_id}' not found")
    return {"success": True}


@app.delete("/analyses/{analysis_id}")
def delete_analysis_route(analysis_id: str, caller: CallerContext = Depends(get_caller)):
    user_id, workspace_id = _require_resource_context(caller)
    ok = analysis_store.delete_analysis(analysis_id, user_id=user_id, workspace_id=workspace_id)
    return {"success": ok, "analysis_id": analysis_id}


# ── Chat (SSE) ────────────────────────────────────────────────────────────────

HEAVY_INTENTS = {"forecast", "report"}
INTENT_FEATURES = {
    "forecast": ("can_forecast", "Forecasting"),
    "report": ("can_generate_report", "Report generation"),
    "crossfile": ("can_use_multiple_datasets", "Multi-dataset analysis"),
}


def _persist(sid, role, content, extra, user_id, workspace_id):
    if not sid:
        return
    try:
        session_store.append_message(sid, role, content, extra, user_id=user_id, workspace_id=workspace_id)
    except PermissionError:
        logger.warning("Refused to append to a session owned by another tenant (session=%s)", sid)
    except Exception as exc:
        CHAT_PERSIST_FAILURES.inc()
        logger.error("Failed to persist chat message: %s", exc)


def _release_query(caller: CallerContext) -> None:
    db = SessionLocal()
    try:
        caller.release("query", db)
    finally:
        db.close()


class _ScopedFiles:
    """Adapter giving enrich_explain_metadata workspace-scoped record access."""

    def __init__(self, workspace_id: str):
        self.workspace_id = workspace_id

    def get_record(self, file_id: str):
        try:
            return get_file_manager().get_record(file_id, self.workspace_id)
        except Exception:
            return None


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest, request: Request, caller: CallerContext = Depends(get_caller),
                      db: Session = Depends(get_db)):
    """SSE chat: classify → agent → stream.  Always ends with exactly one final event."""
    user_id, workspace_id = _require_resource_context(caller)
    message = req.message.strip()
    if not message:
        raise HTTPException(400, "Empty message")

    def _prepare():
        # End the transaction in THIS thread.  Handing an open transaction back to the
        # event loop and closing it in a later threadpool call deadlocks under load: all
        # threadpool tokens can be held by requests blocked on pool checkout, so the
        # close never runs and the connection is never returned.
        with connection_released(db):
            for fid in req.file_ids:
                _require_file_record(fid, caller)
            caller.check_ai_budget(db)
            caller.consume("query", db)
            try:
                llm_client = _llm_for_caller(caller, db)
            except LLMConfigError:
                caller.release("query", db)
                raise
            _, _, features = caller.plan(db)
            return llm_client, features

    llm, features = await run_in_threadpool(_prepare)

    file_ids = list(req.file_ids)
    sid = req.session_id
    history = [
        {"role": str(m.get("role", ""))[:16], "content": str(m.get("content", ""))[:4000]}
        for m in (req.conversation_history or [])[-10:] if isinstance(m, dict)
    ]

    quota_state = {"released": False}

    async def _release_once() -> None:
        # The query was reserved in _prepare(); return it at most once when no answer is produced.
        if not quota_state["released"]:
            quota_state["released"] = True
            await run_in_threadpool(_release_query, caller)

    async def event_generator() -> AsyncGenerator[str, None]:
        final_sent = False
        try:
            for fid in file_ids:
                await run_in_threadpool(dataset_store.touch_last_query, fid)
            await run_in_threadpool(_persist, sid, "user", message, None, user_id, workspace_id)

            yield _sse({"type": "status", "content": "🔍 Analyzing your question...", "is_final": False})
            try:
                intent = await asyncio.wait_for(classify(message, len(file_ids), llm=llm), timeout=15)
            except asyncio.TimeoutError:
                intent = "general"
            logger.info("Intent '%s' files=%s", intent, file_ids)

            if intent == "general" or not file_ids:
                if not file_ids:
                    response_text = (
                        "👋 **Welcome to DataPilot!**\n\n"
                        "Upload a CSV or Excel file to get started. Once uploaded, you can:\n"
                        "- 📊 Ask questions about your data\n- 📈 Generate charts and visualizations\n"
                        "- 🔮 Forecast trends\n- 🧹 Clean and fix data quality issues\n"
                        "- 📋 Get executive summaries and reports"
                    )
                else:
                    files = await run_in_threadpool(get_file_manager().list_files, workspace_id)
                    context_files = [f"{r['filename']} ({r['row_count']} rows, {r['column_count']} columns)"
                                     for r in files if r["file_id"] in file_ids]
                    system = ("You are DataPilot, an AI data assistant. Loaded files: " + ", ".join(context_files)
                              + ". Answer concisely. Never invent numbers about the data; suggest a specific question instead.")
                    response_text = ""
                    async for token in llm.stream(message, system=system):
                        if await request.is_disconnected():
                            return
                        response_text += token
                        yield _sse({"type": "text_chunk", "content": token, "is_final": False})
                meta = {"agent_used": "general", "dataset_refs": file_ids}
                meta["explain"] = await run_in_threadpool(enrich_explain_metadata, meta, file_ids, _ScopedFiles(workspace_id))
                await run_in_threadpool(_persist, sid, "bot", response_text, {"type": "text", "metadata": meta},
                                        user_id, workspace_id)
                final_sent = True
                yield _sse({"type": "text", "content": response_text, "is_final": True, "metadata": meta})
                return

            feature = INTENT_FEATURES.get(intent)
            if feature and not features.get(feature[0], False):
                text_ = f"🔒 {feature[1]} is not included in your current plan. Upgrade to use it."
                await _release_once()  # nothing was run
                await run_in_threadpool(_persist, sid, "bot", text_, {"type": "error"}, user_id, workspace_id)
                final_sent = True
                yield _sse({"type": "error", "content": text_, "error": text_, "is_final": True,
                            "metadata": {"agent_used": intent, "upgrade_prompt": True, "feature": feature[0]}})
                return

            yield _sse({"type": "status", "content": f"⚙️ Running {intent} analysis...", "is_final": False})
            if intent in HEAVY_INTENTS:
                job_id = await asyncio.to_thread(
                    jobs.enqueue, "agent_run",
                    {"intent": intent, "message": message, "file_ids": file_ids, "history": history,
                     "is_guest": caller.is_guest},
                    workspace_id=workspace_id, user_id=user_id, max_attempts=1,
                )
                if jobs.execution_mode() == "inline":
                    job = await asyncio.to_thread(jobs.run_inline, job_id)
                else:
                    deadline = time.monotonic() + _float_env("AGENT_JOB_WAIT_SECONDS", 150)
                    job = None
                    while time.monotonic() < deadline:
                        job = await asyncio.to_thread(jobs.get_job, job_id)
                        if job and job["status"] in jobs.TERMINAL:
                            break
                        if await request.is_disconnected():
                            return
                        yield ": keep-alive\n\n"
                        await asyncio.sleep(1.0)
                if not job or job.get("status") != "succeeded":
                    err = (job or {}).get("error") or "The analysis is taking longer than expected. Please retry in a moment."
                    # Failed, or no result within the wait window: the user got no answer,
                    # so the query is not billed.
                    await _release_once()
                    response = {"type": "error", "content": err, "error": err, "metadata": {"quota_released": True}}
                else:
                    response = job["result"]
            else:
                agent = get_agents(llm, workspace_id)[intent]
                task = asyncio.create_task(agent.run(message, file_ids, history))
                while not task.done():
                    done, _ = await asyncio.wait({task}, timeout=10)
                    if not done:
                        if await request.is_disconnected():
                            task.cancel()
                            await _release_once()  # cancelled before any result
                            return
                        yield ": keep-alive\n\n"
                response = task.result().to_dict()

            meta = response.get("metadata") or {}
            no_result = bool(meta.pop("llm_failure", False)) | bool(meta.pop("no_result", False))
            already_released = bool(meta.pop("quota_released", False))
            if (no_result or response.get("error")) and not already_released:
                # Timeout, AI-provider failure or agent error: no valid answer was produced,
                # so the query is not billed.
                await _release_once()
            if no_result or response.get("error"):
                response["type"] = "error"
            meta["agent_used"] = intent
            meta["dataset_refs"] = file_ids
            meta["explain"] = await run_in_threadpool(enrich_explain_metadata, meta, file_ids, _ScopedFiles(workspace_id))
            response["metadata"] = meta
            response["is_final"] = True
            await run_in_threadpool(
                _persist, sid, "bot", response.get("content", ""),
                {"type": response.get("type", "text"), "chart_data": response.get("chart_data"),
                 "table_data": response.get("table_data"), "metadata": meta},
                user_id, workspace_id,
            )
            final_sent = True
            yield _sse(response)
        except (LLMConfigError, LLMError) as exc:
            await _release_once()
            if isinstance(exc, LLMError):
                logger.warning("AI provider error during chat: %s", exc)
            msg = (str(exc) if isinstance(exc, LLMConfigError)
                   else "The AI provider could not answer right now. This query was not counted; please retry.")
            await run_in_threadpool(_persist, sid, "bot", msg, {"type": "error"}, user_id, workspace_id)
            final_sent = True
            yield _sse({"type": "error", "content": msg, "error": msg, "is_final": True})
        except Exception as exc:
            logger.exception("Chat stream failed: %s", exc)
            if not final_sent:
                await _release_once()  # no answer was delivered
            msg = "Something went wrong while answering. Please retry."
            await run_in_threadpool(_persist, sid, "bot", msg, {"type": "error"}, user_id, workspace_id)
            final_sent = True
            yield _sse({"type": "error", "content": msg, "error": msg, "is_final": True,
                        "metadata": {"request_id": request_id_var.get()}})
        finally:
            if not final_sent:
                logger.info("Chat stream ended without a final event (client disconnected)")

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Saved reports ─────────────────────────────────────────────────────────────

@app.post("/reports")
def save_report_route(req: report_dto.SaveReportRequest, caller: CallerContext = Depends(get_caller)):
    user_id, workspace_id = _require_resource_context(caller)
    report = report_store.save_report(
        session_id=req.session_id, title=req.title, description=req.description, prompt=req.prompt,
        content=req.content, report_type=req.report_type, chart_data=req.chart_data,
        table_data=jsonsafe.to_jsonable(req.table_data), kpis=req.kpis, metadata=req.metadata, file_id=req.file_id,
        filename=req.filename, tags=req.tags, user_id=user_id, workspace_id=workspace_id,
    )
    if report is None:
        raise HTTPException(500, "Failed to save report")
    return {"success": True, "report": report}


@app.get("/reports")
def list_reports_route(session_id: str | None = None, file_id: str | None = None, starred: bool = False,
                       report_type: str | None = None, limit: int = 50, caller: CallerContext = Depends(get_caller)):
    user_id, workspace_id = _require_resource_context(caller)
    reports = report_store.list_reports(session_id=session_id, file_id=file_id, starred_only=starred,
                                        report_type=report_type, limit=min(max(limit, 1), 200),
                                        user_id=user_id, workspace_id=workspace_id)
    return {"success": True, "reports": reports, "count": len(reports)}


@app.get("/reports/{report_id}")
def get_report_route(report_id: str, caller: CallerContext = Depends(get_caller)):
    user_id, workspace_id = _require_resource_context(caller)
    report = report_store.get_report(report_id, user_id=user_id, workspace_id=workspace_id)
    if not report:
        raise HTTPException(404, f"Report '{report_id}' not found")
    return {"success": True, "report": report}


@app.patch("/reports/{report_id}")
def update_report_route(report_id: str, req: report_dto.UpdateReportRequest, caller: CallerContext = Depends(get_caller)):
    user_id, workspace_id = _require_resource_context(caller)
    ok = report_store.update_report(report_id, title=req.title, description=req.description, tags=req.tags,
                                    starred=req.starred, scheduled=req.scheduled, schedule_cron=req.schedule_cron,
                                    user_id=user_id, workspace_id=workspace_id)
    if not ok:
        raise HTTPException(404, f"Report '{report_id}' not found")
    return {"success": True}


@app.delete("/reports/{report_id}")
def delete_report_route(report_id: str, caller: CallerContext = Depends(get_caller)):
    user_id, workspace_id = _require_resource_context(caller)
    if not report_store.delete_report(report_id, user_id=user_id, workspace_id=workspace_id):
        raise HTTPException(404, f"Report '{report_id}' not found")
    return {"success": True}


@app.post("/reports/{report_id}/version")
def create_version_route(report_id: str, req: report_dto.CreateVersionRequest, caller: CallerContext = Depends(get_caller)):
    user_id, workspace_id = _require_resource_context(caller)
    try:
        report = report_store.create_version(report_id, content=req.content, chart_data=req.chart_data, kpis=req.kpis,
                                             metadata=req.metadata, user_id=user_id, workspace_id=workspace_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"success": True, "report": report}


@app.get("/reports/{report_id}/versions")
def get_report_versions_route(report_id: str, caller: CallerContext = Depends(get_caller)):
    user_id, workspace_id = _require_resource_context(caller)
    return {"success": True, "versions": report_store.get_report_versions(report_id, user_id=user_id, workspace_id=workspace_id)}


# ── Query history ─────────────────────────────────────────────────────────────

@app.get("/history")
def get_history_route(session_id: str | None = None, limit: int = 50, offset: int = 0,
                      caller: CallerContext = Depends(get_caller)):
    user_id, workspace_id = _require_resource_context(caller)
    res = session_store.get_history_paginated(session_id=session_id, limit=min(max(limit, 1), 200),
                                              offset=max(offset, 0), user_id=user_id, workspace_id=workspace_id)
    return {"success": True, **res}


@app.get("/history/search")
def search_history_route(q: str, session_id: str | None = None, limit: int = 20, caller: CallerContext = Depends(get_caller)):
    user_id, workspace_id = _require_resource_context(caller)
    results = session_store.search_history(query_text=q, session_id=session_id, limit=min(max(limit, 1), 100),
                                           user_id=user_id, workspace_id=workspace_id)
    return {"success": True, "messages": results}


@app.delete("/history/{message_id}")
def delete_history_route(message_id: str, caller: CallerContext = Depends(get_caller)):
    user_id, workspace_id = _require_resource_context(caller)
    if not session_store.delete_message(message_id, user_id=user_id, workspace_id=workspace_id):
        raise HTTPException(404, f"Message '{message_id}' not found")
    return {"success": True}


@app.post("/history/{message_id}/pin")
def pin_history_route(message_id: str, caller: CallerContext = Depends(get_caller)):
    user_id, workspace_id = _require_resource_context(caller)
    if not session_store.pin_message(message_id, user_id=user_id, workspace_id=workspace_id):
        raise HTTPException(404, f"Message '{message_id}' not found")
    return {"success": True}


# ── Datasets ──────────────────────────────────────────────────────────────────

@app.get("/datasets")
def list_datasets_route(archived: str = "false", session_id: str | None = None, tag: str | None = None,
                        caller: CallerContext = Depends(get_caller)):
    archived_val = {"false": False, "true": True}.get(archived.lower())
    user_id, workspace_id = _require_resource_context(caller)
    datasets = dataset_store.list_datasets(archived=archived_val, session_id=session_id, tag=tag,
                                           user_id=user_id, workspace_id=workspace_id)
    return {"success": True, "datasets": datasets, "count": len(datasets)}


@app.get("/datasets/{dataset_id}")
def get_dataset_route(dataset_id: str, caller: CallerContext = Depends(get_caller)):
    user_id, workspace_id = _require_resource_context(caller)
    dataset = dataset_store.get_dataset(dataset_id, user_id=user_id, workspace_id=workspace_id)
    if not dataset:
        raise HTTPException(404, f"Dataset '{dataset_id}' not found")
    return {"success": True, "dataset": dataset}


@app.patch("/datasets/{dataset_id}")
def update_dataset_route(dataset_id: str, req: UpdateDatasetRequest, caller: CallerContext = Depends(get_caller)):
    user_id, workspace_id = _require_resource_context(caller)
    caller.require_role("Member")
    if not dataset_store.update_dataset(dataset_id, display_name=req.display_name, description=req.description,
                                        tags=req.tags, user_id=user_id, workspace_id=workspace_id):
        raise HTTPException(404, f"Dataset '{dataset_id}' not found")
    return {"success": True}


@app.post("/datasets/{dataset_id}/archive")
def archive_dataset_route(dataset_id: str, caller: CallerContext = Depends(get_caller)):
    user_id, workspace_id = _require_resource_context(caller)
    caller.require_role("Member")
    if not dataset_store.archive_dataset(dataset_id, user_id=user_id, workspace_id=workspace_id):
        raise HTTPException(404, f"Dataset '{dataset_id}' not found")
    return {"success": True}


@app.post("/datasets/{dataset_id}/restore")
def restore_dataset_route(dataset_id: str, caller: CallerContext = Depends(get_caller)):
    user_id, workspace_id = _require_resource_context(caller)
    caller.require_role("Member")
    if not dataset_store.restore_dataset(dataset_id, user_id=user_id, workspace_id=workspace_id):
        raise HTTPException(404, f"Dataset '{dataset_id}' not found")
    return {"success": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=_get_backend_host(), port=_get_backend_port(), reload=True)
