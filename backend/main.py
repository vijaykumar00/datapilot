"""
main.py — FastAPI application entry point.
Routes: /upload, /chat/stream, /files, /files/{id}, /health, /ollama/status
"""

import asyncio
import io
import json
import logging
import logging.handlers
import os
import re
import socket
from pathlib import Path
from typing import AsyncGenerator, List, Optional

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
import pandas as pd
import time
import traceback as tb
from core.db import log_api_error
import core.report_store as report_store
import core.report_dto as report_dto
import core.dataset_store as dataset_store


# Logging setup (before any imports that log)
import sys
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
_stream_handler = logging.StreamHandler(sys.stdout)
_stream_handler.stream.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        _stream_handler,
        logging.handlers.RotatingFileHandler(
            LOG_DIR / "datapilot.log", maxBytes=5_000_000, backupCount=3,
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger("datapilot.main")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

from agents.clean_agent import CleanAgent
from agents.crossfile_agent import CrossFileAgent
from agents.forecast_agent import ForecastAgent
from agents.insight_agent import InsightAgent
from agents.report_agent import ReportAgent
from agents.summary_agent import SummaryAgent
from agents.viz_agent import VizAgent
from core.data_store import get_store
from core.file_manager import get_file_manager, UPLOAD_DIR
from core.llm_client import get_llm_client, get_active_provider, set_active_provider
from core.router import classify
from core.suggestion_engine import generate_suggestions, build_greeting
import core.session_store as session_store
import core.analysis_store as analysis_store
from core.explain_enricher import enrich_explain_metadata
from core.error_intelligence import IntelligentException
from core.request_identity import get_caller, CallerContext
from core.db import get_db
from sqlalchemy.orm import Session


def _get_backend_host() -> str:
    return os.getenv("BACKEND_HOST", "127.0.0.1")


def _get_backend_port() -> int:
    raw = os.getenv("BACKEND_PORT", "8001")
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid BACKEND_PORT '%s', falling back to 8001", raw)
        return 8001


def _can_bind(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def _resolve_backend_port(host: str, preferred_port: int) -> int:
    if _can_bind(host, preferred_port):
        return preferred_port
    for port in range(preferred_port + 1, preferred_port + 20):
        if _can_bind(host, port):
            logger.warning(
                "Port %s is unavailable on %s, using %s instead",
                preferred_port,
                host,
                port,
            )
            return port
    raise RuntimeError(
        f"Could not find an available port starting from {preferred_port} on {host}"
    )

# ── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="DataPilot API",
    description="Local-first AI data analysis assistant",
    version="1.0.0",
)

@app.on_event("startup")
def startup_event():
    from core.db import init_db
    init_db()

from core.auth_routes import router as auth_router
from core.guest_routes import router as guest_router
from core.workspace_routes import router as workspace_router
from core.user_routes import router as user_router
from core.billing_routes import router as billing_router

app.include_router(auth_router)
app.include_router(guest_router)
app.include_router(workspace_router)
app.include_router(user_router)
app.include_router(billing_router)


# ── Audit log helper ─────────────────────────────────────────────────────────
def _audit_log(
    caller: "CallerContext",
    event_type: str,
    description: str,
    db: "Session",
) -> None:
    """Write a lightweight audit log entry for core analytics events."""
    try:
        import uuid
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
        logger.warning(f"Audit log write failed [{event_type}]: {e}")


from collections import defaultdict

allowed_origins_str = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:5174,http://127.0.0.1:5173")
allowed_origins = [orig.strip() for orig in allowed_origins_str.split(",") if orig.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global Request Size Limit Middleware (50MB cap)
@app.middleware("http")
async def limit_request_size(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length:
        if int(content_length) > 50 * 1024 * 1024:
            return JSONResponse(
                status_code=413,
                content={"detail": "Payload too large. Maximum size allowed is 50MB."}
            )
    return await call_next(request)

# Rate Limiting Middleware (IP-based, in-memory sliding window, max 100 req/min)
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_REQUESTS = 100
request_history = defaultdict(list)

@app.middleware("http")
async def rate_limiting_middleware(request: Request, call_next):
    if request.url.path in ("/health", "/uploads"):
        return await call_next(request)
        
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    
    # Clean old requests
    request_history[ip] = [ts for ts in request_history[ip] if now - ts < RATE_LIMIT_WINDOW_SECONDS]
    
    if len(request_history[ip]) >= RATE_LIMIT_MAX_REQUESTS:
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many requests. Please try again later."}
        )
    
    request_history[ip].append(now)
    return await call_next(request)

# Structured Error Logging Middleware
@app.middleware("http")
async def error_logging_middleware(request: Request, call_next):
    try:
        response = await call_next(request)
        return response
    except Exception as exc:
        import traceback as _tb
        request_id = request.headers.get("x-request-id", f"req_{os.urandom(4).hex()}")
        full_tb = _tb.format_exc()
        logger.error(f"Unhandled exception [{request_id}] on {request.url.path}: {exc}\n{full_tb}")
        # Log to db/error_logs
        log_api_error(
            request_id=request_id,
            endpoint=str(request.url.path),
            error_type=exc.__class__.__name__,
            message=str(exc),
            traceback=full_tb,
            user_id="default_user",
            workspace_id="default_workspace"
        )
        # Include CORS headers so browser doesn't show a CORS error
        origin = request.headers.get("origin", "*")
        resp = JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": "Internal Server Error",
                "message": str(exc) if os.getenv("DEBUG", "false").lower() == "true" else "An unexpected error occurred. It has been logged.",
                "request_id": request_id
            }
        )
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp



