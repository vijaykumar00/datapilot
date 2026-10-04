"""
file_manager.py — Durable, multi-worker-safe dataset management.

Source of truth
---------------
* ``dataset_registry`` (Postgres/SQLite) holds the dataset's workspace, status,
  ``current_version`` and metadata.
* Object storage (S3/R2/MinIO, or local disk in development) holds the original
  upload and one immutable Parquet snapshot per version
  (``workspace/<ws>/datasets/<id>/versions/<n>.parquet``).
* ``dataset_versions`` lists the snapshots; undo moves ``current_version`` back.

Every API/worker process therefore sees the same data: nothing is lost on
restart, cache eviction or when a request lands on a different worker.  The
in-process cache is only an optimisation keyed by ``(dataset_id, version)`` and
bounded by memory (``DATASET_CACHE_MAX_BYTES``), never by entry count or TTL.

Mutations (edits, transforms, templates, sheet switches, undo) commit a new
version with an optimistic check on ``current_version`` so concurrent writers
cannot silently overwrite each other (``ConcurrentModificationError`` → 409).
"""

from __future__ import annotations

import copy
import datetime as dt
import io
import json
import logging
import os
import tempfile
import threading
import time
import uuid
import zipfile
from collections import OrderedDict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from core import jsonsafe
from core.db import SessionLocal
from core.error_intelligence import (
    IntelligentException,
    _make_error,
    diagnose_schema,
    diagnose_transform_error,
    diagnose_upload_error,
    format_for_user,
)
from core.insights import build_insights, clean_header_to_label, heuristic_semantic_map, infer_semantic_type
from core.models import DatasetRegistry, DatasetVersion
from core.parsing import ParseError, parse_to_parquet, read_parquet, write_parquet
from core.storage import dataset_prefix, get_storage_provider
from core.transform_engine import execute_transform

logger = logging.getLogger("datapilot.file_manager")


class ColumnMappingError(Exception):
    def __init__(self, failed_mappings: list[dict], available_columns: list[str]):
        self.failed_mappings = failed_mappings
        self.available_columns = available_columns
        super().__init__("Semantic column resolution confidence score below 85%")


class ConcurrentModificationError(RuntimeError):
    """The dataset changed since it was read; the caller should reload and retry."""


class DatasetNotReadyError(RuntimeError):
    def __init__(self, status: str, error: str | None = None):
        self.status = status
        self.error = error
        super().__init__(error or f"Dataset is {status}")


# ── Configuration ────────────────────────────────────────────────────────────

def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (ValueError, TypeError):
        return default


def max_upload_bytes() -> int:
    return _int_env("MAX_UPLOAD_BYTES", 50 * 1024 * 1024)


MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # legacy constant (hard cap is MAX_UPLOAD_BYTES)


def _parse_timeout_seconds() -> int:
    return _int_env("FILE_PARSE_TIMEOUT_SECONDS", 60)


def _max_dataset_rows() -> int:
    return _int_env("MAX_DATASET_ROWS", 250_000)


def _max_dataset_columns() -> int:
    return _int_env("MAX_DATASET_COLUMNS", 500)


def _max_dataset_cells() -> int:
    # rows x columns cap: memory scales with cells, so 250k rows and 500 columns
    # must not both be maxed out at once (125M cells would need several GB).
    return _int_env("MAX_DATASET_CELLS", 20_000_000)


def _max_excel_sheets() -> int:
    return _int_env("MAX_EXCEL_SHEETS", 25)


def _max_workbook_decompressed_bytes() -> int:
    return _int_env("MAX_WORKBOOK_DECOMPRESSED_BYTES", 200 * 1024 * 1024)


def _undo_depth() -> int:
    return _int_env("DATASET_UNDO_DEPTH", 10)


def _cache_max_bytes() -> int:
    return _int_env("DATASET_CACHE_MAX_BYTES", 1024 * 1024 * 1024)


ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls"}
MAGIC_BYTES = {b"PK\x03\x04": "xlsx", b"\xd0\xcf\x11\xe0": "xls"}

# Kept for import compatibility; nothing is served from this directory any more.
UPLOAD_DIR = Path(__file__).parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


def _now_iso() -> str:
    return dt.datetime.utcnow().isoformat()


def new_dataset_id() -> str:
    return uuid.uuid4().hex


def table_name_for(dataset_id: str) -> str:
    return f"file_{dataset_id.replace('-', '_')}"


# ── Memory-bounded cache ─────────────────────────────────────────────────────

class DatasetCache:
    """LRU cache of immutable DataFrame versions bounded by total memory."""

    def __init__(self, max_bytes: int | None = None):
        self.max_bytes = max_bytes or _cache_max_bytes()
        self._items: "OrderedDict[tuple[str, int], tuple[pd.DataFrame, int]]" = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: tuple[str, int]) -> pd.DataFrame | None:
        with self._lock:
            item = self._items.get(key)
            if item is None:
                self.misses += 1
                return None
            self._items.move_to_end(key)
            self.hits += 1
            return item[0]

    def put(self, key: tuple[str, int], df: pd.DataFrame) -> None:
        size = int(df.memory_usage(deep=True).sum())
        if size > self.max_bytes:
            return  # never cache something that would evict everything
        with self._lock:
            old = self._items.pop(key, None)
            if old:
                self._bytes -= old[1]
            self._items[key] = (df, size)
            self._bytes += size
            while self._bytes > self.max_bytes and self._items:
                _, (_, evicted) = self._items.popitem(last=False)
                self._bytes -= evicted

    def invalidate(self, dataset_id: str) -> None:
        with self._lock:
            for key in [k for k in self._items if k[0] == dataset_id]:
                self._bytes -= self._items.pop(key)[1]

    def stats(self) -> dict:
        with self._lock:
            return {
                "current_entries": len(self._items),
                "current_bytes": self._bytes,
                "max_bytes": self.max_bytes,
                "hits": self.hits,
                "misses": self.misses,
            }


