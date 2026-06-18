"""
storage.py — Abstraction layer for file storage.
Supports local namespaced directory structure and prepares for S3 storage provider swaps.
"""

import logging
import os
import shutil
from abc import ABC, abstractmethod
from pathlib import Path

logger = logging.getLogger("datapilot.storage")

class BaseStorageProvider(ABC):
    """Abstract Base Class for file storage engines."""
    
    @abstractmethod
    def save_file(self, workspace_id: str, dataset_id: str, filename: str, content: bytes) -> tuple[Path, str]:
        """
        Save file content and return local Path and access URI/path string.
        """
        pass

    @abstractmethod
    def read_file(self, workspace_id: str, dataset_id: str, filename: str) -> bytes:
        """
        Read file bytes.
        """
        pass

    @abstractmethod
    def delete_file(self, workspace_id: str, dataset_id: str, filename: str) -> bool:
        """
        Delete a file. Return True if successful.
        """
        pass

    @abstractmethod
    def delete_dataset_dir(self, workspace_id: str, dataset_id: str) -> bool:
        """
        Delete the entire directory associated with a dataset.
        """
        pass


class LocalStorageProvider(BaseStorageProvider):
    """Local disk namespaced storage provider: uploads/{workspace_id}/{dataset_id}/{filename}"""
    
    def __init__(self, base_dir: Path | None = None):
        if base_dir is None:
            self.base_dir = Path(__file__).parent.parent / "uploads"
        else:
            self.base_dir = base_dir
        self.base_dir.mkdir(exist_ok=True, parents=True)

    def _get_target_dir(self, workspace_id: str, dataset_id: str) -> Path:
        target = self.base_dir / workspace_id / dataset_id
        target.mkdir(exist_ok=True, parents=True)
        return target

    def save_file(self, workspace_id: str, dataset_id: str, filename: str, content: bytes) -> tuple[Path, str]:
        target_dir = self._get_target_dir(workspace_id, dataset_id)
        # Avoid file traversal vulnerability by taking Path(filename).name
        safe_filename = Path(filename).name
        target_path = target_dir / safe_filename
        
        target_path.write_bytes(content)
        
        # URI/relative path representation
        uri = f"/uploads/{workspace_id}/{dataset_id}/{safe_filename}"
        logger.info(f"Saved file locally: {uri}")
        return target_path, uri

    def read_file(self, workspace_id: str, dataset_id: str, filename: str) -> bytes:
        safe_filename = Path(filename).name
        target_path = self.base_dir / workspace_id / dataset_id / safe_filename
        if not target_path.exists():
            raise FileNotFoundError(f"File not found: {target_path}")
        return target_path.read_bytes()

    def delete_file(self, workspace_id: str, dataset_id: str, filename: str) -> bool:
        safe_filename = Path(filename).name
        target_path = self.base_dir / workspace_id / dataset_id / safe_filename
        if target_path.exists():
            try:
                target_path.unlink()
                logger.info(f"Deleted local file: {workspace_id}/{dataset_id}/{safe_filename}")
                return True
            except Exception as e:
                logger.error(f"Error deleting local file {target_path}: {e}")
                return False
        return False

    def delete_dataset_dir(self, workspace_id: str, dataset_id: str) -> bool:
        target_dir = self.base_dir / workspace_id / dataset_id
        if target_dir.exists() and target_dir.is_dir():
            try:
                shutil.rmtree(target_dir)
                logger.info(f"Deleted dataset directory: {workspace_id}/{dataset_id}")
                return True
            except Exception as e:
                logger.error(f"Error removing directory {target_dir}: {e}")
                return False
        return False


# Global default storage provider instance
_storage_provider: BaseStorageProvider | None = None

def get_storage_provider() -> BaseStorageProvider:
    global _storage_provider
    if _storage_provider is None:
        _storage_provider = LocalStorageProvider()
    return _storage_provider