@app.exception_handler(IntelligentException)
async def intelligent_exception_handler(request: Request, exc: IntelligentException):
    import os
    request_id = request.headers.get("x-request-id", f"req_{os.urandom(4).hex()}")
    log_api_error(
        request_id=request_id,
        endpoint=str(request.url.path),
        error_type="IntelligentException",
        message=exc.err_dict.get("message", "Intelligent error"),
        traceback=None,
        user_id="default_user",
        workspace_id="default_workspace"
    )
    return JSONResponse(
        status_code=400,
        content={
            "success": False,
            "error": exc.err_dict.get("title", "Error"),
            "message": exc.err_dict.get("message"),
            "intelligent_error": exc.err_dict
        }
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"success": False, "error": exc.detail}
        )
        
    import os
    request_id = request.headers.get("x-request-id", f"req_{os.urandom(4).hex()}")
    log_api_error(
        request_id=request_id,
        endpoint=str(request.url.path),
        error_type=exc.__class__.__name__,
        message=str(exc),
        traceback=tb.format_exc(),
        user_id="default_user",
        workspace_id="default_workspace"
    )

    path = request.url.path
    from core.error_intelligence import _make_error, diagnose_upload_error, diagnose_transform_error

    if "/upload" in path:
        err = diagnose_upload_error(exc, "uploaded_file")
    elif "/transform" in path:
        err = diagnose_transform_error(exc, {"operation": "transform"})
    elif "/sheet" in path:
        err = _make_error(
            code="SHEET_ERROR",
            title="Sheet operation failed",
            message=f"Failed to switch or read Excel sheet: {str(exc)}",
            suggestions=["Ensure the Excel file is not password protected.", "Try re-saving the file in Excel."],
            severity="error"
        )
    else:
        err = _make_error(
            code="SERVER_ERROR",
            title="Server operation failed",
            message=f"An unexpected error occurred: {str(exc)}",
            suggestions=["Retry the action.", "Check the server logs if hosting locally.", "Refresh your browser window."],
            severity="critical"
        )

    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": err.get("title", "Server Error"),
            "message": err.get("message"),
            "intelligent_error": err,
            "request_id": request_id
        }
    )


app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")


# ── Dependency injectors ─────────────────────────────────────────────────────
def get_agents():
    llm = get_llm_client()
    store = get_store()
    files = get_file_manager()
    return {
        "insight": InsightAgent(llm, store, files),
        "clean": CleanAgent(llm, store, files),
        "visualize": VizAgent(llm, store, files),
        "forecast": ForecastAgent(llm, store, files),
        "summary": SummaryAgent(llm, store, files),
        "report": ReportAgent(llm, store, files),
        "crossfile": CrossFileAgent(llm, store, files),
    }


# ── Request / Response models ─────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str
    file_ids: list[str] = []
    conversation_history: list[dict] = []
    session_id: str | None = None


class ExportRowsRequest(BaseModel):
    rows: list[dict]
    filename: str | None = None


class ExportReportRequest(BaseModel):
    content: str
    filename: str | None = None


class CellEdit(BaseModel):
    row_index: int
    column: str
    value: str | int | float | bool | None = None


class UpdateCellsRequest(BaseModel):
    edits: list[CellEdit]


class CreateSessionRequest(BaseModel):
    session_id: str | None = None
    name: str | None = None


class UpdateSessionRequest(BaseModel):
    name: str | None = None
    pinned: bool | None = None


class TransformPreviewRequest(BaseModel):
    query: str


class TransformApplyRequest(BaseModel):
    transformation_id: str


class TransformPipelineRequest(BaseModel):
    pipeline: list[dict]


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



def _safe_export_name(name: str, fallback: str) -> str:
    stem = Path(name).stem if name else fallback
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._")
    return cleaned or fallback


def _dataframe_to_bytes(df: pd.DataFrame, export_format: str) -> tuple[bytes, str, str]:
    export_format = export_format.lower()
    if export_format == "csv":
        return (
            df.to_csv(index=False).encode("utf-8"),
            "text/csv; charset=utf-8",
            "csv",
        )
    if export_format == "xlsx":
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="data", index=False)
        return (
            buffer.getvalue(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "xlsx",
        )
    raise HTTPException(400, "Unsupported export format. Use csv or xlsx")


def _bytes_download_response(payload: bytes, media_type: str, filename: str) -> StreamingResponse:
    response = StreamingResponse(io.BytesIO(payload), media_type=media_type)
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    """Health check endpoint."""
    llm = get_llm_client()
    ollama_up = await llm.is_online()
    return {
        "status": "ok",
        "ollama": ollama_up,
        "provider": get_active_provider(),
        "files_loaded": len(get_file_manager().list_files()),
    }


@app.get("/provider")
async def get_provider():
    """Get current LLM provider and its status."""
    provider = get_active_provider()
    llm = get_llm_client()
    online = await llm.is_online()
    return {"provider": provider, "online": online}


class ProviderRequest(BaseModel):
    provider: str
    api_key: str | None = None


@app.post("/provider")
async def switch_provider(req: ProviderRequest):
    """Switch LLM provider at runtime. Saves API key to .env for persistence."""
    valid = {"gemini", "openai", "claude", "ollama"}
    if req.provider not in valid:
        raise HTTPException(400, f"Invalid provider. Choose from: {', '.join(valid)}")

    set_active_provider(req.provider, req.api_key)

    # Persist key to .env so it survives restarts
    if req.api_key:
        _persist_key_to_env(req.provider, req.api_key)

    llm = get_llm_client()
    online = await llm.is_online()
    logger.info(f"Provider switched to '{req.provider}', online={online}")
    return {"success": True, "provider": req.provider, "online": online}


def _persist_key_to_env(provider: str, api_key: str):
    """Write or update an API key in the .env file."""
    import re
    env_key_map = {
        "gemini": "GEMINI_API_KEY",
        "openai": "OPENAI_API_KEY",
        "claude": "ANTHROPIC_API_KEY",
    }
    env_var = env_key_map.get(provider)
    if not env_var:
        return
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    try:
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                content = f.read()
            # Replace existing key or append
            pattern = rf"^{env_var}=.*$"
            replacement = f"{env_var}={api_key}"
            if re.search(pattern, content, re.MULTILINE):
                content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
            else:
                content += f"\n{replacement}\n"
            with open(env_path, "w") as f:
                f.write(content)
            # Also update LLM_PROVIDER in .env
            provider_pattern = r"^LLM_PROVIDER=.*$"
            if re.search(provider_pattern, content, re.MULTILINE):
                content = re.sub(provider_pattern, f"LLM_PROVIDER={provider}", content, flags=re.MULTILINE)
                with open(env_path, "w") as f:
                    f.write(content)
        logger.info(f"Persisted {env_var} to .env")
    except Exception as e:
        logger.warning(f"Could not persist key to .env: {e}")


@app.get("/ollama/status")
async def ollama_status():
    """Check Ollama and available models."""
    llm = get_llm_client()
    import httpx
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get("http://localhost:11434/api/tags")
            if resp.status_code == 200:
                data = resp.json()
                models = [m["name"] for m in data.get("models", [])]
                return {"online": True, "models": models}
    except Exception:
        pass
    return {"online": False, "models": []}


@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    caller: CallerContext = Depends(get_caller),
    db: Session = Depends(get_db),
):
    """Upload and parse a CSV or Excel file. Returns file summary + AI suggestions."""
    # Enforce upload limit before processing
    caller.check_limit("upload", db)

    manager = get_file_manager()
    try:
        result = await manager.process_upload(
            file,
            workspace_id=caller.effective_workspace_id,
            user_id=caller.user_id,
        )
        logger.info(f"Upload successful: {file.filename} -> {result['file_id']} [caller={caller.user_id}]")

        # Generate smart suggestions from profiled metadata
        record = manager.get_record(result["file_id"])
        suggestions = []
        greeting = ""
        if record is not None:
            try:
                suggestions = generate_suggestions(
                    record.df,
                    filename=record.filename,
                    metadata=record.metadata,
                )
                greeting = build_greeting(
                    filename=record.filename,
                    row_count=len(record.df),
                    col_count=len(record.df.columns),
                    suggestions=suggestions,
                )
            except Exception as e:
                logger.warning(f"Suggestion generation failed: {e}")

        # Increment usage after successful upload
        caller.increment_usage("upload", db)

        # Audit log
        _audit_log(caller, "FILE_UPLOADED", f"File '{file.filename}' uploaded (id={result['file_id']})", db)

        return {"success": True, **result, "suggestions": suggestions, "greeting": greeting}
    except HTTPException:
        raise
    except ValueError as e:
        logger.warning(f"Upload validation failed: {e}")
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.exception(f"Upload failed unexpectedly: {e}")
        return {"success": False, "error": "Internal error during file processing"}