# ── Record snapshot ──────────────────────────────────────────────────────────

class FileRecord:
    """Read-only snapshot of one dataset version handed to routes/agents."""

    def __init__(
        self,
        file_id: str,
        filename: str,
        df: pd.DataFrame,
        path: Any = None,
        metadata: dict[str, Any] | None = None,
        workspace_id: str = "default_workspace",
        user_id: str = "default_user",
        version: int = 1,
        history: list[dict] | None = None,
        uploaded_at: float | None = None,
    ):
        self.file_id = file_id
        self.filename = filename
        self.df = df
        self.path = path
        self.metadata = metadata or {}
        self.uploaded_at = uploaded_at or time.time()
        self.table_name = table_name_for(file_id)
        self.workspace_id = workspace_id
        self.user_id = user_id
        self.version = version
        self.history = history or []


def _registry_dict(row: DatasetRegistry) -> dict:
    meta = {}
    if row.metadata_json:
        try:
            meta = json.loads(row.metadata_json)
        except Exception:
            meta = {}
    return meta


def _column_summary(df: pd.DataFrame) -> list[dict]:
    return [{"name": str(c), "dtype": str(df[c].dtype)} for c in df.columns]


def _check_bounds(rows: int, columns: int) -> None:
    if rows > _max_dataset_rows():
        raise ValueError(f"Dataset has too many rows. Maximum supported rows: {_max_dataset_rows()}")
    if columns > _max_dataset_columns():
        raise ValueError(f"Dataset has too many columns. Maximum supported columns: {_max_dataset_columns()}")
    if rows * columns > _max_dataset_cells():
        raise ValueError(
            f"Dataset has too many rows for its number of columns ({rows:,} x {columns:,}). "
            f"Maximum supported cells (rows x columns): {_max_dataset_cells():,}"
        )


