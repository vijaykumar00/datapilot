"""
job_handlers.py — Durable background job implementations.

Every handler is a plain blocking function executed by ``worker.py`` (or inline
in development).  Handlers only use durable state (database + object storage),
so any worker on any host can run any job.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import tempfile
import time
from pathlib import Path

import pandas as pd

from core import jobs
from core.jsonsafe import to_jsonable

logger = logging.getLogger("datapilot.job_handlers")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _llm_for(user_id: str | None, workspace_id: str | None, *, is_guest: bool):
    """Request-equivalent LLM client for a job (user's own key when configured)."""
    from core.db import SessionLocal
    from core.llm_client import build_client, platform_settings, resolve_settings_for_user
    from core.usage import record_ai_tokens

    db = SessionLocal()
    try:
        settings = platform_settings() if is_guest or not user_id else resolve_settings_for_user(user_id, db)
    finally:
        db.close()

    def _usage(_provider: str, tokens: int) -> None:
        if workspace_id and not is_guest:
            record_ai_tokens(workspace_id, tokens)

    return build_client(settings, _usage)


def _release_quota(payload: dict) -> None:
    quota = payload.get("quota") or {}
    if not quota:
        return
    from core.db import SessionLocal
    from core.usage import release_guest, release_workspace

    db = SessionLocal()
    try:
        if quota.get("kind") == "guest":
            release_guest(quota["namespace"], quota["action"], db, quota.get("amount", 1))
        elif quota.get("kind") == "workspace":
            release_workspace(quota["namespace"], quota["action"], db, quota.get("amount", 1))
    finally:
        db.close()


def _store_result_file(job_id: str, workspace_id: str, filename: str, payload: bytes | None = None,
                       path: str | None = None) -> str:
    from core.storage import get_storage_provider

    key = f"workspace/{workspace_id}/jobs/{job_id}/{filename}"
    if path is not None:
        get_storage_provider().put_object_file(key, Path(path))
    else:
        get_storage_provider().put_object(key, payload)
    return key


# ── Dataset ingest (upload parsing + profiling) ──────────────────────────────

def _ingest_failed(payload: dict, ctx: jobs.JobContext, error: str) -> None:
    from core.file_manager import get_file_manager

    get_file_manager()._mark_failed(payload["dataset_id"], error)
    _release_quota(payload)


@jobs.register("dataset_ingest", on_failure=_ingest_failed)
def dataset_ingest(payload: dict, ctx: jobs.JobContext) -> dict:
    from core.file_manager import get_file_manager
    from core.insights import profile_columns_semantically
    from core.suggestion_engine import build_greeting, generate_suggestions

    refiner = None
    if payload.get("refine_semantics", True):
        try:
            llm = _llm_for(ctx.user_id, ctx.workspace_id, is_guest=payload.get("is_guest", False))
            if llm.settings.configured:
                def refiner(df, table_name):
                    return asyncio.run(profile_columns_semantically(df, table_name, llm=llm))
        except Exception as exc:  # AI semantics are optional; parsing is not
            logger.info("Semantic AI refinement disabled for ingest: %s", exc)

    manager = get_file_manager()
    try:
        summary = manager.ingest(payload["dataset_id"], semantic_refiner=refiner)
    except ValueError as exc:
        raise jobs.PermanentJobError(str(exc)) from exc

    record = manager.get_record(payload["dataset_id"])
    suggestions, greeting = [], ""
    try:
        suggestions = generate_suggestions(record.df, filename=record.filename, metadata=record.metadata)
        greeting = build_greeting(filename=record.filename, row_count=len(record.df),
                                  col_count=len(record.df.columns), suggestions=suggestions)
    except Exception as exc:
        logger.warning("Suggestion generation failed: %s", exc)
    return to_jsonable({**summary, "suggestions": suggestions, "greeting": greeting})


# ── Large template application ───────────────────────────────────────────────

def _template_failed(payload: dict, ctx: jobs.JobContext, error: str) -> None:
    from core.file_manager import get_file_manager

    get_file_manager().set_async_task(payload["dataset_id"], {
        "task_id": ctx.job_id, "template_id": payload.get("template_id"),
        "status": "failed", "progress": 0, "error": error,
    })


@jobs.register("dataset_template_apply", on_failure=_template_failed)
def dataset_template_apply(payload: dict, ctx: jobs.JobContext) -> dict:
    from core.file_manager import ConcurrentModificationError, get_file_manager

    manager = get_file_manager()
    try:
        result = manager.apply_actions(
            payload["dataset_id"], payload["steps"],
            f"Apply Template workflow (background): {payload.get('template_id')}",
            base_version=payload.get("base_version"),
            workflow_entry={"template_id": payload.get("template_id"), "steps": payload["steps"], "timestamp": time.time()},
        )
    except (ValueError, ConcurrentModificationError) as exc:
        raise jobs.PermanentJobError(str(exc)) from exc
    manager.set_async_task(payload["dataset_id"], {
        "task_id": ctx.job_id, "template_id": payload.get("template_id"),
        "status": "completed", "progress": 100, "error": None,
    })
    return {"status": "completed", "history_count": result["history_count"]}


# ── Reports ───────────────────────────────────────────────────────────────────

def compute_kpis(df: pd.DataFrame, x_col: str | None, y_col: str | None) -> list[dict]:
    """KPIs computed from the data (never taken from AI text)."""
    kpis = [{"title": "Rows", "metric": f"{len(df):,}", "severity": "info"}]
    if y_col and y_col in df.columns and pd.api.types.is_numeric_dtype(df[y_col]):
        series = pd.to_numeric(df[y_col], errors="coerce")
        kpis.append({"title": f"Total {y_col}", "metric": f"{series.sum():,.2f}", "severity": "info"})
        kpis.append({"title": f"Average {y_col}", "metric": f"{series.mean():,.2f}", "severity": "info"})
        if x_col and x_col in df.columns:
            grouped = series.groupby(df[x_col]).sum(min_count=1).dropna().sort_values(ascending=False)
            if not grouped.empty and grouped.sum():
                share = float(grouped.iloc[0]) / float(grouped.sum()) * 100
                kpis.append({"title": f"Top {x_col}", "metric": f"{grouped.index[0]} ({share:.1f}%)", "severity": "success"})
    missing = int(df.isnull().sum().sum())
    kpis.append({"title": "Missing cells", "metric": f"{missing:,}", "severity": "warning" if missing else "info"})
    return kpis[:5]


def _report_failed(payload: dict, ctx: jobs.JobContext, error: str) -> None:
    _release_quota(payload)


@jobs.register("report_generate", on_failure=_report_failed)
def report_generate(payload: dict, ctx: jobs.JobContext) -> dict:
    from agents.report_agent import compute_report_facts, facts_to_text, REPORT_SYSTEM
    from core.file_manager import get_file_manager
    from core.llm_client import LLMError
    from core.report_generator import generate_branded_chart

    record = get_file_manager().get_record(payload["file_id"], ctx.workspace_id)
    if record is None:
        raise jobs.PermanentJobError("Dataset not found")
    df = record.df
    x_col = payload.get("x_col") or (str(df.columns[0]) if len(df.columns) else None)
    y_col = payload.get("y_col")
    if not y_col:
        nums = [c for c in df.select_dtypes(include="number").columns]
        y_col = str(nums[0]) if nums else None

    chart_url = None
    if x_col and y_col:
        with tempfile.TemporaryDirectory(prefix="dp_report_") as tmp:
            path = os.path.join(tmp, "chart.png")
            if generate_branded_chart(df, x_col, y_col, payload.get("chart_type", "bar"), payload.get("brand_colors") or {}, path):
                chart_url = "data:image/png;base64," + base64.b64encode(Path(path).read_bytes()).decode()

    facts = compute_report_facts(df, record.filename)
    prompt = (
        f"Write a {payload.get('report_type', 'business')} report titled '{payload.get('title', 'Report')}' "
        f"covering: {payload.get('date_range') or 'all periods'}. Focus on '{y_col}' by '{x_col}'.\n\n"
        f"{facts_to_text(facts)}"
    )
    llm = _llm_for(ctx.user_id, ctx.workspace_id, is_guest=payload.get("is_guest", False))
    try:
        narrative = asyncio.run(llm.generate(prompt, system=REPORT_SYSTEM, temperature=0.2))
    except LLMError as exc:
        # No fabricated fallback narrative: fail clearly (quota is released).
        raise jobs.PermanentJobError(
            f"The AI narrative could not be generated ({exc}). No report was created; please retry."
        ) from exc

    return to_jsonable({
        "success": True,
        "title": payload.get("title"),
        "date_range": payload.get("date_range"),
        "report_type": payload.get("report_type"),
        "narrative": narrative,
        "narrative_source": "ai",
        "kpis": compute_kpis(df, x_col, y_col),
        "facts": facts,
        "chart_url": chart_url,
        "x_col": x_col,
        "y_col": y_col,
        "chart_type": payload.get("chart_type", "bar"),
        "brand_colors": payload.get("brand_colors"),
    })


@jobs.register("report_export")
def report_export(payload: dict, ctx: jobs.JobContext) -> dict:
    from core.file_manager import get_file_manager
    from core.report_generator import compile_docx, compile_pdf, compile_pptx, compile_xlsx, generate_branded_chart

    record = get_file_manager().get_record(payload["file_id"], ctx.workspace_id)
    if record is None:
        raise jobs.PermanentJobError("Dataset not found")
    df = record.df
    fmt = payload["format"]
    colors = payload.get("brand_colors") or {}
    x_col = payload.get("x_col") or (str(df.columns[0]) if len(df.columns) else None)
    y_col = payload.get("y_col") or next((str(c) for c in df.select_dtypes(include="number").columns), None)
    with tempfile.TemporaryDirectory(prefix="dp_export_") as tmp:
        out_path = os.path.join(tmp, f"report.{fmt}")
        chart_path = os.path.join(tmp, "chart.png")
        chart_ok = bool(x_col and y_col) and generate_branded_chart(df, x_col, y_col, payload.get("chart_type", "bar"), colors, chart_path)
        real_chart = chart_path if chart_ok else None
        args = (out_path, payload["title"], payload.get("date_range") or "", payload["narrative"], payload.get("kpis") or [], real_chart, colors)
        if fmt == "pdf":
            compile_pdf(*args)
        elif fmt == "docx":
            compile_docx(*args)
        elif fmt == "pptx":
            compile_pptx(*args)
        elif fmt == "xlsx":
            compile_xlsx(out_path, payload["title"], df, colors)
        else:
            raise jobs.PermanentJobError(f"Unsupported export format '{fmt}'")
        data = Path(out_path).read_bytes()
    key = _store_result_file(ctx.job_id, ctx.workspace_id or "anon", payload["filename"], data)
    return {"filename": payload["filename"], "media_type": payload["media_type"], "size": len(data), "_result_key": key}


# ── Data exports (full results, not just what the browser holds) ─────────────

_TRAILING_POINT_ZERO = r"(?<=\d)\.0$"


def _csv_ready(df: pd.DataFrame) -> pd.DataFrame:
    """Render float columns without a spurious ``.0`` on whole numbers.

    A column that mixes 100.5 and 200 is float64, and pandas would write the
    second value as ``200.0`` although the source said ``200``.  Values keep
    Python's shortest round-trip repr otherwise (so no precision is lost), and
    missing values stay empty.  Only float columns are re-rendered; the frame is
    shallow-copied so other columns are not duplicated in memory.
    """
    out = None
    for name in df.columns:
        col = df[name]
        if not pd.api.types.is_float_dtype(col.dtype):
            continue
        text = col.astype(str).str.replace(_TRAILING_POINT_ZERO, "", regex=True)
        text = text.where(col.notna(), None)
        if out is None:
            out = df.copy(deep=False)
        out[name] = text
    return df if out is None else out


CSV_CHUNK_ROWS = 50_000


def write_csv(df: pd.DataFrame, handle) -> None:
    """Write *df* as CSV in row chunks so only one chunk is ever rendered as text."""
    if len(df) == 0:
        df.to_csv(handle, index=False)
        return
    for start in range(0, len(df), CSV_CHUNK_ROWS):
        chunk = df.iloc[start:start + CSV_CHUNK_ROWS]
        _csv_ready(chunk).to_csv(handle, index=False, header=(start == 0))


def write_df_file(df: pd.DataFrame, fmt: str, path: str) -> None:
    if fmt == "csv":
        with open(path, "w", encoding="utf-8", newline="") as fh:
            write_csv(df, fh)
        return
    with open(path, "wb") as fh:
        fh.write(_df_to_bytes(df, fmt))


def _df_to_bytes(df: pd.DataFrame, fmt: str) -> bytes:
    if fmt == "csv":
        buf = io.StringIO()
        write_csv(df, buf)
        return buf.getvalue().encode("utf-8")
    buffer = io.BytesIO()
    tz_cols = [c for c in df.columns if isinstance(df[c].dtype, pd.DatetimeTZDtype)]
    safe = df
    if tz_cols:  # Excel cannot store tz-aware datetimes; copy only when needed
        safe = df.copy(deep=False)
        for col in tz_cols:
            safe[col] = safe[col].dt.tz_localize(None)
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        safe.to_excel(writer, sheet_name="data", index=False)
    return buffer.getvalue()


def _export_failed(payload: dict, ctx: jobs.JobContext, error: str) -> None:
    _release_quota(payload)


@jobs.register("data_export", on_failure=_export_failed)
def data_export(payload: dict, ctx: jobs.JobContext) -> dict:
    from core.data_store import execute_select_df
    from core.file_manager import get_file_manager

    manager = get_file_manager()
    fmt = payload["format"]
    if payload.get("sql"):
        tables = {}
        for fid in payload.get("file_ids", []):
            rec = manager.get_record(fid, ctx.workspace_id)
            if rec is None:
                raise jobs.PermanentJobError(f"Dataset {fid} not found")
            tables[rec.table_name] = rec.df
        try:
            df = execute_select_df(payload["sql"], tables)
        except ValueError as exc:
            raise jobs.PermanentJobError(str(exc)) from exc
    else:
        rec = manager.get_record(payload["file_id"], ctx.workspace_id)
        if rec is None:
            raise jobs.PermanentJobError("Dataset not found")
        df = rec.df
    max_xlsx_rows = 1_048_575
    if fmt == "xlsx" and len(df) > max_xlsx_rows:
        raise jobs.PermanentJobError("Result exceeds Excel's row limit; export as CSV instead.")
    # Stream the export to a temp file and upload it, instead of building the whole
    # file as a string plus a byte copy in memory.
    with tempfile.TemporaryDirectory(prefix="dp_export_") as tmp:
        out_path = os.path.join(tmp, "export")
        write_df_file(df, fmt, out_path)
        size = os.path.getsize(out_path)
        key = _store_result_file(ctx.job_id, ctx.workspace_id or "anon", payload["filename"], path=out_path)
    return {"filename": payload["filename"], "media_type": payload["media_type"], "rows": int(len(df)),
            "size": size, "_result_key": key}


# ── Heavy chat agents (forecast / report) ─────────────────────────────────────

@jobs.register("agent_run")
def agent_run(payload: dict, ctx: jobs.JobContext) -> dict:
    from agents.forecast_agent import ForecastAgent
    from agents.report_agent import ReportAgent
    from core.data_store import get_store
    from core.file_manager import get_file_manager

    intent = payload["intent"]
    cls = {"forecast": ForecastAgent, "report": ReportAgent}.get(intent)
    if cls is None:
        raise jobs.PermanentJobError(f"Agent '{intent}' cannot run as a background job")
    llm = None
    if intent == "report":
        llm = _llm_for(ctx.user_id, ctx.workspace_id, is_guest=payload.get("is_guest", False))
    agent = cls(llm, get_store(), get_file_manager(), workspace_id=ctx.workspace_id)
    result = asyncio.run(agent.run(payload["message"], payload["file_ids"], payload.get("history") or []))
    return to_jsonable(result.to_dict())


# ── Data lifecycle ───────────────────────────────────────────────────────────

@jobs.register("workspace_cleanup")
def workspace_cleanup(payload: dict, ctx: jobs.JobContext) -> dict:
    from core.file_manager import get_file_manager
    from core.storage import get_storage_provider

    deleted = get_file_manager().delete_workspace_data(payload["workspace_id"])
    try:
        get_storage_provider().delete_prefix(f"workspace/{payload['workspace_id']}/")
    except Exception as exc:
        logger.warning("Workspace prefix cleanup failed: %s", exc)
    return {"datasets_deleted": deleted}


def cleanup_expired_guests(batch: int = 100) -> int:
    """Delete datasets/sessions of guest sessions that expired without converting."""
    import datetime as dt

    from core.db import SessionLocal
    from core.file_manager import get_file_manager
    from core.models import GuestSession, Session as ChatSession

    cutoff = dt.datetime.utcnow() - dt.timedelta(hours=int(os.getenv("GUEST_DATA_RETENTION_HOURS", "24")))
    db = SessionLocal()
    try:
        expired = (
            db.query(GuestSession.guest_session_id)
            .filter(GuestSession.expires_at < cutoff, GuestSession.converted_to_user_id.is_(None))
            .limit(batch)
            .all()
        )
        ids = [r[0] for r in expired]
    finally:
        db.close()
    manager = get_file_manager()
    for gid in ids:
        manager.delete_workspace_data(gid)
        db = SessionLocal()
        try:
            db.query(ChatSession).filter(ChatSession.workspace_id == gid).delete(synchronize_session=False)
            db.query(GuestSession).filter(GuestSession.guest_session_id == gid).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()
    return len(ids)


def cleanup_staged_transforms() -> int:
    import datetime as dt

    from core.db import SessionLocal
    from core.models import StagedTransform

    db = SessionLocal()
    try:
        n = db.query(StagedTransform).filter(StagedTransform.expires_at < dt.datetime.utcnow()).delete(synchronize_session=False)
        db.commit()
        return n
    finally:
        db.close()
