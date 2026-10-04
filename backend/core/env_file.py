"""Load ``backend/.env`` for local runs (``python main.py``, ``python worker.py``).

This must run before any ``core`` module reads configuration at import time
(``core.auth`` refuses to import without ``JWT_SECRET``).  Real environment
variables always win (``override=False``), so container and production
deployments that inject env vars are unaffected; the file is optional.
"""

from __future__ import annotations

from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def load_local_env() -> bool:
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - python-dotenv is a pinned dependency
        return False
    if not ENV_FILE.is_file():
        return False
    return bool(load_dotenv(ENV_FILE, override=False))
