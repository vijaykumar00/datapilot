"""
llm_client.py — Ollama HTTP API wrapper.
Supports streaming, model fallback, and graceful offline degradation.
"""

import asyncio
import json
import logging
from typing import AsyncGenerator

import httpx

logger = logging.getLogger("datapilot.llm_client")

OLLAMA_BASE_URL = "http://localhost:11434"
TIMEOUT_SECONDS = 10

MODEL_PRIORITY = [
    "llama3.1:8b",
    "llama3.1",
    "llama3:8b",
    "llama3",
    "mistral:7b",
    "mistral",
    "phi3:mini",
    "phi3",
    "phi",
]


class LLMClient:
    def __init__(self, base_url: str = OLLAMA_BASE_URL):
        self.base_url = base_url
        self._available_model: str | None = None
        self._ollama_online: bool | None = None

    async def _check_ollama(self) -> bool:
        """Check if Ollama is reachable."""
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                self._ollama_online = resp.status_code == 200
        except Exception:
            self._ollama_online = False
        return self._ollama_online

    async def _get_best_model(self) -> str | None:
        """Return the highest-priority model that is pulled locally."""
        if self._available_model:
            return self._available_model
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                if resp.status_code != 200:
                    return None
                data = resp.json()
                pulled = {m["name"] for m in data.get("models", [])}
                for model in MODEL_PRIORITY:
                    if model in pulled:
                        self._available_model = model
                        logger.info(f"Selected model: {model}")
                        return model
            return None
        except Exception as e:
            logger.warning(f"Could not list Ollama models: {e}")
            return None

    async def generate(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.1,
        json_mode: bool = False,
    ) -> str:
        """Non-streaming generation. Returns full response string."""
        model = await self._get_best_model()
        if not model:
            logger.warning("Ollama offline or no model available — returning stub")
            return self._stub_response(prompt, json_mode)

        payload = {
            "model": model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if json_mode:
            payload["format"] = "json"

        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
                resp = await asyncio.wait_for(
                    client.post(f"{self.base_url}/api/generate", json=payload),
                    timeout=TIMEOUT_SECONDS,
                )
                data = resp.json()
                return data.get("response", "")
        except asyncio.TimeoutError:
            logger.error("LLM generate timed out after 10s")
            return self._stub_response(prompt, json_mode)
        except Exception as e:
            logger.error(f"LLM generate error: {e}")
            return self._stub_response(prompt, json_mode)

    async def stream(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.1,
    ) -> AsyncGenerator[str, None]:
        """Streaming generation — yields text chunks as they arrive."""
        model = await self._get_best_model()
        if not model:
            yield self._stub_response(prompt, False)
            return

        payload = {
            "model": model,
            "prompt": prompt,
            "system": system,
            "stream": True,
            "options": {"temperature": temperature},
        }

        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
                async with client.stream(
                    "POST", f"{self.base_url}/api/generate", json=payload
                ) as response:
                    async for line in response.aiter_lines():
                        if line.strip():
                            try:
                                chunk = json.loads(line)
                                token = chunk.get("response", "")
                                if token:
                                    yield token
                                if chunk.get("done"):
                                    break
                            except json.JSONDecodeError:
                                continue
        except asyncio.TimeoutError:
            logger.error("LLM stream timed out")
            yield "\n[Response timed out after 10s]"
        except Exception as e:
            logger.error(f"LLM stream error: {e}")
            yield f"\n[LLM unavailable: {str(e)}]"

    def _stub_response(self, prompt: str, json_mode: bool) -> str:
        """Fallback when Ollama is offline."""
        if json_mode:
            return json.dumps(
                {
                    "error": "Ollama is not running. Start it with: ollama serve",
                    "intent": "general",
                }
            )
        return (
            "⚠️ Ollama is not running. Start it with `ollama serve` in a terminal. "
            "Download from https://ollama.ai"
        )

    async def is_online(self) -> bool:
        return await self._check_ollama()


# Module-level singleton
_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
