"""
file_manager.py - Upload, parse, cache, and register CSV/Excel files.
Uses chunked reading for large files and an LRU cache for speed.
"""

import logging
import tempfile
import time
import uuid
import asyncio
from pathlib import Path
from typing import Any

class ColumnMappingError(Exception):
    def __init__(self, failed_mappings: list[dict], available_columns: list[str]):
        self.failed_mappings = failed_mappings
        self.available_columns = available_columns
        super().__init__("Semantic column resolution confidence score below 85%")

import numpy as np
import pandas as pd
from cachetools import LRUCache
from fastapi import UploadFile

from core.data_store import get_store
from core.insights import clean_header_to_label, infer_semantic_type, generate_insights, profile_columns_semantically
from core.transform_engine import execute_transform

logger = logging.getLogger("datapilot.file_manager")

# Config
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB
CHUNK_THRESHOLD = 5 * 1024 * 1024  # 5 MB -> use chunked reading
MAX_CACHE_ENTRIES = 10
ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls"}
MAGIC_BYTES = {
    b"PK\x03\x04": "xlsx",   # ZIP-based (xlsx)
    b"\xd0\xcf\x11\xe0": "xls",  # OLE2 (xls)
}

# Persistent upload directory (survives backend restarts)
UPLOAD_DIR = Path(__file__).parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


class FileRecord:
    def __init__(
        self,
        file_id: str,
        filename: str,
        df: pd.DataFrame,
        path: Path,
        metadata: dict[str, Any] | None = None,
    ):
        self.file_id = file_id
        self.filename = filename
        self.df = df
        self.path = path
        self.metadata = metadata or {}
        self.uploaded_at = time.time()
        self.table_name = f"file_{file_id.replace('-', '_')}"
        self.history = []  # list of tuples (df_copy, metadata_copy, description)

    def push_state(self, description: str):
        """Push the current state of df and metadata to the transactional history stack."""
        import copy
        df_copy = self.df.copy()
        metadata_copy = copy.deepcopy(self.metadata)
        self.history.append((df_copy, metadata_copy, description))
        # Quiet FIFO eviction when stack depth exceeds 10
        if len(self.history) > 10:
            self.history.pop(0)

    def undo(self) -> str | None:
        """Pop the last checkpoint state, restoring the dataframe and metadata, returning the description."""
        if not self.history:
            return None
        df_copy, metadata_copy, description = self.history.pop()
        self.df = df_copy
        self.metadata = metadata_copy
        return description