@app.get("/files")
async def list_files():
    """List all currently loaded files."""
    return {"files": get_file_manager().list_files()}


@app.get("/files/{file_id}/suggestions")
async def get_file_suggestions(file_id: str):
    """Return fresh AI suggestions for a loaded file (re-computed on demand)."""
    manager = get_file_manager()
    record = manager.get_record(file_id)
    if record is None:
        raise HTTPException(404, f"File '{file_id}' not found")
    try:
        suggestions = generate_suggestions(
            record.df,
            filename=record.filename,
            metadata=record.metadata,
        )
        greeting = build_greeting(
            filename=record.filename,
            row_count=len(record.df),
            col_count=len(record.df.columns),
            suggestions=suggestions,
        )
        return {"suggestions": suggestions, "greeting": greeting}
    except Exception as e:
        logger.warning(f"Suggestions failed for {file_id}: {e}")
        return {"suggestions": [], "greeting": ""}


@app.get("/files/{file_id}")
async def get_file_preview(file_id: str):
    """Return preview rows and metadata for one loaded file."""
    preview = get_file_manager().get_preview_data(file_id)
    if preview is None:
        raise HTTPException(404, f"File '{file_id}' not found")
    return {"success": True, **preview}


@app.get("/files/{file_id}/diagnostics")
async def get_file_diagnostics(file_id: str):
    """Re-run full schema diagnostics on a loaded file and return structured warnings."""
    from core.error_intelligence import diagnose_schema
    manager = get_file_manager()
    record = manager.get_record(file_id)
    if record is None:
        raise HTTPException(404, f"File '{file_id}' not found")
    try:
        warnings = diagnose_schema(record.df, record.filename)
        record.metadata["schema_warnings"] = warnings
        return {
            "success": True,
            "file_id": file_id,
            "filename": record.filename,
            "warnings": warnings,
            "warning_count": len(warnings),
            "warning_count_by_severity": {
                "critical": sum(1 for w in warnings if w.get("severity") == "critical"),
                "warning": sum(1 for w in warnings if w.get("severity") == "warning"),
                "info": sum(1 for w in warnings if w.get("severity") == "info"),
            },
        }
    except Exception as e:
        logger.exception(f"Diagnostics failed for {file_id}: {e}")
        raise HTTPException(500, f"Diagnostics failed: {e}")