class FileManager:
    def __init__(self):
        self.cache = DatasetCache()

    # ── Validation helpers (also used directly by tests) ──────────────────────
    def _validate_extension(self, filename: str) -> str:
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError(f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}")
        return ext

    def _validate_magic(self, raw: bytes, ext: str) -> None:
        if ext == ".csv":
            if b"\x00" in raw[:4096]:
                raise ValueError("File content does not look like a text CSV file")
            return
        for magic in MAGIC_BYTES:
            if raw.startswith(magic):
                return
        raise ValueError("File content does not match Excel format")

    def _validate_workbook_expansion(self, raw: bytes | str | Path, ext: str) -> None:
        if ext != ".xlsx":
            return
        source = io.BytesIO(raw) if isinstance(raw, (bytes, bytearray)) else raw
        try:
            with zipfile.ZipFile(source) as workbook_zip:
                total = sum(item.file_size for item in workbook_zip.infolist())
        except zipfile.BadZipFile as exc:
            raise ValueError("Invalid XLSX container") from exc
        if total > _max_workbook_decompressed_bytes():
            raise ValueError("Excel workbook expands beyond the supported decompressed size limit.")

    def _validate_dataframe_bounds(self, df: pd.DataFrame) -> None:
        _check_bounds(len(df), len(df.columns))

    @staticmethod
    def _validate_parquet_bounds(path: Path) -> None:
        """Check limits from Parquet metadata *before* loading the frame into memory."""
        import pyarrow.parquet as pq

        meta = pq.ParquetFile(path).metadata
        _check_bounds(meta.num_rows, meta.num_columns)

    # ── Upload (API side: fast, no parsing) ────────────────────────────────────
    def stage_upload(
        self,
        tmp_path: Path,
        filename: str,
        size: int,
        *,
        workspace_id: str,
        user_id: str,
        max_size: int | None = None,
    ) -> str:
        """Validate a spooled upload, store the original durably and register it as 'processing'."""
        ext = self._validate_extension(filename)
        limit = min(max_size or max_upload_bytes(), max_upload_bytes())
        if size == 0:
            raise ValueError("File is empty")
        if size > limit:
            raise ValueError(f"File too large ({size / (1024 * 1024):.1f}MB). Max for your plan: {limit // (1024 * 1024)}MB")
        with open(tmp_path, "rb") as fh:
            head = fh.read(8192)
        self._validate_magic(head, ext)
        self._validate_workbook_expansion(tmp_path, ext)

        dataset_id = new_dataset_id()
        safe_name = Path(filename).name[:200] or f"dataset{ext}"
        original_key = f"{dataset_prefix(workspace_id, dataset_id)}original/{_safe_object_name(safe_name)}"
        get_storage_provider().put_object_file(original_key, tmp_path)

        now = _now_iso()
        db = SessionLocal()
        try:
            db.add(DatasetRegistry(
                dataset_id=dataset_id,
                filename=safe_name,
                display_name=safe_name,
                description="",
                tags="[]",
                row_count=0,
                column_count=0,
                sheet_count=1,
                file_size_bytes=size,
                archived=0,
                upload_date=now,
                last_query_date=None,
                session_id=None,
                column_summary="[]",
                schema_warnings="[]",
                user_id=user_id,
                workspace_id=workspace_id,
                created_at=now,
                updated_at=now,
                status="processing",
                current_version=None,
                storage_workspace_id=workspace_id,
                original_key=original_key,
                metadata_json="{}",
                storage_bytes=size,
            ))
            db.commit()
        finally:
            db.close()
        return dataset_id

    # ── Ingest (worker side: parse, profile, persist version 1) ────────────────
    def ingest(self, dataset_id: str, *, semantic_refiner=None) -> dict[str, Any]:
        row = self._load_row(dataset_id)
        if row is None:
            raise LookupError(f"Dataset {dataset_id} not found")
        ext = Path(row["filename"]).suffix.lower()
        storage = get_storage_provider()
        with tempfile.TemporaryDirectory(prefix="dp_ingest_") as tmp:
            local = Path(tmp) / f"original{ext}"
            parquet_path = Path(tmp) / "version.parquet"
            storage.download_object(row["original_key"], local)
            with open(local, "rb") as fh:
                raw_head = fh.read(65536)
            try:
                # The parser (a killable child process) writes the canonical Parquet file;
                # this process only reads it back, and later uploads the same file as v1.
                parse_meta = parse_to_parquet(local, ext, None, _parse_timeout_seconds(), parquet_path)
                if parse_meta.get("sheet_names") and len(parse_meta["sheet_names"]) > _max_excel_sheets():
                    raise ValueError(
                        f"Excel workbook has too many sheets. Maximum supported sheets: {_max_excel_sheets()}"
                    )
                local.unlink(missing_ok=True)  # free disk before loading the frame
                self._validate_parquet_bounds(parquet_path)
                df = read_parquet(parquet_path)
                if df.empty and len(df.columns) == 0:
                    raise ValueError("File is empty")
            except Exception as exc:
                message = str(exc) if isinstance(exc, ParseError) else format_for_user(
                    diagnose_upload_error(exc, row["filename"], raw_head)
                )
                self._mark_failed(dataset_id, message)
                raise ValueError(message) from exc

            metadata = self._profile(df, row["filename"], parse_meta, previous_semantic=None)
            if semantic_refiner is not None:
                try:
                    metadata["semantic_map"] = semantic_refiner(df, table_name_for(dataset_id)) or metadata["semantic_map"]
                except Exception as exc:
                    logger.warning("Semantic refinement skipped for %s: %s", dataset_id, exc)

            self._write_version(
                dataset_id,
                df,
                metadata,
                expected_version=None,
                description="Initial upload",
                action=None,
                user_id=row["user_id"],
                status="ready",
                parquet_path=parquet_path,
            )
        return self._summary(dataset_id, row["filename"], df, metadata)

    def _profile(self, df: pd.DataFrame, filename: str, parse_meta: dict, previous_semantic: dict | None) -> dict:
        metadata: dict[str, Any] = {}
        for key in ("sheet_names", "active_sheet", "sheet_columns", "encoding", "encoding_guessed", "delimiter", "header_row", "numeric_conversions"):
            if key in parse_meta:
                metadata[key] = parse_meta[key]
        try:
            metadata["insights"] = build_insights(df, table_name="data")
        except Exception as exc:
            logger.warning("Insight profiling failed: %s", exc)
            metadata["insights"] = []
        metadata["semantic_map"] = heuristic_semantic_map(df, previous_semantic)
        try:
            warnings = diagnose_schema(df, filename)
        except Exception as exc:
            logger.warning("Schema diagnostics failed: %s", exc)
            warnings = []
        if parse_meta.get("encoding_guessed"):
            warnings.append({
                "code": "ENCODING_GUESSED",
                "title": "Text encoding was guessed",
                "message": "The file is not valid UTF-8 or Windows-1252; some characters may display incorrectly.",
                "severity": "warning",
            })
        metadata["schema_warnings"] = warnings
        return metadata

    def _summary(self, dataset_id: str, filename: str, df: pd.DataFrame, metadata: dict) -> dict[str, Any]:
        sem_map = metadata.get("semantic_map") or {}
        sample = jsonsafe.records(df.head(10).astype(object).where(df.head(10).notna(), ""))
        null_counts = df.isnull().sum().to_dict()
        col_info = []
        for col in df.columns:
            meta = sem_map.get(str(col)) or {}
            col_info.append({
                "name": col,
                "label": meta.get("label", clean_header_to_label(col)),
                "dtype": str(df[col].dtype),
                "semantic_type": meta.get("semantic_type", infer_semantic_type(col, df[col])),
                "inferred_meaning": meta.get("inferred_meaning", ""),
                "confidence": meta.get("confidence"),
                "aliases": meta.get("aliases", []),
                "null_count": int(null_counts.get(col, 0)),
                "unique_count": int(df[col].nunique()),
                "sample_values": [str(v) for v in df[col].dropna().head(3).tolist()],
            })
        return jsonsafe.to_jsonable({
            "file_id": dataset_id,
            "filename": filename,
            "row_count": len(df),
            "column_count": len(df.columns),
            "columns": col_info,
            "sample_data": sample,
            "file_size_kb": round(df.memory_usage(deep=True).sum() / 1024, 1),
            "metadata": metadata,
            "schema_warnings": metadata.get("schema_warnings", []),
        })

    # ── Persistence primitives ─────────────────────────────────────────────────
    def _load_row(self, dataset_id: str, workspace_id: str | None = None) -> dict | None:
        db = SessionLocal()
        try:
            q = db.query(DatasetRegistry).filter(DatasetRegistry.dataset_id == dataset_id)
            if workspace_id is not None:
                q = q.filter(DatasetRegistry.workspace_id == workspace_id)
            row = q.first()
            if row is None:
                return None
            return {
                "dataset_id": row.dataset_id,
                "filename": row.display_name or row.filename,
                "raw_filename": row.filename,
                "workspace_id": row.workspace_id,
                "user_id": row.user_id,
                "status": row.status or "ready",
                "error": row.error,
                "current_version": row.current_version,
                "storage_workspace_id": row.storage_workspace_id or row.workspace_id,
                "original_key": row.original_key,
                "metadata": _registry_dict(row),
                "row_count": row.row_count,
                "column_count": row.column_count,
                "column_summary": row.column_summary,
                "upload_date": row.upload_date,
                "archived": bool(row.archived),
            }
        finally:
            db.close()

    def _mark_failed(self, dataset_id: str, message: str) -> None:
        db = SessionLocal()
        try:
            row = db.query(DatasetRegistry).filter(DatasetRegistry.dataset_id == dataset_id).first()
            if row:
                row.status = "failed"
                row.error = message[:2000]
                row.updated_at = _now_iso()
                db.commit()
        finally:
            db.close()

    def _version_key(self, storage_ws: str, dataset_id: str, version: int) -> str:
        # Unique per write attempt: a writer that loses the optimistic-concurrency race
        # deletes only its own object, never the winner's snapshot.
        return f"{dataset_prefix(storage_ws, dataset_id)}versions/{version}-{uuid.uuid4().hex[:12]}.parquet"

    def _write_version(
        self,
        dataset_id: str,
        df: pd.DataFrame,
        metadata: dict,
        *,
        expected_version: int | None,
        description: str,
        action: Any,
        user_id: str | None,
        status: str | None = None,
        parquet_path: Path | None = None,
    ) -> int:
        """Persist *df* as the next version, atomically advancing current_version.

        *parquet_path*, when given, is an already-written canonical Parquet file of
        *df* (e.g. from the parser) that is uploaded as-is.  Otherwise *df* is
        written to a temporary file and streamed to storage — never serialised to
        an in-memory byte string.
        """
        row = self._load_row(dataset_id)
        if row is None:
            raise LookupError(dataset_id)
        if row["current_version"] != expected_version:
            raise ConcurrentModificationError("Dataset was modified by another request. Reload and try again.")
        new_version = (expected_version or 0) + 1
        key = self._version_key(row["storage_workspace_id"], dataset_id, new_version)
        storage = get_storage_provider()
        if parquet_path is not None:
            size_bytes = os.path.getsize(parquet_path)
            storage.put_object_file(key, Path(parquet_path))
        else:
            with tempfile.TemporaryDirectory(prefix="dp_version_") as tmp:
                path = Path(tmp) / "version.parquet"
                write_parquet(df, path)
                size_bytes = os.path.getsize(path)
                storage.put_object_file(key, path)

        clean_meta = jsonsafe.to_jsonable(metadata)
        now = _now_iso()
        db = SessionLocal()
        try:
            q = db.query(DatasetRegistry).filter(DatasetRegistry.dataset_id == dataset_id)
            if expected_version is None:
                q = q.filter(DatasetRegistry.current_version.is_(None))
            else:
                q = q.filter(DatasetRegistry.current_version == expected_version)
            values = {
                DatasetRegistry.current_version: new_version,
                DatasetRegistry.row_count: int(len(df)),
                DatasetRegistry.column_count: int(len(df.columns)),
                DatasetRegistry.column_summary: json.dumps(_column_summary(df)),
                DatasetRegistry.schema_warnings: jsonsafe.dumps(clean_meta.get("schema_warnings", [])),
                DatasetRegistry.metadata_json: jsonsafe.dumps(clean_meta),
                DatasetRegistry.sheet_count: len(clean_meta.get("sheet_names") or []) or 1,
                DatasetRegistry.updated_at: now,
                DatasetRegistry.error: None,
            }
            if status:
                values[DatasetRegistry.status] = status
            updated = q.update(values, synchronize_session=False)
            if updated != 1:
                db.rollback()
                storage.delete_object(key)
                raise ConcurrentModificationError("Dataset was modified by another request. Reload and try again.")
            db.add(DatasetVersion(
                id=uuid.uuid4().hex,
                dataset_id=dataset_id,
                version=new_version,
                storage_key=key,
                description=description[:500],
                action_json=jsonsafe.dumps(action) if action is not None else None,
                metadata_json=jsonsafe.dumps(clean_meta),
                row_count=int(len(df)),
                column_count=int(len(df.columns)),
                size_bytes=size_bytes,
                created_by=user_id,
                created_at=dt.datetime.utcnow(),
            ))
            db.commit()
        finally:
            db.close()

        # Keep only the current version cached: older versions are needed only for
        # undo, which re-reads them from storage.  Holding them would double the
        # resident memory of every edited dataset.
        self.cache.invalidate(dataset_id)
        self.cache.put((dataset_id, new_version), df)
        self._prune_versions(dataset_id, new_version)
        return new_version

    def _prune_versions(self, dataset_id: str, current: int) -> None:
        keep_from = current - _undo_depth()
        if keep_from <= 1:
            return
        db = SessionLocal()
        try:
            old = (
                db.query(DatasetVersion)
                .filter(DatasetVersion.dataset_id == dataset_id, DatasetVersion.version < keep_from)
                .all()
            )
            keys = [v.storage_key for v in old]
            for v in old:
                db.delete(v)
            db.commit()
        finally:
            db.close()
        storage = get_storage_provider()
        for key in keys:
            try:
                storage.delete_object(key)
            except Exception as exc:  # orphaned objects are reclaimed by dataset deletion
                logger.warning("Could not delete pruned version %s: %s", key, exc)

    def _version_row(self, dataset_id: str, version: int) -> DatasetVersion | None:
        db = SessionLocal()
        try:
            return db.query(DatasetVersion).filter(
                DatasetVersion.dataset_id == dataset_id, DatasetVersion.version == version
            ).first()
        finally:
            db.close()

    def _history(self, dataset_id: str, current: int) -> list[dict]:
        db = SessionLocal()
        try:
            rows = (
                db.query(DatasetVersion.version, DatasetVersion.description)
                .filter(DatasetVersion.dataset_id == dataset_id, DatasetVersion.version < current)
                .order_by(DatasetVersion.version)
                .all()
            )
            return [{"version": v, "description": d} for v, d in rows]
        finally:
            db.close()

    def _load_df(self, row: dict, version: int) -> tuple[pd.DataFrame, dict]:
        vrow = self._version_row(row["dataset_id"], version)
        if vrow is None:
            raise LookupError(f"Version {version} of dataset {row['dataset_id']} is missing")
        meta = json.loads(vrow.metadata_json) if vrow.metadata_json else {}
        cached = self.cache.get((row["dataset_id"], version))
        if cached is not None:
            return cached, meta
        with tempfile.TemporaryDirectory(prefix="dp_load_") as tmp:
            path = Path(tmp) / "version.parquet"
            get_storage_provider().download_object(vrow.storage_key, path)
            df = read_parquet(path)
        self.cache.put((row["dataset_id"], version), df)
        return df, meta

    def _migrate_legacy(self, row: dict) -> dict | None:
        """Bring a pre-versioning dataset (raw file on disk / old S3 key) into versioned storage."""
        storage = get_storage_provider()
        candidates: list[Path] = []
        legacy_dir = UPLOAD_DIR / row["workspace_id"] / row["dataset_id"]
        if legacy_dir.exists():
            candidates = [p for p in legacy_dir.iterdir() if p.is_file() and p.suffix.lower() in ALLOWED_EXTENSIONS]
        flat = [p for p in UPLOAD_DIR.glob(f"{row['dataset_id']}.*") if p.suffix.lower() in ALLOWED_EXTENSIONS]
        candidates.extend(flat)
        raw_bytes = None
        name = row["raw_filename"]
        if candidates:
            raw_bytes = candidates[0].read_bytes()
            name = candidates[0].name if not Path(name).suffix else name
        else:
            try:
                raw_bytes = storage.read_file(row["workspace_id"], row["dataset_id"], row["raw_filename"])
            except Exception:
                raw_bytes = None
        if raw_bytes is None:
            self._mark_failed(row["dataset_id"], "Original file is no longer available. Please upload it again.")
            return None
        key = f"{dataset_prefix(row['workspace_id'], row['dataset_id'])}original/{_safe_object_name(name)}"
        storage.put_object(key, raw_bytes)
        db = SessionLocal()
        try:
            reg = db.query(DatasetRegistry).filter(DatasetRegistry.dataset_id == row["dataset_id"]).first()
            reg.original_key = key
            reg.storage_workspace_id = row["workspace_id"]
            db.commit()
        finally:
            db.close()
        try:
            self.ingest(row["dataset_id"])
        except Exception as exc:
            logger.warning("Legacy dataset %s could not be migrated: %s", row["dataset_id"], exc)
            return None
        return self._load_row(row["dataset_id"])

    # ── Public read API ────────────────────────────────────────────────────────
    def get_record(self, file_id: str, workspace_id: str | None = None) -> FileRecord | None:
        row = self._load_row(file_id, workspace_id)
        if row is None:
            return None
        if row["status"] != "ready":
            raise DatasetNotReadyError(row["status"], row["error"])
        if row["current_version"] is None:
            row = self._migrate_legacy(row)
            if row is None or row["current_version"] is None:
                return None
        df, meta = self._load_df(row, row["current_version"])
        registry_meta = row["metadata"]
        if "async_task" in registry_meta:
            meta = {**meta, "async_task": registry_meta["async_task"]}
        return FileRecord(
            file_id=row["dataset_id"],
            filename=row["filename"],
            df=df,
            path=row["original_key"],
            metadata=copy.deepcopy(meta),
            workspace_id=row["workspace_id"],
            user_id=row["user_id"],
            version=row["current_version"],
            history=self._history(row["dataset_id"], row["current_version"]),
        )

    def get_dataframe(self, file_id: str, workspace_id: str | None = None) -> pd.DataFrame | None:
        record = self.get_record(file_id, workspace_id)
        return record.df if record else None

    def get_preview_data(self, file_id: str, limit: int = 200, workspace_id: str | None = None) -> dict[str, Any] | None:
        record = self.get_record(file_id, workspace_id)
        if record is None:
            return None
        return self._preview_for(record, limit)

    def _preview_for(self, record: FileRecord, limit: int = 200) -> dict[str, Any]:
        head = record.df.head(limit)
        rows = jsonsafe.records(head.astype(object).where(head.notna(), ""))
        for idx, row in enumerate(rows):
            row["_row_index"] = idx
        return jsonsafe.to_jsonable({
            "file_id": record.file_id,
            "filename": record.filename,
            "row_count": len(record.df),
            "column_count": len(record.df.columns),
            "version": record.version,
            "columns": [
                {
                    "name": col,
                    "label": clean_header_to_label(col),
                    "dtype": str(record.df[col].dtype),
                    "semantic_type": (record.metadata.get("semantic_map", {}).get(str(col)) or {}).get(
                        "semantic_type", infer_semantic_type(col, record.df[col])
                    ),
                    "null_count": int(record.df[col].isnull().sum()),
                    "unique_count": int(record.df[col].nunique()),
                }
                for col in record.df.columns
            ],
            "sample_data": rows,
            "metadata": record.metadata,
        })

    def list_files(self, workspace_id: str | None = None) -> list[dict[str, Any]]:
        db = SessionLocal()
        try:
            q = db.query(DatasetRegistry).filter(DatasetRegistry.archived == 0)
            if workspace_id is not None:
                q = q.filter(DatasetRegistry.workspace_id == workspace_id)
            rows = q.order_by(DatasetRegistry.created_at.desc()).all()
            out = []
            for r in rows:
                status = r.status or "ready"
                if status == "failed":
                    continue
                try:
                    cols = [c.get("name") for c in json.loads(r.column_summary or "[]") if isinstance(c, dict)]
                except Exception:
                    cols = []
                out.append({
                    "file_id": r.dataset_id,
                    "filename": r.display_name or r.filename,
                    "table_name": table_name_for(r.dataset_id),
                    "row_count": r.row_count or 0,
                    "column_count": r.column_count or 0,
                    "columns": cols,
                    "metadata": _registry_dict(r),
                    "uploaded_at": r.upload_date,
                    "status": status,
                    "version": r.current_version,
                })
            return out
        finally:
            db.close()

    # ── Mutations ──────────────────────────────────────────────────────────────
    def _commit(self, record: FileRecord, new_df: pd.DataFrame, description: str, action: Any, metadata_updates: dict | None = None) -> FileRecord:
        meta = copy.deepcopy(record.metadata)
        meta.pop("async_task", None)
        meta.update(metadata_updates or {})
        profile = self._profile(new_df, record.filename, {k: meta[k] for k in ("sheet_names", "active_sheet", "sheet_columns") if k in meta}, meta.get("semantic_map"))
        meta["insights"] = profile["insights"]
        meta["schema_warnings"] = profile["schema_warnings"]
        meta["semantic_map"] = profile["semantic_map"]
        version = self._write_version(
            record.file_id,
            new_df,
            meta,
            expected_version=record.version,
            description=description,
            action=action,
            user_id=record.user_id,
        )
        return FileRecord(
            file_id=record.file_id,
            filename=record.filename,
            df=new_df,
            path=record.path,
            metadata=meta,
            workspace_id=record.workspace_id,
            user_id=record.user_id,
            version=version,
            history=self._history(record.file_id, version),
        )

    def apply_edits(self, file_id: str, edits: list[dict[str, Any]], workspace_id: str | None = None) -> dict[str, Any] | None:
        record = self.get_record(file_id, workspace_id)
        if record is None:
            return None
        df = record.df.copy()
        applied = 0
        for edit in edits:
            row_index = int(edit["row_index"])
            column = edit["column"]
            if column not in df.columns:
                raise ValueError(f"Column '{column}' does not exist")
            if row_index < 0 or row_index >= len(df):
                raise ValueError(f"Row index {row_index} is out of range")
            df.iat[row_index, df.columns.get_loc(column)] = self._coerce_value(df[column], edit.get("value"))
            applied += 1
        updated = self._commit(record, df, f"Edited {applied} cell(s)", {"action": "cell_edits", "count": applied})
        return {"success": True, "applied": applied, "preview": self._preview_for(updated)}

    def apply_actions(self, file_id: str, actions: list[dict], description: str, workspace_id: str | None = None,
                      base_version: int | None = None, workflow_entry: dict | None = None) -> dict[str, Any] | None:
        """Apply one or more declarative steps as a single undoable version."""
        record = self.get_record(file_id, workspace_id)
        if record is None:
            return None
        if base_version is not None and record.version != base_version:
            raise ConcurrentModificationError("Dataset changed since this plan was previewed. Preview again.")
        df = record.df
        for action in actions:
            try:
                df = execute_transform(df, action)
            except Exception as exc:
                raise ValueError(format_for_user(diagnose_transform_error(exc, action, df))) from exc
        workflows = list(record.metadata.get("applied_workflows", []))
        workflows.append(workflow_entry or {
            "steps": actions,
            "description": description,
            "timestamp": time.time(),
        })
        updated = self._commit(record, df, description, actions, {"applied_workflows": workflows})
        return {
            "success": True,
            "description": description,
            "history_count": len(updated.history),
            "preview": self._preview_for(updated),
            "version": updated.version,
        }

    def apply_transform(self, file_id: str, action: dict, description: str, workspace_id: str | None = None) -> dict[str, Any] | None:
        return self.apply_actions(
            file_id, [action], description, workspace_id,
            workflow_entry={"action": action, "description": description, "timestamp": time.time()},
        )

    def undo_transform(self, file_id: str, workspace_id: str | None = None) -> dict[str, Any] | None:
        record = self.get_record(file_id, workspace_id)
        if record is None:
            return None
        if not record.history:
            raise ValueError("No changes in the undo stack")
        previous = record.history[-1]["version"]
        current_row = self._version_row(file_id, record.version)
        db = SessionLocal()
        try:
            updated = db.query(DatasetRegistry).filter(
                DatasetRegistry.dataset_id == file_id, DatasetRegistry.current_version == record.version
            ).update({DatasetRegistry.current_version: previous, DatasetRegistry.updated_at: _now_iso()},
                     synchronize_session=False)
            if updated != 1:
                db.rollback()
                raise ConcurrentModificationError("Dataset was modified by another request. Reload and try again.")
            prev_row = db.query(DatasetVersion).filter(
                DatasetVersion.dataset_id == file_id, DatasetVersion.version == previous
            ).first()
            if prev_row is not None:
                reg = db.query(DatasetRegistry).filter(DatasetRegistry.dataset_id == file_id).first()
                reg.metadata_json = prev_row.metadata_json
                reg.row_count = prev_row.row_count
                reg.column_count = prev_row.column_count
            db.query(DatasetVersion).filter(
                DatasetVersion.dataset_id == file_id, DatasetVersion.version == record.version
            ).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()
        if current_row is not None:
            try:
                get_storage_provider().delete_object(current_row.storage_key)
            except Exception:
                pass
        self.cache.invalidate(file_id)
        restored = self.get_record(file_id, workspace_id)
        description = current_row.description if current_row else "last change"
        return {
            "success": True,
            "undone_description": description,
            "history_count": len(restored.history),
            "preview": self._preview_for(restored),
        }

    def switch_sheet(self, file_id: str, sheet_name: str, workspace_id: str | None = None) -> dict[str, Any] | None:
        record = self.get_record(file_id, workspace_id)
        if record is None:
            return None
        sheet_names = record.metadata.get("sheet_names", [])
        if sheet_name not in sheet_names:
            import difflib

            close = difflib.get_close_matches(sheet_name, sheet_names, n=1, cutoff=0.5)
            suggestion = f"Did you mean '{close[0]}?'" if close else f"Available sheets: {', '.join(sheet_names)}"
            err = _make_error(
                code="INCORRECT_SHEET_NAME",
                title="Incorrect sheet name",
                message=f"The workbook does not contain a sheet named '{sheet_name}'. {suggestion}",
                suggestions=[
                    f"Switch to sheet '{close[0]}' instead." if close else "Check sheet names in the workbook.",
                    f"Available sheets: {', '.join(sheet_names)}.",
                ],
                severity="error",
            )
            if close:
                err["recovery"] = {"type": "switch_sheet", "sheet": close[0], "file_id": file_id,
                                   "label": f"Switch to '{close[0]}' and retry"}
            raise IntelligentException(err)
        ext = Path(record.filename).suffix.lower() or ".xlsx"
        with tempfile.TemporaryDirectory(prefix="dp_sheet_") as tmp:
            local = Path(tmp) / f"original{ext}"
            parquet_path = Path(tmp) / "version.parquet"
            get_storage_provider().download_object(record.path, local)
            parse_meta = parse_to_parquet(local, ext, sheet_name, _parse_timeout_seconds(), parquet_path)
            self._validate_parquet_bounds(parquet_path)
            df = read_parquet(parquet_path)
        updated = self._commit(
            record, df, f"Switched to sheet '{sheet_name}'", {"action": "switch_sheet", "sheet": sheet_name},
            {"active_sheet": sheet_name, "numeric_conversions": parse_meta.get("numeric_conversions", []),
             "semantic_map": {}},
        )
        return self._summary(file_id, updated.filename, updated.df, updated.metadata)

    def rename_file(self, file_id: str, new_name: str, workspace_id: str | None = None) -> bool:
        db = SessionLocal()
        try:
            q = db.query(DatasetRegistry).filter(DatasetRegistry.dataset_id == file_id)
            if workspace_id is not None:
                q = q.filter(DatasetRegistry.workspace_id == workspace_id)
            row = q.first()
            if row is None:
                return False
            row.display_name = new_name.strip()[:255]
            row.updated_at = _now_iso()
            db.commit()
            return True
        finally:
            db.close()

    def delete_file(self, file_id: str, workspace_id: str | None = None) -> bool:
        db = SessionLocal()
        try:
            q = db.query(DatasetRegistry).filter(DatasetRegistry.dataset_id == file_id)
            if workspace_id is not None:
                q = q.filter(DatasetRegistry.workspace_id == workspace_id)
            row = q.first()
            if row is None:
                return False
            storage_ws = row.storage_workspace_id or row.workspace_id
            ws = row.workspace_id
            size = int(row.storage_bytes or 0)
            db.query(DatasetVersion).filter(DatasetVersion.dataset_id == file_id).delete(synchronize_session=False)
            db.delete(row)
            db.commit()
        finally:
            db.close()
        self.cache.invalidate(file_id)
        try:
            get_storage_provider().delete_prefix(dataset_prefix(storage_ws, file_id))
        except Exception as exc:
            logger.error("Storage cleanup failed for dataset %s: %s", file_id, exc)
        legacy = UPLOAD_DIR / ws / file_id
        if legacy.exists():
            import shutil

            shutil.rmtree(legacy, ignore_errors=True)
        try:
            from core.usage import adjust_storage_bytes
            adjust_storage_bytes(ws, -size)
        except Exception:
            pass
        logger.info("Deleted dataset %s", file_id)
        return True

    def delete_workspace_data(self, workspace_id: str) -> int:
        db = SessionLocal()
        try:
            ids = [r[0] for r in db.query(DatasetRegistry.dataset_id).filter(DatasetRegistry.workspace_id == workspace_id).all()]
        finally:
            db.close()
        for dataset_id in ids:
            self.delete_file(dataset_id)
        return len(ids)

    def evict_workspace(self, workspace_id: str) -> int:
        """Drop cached versions for a workspace (memory only; data stays durable)."""
        count = 0
        for item in self.list_files(workspace_id):
            self.cache.invalidate(item["file_id"])
            count += 1
        return count

    def get_cache_stats(self) -> dict:
        return self.cache.stats()

    def set_async_task(self, file_id: str, task: dict | None) -> None:
        db = SessionLocal()
        try:
            row = db.query(DatasetRegistry).filter(DatasetRegistry.dataset_id == file_id).first()
            if row is None:
                return
            meta = _registry_dict(row)
            if task is None:
                meta.pop("async_task", None)
            else:
                meta["async_task"] = task
            row.metadata_json = jsonsafe.dumps(meta)
            db.commit()
        finally:
            db.close()

    @staticmethod
    def _coerce_value(series: pd.Series, raw_value: Any) -> Any:
        if raw_value == "":
            raw_value = None
        if pd.api.types.is_integer_dtype(series.dtype):
            if raw_value is None:
                return np.nan
            return int(float(raw_value))
        if pd.api.types.is_float_dtype(series.dtype):
            return np.nan if raw_value is None else float(raw_value)
        if pd.api.types.is_bool_dtype(series.dtype):
            if raw_value is None:
                return False
            text = str(raw_value).strip().lower()
            if text in {"true", "1", "yes", "y"}:
                return True
            if text in {"false", "0", "no", "n"}:
                return False
            raise ValueError(f"Invalid boolean value '{raw_value}'")
        if pd.api.types.is_datetime64_any_dtype(series.dtype):
            return pd.NaT if raw_value is None else pd.to_datetime(raw_value)
        return raw_value

    # ── Templates ──────────────────────────────────────────────────────────────
    def resolve_template_column(self, df: pd.DataFrame, target_col: str, semantic_map: dict | None) -> tuple[str, float]:
        if target_col in df.columns:
            return target_col, 1.0
        for col in df.columns:
            if str(col).lower() == target_col.lower():
                return col, 0.99
        if semantic_map:
            best_col, best_conf = None, 0.0
            for col, meta in semantic_map.items():
                if col not in df.columns:
                    continue
                sem_type = str(meta.get("semantic_type", "")).lower()
                label = str(meta.get("label", "")).lower()
                inferred = str(meta.get("inferred_meaning", "")).lower()
                confidence = float(meta.get("confidence") or 0.6)
                if target_col.lower() in (sem_type, label) or target_col.lower() in inferred:
                    if confidence > best_conf:
                        best_conf, best_col = confidence, col
            if best_col and best_conf > 0.0:
                return best_col, best_conf
        return target_col, 0.0

    def resolve_step_columns(self, df: pd.DataFrame, step: dict, semantic_map: dict | None,
                             overrides: dict[str, str] | None) -> tuple[dict, list[dict]]:
        resolved_step = copy.deepcopy(step)
        resolutions = []

        def _resolve(orig: str) -> tuple[str, float]:
            if overrides and orig in overrides:
                return overrides[orig], 1.0
            return self.resolve_template_column(df, orig, semantic_map)

        for key in ("column", "target"):
            if key in step and isinstance(step[key], str):
                col, conf = _resolve(step[key])
                resolved_step[key] = col
                resolutions.append({"template_col": step[key], "resolved_col": col, "confidence": conf})
        if "columns" in step and isinstance(step["columns"], list):
            cols = []
            for orig in step["columns"]:
                if not isinstance(orig, str):
                    cols.append(orig)
                    continue
                col, conf = _resolve(orig)
                cols.append(col)
                resolutions.append({"template_col": orig, "resolved_col": col, "confidence": conf})
            resolved_step["columns"] = cols
        return resolved_step, resolutions

    def plan_template(self, file_id: str, steps: list[dict], mapping_overrides: dict[str, str] | None,
                      workspace_id: str | None = None) -> tuple[FileRecord, list[dict]]:
        record = self.get_record(file_id, workspace_id)
        if record is None:
            raise LookupError(file_id)
        semantic_map = record.metadata.get("semantic_map")
        resolved_steps, failed, seen = [], [], set()
        for step in copy.deepcopy(steps):
            resolved, resolutions = self.resolve_step_columns(record.df, step, semantic_map, mapping_overrides)
            resolved_steps.append(resolved)
            for res in resolutions:
                if res["confidence"] < 0.85 and res["template_col"] not in seen:
                    seen.add(res["template_col"])
                    failed.append({"template_col": res["template_col"], "suggestions": list(record.df.columns)})
        if failed:
            raise ColumnMappingError(failed, list(record.df.columns))
        return record, resolved_steps

    def apply_template(self, file_id: str, template_id: str, steps: list[dict],
                       mapping_overrides: dict[str, str] | None = None, workspace_id: str | None = None,
                       user_id: str | None = None) -> dict[str, Any] | None:
        try:
            record, resolved_steps = self.plan_template(file_id, steps, mapping_overrides, workspace_id)
        except LookupError:
            return None
        is_large = len(record.df) > 10000 or len(resolved_steps) > 5
        if is_large:
            from core import jobs

            job_id = jobs.enqueue(
                "dataset_template_apply",
                {"dataset_id": file_id, "template_id": template_id, "steps": resolved_steps,
                 "base_version": record.version},
                workspace_id=record.workspace_id,
                user_id=user_id,
                max_attempts=1,
            )
            self.set_async_task(file_id, {"task_id": job_id, "template_id": template_id, "status": "processing",
                                          "progress": 0, "error": None})
            if jobs.execution_mode() == "inline":
                jobs.run_inline(job_id)
            return {"success": True, "status": "processing", "task_id": job_id,
                    "message": "Template execution queued as a background job due to dataset size."}
        result = self.apply_actions(
            file_id, resolved_steps, f"Apply Template workflow: {template_id}", workspace_id,
            base_version=record.version,
            workflow_entry={"template_id": template_id, "steps": resolved_steps, "timestamp": time.time()},
        )
        return {"success": True, "status": "completed", "history_count": result["history_count"], "preview": result["preview"]}


def _safe_object_name(name: str) -> str:
    import re

    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(name).name).strip(".-")
    return cleaned or "dataset"


_manager: FileManager | None = None
_manager_lock = threading.Lock()


def get_file_manager() -> FileManager:
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = FileManager()
    return _manager
