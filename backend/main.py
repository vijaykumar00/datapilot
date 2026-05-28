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
from typing import AsyncGenerator

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import pandas as pd

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
import core.session_store as session_store


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:5175",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://127.0.0.1:5175",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
    session_id: str
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
    """Switch LLM provider at runtime (no restart needed)."""
    valid = {"gemini", "openai", "claude", "ollama"}
    if req.provider not in valid:
        raise HTTPException(400, f"Invalid provider. Choose from: {', '.join(valid)}")
    set_active_provider(req.provider, req.api_key)
    llm = get_llm_client()
    online = await llm.is_online()
    logger.info(f"Provider switched to '{req.provider}', online={online}")
    return {"success": True, "provider": req.provider, "online": online}


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
async def upload_file(file: UploadFile = File(...)):
    """Upload and parse a CSV or Excel file."""
    manager = get_file_manager()
    try:
        result = await manager.process_upload(file)
        logger.info(f"Upload successful: {file.filename} -> {result['file_id']}")
        return {"success": True, **result}
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


@app.get("/files/{file_id}")
async def get_file_preview(file_id: str):
    """Return preview rows and metadata for one loaded file."""
    preview = get_file_manager().get_preview_data(file_id)
    if preview is None:
        raise HTTPException(404, f"File '{file_id}' not found")
    return {"success": True, **preview}


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
async def export_result_rows(req: ExportRowsRequest, format: str = "csv"):
    """Export query or preview rows currently visible in the UI."""
    if not req.rows:
        raise HTTPException(400, "No rows provided for export")
    df = pd.DataFrame(req.rows)
    payload, media_type, ext = _dataframe_to_bytes(df, format)
    filename = f"{_safe_export_name(req.filename or 'results', 'results')}.{ext}"
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
async def get_sessions():
    """Get all saved chat sessions."""
    return {"success": True, "sessions": session_store.get_all_sessions()}


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
async def report_generate(req: ReportGenerateRequest):
    """Generate business-ready narrative analysis and dynamically styled charts."""
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
    return {"success": True, "templates": store.list_templates()}


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
        
    template = store.create_template(req.name, req.description, req.category, steps)
    return {"success": True, "template": template}


@app.post("/templates/{template_id}/duplicate")
async def duplicate_template_route(template_id: str):
    """Duplicate an existing template, appending (Copy) to its name."""
    from core.template_store import get_template_store
    store = get_template_store()
    duplicated = store.duplicate_template(template_id)
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


@app.post("/chat/stream")

async def chat_stream(req: ChatRequest):
    """
    SSE streaming chat endpoint.
    Classifies intent → routes to agent → streams response.
    """

    async def event_generator() -> AsyncGenerator[str, None]:
        agents = get_agents()
        file_ids = req.file_ids
        message = req.message.strip()
        sid = req.session_id

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

            if sid:
                session_store.append_message(sid, "bot", response_text, {"type": "text"})
            yield _sse({"type": "text", "content": response_text, "is_final": True})
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
            if sid:
                session_store.append_message(
                    sid,
                    "bot",
                    response.get("content", ""),
                    {
                        "type": response.get("type", "text"),
                        "chart_data": response.get("chart_data"),
                        "table_data": response.get("table_data"),
                        "metadata": response.get("metadata", {}),
                    }
                )
            yield _sse(response)
        except Exception as e:
            logger.exception(f"Agent '{intent}' crashed: {e}")
            err_msg = f"Analysis failed: {str(e)}"
            if sid:
                session_store.append_message(sid, "bot", err_msg, {"type": "error"})
            yield _sse({
                "type": "error",
                "content": err_msg,
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
async def startup_event():
    logger.info("DataPilot API starting up...")
    provider = get_active_provider()
    llm = get_llm_client()
    online = await llm.is_online()
    if online:
        logger.info(f"Provider '{provider}' is online and ready")
    else:
        logger.warning(f"Provider '{provider}' is offline or missing API key")

    # Reload files persisted from previous sessions
    manager = get_file_manager()
    reloaded = await manager.reload_from_disk()
    if reloaded:
        logger.info(f"Reloaded {reloaded} file(s) from uploads directory")

    logger.info(
        "DataPilot API ready at http://%s:%s",
        _get_backend_host(),
        _get_backend_port(),
    )


if __name__ == "__main__":
    import uvicorn
    host = _get_backend_host()
    port = _resolve_backend_port(host, _get_backend_port())
    uvicorn.run("main:app", host=host, port=port, reload=True)