@app.patch("/files/{file_id}")
async def update_file_cells(file_id: str, req: UpdateCellsRequest):
    """Apply user edits to the loaded dataframe."""
    try:
        result = get_file_manager().apply_edits(
            file_id,
            [edit.model_dump() for edit in req.edits],
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    if result is None:
        raise HTTPException(404, f"File '{file_id}' not found")
    return result


@app.get("/export/file/{file_id}")
async def export_file_data(file_id: str, format: str = "csv"):
    """Export the full uploaded dataset as CSV or XLSX."""
    record = get_file_manager().get_record(file_id)
    if record is None:
        raise HTTPException(404, f"File '{file_id}' not found")
    payload, media_type, ext = _dataframe_to_bytes(record.df, format)
    filename = f"{_safe_export_name(record.filename, 'dataset')}.{ext}"
    return _bytes_download_response(payload, media_type, filename)


@app.post("/export/results")
async def export_result_rows(
    req: ExportRowsRequest,
    format: str = "csv",
    caller: CallerContext = Depends(get_caller),
    db: Session = Depends(get_db),
):
    """Export query or preview rows currently visible in the UI."""
    caller.check_limit("export", db)
    if not req.rows:
        raise HTTPException(400, "No rows provided for export")
    df = pd.DataFrame(req.rows)
    payload, media_type, ext = _dataframe_to_bytes(df, format)
    filename = f"{_safe_export_name(req.filename or 'results', 'results')}.{ext}"
    caller.increment_usage("export", db)
    return _bytes_download_response(payload, media_type, filename)


@app.post("/export/report")
async def export_report(req: ExportReportRequest, format: str = "md"):
    """Export a generated narrative/report as markdown or text."""
    export_format = format.lower()
    if export_format not in {"md", "txt"}:
        raise HTTPException(400, "Unsupported report format. Use md or txt")
    payload = req.content.encode("utf-8")
    filename = f"{_safe_export_name(req.filename or 'report', 'report')}.{export_format}"
    return _bytes_download_response(payload, "text/plain; charset=utf-8", filename)


@app.get("/files/{file_id}/sheets")
async def list_sheets(file_id: str):
    """List all sheet names for an Excel file and show the active sheet."""
    record = get_file_manager().get_record(file_id)
    if record is None:
        raise HTTPException(404, f"File '{file_id}' not found")
    sheet_names = record.metadata.get("sheet_names", [])
    active_sheet = record.metadata.get("active_sheet")
    return {"file_id": file_id, "sheets": sheet_names, "active_sheet": active_sheet}


class SwitchSheetRequest(BaseModel):
    sheet: str


@app.post("/files/{file_id}/sheet")
async def switch_sheet(file_id: str, req: SwitchSheetRequest):
    """Switch the active sheet for an Excel file."""
    try:
        summary = await get_file_manager().switch_sheet(file_id, req.sheet)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if summary is None:
        raise HTTPException(404, f"File '{file_id}' not found")
    return {"success": True, **summary}


class RenameFileRequest(BaseModel):
    filename: str


@app.post("/files/{file_id}/rename")
async def rename_file(file_id: str, req: RenameFileRequest):
    """Rename a file's display name."""
    if not req.filename.strip():
        raise HTTPException(400, "Filename cannot be empty")
    ok = get_file_manager().rename_file(file_id, req.filename)
    if not ok:
        raise HTTPException(404, f"File '{file_id}' not found")
    return {"success": True, "file_id": file_id, "filename": req.filename.strip()}


@app.get("/sessions")
async def get_sessions(
    limit: Optional[int] = None,
    offset: int = 0,
    q: Optional[str] = None
):
    """Get all or paginated saved chat sessions, with optional search."""
    res = session_store.get_sessions_paginated(
        user_id="default_user",
        workspace_id="default_workspace",
        limit=limit,
        offset=offset,
        search=q
    )
    return {"success": True, "sessions": res["sessions"], "total": res["total"]}


@app.post("/sessions")
async def create_session(req: CreateSessionRequest):
    """Create a new chat session."""
    res = session_store.create_session(req.session_id, req.name)
    return {"success": True, "session": res}


@app.put("/sessions/{session_id}")
async def update_session_route(session_id: str, req: UpdateSessionRequest):
    """Rename or pin/unpin a session."""
    ok = session_store.update_session(session_id, req.name, req.pinned)
    if not ok:
        raise HTTPException(404, f"Session '{session_id}' not found")
    return {"success": True}


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a session entirely."""
    ok = session_store.delete_session(session_id)
    return {"success": ok, "session_id": session_id}


@app.get("/sessions/{session_id}/messages")
async def get_session_messages(session_id: str):
    """Get message history for a session."""
    history = session_store.get_history(session_id)
    return {"success": True, "messages": history}


@app.delete("/session/{session_id}")
async def clear_session(session_id: str):
    """Clear a chat session's server-side history."""
    ok = session_store.clear_session(session_id)
    return {"success": ok, "session_id": session_id}


@app.delete("/files/{file_id}")
async def delete_file(file_id: str):
    """Remove a file from memory and disk."""
    ok = get_file_manager().delete_file(file_id)
    return {"success": ok, "file_id": file_id}


import uuid
_staged_transformations: dict[str, tuple[list[dict], str]] = {}


@app.post("/files/{file_id}/transform/preview")
async def transform_preview(file_id: str, req: TransformPreviewRequest):
    """NLP proposal planner running a safe, head-sliced subset dry-run simulation of transformations."""
    manager = get_file_manager()
    record = manager.get_record(file_id)
    if record is None:
        raise HTTPException(404, f"File '{file_id}' not found")

    from core.transform_engine import propose_transformations, execute_transform
    try:
        proposed_actions = await propose_transformations(req.query, record.df, record.table_name)
    except Exception as e:
        raise HTTPException(400, f"Failed to generate transformation proposal: {e}")

    # Optimize preview on deep copy of a head-sliced subset (first 5,000 rows max) to guarantee 0ms preview speed
    MAX_PREVIEW_ROWS = 5000
    df_slice = record.df.head(MAX_PREVIEW_ROWS).copy()
    df_transformed = df_slice.copy()
    
    for action in proposed_actions:
        try:
            df_transformed = execute_transform(df_transformed, action)
        except Exception as e:
            logger.warning(f"Dry run failed for step {action}: {e}")

    # Estimate affected rows
    affected_rows = len(record.df) - len(df_transformed) if len(proposed_actions) > 0 else 0
    if affected_rows < 0:
        affected_rows = abs(affected_rows)

    # Store in staged list
    trans_id = str(uuid.uuid4())[:8]
    _staged_transformations[trans_id] = (proposed_actions, file_id)

    # Clean previews for serialization
    rows_before = df_slice.head(50).fillna("").to_dict(orient="records")
    rows_after = df_transformed.head(50).fillna("").to_dict(orient="records")
    
    for idx, r in enumerate(rows_before):
        r["_row_index"] = idx
    for idx, r in enumerate(rows_after):
        r["_row_index"] = idx

    return {
        "success": True,
        "transformation_id": trans_id,
        "actions": proposed_actions,
        "affected_rows": affected_rows,
        "preview_before": {
            "columns": list(df_slice.columns),
            "rows": rows_before
        },
        "preview_after": {
            "columns": list(df_transformed.columns),
            "rows": rows_after
        }
    }


@app.post("/files/{file_id}/transform/apply")
async def transform_apply(file_id: str, req: TransformApplyRequest):
    """Commit the staged declarative transformations, executing them on the active dataframe and re-generating insights."""
    manager = get_file_manager()
    record = manager.get_record(file_id)
    if record is None:
        raise HTTPException(404, f"File '{file_id}' not found")

    staged = _staged_transformations.get(req.transformation_id)
    if staged is None or staged[1] != file_id:
        raise HTTPException(404, "Transformation plan not found or expired")

    actions, _ = staged
    last_res = None
    for action in actions:
        desc = action.get("description", "Apply transformation")
        last_res = await manager.apply_transform(file_id, action, desc)

    if req.transformation_id in _staged_transformations:
        del _staged_transformations[req.transformation_id]

    return {
        "success": True,
        "message": f"Successfully committed {len(actions)} transformation steps.",
        "preview": last_res.get("preview") if last_res else manager.get_preview_data(file_id),
        "history_count": len(record.history)
    }


@app.post("/files/{file_id}/transform/undo")
async def transform_undo(file_id: str):
    """Roll back the last transformation from the transactional history stack in memory."""
    manager = get_file_manager()
    record = manager.get_record(file_id)
    if record is None:
        raise HTTPException(404, f"File '{file_id}' not found")

    try:
        res = await manager.undo_transform(file_id)
        return {
            "success": True,
            "undone_description": res.get("undone_description"),
            "preview": res.get("preview"),
            "history_count": len(record.history)
        }
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/files/{file_id}/transform/pipeline")
async def transform_pipeline(file_id: str, req: TransformPipelineRequest):
    """Execute a pre-configured multi-step pipeline chain sequentially."""
    manager = get_file_manager()
    record = manager.get_record(file_id)
    if record is None:
        raise HTTPException(404, f"File '{file_id}' not found")

    last_res = None
    for step in req.pipeline:
        desc = step.get("description", f"Execute {step.get('action')} pipeline step")
        last_res = await manager.apply_transform(file_id, step, desc)

    return {
        "success": True,
        "message": f"Successfully completed pipeline chain with {len(req.pipeline)} steps.",
        "preview": last_res.get("preview") if last_res else manager.get_preview_data(file_id),
        "history_count": len(record.history)
    }


@app.post("/report/generate")
async def report_generate(
    req: ReportGenerateRequest,
    caller: CallerContext = Depends(get_caller),
    db: Session = Depends(get_db),
):
    """Generate business-ready narrative analysis and dynamically styled charts."""
    caller.check_limit("report", db)
    manager = get_file_manager()
    record = manager.get_record(req.file_id)
    if record is None:
        raise HTTPException(404, f"File '{req.file_id}' not found")

    # Resolve default chart columns
    x_col = req.x_col or (record.df.columns[0] if len(record.df.columns) > 0 else None)
    y_col = req.y_col
    if not y_col:
        nums = record.df.select_dtypes(include="number").columns
        y_col = nums[0] if len(nums) > 0 else (record.df.columns[1] if len(record.df.columns) > 1 else record.df.columns[0])

    # Generate custom branded chart
    chart_filename = f"report_chart_{req.file_id}.png"
    chart_path = str(UPLOAD_DIR / chart_filename)
    
    from core.report_generator import generate_branded_chart
    chart_ok = generate_branded_chart(record.df, x_col, y_col, req.chart_type, req.brand_colors, chart_path)

    # Invoke report agent to construct professional narrative
    agents = get_agents()
    report_agent = agents.get("report")
    narrative_text = ""
    if report_agent:
        custom_query = (
            f"Write a {req.report_type} report titled '{req.title}' "
            f"covering date range: {req.date_range or 'All Periods'}. "
            f"Highlight '{y_col}' grouped by '{x_col}'."
        )
        try:
            resp = await report_agent.run(custom_query, [req.file_id])
            narrative_text = resp.content
        except Exception as e:
            logger.warning(f"ReportAgent narrative generation failed: {e}")

    if not narrative_text:
        narrative_text = (
            f"## Overview\n"
            f"This {req.report_type} operational review details core observations from '{record.filename}' "
            f"containing {len(record.df):,} rows.\n\n"
            f"## Performance breakdown\n"
            f"Evaluating the '{y_col}' metric mapped across the '{x_col}' dimension shows consistent running averages, "
            f"with major contributors maintaining a healthy contribution rate."
        )

    # Assemble KPIs list
    kpis = []
    insights = record.metadata.get("insights", [])
    for ins in insights:
        if ins.get("metric"):
            kpis.append({
                "title": ins.get("title", "Observation"),
                "metric": ins.get("metric", ""),
                "severity": ins.get("severity", "info")
            })
    if not kpis:
        kpis = [
            {"title": "Record Capacity", "metric": f"{len(record.df):,} rows", "severity": "info"},
            {"title": "Total Parameters", "metric": f"{len(record.df.columns)} cols", "severity": "info"},
            {"title": "Completeness", "metric": f"{record.df.isnull().sum().sum()} nulls", "severity": "warning"}
        ]

    chart_url = f"/uploads/{chart_filename}" if chart_ok else None

    # Increment report usage after successful generation
    caller.increment_usage("report", db)

    # Audit log
    _audit_log(caller, "REPORT_GENERATED", f"Report '{req.title}' generated (type={req.report_type})", db)

    return {
        "success": True,
        "title": req.title,
        "date_range": req.date_range,
        "report_type": req.report_type,
        "narrative": narrative_text,
        "kpis": kpis[:5],
        "chart_url": chart_url,
        "x_col": x_col,
        "y_col": y_col,
        "chart_type": req.chart_type,
        "brand_colors": req.brand_colors
    }


@app.post("/report/export")
async def report_export(req: ReportExportRequest):
    """Asynchronously compile and export the bespoke report in PDF, DOCX, PPTX, or XLSX formats."""
    manager = get_file_manager()
    record = manager.get_record(req.file_id)
    if record is None:
        raise HTTPException(404, f"File '{req.file_id}' not found")

    fmt = req.format.lower()
    export_filename = f"{_safe_export_name(req.title or 'report', 'report')}.{fmt}"
    out_path = str(UPLOAD_DIR / f"export_{uuid.uuid4().hex[:8]}.{fmt}")

    # Re-generate temporary chart for compilation
    x_col = req.x_col or record.df.columns[0]
    y_col = req.y_col or (record.df.columns[1] if len(record.df.columns) > 1 else record.df.columns[0])
    chart_filename = f"temp_export_chart_{uuid.uuid4().hex[:8]}.png"
    chart_path = str(UPLOAD_DIR / chart_filename)
    
    from core.report_generator import generate_branded_chart, compile_pdf, compile_docx, compile_pptx, compile_xlsx
    chart_ok = generate_branded_chart(record.df, x_col, y_col, req.chart_type, req.brand_colors, chart_path)
    real_chart_path = chart_path if chart_ok else None

    try:
        if fmt == "pdf":
            # Offload CPU-bound compilation to thread pool to maintain non-blocking event loops
            await asyncio.to_thread(
                compile_pdf,
                out_path,
                req.title,
                req.date_range or "",
                req.narrative,
                req.kpis,
                real_chart_path,
                req.brand_colors
            )
            media_type = "application/pdf"
        elif fmt == "docx":
            await asyncio.to_thread(
                compile_docx,
                out_path,
                req.title,
                req.date_range or "",
                req.narrative,
                req.kpis,
                real_chart_path,
                req.brand_colors
            )
            media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        elif fmt == "pptx":
            await asyncio.to_thread(
                compile_pptx,
                out_path,
                req.title,
                req.date_range or "",
                req.narrative,
                req.kpis,
                real_chart_path,
                req.brand_colors
            )
            media_type = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        elif fmt == "xlsx":
            await asyncio.to_thread(
                compile_xlsx,
                out_path,
                req.title,
                record.df,
                req.brand_colors
            )
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            raise HTTPException(400, f"Unsupported export format '{fmt}'")

        if not os.path.exists(out_path):
            raise RuntimeError("Failed to compile target report file")

        payload = Path(out_path).read_bytes()
        
    except Exception as e:
        logger.exception(f"Report compilation failed: {e}")
        raise HTTPException(500, f"Document compilation error: {e}")
    finally:
        # Secure cleanup
        if os.path.exists(out_path):
            try:
                os.unlink(out_path)
            except Exception:
                pass
        if real_chart_path and os.path.exists(real_chart_path):
            try:
                os.unlink(real_chart_path)
            except Exception:
                pass

    return _bytes_download_response(payload, media_type, export_filename)


@app.get("/templates")
async def get_templates_route():
    """List all default built-in and user-created custom templates."""
    from core.template_store import get_template_store
    store = get_template_store()
    return {"success": True, "templates": store.list_templates(user_id="default_user", workspace_id="default_workspace")}


@app.post("/templates")
async def create_template_route(req: TemplateCreateRequest):
    """Save a new custom template (either from raw steps or extracted from a file's transaction history)."""
    from core.template_store import get_template_store
    store = get_template_store()
    
    steps = req.steps
    if req.file_id:
        manager = get_file_manager()
        record = manager.get_record(req.file_id)
        if record is None:
            raise HTTPException(404, f"File '{req.file_id}' not found")
        
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
        
    template = store.create_template(req.name, req.description, req.category, steps, user_id="default_user", workspace_id="default_workspace")
    return {"success": True, "template": template}


@app.post("/templates/{template_id}/duplicate")
async def duplicate_template_route(template_id: str):
    """Duplicate an existing template, appending (Copy) to its name."""
    from core.template_store import get_template_store
    store = get_template_store()
    duplicated = store.duplicate_template(template_id, user_id="default_user", workspace_id="default_workspace")
    if not duplicated:
        raise HTTPException(404, f"Template '{template_id}' not found")
    return {"success": True, "template": duplicated}


@app.delete("/templates/{template_id}")
async def delete_template_route(template_id: str):
    """Delete a custom template."""
    from core.template_store import get_template_store
    store = get_template_store()
    ok = store.delete_template(template_id)
    if not ok:
        raise HTTPException(404, f"Custom Template '{template_id}' not found or is a built-in template.")
    return {"success": True}


@app.post("/files/{file_id}/transform/template/{template_id}")
async def run_template_on_file(file_id: str, template_id: str, req: TemplateRunRequest):
    """Run template steps on a loaded dataset with dynamic semantic resolution fallbacks and 85% confidence gates."""
    from core.template_store import get_template_store
    from core.file_manager import get_file_manager, ColumnMappingError
    from fastapi.responses import JSONResponse
    
    t_store = get_template_store()
    template = t_store.get_template(template_id)
    if not template:
        raise HTTPException(404, f"Template '{template_id}' not found")
        
    manager = get_file_manager()
    try:
        res = await manager.apply_template(
            file_id,
            template_id,
            template["steps"],
            req.mapping_overrides
        )
        if res is None:
            raise HTTPException(404, f"File '{file_id}' not found")
            
        return res
    except ColumnMappingError as e:
        # Halt execution, raise 422 with structured override options
        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "error_type": "column_mapping_required",
                "message": str(e),
                "unmapped_columns": e.failed_mappings,
                "available_columns": e.available_columns
            }
        )
    except Exception as e:
        logger.exception("Template execution crashed: %s", e)
        raise HTTPException(500, f"Template execution failed: {e}")


