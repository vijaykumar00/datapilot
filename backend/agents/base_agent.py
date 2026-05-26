"""
base_agent.py — Abstract base class for all DataPilot agents.
Enforces 10-second timeout and standard response shape.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger("datapilot.agent")

AGENT_TIMEOUT = 10  # seconds


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
    ):
        self.type = type
        self.content = content
        self.chart_data = chart_data
        self.table_data = table_data
        self.metadata = metadata or {}
        self.error = error

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "content": self.content,
            "chart_data": self.chart_data,
            "table_data": self.table_data,
            "metadata": self.metadata,
            "error": self.error,
        }

    @classmethod
    def error_response(cls, message: str, agent_type: str = "error") -> "AgentResponse":
        return cls(type=agent_type, content=message, error=message)


class BaseAgent(ABC):
    """Abstract agent. Subclasses implement _execute()."""

    agent_type: str = "base"

    def __init__(self, llm_client=None, data_store=None, file_manager=None):
        self.llm = llm_client
        self.store = data_store
        self.files = file_manager
        self.logger = logging.getLogger(f"datapilot.agent.{self.agent_type}")

    async def run(
        self,
        query: str,
        file_ids: list[str],
        context: list[dict] | None = None,
    ) -> AgentResponse:
        """Public entry point — wraps _execute with timeout and error handling."""
        try:
            return await asyncio.wait_for(
                self._execute(query, file_ids, context or []),
                timeout=AGENT_TIMEOUT,
            )
        except asyncio.TimeoutError:
            msg = f"{self.agent_type} agent timed out after {AGENT_TIMEOUT}s"
            self.logger.error(msg)
            return AgentResponse.error_response(msg, self.agent_type)
        except Exception as e:
            msg = f"{self.agent_type} agent failed: {str(e)}"
            self.logger.exception(msg)
            return AgentResponse.error_response(msg, self.agent_type)

    @abstractmethod
    async def _execute(
        self,
        query: str,
        file_ids: list[str],
        context: list[dict],
    ) -> AgentResponse:
        """Implement this in each agent subclass."""
        ...

    def _get_primary_file(self, file_ids: list[str]):
        """Return (file_id, record) for the first valid file_id."""
        for fid in file_ids:
            record = self.files.get_record(fid)
            if record is not None:
                return fid, record
        return None, None
