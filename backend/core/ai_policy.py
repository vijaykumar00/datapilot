"""
ai_policy.py — whether a workspace's data may be sent to an AI service.

A workspace owner or admin can turn AI off ("never send my data to AI").  Every
AI client is built through ``client_for_workspace``; when AI is off it returns a
``DisabledLLM`` whose calls raise ``AIDisabledError`` before any network request,
so no code path can send data by accident.  Tallis's own question engine and the
saved-query cache keep working because they never call an AI service.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from core.llm_client import LLMConfigError

logger = logging.getLogger("datapilot.ai_policy")

AI_OFF_MESSAGE = (
    "AI is turned off for this workspace, so nothing is sent to an AI service. Tallis can still answer direct "
    "questions with its built-in engine, for example “total revenue by region” or “top 5 products by sales”. "
    "A workspace admin can turn AI on in Settings → Privacy."
)


class AIDisabledError(LLMConfigError):
    """Raised instead of calling an AI service for a workspace with AI turned off."""

    def __init__(self, message: str = AI_OFF_MESSAGE):
        super().__init__(message)


@dataclass(frozen=True)
class _OffSettings:
    provider: str = "off"
    model: str = ""
    api_key: str = ""
    configured: bool = False


class DisabledLLM:
    """Stands in for an AI client when AI is off (or not set up); it never makes a request."""

    settings = _OffSettings()

    def __init__(self, message: str | None = None):
        self._message = message

    def _error(self) -> LLMConfigError:
        return AIDisabledError() if self._message is None else LLMConfigError(self._message)

    async def generate(self, *args, **kwargs):
        raise self._error()

    async def stream(self, *args, **kwargs):
        raise self._error()
        yield ""  # pragma: no cover - makes this an async generator


def workspace_ai_enabled(workspace_id: str | None) -> bool:
    """Guests (no workspace row) use AI under the guest notice; real workspaces follow their switch."""
    if not workspace_id:
        return True
    from core.db import SessionLocal
    from core.models import Workspace

    db = SessionLocal()
    try:
        row = db.query(Workspace.ai_enabled).filter(Workspace.workspace_id == workspace_id).first()
        return True if row is None else bool(row[0])
    finally:
        db.close()


def client_for_workspace(workspace_id: str | None, build):
    """Return ``build()`` when AI is allowed for the workspace, else a ``DisabledLLM``."""
    if not workspace_ai_enabled(workspace_id):
        return DisabledLLM()
    return build()