# ── Saved Analyses endpoints ──────────────────────────────────────────────────

@app.post("/analyses")
async def create_analysis(req: SaveAnalysisRequest):
    """Persist a new saved analysis checkpoint."""
    try:
        result = analysis_store.save_analysis(
            session_id=req.session_id,
            title=req.title,
            query=req.query,
            response=req.response,
            type=req.type,
            chart_data=req.chart_data,
            table_data=req.table_data,
            metadata=req.metadata,
            file_id=req.file_id,
            filename=req.filename,
            tags=req.tags,
        )
        return {"success": True, "analysis": result}
    except Exception as e:
        logger.exception(f"Failed to save analysis: {e}")
        raise HTTPException(500, f"Failed to save analysis: {e}")


@app.get("/analyses")
async def list_analyses_route(
    session_id: str | None = None,
    file_id: str | None = None,
    starred: bool = False,
    limit: int = 100,
):
    """List saved analyses, optionally filtered by session, file, or starred status."""
    results = analysis_store.list_analyses(
        session_id=session_id,
        file_id=file_id,
        starred_only=starred,
        limit=limit,
    )
    return {"success": True, "analyses": results, "count": len(results)}


@app.get("/analyses/{analysis_id}")
async def get_analysis_route(analysis_id: str):
    """Fetch a single saved analysis by ID."""
    result = analysis_store.get_analysis(analysis_id)
    if result is None:
        raise HTTPException(404, f"Analysis '{analysis_id}' not found")
    return {"success": True, "analysis": result}


