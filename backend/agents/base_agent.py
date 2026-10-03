"""
base_agent.py — Abstract base class for all DataPilot agents.

Agents are constructed per request with:
* a request-scoped LLM client (never a global one),
* the stateless sandboxed query engine,
* the durable file manager and the caller's ``workspace_id`` — every dataset
  lookup is scoped to that workspace.
Blocking work (dataset loads, pandas, DuckDB) runs in worker threads so the
API event loop stays responsive.
"""

import asyncio
import logging
import os
from abc import ABC, abstractmethod
from typing import Any

from core.error_intelligence import diagnose_agent_error, format_for_user
from core.llm_client import LLMConfigError, LLMError

logger = logging.getLogger("datapilot.agent")


def _timeout_env(default: int) -> int:
    try:
        return max(5, int(os.getenv("AGENT_TIMEOUT_SECONDS", str(default))))
    except (TypeError, ValueError):
        return default


AGENT_TIMEOUT = _timeout_env(45)


class AgentResponse:
    """Standard response object returned by every agent."""

    def __init__(
        self,
        type: str,
        content: str,
        chart_data: dict | None = None,
        table_data: list[dict] | None = None,
        metadata: dict | None = None,
        error: str | None = None,
        intelligent_error: dict | None = None,
    ):
        self.type = type
        self.content = content
        self.chart_data = chart_data
        self.table_data = table_data
        self.metadata = metadata or {}
        self.error = error
        self.intelligent_error = intelligent_error

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "content": self.content,
            "chart_data": self.chart_data,
            "table_data": self.table_data,
            "metadata": {
                **self.metadata,
                **({"intelligent_error": self.intelligent_error} if self.intelligent_error else {}),
            },
            "error": self.error,
        }

    @classmethod
    def error_response(cls, message: str, agent_type: str = "error", intelligent_error: dict | None = None,
                       metadata: dict | None = None) -> "AgentResponse":
        return cls(type=agent_type, content=message, error=message, intelligent_error=intelligent_error,
                   metadata=metadata)


class BaseAgent(ABC):
    """Abstract agent. Subclasses implement _execute()."""

    agent_type: str = "base"
    timeout_seconds: int = AGENT_TIMEOUT

    def __init__(self, llm_client=None, data_store=None, file_manager=None, workspace_id: str | None = None):
        self.llm = llm_client
        self.store = data_store
        self.files = file_manager
        self.workspace_id = workspace_id
        self.logger = logging.getLogger(f"datapilot.agent.{self.agent_type}")

    async def run(self, query: str, file_ids: list[str], context: list[dict] | None = None) -> AgentResponse:
        """Public entry point — wraps _execute with timeout and error handling."""
        try:
            return await asyncio.wait_for(self._execute(query, file_ids, context or []), timeout=self.timeout_seconds)
        except asyncio.TimeoutError:
            err = diagnose_agent_error(
                Exception(f"{self.agent_type} agent timed out after {self.timeout_seconds}s"),
                self.agent_type, None, query,
            )
            msg = format_for_user(err)
            self.logger.error(msg)
            return AgentResponse.error_response(msg, self.agent_type, intelligent_error=err)
        except LLMConfigError as exc:
            # ``llm_failure`` tells the caller no result was produced, so the query is not billed.
            return AgentResponse.error_response(str(exc), self.agent_type, metadata={"llm_failure": True})
        except LLMError as exc:
            msg = f"The AI provider could not complete this request ({exc}). No result was generated; please retry."
            return AgentResponse.error_response(msg, self.agent_type, metadata={"llm_failure": True})
        except Exception as e:
            err = diagnose_agent_error(e, self.agent_type, None, query)
            msg = format_for_user(err)
            self.logger.exception(msg)
            return AgentResponse.error_response(msg, self.agent_type, intelligent_error=err)

    @abstractmethod
    async def _execute(self, query: str, file_ids: list[str], context: list[dict]) -> AgentResponse:
        ...

    async def _get_record(self, file_id: str):
        return await asyncio.to_thread(self.files.get_record, file_id, self.workspace_id)

    async def _get_primary_file(self, file_ids: list[str]):
        """Return (file_id, record) for the first accessible file_id."""
        for fid in file_ids:
            record = await self._get_record(fid)
            if record is not None:
                return fid, record
        return None, None

    @staticmethod
    async def cpu(fn, *args, **kwargs):
        """Run blocking pandas/DuckDB work off the event loop."""
        return await asyncio.to_thread(fn, *args, **kwargs)