class FileManager:
    def __init__(self):
        self._cache: LRUCache = LRUCache(maxsize=MAX_CACHE_ENTRIES)
        self._store = get_store()

    def _validate_extension(self, filename: str) -> str:
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file type '{ext}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
            )
        return ext

    def _validate_magic(self, raw: bytes, ext: str) -> None:
        """Validate file magic bytes for xlsx/xls."""
        if ext == ".csv":
            return
        for magic in MAGIC_BYTES:
            if raw.startswith(magic):
                return
        raise ValueError("File content does not match Excel format")

    def _read_file(
        self,
        path: Path,
        ext: str,
        file_size: int,
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        """Read CSV or Excel into a DataFrame, returning lightweight metadata too."""
        if ext == ".csv":
            if file_size > CHUNK_THRESHOLD:
                logger.info("Large file (%sKB) - using chunked reading", file_size // 1024)
                for encoding in ("utf-8", "latin-1", "cp1252"):
                    try:
                        chunks = pd.read_csv(path, chunksize=50_000, low_memory=False, encoding=encoding)
                        return pd.concat(chunks, ignore_index=True), {}
                    except UnicodeDecodeError:
                        continue
                raise ValueError("Could not decode CSV with UTF-8, Latin-1, or CP1252 encoding")
            for encoding in ("utf-8", "latin-1", "cp1252"):
                try:
                    return pd.read_csv(path, low_memory=False, encoding=encoding), {}
                except UnicodeDecodeError:
                    continue
            raise ValueError("Could not decode CSV with UTF-8, Latin-1, or CP1252 encoding")

        if ext in {".xlsx", ".xls"}:
            engine = "openpyxl" if ext == ".xlsx" else "xlrd"
            workbook = pd.ExcelFile(path, engine=engine)
            sheet_names = workbook.sheet_names
            active_sheet = sheet_names[0] if sheet_names else None
            df = workbook.parse(sheet_name=active_sheet)
            return df, {
                "sheet_names": sheet_names,
                "active_sheet": active_sheet,
            }

        raise ValueError(f"Unknown extension: {ext}")

    def _build_summary(self, df: pd.DataFrame, file_id: str, filename: str, sem_map: dict | None = None) -> dict[str, Any]:
        """Build column summary metadata with semantic understanding."""
        sample = df.head(10).fillna("").to_dict(orient="records")
        for row in sample:
            for k, v in row.items():
                if hasattr(v, "item"):
                    row[k] = v.item()
                elif not isinstance(v, (str, int, float, bool, type(None))):
                    row[k] = str(v)

        null_counts = df.isnull().sum().to_dict()
        col_info = []
        for col in df.columns:
            lbl = clean_header_to_label(col)
            meta = sem_map.get(str(col)) if sem_map else None
            col_info.append(
                {
                    "name": col,
                    "label": meta.get("label", lbl) if meta else lbl,
                    "dtype": str(df[col].dtype),
                    "semantic_type": meta.get("semantic_type", infer_semantic_type(col, df[col])) if meta else infer_semantic_type(col, df[col]),
                    "inferred_meaning": meta.get("inferred_meaning", "Numerical metric column.") if meta else "Numerical metric column.",
                    "confidence": meta.get("confidence", 0.6) if meta else 0.6,
                    "aliases": meta.get("aliases", []) if meta else [],
                    "null_count": int(null_counts.get(col, 0)),
                    "unique_count": int(df[col].nunique()),
                    "sample_values": [str(v) for v in df[col].dropna().head(3).tolist()],
                }
            )

        return {
            "file_id": file_id,
            "filename": filename,
            "row_count": len(df),
            "column_count": len(df.columns),
            "columns": col_info,
            "sample_data": sample,
            "file_size_kb": round(df.memory_usage(deep=True).sum() / 1024, 1),
        }

    async def process_upload(self, upload: UploadFile) -> dict[str, Any]:
        """Process an uploaded file: validate, parse, cache, register in DuckDB, and run insights profiling."""
        filename = upload.filename or "unknown"
        ext = self._validate_extension(filename)

        raw = await upload.read()
        if len(raw) > MAX_FILE_SIZE_BYTES:
            raise ValueError(
                f"File too large ({len(raw) // (1024 * 1024)}MB). Max: {MAX_FILE_SIZE_BYTES // (1024 * 1024)}MB"
            )
        self._validate_magic(raw, ext)

        file_id = str(uuid.uuid4())[:8]
        save_path = UPLOAD_DIR / f"{file_id}{ext}"
        save_path.write_bytes(raw)

        try:
            df, metadata = self._read_file(save_path, ext, len(raw))
        except Exception as e:
            save_path.unlink(missing_ok=True)
            raise ValueError(f"Could not parse file: {e}")

        # Generate automated insights profiling
        table_name = f"file_{file_id.replace('-', '_')}"
        try:
            insights_list = await generate_insights(df, table_name=table_name)
            metadata["insights"] = insights_list
        except Exception as e:
            logger.warning(f"Could not generate upload insights: {e}")
            metadata["insights"] = []

        # Run semantic mapping profiling
        try:
            sem_map = await profile_columns_semantically(df, table_name=table_name)
            metadata["semantic_map"] = sem_map
        except Exception as e:
            logger.warning(f"Could not profile columns semantically: {e}")
            sem_map = {}

        record = FileRecord(file_id, filename, df, save_path, metadata=metadata)
        self._cache[file_id] = record
        self._store.register_dataframe(record.table_name, df)

        logger.info("Processed '%s' -> file_id=%s, %s rows", filename, file_id, len(df))
        summary = self._build_summary(df, file_id, filename, sem_map=sem_map)
        summary["metadata"] = metadata
        return summary

    def get_record(self, file_id: str) -> FileRecord | None:
        return self._cache.get(file_id)

    def get_dataframe(self, file_id: str) -> pd.DataFrame | None:
        record = self._cache.get(file_id)
        return record.df if record else None

    def get_table_name(self, file_id: str) -> str | None:
        record = self._cache.get(file_id)
        return record.table_name if record else None

    def get_preview_data(self, file_id: str, limit: int = 200) -> dict[str, Any] | None:
        record = self._cache.get(file_id)
        if record is None:
            return None

        df = record.df.head(limit).copy()
        rows = df.fillna("").to_dict(orient="records")
        for idx, row in enumerate(rows):
            row["_row_index"] = idx
            for key, value in row.items():
                if hasattr(value, "item"):
                    row[key] = value.item()
                elif not isinstance(value, (str, int, float, bool, type(None))):
                    row[key] = str(value)

        return {
            "file_id": record.file_id,
            "filename": record.filename,
            "row_count": len(record.df),
            "column_count": len(record.df.columns),
            "columns": [
                {
                    "name": col,
                    "label": clean_header_to_label(col),
                    "dtype": str(record.df[col].dtype),
                    "semantic_type": infer_semantic_type(col, record.df[col]),
                    "null_count": int(record.df[col].isnull().sum()),
                    "unique_count": int(record.df[col].nunique()),
                }
                for col in record.df.columns
            ],
            "sample_data": rows,
            "metadata": record.metadata,
        }

    def apply_edits(self, file_id: str, edits: list[dict[str, Any]]) -> dict[str, Any] | None:
        record = self._cache.get(file_id)
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

            df.at[row_index, column] = self._coerce_value(df[column], edit.get("value"))
            applied += 1

        record.df = df
        self._store.register_dataframe(record.table_name, df)
        logger.info("Applied %s edit(s) to '%s'", applied, record.filename)
        return {
            "success": True,
            "applied": applied,
            "preview": self.get_preview_data(file_id),
        }

    async def apply_transform(self, file_id: str, action: dict, description: str) -> dict[str, Any] | None:
        """Apply a declarative pandas transformation to a loaded file, saving the state to Undo stack and re-running profiling."""
        record = self._cache.get(file_id)
        if record is None:
            return None

        # Push state to Undo Stack first
        record.push_state(description)

        # Apply transformation
        try:
            new_df = execute_transform(record.df, action)
            record.df = new_df
        except Exception as e:
            # Rollback stack immediately on failure
            record.undo()
            raise ValueError(f"Transformation failed: {e}")

        # Update metadata applied workflows
        if "applied_workflows" not in record.metadata:
            record.metadata["applied_workflows"] = []
        record.metadata["applied_workflows"].append({
            "action": action,
            "description": description,
            "timestamp": time.time()
        })

        # Register in DuckDB
        self._store.register_dataframe(record.table_name, record.df)

        # Regenerate automated insights and semantic map
        try:
            insights_list = await generate_insights(record.df, table_name=record.table_name)
            record.metadata["insights"] = insights_list
        except Exception as e:
            logger.warning(f"Could not regenerate insights after transform: {e}")

        try:
            sem_map = await profile_columns_semantically(record.df, table_name=record.table_name)
            record.metadata["semantic_map"] = sem_map
        except Exception as e:
            logger.warning(f"Could not regenerate semantic map after transform: {e}")

        logger.info("Successfully applied transform '%s' to '%s'", description, record.filename)
        return {
            "success": True,
            "description": description,
            "history_count": len(record.history),
            "preview": self.get_preview_data(file_id),
        }

    async def undo_transform(self, file_id: str) -> dict[str, Any] | None:
        """Undo the last declarative transformation from the FileRecord stack, restoring specifications."""
        record = self._cache.get(file_id)
        if record is None:
            return None

        description = record.undo()
        if description is None:
            raise ValueError("No changes in the undo stack")

        # Update applied workflows list in metadata
        if "applied_workflows" in record.metadata and record.metadata["applied_workflows"]:
            record.metadata["applied_workflows"].pop()

        # Re-register restored df in DuckDB
        self._store.register_dataframe(record.table_name, record.df)

        # Re-profile insights
        try:
            insights_list = await generate_insights(record.df, table_name=record.table_name)
            record.metadata["insights"] = insights_list
        except Exception as e:
            logger.warning(f"Could not regenerate insights after undo: {e}")

        try:
            sem_map = await profile_columns_semantically(record.df, table_name=record.table_name)
            record.metadata["semantic_map"] = sem_map
        except Exception as e:
            logger.warning(f"Could not profile columns after undo: {e}")

        logger.info("Successfully rolled back last transform ('%s') on '%s'", description, record.filename)
        return {
            "success": True,
            "undone_description": description,
            "history_count": len(record.history),
            "preview": self.get_preview_data(file_id),
        }

    def _coerce_value(self, series: pd.Series, raw_value: Any) -> Any:
        if raw_value == "":
            raw_value = None

        if pd.api.types.is_integer_dtype(series.dtype):
            if raw_value is None:
                return np.nan
            return int(float(raw_value))
        if pd.api.types.is_float_dtype(series.dtype):
            if raw_value is None:
                return np.nan
            return float(raw_value)
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
            if raw_value is None:
                return pd.NaT
            return pd.to_datetime(raw_value)
        return raw_value

    def list_files(self) -> list[dict[str, Any]]:
        return [
            {
                "file_id": r.file_id,
                "filename": r.filename,
                "table_name": r.table_name,
                "row_count": len(r.df),
                "column_count": len(r.df.columns),
                "columns": list(r.df.columns),
                "metadata": r.metadata,
                "uploaded_at": r.uploaded_at,
            }
            for r in self._cache.values()
        ]

    async def switch_sheet(self, file_id: str, sheet_name: str) -> dict[str, Any] | None:
        """Load a different sheet from the same Excel file into DuckDB, triggering auto-insights."""
        record = self._cache.get(file_id)
        if record is None:
            return None
        sheet_names = record.metadata.get("sheet_names", [])
        if sheet_name not in sheet_names:
            raise ValueError(f"Sheet '{sheet_name}' not found. Available: {sheet_names}")
        ext = record.path.suffix.lower()
        engine = "openpyxl" if ext == ".xlsx" else "xlrd"
        df = pd.ExcelFile(record.path, engine=engine).parse(sheet_name=sheet_name)
        record.df = df
        record.metadata["active_sheet"] = sheet_name

        # Regenerate automated insights profiling
        try:
            insights_list = await generate_insights(df, table_name=record.table_name)
            record.metadata["insights"] = insights_list
        except Exception as e:
            logger.warning(f"Could not generate sheet insights: {e}")
            record.metadata["insights"] = []

        # Run semantic mapping profiling
        try:
            sem_map = await profile_columns_semantically(df, table_name=record.table_name)
            record.metadata["semantic_map"] = sem_map
        except Exception as e:
            logger.warning(f"Could not profile sheet columns: {e}")
            sem_map = {}

        self._store.register_dataframe(record.table_name, df)
        logger.info("Switched '%s' to sheet '%s' (%s rows)", record.filename, sheet_name, len(df))
        return self._build_summary(df, file_id, record.filename, sem_map=sem_map)

    def rename_file(self, file_id: str, new_name: str) -> bool:
        """Rename a loaded file (display name only, not disk)."""
        record = self._cache.get(file_id)
        if record is None:
            return False
        record.filename = new_name.strip()
        logger.info("Renamed file %s to '%s'", file_id, record.filename)
        return True

    def delete_file(self, file_id: str) -> bool:
        """Delete a file from cache, disk, and DuckDB."""
        record = self._cache.pop(file_id, None)
        if record is None:
            return False
        # Remove from disk
        if record.path and record.path.exists():
            try:
                record.path.unlink(missing_ok=True)
            except Exception as e:
                logger.warning(f"Could not delete physical file: {e}")
        # Drop from store
        try:
            self._store.drop_table(record.table_name)
        except Exception as e:
            logger.warning(f"Could not drop table for deleted file: {e}")
        logger.info(f"Deleted file {file_id} ({record.filename})")
        return True

    async def reload_from_disk(self) -> int:
        """On startup, reload any files persisted in the uploads directory and regenerate insights if missing."""
        loaded = 0
        for path in sorted(UPLOAD_DIR.glob("*")):
            ext = path.suffix.lower()
            if ext not in ALLOWED_EXTENSIONS:
                continue
            file_id = path.stem
            if file_id in self._cache:
                continue
            try:
                df, metadata = self._read_file(path, ext, path.stat().st_size)
                table_name = f"file_{file_id.replace('-', '_')}"
                # If we don't have insights yet, let's load/generate them!
                if "insights" not in metadata:
                    try:
                        insights_list = await generate_insights(df, table_name=table_name)
                        metadata["insights"] = insights_list
                    except Exception as e:
                        logger.warning(f"Could not generate reload insights: {e}")
                        metadata["insights"] = []

                # If we don't have semantic map yet, let's generate it!
                if "semantic_map" not in metadata:
                    try:
                        sem_map = await profile_columns_semantically(df, table_name=table_name)
                        metadata["semantic_map"] = sem_map
                    except Exception as e:
                        logger.warning(f"Could not generate reload semantic map: {e}")

                orig_name = path.name
                record = FileRecord(file_id, orig_name, df, path, metadata=metadata)
                self._cache[file_id] = record
                self._store.register_dataframe(record.table_name, df)
                loaded += 1
                logger.info("Reloaded persisted file: %s (%s rows)", orig_name, len(df))
            except Exception as e:
                logger.warning("Could not reload %s: %s", path.name, e)
        return loaded

    def resolve_template_column(self, df: pd.DataFrame, target_col: str, semantic_map: dict | None) -> tuple[str, float]:
        """
        Resolve template column targeting. Falls back to semantic aliases if the exact column is missing.
        Returns: (resolved_column_name, confidence_score)
        """
        # 1. Exact case-sensitive match (100% confidence)
        if target_col in df.columns:
            return target_col, 1.0

        # 2. Case-insensitive match (99% confidence)
        for col in df.columns:
            if col.lower() == target_col.lower():
                return col, 0.99

        # 3. Check semantic map generated by Phase 2 (Data Understanding Layer)
        if semantic_map:
            best_col = None
            best_conf = 0.0

            for col, meta in semantic_map.items():
                if col not in df.columns:
                    continue

                # Check label, semantic type, or inferred meaning
                sem_type = str(meta.get("semantic_type", "")).lower()
                label = str(meta.get("label", "")).lower()
                inferred = str(meta.get("inferred_meaning", "")).lower()
                confidence = float(meta.get("confidence", 0.6))

                # Match criteria
                if target_col.lower() in (sem_type, label) or target_col.lower() in inferred:
                    if confidence > best_conf:
                        best_conf = confidence
                        best_col = col

            if best_col and best_conf > 0.0:
                return best_col, best_conf

        # 4. Unresolved column
        return target_col, 0.0

    def resolve_step_columns(self, df: pd.DataFrame, step: dict, semantic_map: dict | None, overrides: dict[str, str] | None) -> tuple[dict, list[dict]]:
        """Resolve all column references inside a pipeline step dictionary."""
        import copy
        resolved_step = copy.deepcopy(step)
        resolutions = []

        # Resolve "column" key
        if "column" in step and isinstance(step["column"], str):
            orig_col = step["column"]
            if overrides and orig_col in overrides:
                resolved_col = overrides[orig_col]
                conf = 1.0
            else:
                resolved_col, conf = self.resolve_template_column(df, orig_col, semantic_map)
            
            resolved_step["column"] = resolved_col
            resolutions.append({
                "template_col": orig_col,
                "resolved_col": resolved_col,
                "confidence": conf
            })

        # Resolve "target" key
        if "target" in step and isinstance(step["target"], str):
            orig_col = step["target"]
            if overrides and orig_col in overrides:
                resolved_col = overrides[orig_col]
                conf = 1.0
            else:
                resolved_col, conf = self.resolve_template_column(df, orig_col, semantic_map)
            
            resolved_step["target"] = resolved_col
            resolutions.append({
                "template_col": orig_col,
                "resolved_col": resolved_col,
                "confidence": conf
            })

        # Resolve "columns" list key
        if "columns" in step and isinstance(step["columns"], list):
            resolved_cols = []
            for orig_col in step["columns"]:
                if not isinstance(orig_col, str):
                    resolved_cols.append(orig_col)
                    continue
                if overrides and orig_col in overrides:
                    resolved_col = overrides[orig_col]
                    conf = 1.0
                else:
                    resolved_col, conf = self.resolve_template_column(df, orig_col, semantic_map)
                
                resolved_cols.append(resolved_col)
                resolutions.append({
                    "template_col": orig_col,
                    "resolved_col": resolved_col,
                    "confidence": conf
                })
            resolved_step["columns"] = resolved_cols

        return resolved_step, resolutions

    async def apply_template(
        self,
        file_id: str,
        template_id: str,
        steps: list[dict],
        mapping_overrides: dict[str, str] | None = None
    ) -> dict[str, Any] | None:
        """Resolve AI-adaptive column mappings, check 85% confidence gates, and run either synchronously or asynchronously."""
        record = self._cache.get(file_id)
        if record is None:
            return None

        # 1. Profile dataset size/step count for Asynchronous Gateway
        row_count = len(record.df)
        steps_count = len(steps)
        is_large = row_count > 10000 or steps_count > 5

        # 2. Deep-copy steps to guarantee IMMUTABLE STATE SEPARATION
        import copy
        pipeline_steps = copy.deepcopy(steps)

        # 3. Resolve columns for each step & check 85% confidence gate
        semantic_map = record.metadata.get("semantic_map")
        resolved_steps = []
        all_resolutions = []
        failed_mappings = []

        for step in pipeline_steps:
            resolved_step, resolutions = self.resolve_step_columns(
                record.df, step, semantic_map, mapping_overrides
            )
            resolved_steps.append(resolved_step)
            all_resolutions.extend(resolutions)

        # Filter out unique failed mappings
        seen_failed = set()
        for res in all_resolutions:
            if res["confidence"] < 0.85:
                t_col = res["template_col"]
                if t_col not in seen_failed:
                    seen_failed.add(t_col)
                    failed_mappings.append({
                        "template_col": t_col,
                        "suggestions": list(record.df.columns)
                    })

        if failed_mappings:
            raise ColumnMappingError(failed_mappings, list(record.df.columns))

        # 4. Handle Async queue or Sync execution
        if is_large:
            task_id = str(uuid.uuid4())[:8]
            record.metadata["async_task"] = {
                "task_id": task_id,
                "template_id": template_id,
                "status": "processing",
                "progress": 0,
                "error": None
            }
            # Start background execution
            asyncio.create_task(
                self._execute_template_background(
                    file_id, task_id, template_id, resolved_steps
                )
            )
            return {
                "success": True,
                "status": "processing",
                "task_id": task_id,
                "message": "Template execution queued asynchronously due to dataset size."
            }

        # Sync execution
        return await self._execute_template_sync(file_id, template_id, resolved_steps)

    async def _execute_template_sync(
        self,
        file_id: str,
        template_id: str,
        resolved_steps: list[dict]
    ) -> dict[str, Any]:
        """Synchronously execute each step of the resolved template steps, registering in DuckDB and profiling insights."""
        record = self._cache.get(file_id)
        
        # Save a single unified undo state before template run
        record.push_state(f"Apply Template workflow: {template_id}")

        from core.transform_engine import execute_transform
        
        # Execute each step sequentially
        df = record.df
        for step in resolved_steps:
            df = execute_transform(df, step)
            
        record.df = df
        
        # Add to applied workflows
        if "applied_workflows" not in record.metadata:
            record.metadata["applied_workflows"] = []
            
        # Append as a single block
        record.metadata["applied_workflows"].append({
            "template_id": template_id,
            "steps": resolved_steps,
            "timestamp": time.time()
        })

        # Register in DuckDB
        self._store.register_dataframe(record.table_name, record.df)

        # Regenerate automated insights and semantic map
        try:
            insights_list = await generate_insights(record.df, table_name=record.table_name)
            record.metadata["insights"] = insights_list
        except Exception as e:
            logger.warning(f"Could not regenerate insights after template: {e}")

        try:
            sem_map = await profile_columns_semantically(record.df, table_name=record.table_name)
            record.metadata["semantic_map"] = sem_map
        except Exception as e:
            logger.warning(f"Could not profile columns after template: {e}")

        return {
            "success": True,
            "status": "completed",
            "history_count": len(record.history),
            "preview": self.get_preview_data(file_id)
        }

    async def _execute_template_background(
        self,
        file_id: str,
        task_id: str,
        template_id: str,
        resolved_steps: list[dict]
    ):
        """Asynchronously execute template steps in the background for large datasets, providing reactive progress states."""
        record = self._cache.get(file_id)
        if not record:
            return
            
        try:
            # Sleep slightly to let the route return first
            await asyncio.sleep(0.5)
            
            # Save undo state
            record.push_state(f"Apply Template workflow (Async): {template_id}")
            
            from core.transform_engine import execute_transform
            
            df = record.df
            total_steps = len(resolved_steps)
            for idx, step in enumerate(resolved_steps):
                df = execute_transform(df, step)
                
                # Update progress
                record.metadata["async_task"]["progress"] = int((idx + 1) / total_steps * 100)
                
            record.df = df
            
            # Append applied workflow as a single block
            if "applied_workflows" not in record.metadata:
                record.metadata["applied_workflows"] = []
            record.metadata["applied_workflows"].append({
                "template_id": template_id,
                "steps": resolved_steps,
                "timestamp": time.time()
            })

            # Register in DuckDB
            self._store.register_dataframe(record.table_name, record.df)

            # Regenerate insights and semantic map
            insights_list = await generate_insights(record.df, table_name=record.table_name)
            record.metadata["insights"] = insights_list
            
            sem_map = await profile_columns_semantically(record.df, table_name=record.table_name)
            record.metadata["semantic_map"] = sem_map

            # Mark completed
            record.metadata["async_task"]["status"] = "completed"
            record.metadata["async_task"]["progress"] = 100
            
            logger.info("Successfully completed async template run '%s' on '%s'", template_id, record.filename)
            
        except Exception as e:
            logger.exception("Failed to run template asynchronously: %s", e)
            record.metadata["async_task"]["status"] = "failed"
            record.metadata["async_task"]["error"] = str(e)
            # rollback
            record.undo()


_manager: FileManager | None = None


def get_file_manager() -> FileManager:
    global _manager
    if _manager is None:
        _manager = FileManager()
    return _manager