@app.patch("/analyses/{analysis_id}")
async def update_analysis_route(analysis_id: str, req: UpdateAnalysisRequest):
    """Update a saved analysis: rename, re-tag, or star/unstar."""
    ok = analysis_store.update_analysis(
        analysis_id,
        title=req.title,
        tags=req.tags,
        starred=req.starred,
    )
    if not ok:
        raise HTTPException(404, f"Analysis '{analysis_id}' not found")
    return {"success": True}


@app.delete("/analyses/{analysis_id}")
async def delete_analysis_route(analysis_id: str):
    """Permanently delete a saved analysis."""
    ok = analysis_store.delete_analysis(analysis_id)
    return {"success": ok, "analysis_id": analysis_id}


@app.post("/chat/stream")
async def chat_stream(
    req: ChatRequest,
    caller: CallerContext = Depends(get_caller),
    db: Session = Depends(get_db),
):
    """
    SSE streaming chat endpoint.
    Classifies intent → routes to agent → streams response.
    """
    # Enforce query limit before dispatching
    caller.check_limit("query", db)
    # Increment usage — do it before streaming so limit is counted even on errors
    caller.increment_usage("query", db)

    async def event_generator() -> AsyncGenerator[str, None]:
        agents = get_agents()
        file_ids = req.file_ids
        message = req.message.strip()
        sid = req.session_id

        # If authenticated, load user's DB API key (encrypted) into runtime
        if caller.is_authenticated and caller.user_id and caller.user_id != "anonymous":
            from core.llm_client import load_user_api_key
            load_user_api_key(caller.user_id, get_active_provider(), db)

        # Touch last query date for all referenced files
        if file_ids:
            for fid in file_ids:
                try:
                    dataset_store.touch_last_query(fid)

                except Exception as e:
                    logger.warning(f"Failed to touch last query date for dataset {fid}: {e}")

        if not message:
            yield _sse({"type": "error", "content": "Empty message", "is_final": True})
            return

        # Persist user message to session
        if sid:
            session_store.append_message(sid, "user", message)

        # Merge server-side history with client-sent history (client wins if both present)
        history = req.conversation_history or session_store.get_history(sid)

        # ── Classify intent ──────────────────────────────────────────────────
        try:
            yield _sse({"type": "status", "content": "🔍 Analyzing your question...", "is_final": False})
            intent = await asyncio.wait_for(
                classify(message, len(file_ids)), timeout=5
            )
            logger.info(f"Intent: '{intent}' | files={file_ids} | msg='{message[:60]}'")
        except asyncio.TimeoutError:
            intent = "general"

        # ── General / no-file fallback ────────────────────────────────────────
        if intent == "general" or not file_ids:
            if not file_ids:
                response_text = (
                    "👋 **Welcome to DataPilot!**\n\n"
                    "Upload a CSV or Excel file to get started. Once uploaded, you can:\n"
                    "- 📊 Ask questions about your data\n"
                    "- 📈 Generate charts and visualizations\n"
                    "- 🔮 Forecast trends\n"
                    "- 🧹 Clean and fix data quality issues\n"
                    "- 📋 Get executive summaries and reports"
                )
            else:
                llm = get_llm_client()
                file_mgr = get_file_manager()
                context_files = [
                    f"{r['filename']} ({r['row_count']} rows, {r['column_count']} columns)"
                    for r in file_mgr.list_files()
                    if r["file_id"] in file_ids
                ]
                system = f"You are DataPilot, an AI data assistant. Loaded files: {', '.join(context_files)}. Answer concisely."
                response_text = ""
                async for token in llm.stream(message, system=system):
                    response_text += token
                    yield _sse({"type": "text_chunk", "content": token, "is_final": False})
                if not response_text.strip():
                    response_text = (
                        "I could not generate a response right now. The selected provider may be "
                        "offline, out of quota, or returned an empty result. Try switching provider "
                        "or asking a more specific data question."
                    )

            meta = {
                "agent_used": "general",
                "dataset_refs": file_ids
            }
            meta["explain"] = enrich_explain_metadata(meta, file_ids, get_file_manager())

            if sid:
                session_store.append_message(
                    sid,
                    "bot",
                    response_text,
                    {
                        "type": "text",
                        "metadata": meta
                    }
                )
            yield _sse({
                "type": "text",
                "content": response_text,
                "is_final": True,
                "metadata": meta
            })
            return

        # ── Route to agent ────────────────────────────────────────────────────
        agent = agents.get(intent)
        if not agent:
            err_msg = f"Unknown intent: '{intent}'"
            if sid:
                session_store.append_message(sid, "bot", err_msg, {"type": "error"})
            yield _sse({
                "type": "error",
                "content": err_msg,
                "is_final": True,
            })
            return

        yield _sse({"type": "status", "content": f"⚙️ Running {intent} analysis...", "is_final": False})

        try:
            result = await agent.run(message, file_ids, req.conversation_history)
            response = result.to_dict()
            response["is_final"] = True
            
            meta = response.get("metadata", {}) or {}
            meta["agent_used"] = intent
            meta["dataset_refs"] = file_ids
            meta["explain"] = enrich_explain_metadata(meta, file_ids, get_file_manager())
            response["metadata"] = meta

            if sid:
                session_store.append_message(
                    sid,
                    "bot",
                    response.get("content", ""),
                    {
                        "type": response.get("type", "text"),
                        "chart_data": response.get("chart_data"),
                        "table_data": response.get("table_data"),
                        "metadata": meta,
                    }
                )
            yield _sse(response)
        except Exception as e:
            logger.exception(f"Agent '{intent}' crashed: {e}")
            from core.error_intelligence import diagnose_agent_error, format_for_user
            
            # Fetch df for diagnostics
            _df = None
            try:
                record = get_file_manager().get_record(file_ids[0]) if file_ids else None
                _df = record.df if record else None
            except Exception:
                pass
                
            intelligent_err = diagnose_agent_error(e, intent, _df, message)
            err_msg = format_for_user(intelligent_err)
            
            meta = {
                "agent_used": intent,
                "dataset_refs": file_ids,
                "intelligent_error": intelligent_err
            }
            if sid:
                session_store.append_message(
                    sid,
                    "bot",
                    err_msg,
                    {
                        "type": "error",
                        "error": err_msg,
                        "metadata": meta
                    }
                )
            yield _sse({
                "type": "error",
                "content": err_msg,
                "error": err_msg,
                "metadata": meta,
                "is_final": True,
            })

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _sse(data: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(data)}\n\n"


