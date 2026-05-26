"""
main.py — FastAPI application entry point.
Routes: /upload, /chat/stream, /files, /files/{id}, /health, /ollama/status
"""

import asyncio
import json
import logging
import logging.handlers
import os
from pathlib import Path
from typing import AsyncGenerator

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# Logging setup (before any imports that log)
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            LOG_DIR / "datapilot.log", maxBytes=5_000_000, backupCount=3
        ),
    ],
)
logger = logging.getLogger("datapilot.main")

from agents.clean_agent import CleanAgent
from agents.crossfile_agent import CrossFileAgent
from agents.forecast_agent import ForecastAgent
from agents.insight_agent import InsightAgent
from agents.report_agent import ReportAgent
from agents.summary_agent import SummaryAgent
from agents.viz_agent import VizAgent
from core.data_store import get_store
from core.file_manager import get_file_manager
from core.llm_client import get_llm_client
from core.router import classify

# ── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="DataPilot API",
    description="Local-first AI data analysis assistant",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    """Health check endpoint."""
    llm = get_llm_client()
    ollama_up = await llm.is_online()
    return {
        "status": "ok",
        "ollama": ollama_up,
        "files_loaded": len(get_file_manager().list_files()),
    }


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
        logger.info(f"Upload successful: {file.filename} → {result['file_id']}")
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


@app.delete("/files/{file_id}")
async def delete_file(file_id: str):
    """Remove a file from memory."""
    ok = get_file_manager().delete_file(file_id)
    return {"success": ok, "file_id": file_id}


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

        if not message:
            yield _sse({"type": "error", "content": "Empty message", "is_final": True})
            return

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
                yield _sse({"type": "text", "content": response_text, "is_final": True})
                return

            yield _sse({"type": "text", "content": response_text, "is_final": True})
            return

        # ── Route to agent ────────────────────────────────────────────────────
        agent = agents.get(intent)
        if not agent:
            yield _sse({
                "type": "error",
                "content": f"Unknown intent: '{intent}'",
                "is_final": True,
            })
            return

        yield _sse({"type": "status", "content": f"⚙️ Running {intent} analysis...", "is_final": False})

        try:
            result = await agent.run(message, file_ids, req.conversation_history)
            response = result.to_dict()
            response["is_final"] = True
            yield _sse(response)
        except Exception as e:
            logger.exception(f"Agent '{intent}' crashed: {e}")
            yield _sse({
                "type": "error",
                "content": f"Analysis failed: {str(e)}",
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
    llm = get_llm_client()
    online = await llm.is_online()
    if online:
        model = await llm._get_best_model()
        logger.info(f"Ollama online — using model: {model}")
    else:
        logger.warning("Ollama is offline — LLM features will be limited")
    logger.info("DataPilot API ready at http://localhost:8000")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
