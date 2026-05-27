"""
file_manager.py - Upload, parse, cache, and register CSV/Excel files.
Uses chunked reading for large files and an LRU cache for speed.
"""

import logging
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import pandas as pd
from cachetools import LRUCache
from fastapi import UploadFile

from core.data_store import get_store

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

# Upload directory (temp, auto-cleaned on restart)
UPLOAD_DIR = Path(tempfile.gettempdir()) / "datapilot"
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
                chunks = pd.read_csv(path, chunksize=50_000, low_memory=False)
                return pd.concat(chunks, ignore_index=True), {}
            return pd.read_csv(path, low_memory=False), {}

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

    def _build_summary(self, df: pd.DataFrame, file_id: str, filename: str) -> dict[str, Any]:
        """Build column summary metadata."""
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
            col_info.append(
                {
                    "name": col,
                    "dtype": str(df[col].dtype),
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
        """Process an uploaded file: validate, parse, cache, register in DuckDB."""
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

        record = FileRecord(file_id, filename, df, save_path, metadata=metadata)
        self._cache[file_id] = record
        self._store.register_dataframe(record.table_name, df)

        logger.info("Processed '%s' -> file_id=%s, %s rows", filename, file_id, len(df))
        summary = self._build_summary(df, file_id, filename)
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
        for row in rows:
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
                    "dtype": str(record.df[col].dtype),
                    "null_count": int(record.df[col].isnull().sum()),
                    "unique_count": int(record.df[col].nunique()),
                }
                for col in record.df.columns
            ],
            "sample_data": rows,
            "metadata": record.metadata,
        }

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

    def delete_file(self, file_id: str) -> bool:
        record = self._cache.pop(file_id, None)
        if record:
            self._store.drop_table(record.table_name)
            record.path.unlink(missing_ok=True)
            return True
        return False


_manager: FileManager | None = None


def get_file_manager() -> FileManager:
    global _manager
    if _manager is None:
        _manager = FileManager()
    return _manager