# ── Startup ───────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup_event_llm():
    logger.info("DataPilot API starting up...")
    provider = get_active_provider()
    
    # Validate API key config
    provider_keys = {
        "gemini": "GEMINI_API_KEY",
        "openai": "OPENAI_API_KEY",
        "claude": "ANTHROPIC_API_KEY"
    }
    if provider in provider_keys:
        key_name = provider_keys[provider]
        if not os.getenv(key_name):
            logger.error(f"CRITICAL CONFIGURATION ERROR: Active provider is set to '{provider}', but '{key_name}' is not defined in the environment!")
            
    async def check_provider_online():
        try:
            llm = get_llm_client()
            online = await llm.is_online()
            if online:
                logger.info(f"Provider '{provider}' is online and ready")
            else:
                logger.warning(f"Provider '{provider}' is offline or missing API key")
        except Exception as e:
            logger.warning(f"Failed to verify provider status: {e}")

    # Run network check in a background task so it doesn't block uvicorn startup
    asyncio.create_task(check_provider_online())


    # Reload files persisted from previous sessions in the background
    manager = get_file_manager()
    asyncio.create_task(manager.reload_from_disk())


    logger.info(
        "DataPilot API ready at http://%s:%s",
        _get_backend_host(),
        _get_backend_port(),
    )

# ── Reports Endpoints (Feature 1) ─────────────────────────────────────────────

@app.post("/reports")
async def save_report_route(req: report_dto.SaveReportRequest):
    """Save a new AI-generated report."""
    try:
        report = report_store.save_report(
            session_id=req.session_id,
            title=req.title,
            description=req.description,
            prompt=req.prompt,
            content=req.content,
            report_type=req.report_type,
            chart_data=req.chart_data,
            table_data=req.table_data,
            kpis=req.kpis,
            metadata=req.metadata,
            file_id=req.file_id,
            filename=req.filename,
            tags=req.tags,
            user_id="default_user",
            workspace_id="default_workspace"
        )
        return {"success": True, "report": report}
    except Exception as e:
        logger.exception("Failed to save report: %s", e)
        raise HTTPException(500, f"Failed to save report: {e}")

@app.get("/reports")
async def list_reports_route(
    session_id: str | None = None,
    file_id: str | None = None,
    starred: bool = False,
    report_type: str | None = None,
    limit: int = 50
):
    """List all saved reports, showing only the latest version of each report."""
    reports = report_store.list_reports(
        session_id=session_id,
        file_id=file_id,
        starred_only=starred,
        report_type=report_type,
        limit=limit,
        user_id="default_user",
        workspace_id="default_workspace"
    )
    return {"success": True, "reports": reports, "count": len(reports)}

@app.get("/reports/{report_id}")
async def get_report_route(report_id: str):
    """Fetch a single report version by ID."""
    report = report_store.get_report(report_id)
    if not report:
        raise HTTPException(404, f"Report '{report_id}' not found")
    return {"success": True, "report": report}

@app.patch("/reports/{report_id}")
async def update_report_route(report_id: str, req: report_dto.UpdateReportRequest):
    """Update title/description/tags/starred/scheduled metadata for a report."""
    ok = report_store.update_report(
        report_id,
        title=req.title,
        description=req.description,
        tags=req.tags,
        starred=req.starred,
        scheduled=req.scheduled,
        schedule_cron=req.schedule_cron
    )
    if not ok:
        raise HTTPException(404, f"Report '{report_id}' not found")
    return {"success": True}

@app.delete("/reports/{report_id}")
async def delete_report_route(report_id: str):
    """Permanently delete a report and all of its versions."""
    ok = report_store.delete_report(report_id)
    if not ok:
        raise HTTPException(404, f"Report '{report_id}' not found")
    return {"success": True}

@app.post("/reports/{report_id}/version")
async def create_version_route(report_id: str, req: report_dto.CreateVersionRequest):
    """Save a new version of a report."""
    try:
        report = report_store.create_version(
            report_id,
            content=req.content,
            chart_data=req.chart_data,
            kpis=req.kpis,
            metadata=req.metadata
        )
        return {"success": True, "report": report}
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.exception("Failed to save report version: %s", e)
        raise HTTPException(500, f"Failed to save report version: {e}")

@app.get("/reports/{report_id}/versions")
async def get_report_versions_route(report_id: str):
    """List all versions of a report."""
    versions = report_store.get_report_versions(report_id)
    return {"success": True, "versions": versions}


# ── Query History Endpoints (Feature 2) ───────────────────────────────────────

@app.get("/history")
async def get_history_route(
    session_id: str | None = None,
    limit: int = 50,
    offset: int = 0
):
    """Get cross-session paginated history of user queries."""
    res = session_store.get_history_paginated(
        session_id=session_id,
        limit=limit,
        offset=offset,
        user_id="default_user",
        workspace_id="default_workspace"
    )
    return {"success": True, **res}

@app.get("/history/search")
async def search_history_route(
    q: str,
    session_id: str | None = None,
    limit: int = 20
):
    """Search cross-session history for queries containing substring 'q'."""
    results = session_store.search_history(
        query_text=q,
        session_id=session_id,
        limit=limit,
        user_id="default_user",
        workspace_id="default_workspace"
    )
    return {"success": True, "messages": results}

@app.delete("/history/{message_id}")
async def delete_history_route(message_id: str):
    """Delete a user query and its response."""
    ok = session_store.delete_message(message_id)
    if not ok:
        raise HTTPException(404, f"Message '{message_id}' not found")
    return {"success": True}

@app.post("/history/{message_id}/pin")
async def pin_history_route(message_id: str):
    """Toggle pin status of a message."""
    ok = session_store.pin_message(message_id)
    if not ok:
        raise HTTPException(404, f"Message '{message_id}' not found")
    return {"success": True}


# ── Dataset Management Endpoints (Feature 3) ──────────────────────────────────

class UpdateDatasetRequest(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None

@app.get("/datasets")
async def list_datasets_route(
    archived: str = "false",
    session_id: str | None = None,
    tag: str | None = None
):
    """List registered datasets (excluding archived by default)."""
    archived_val = None
    if archived.lower() == "false":
        archived_val = False
    elif archived.lower() == "true":
        archived_val = True

    datasets = dataset_store.list_datasets(
        archived=archived_val,
        session_id=session_id,
        tag=tag,
        user_id="default_user",
        workspace_id="default_workspace"
    )
    return {"success": True, "datasets": datasets, "count": len(datasets)}

@app.get("/datasets/{dataset_id}")
async def get_dataset_route(dataset_id: str):
    """Fetch details for a single registered dataset."""
    dataset = dataset_store.get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(404, f"Dataset '{dataset_id}' not found")
    return {"success": True, "dataset": dataset}

@app.patch("/datasets/{dataset_id}")
async def update_dataset_route(dataset_id: str, req: UpdateDatasetRequest):
    """Update dataset details."""
    ok = dataset_store.update_dataset(
        dataset_id,
        display_name=req.display_name,
        description=req.description,
        tags=req.tags
    )
    if not ok:
        raise HTTPException(404, f"Dataset '{dataset_id}' not found")
        
    # Also update in file manager memory if cached
    manager = get_file_manager()
    record = manager.get_record(dataset_id)
    if record and req.display_name:
        record.filename = req.display_name
        
    return {"success": True}

@app.post("/datasets/{dataset_id}/archive")
async def archive_dataset_route(dataset_id: str):
    """Soft-archive a dataset."""
    ok = dataset_store.archive_dataset(dataset_id)
    if not ok:
        raise HTTPException(404, f"Dataset '{dataset_id}' not found")
    return {"success": True}

@app.post("/datasets/{dataset_id}/restore")
async def restore_dataset_route(dataset_id: str):
    """Restore a soft-archived dataset."""
    ok = dataset_store.restore_dataset(dataset_id)
    if not ok:
        raise HTTPException(404, f"Dataset '{dataset_id}' not found")
    return {"success": True}


if __name__ == "__main__":
    import uvicorn
    host = _get_backend_host()
    port = _resolve_backend_port(host, _get_backend_port())
    uvicorn.run("main:app", host=host, port=port, reload=True)
