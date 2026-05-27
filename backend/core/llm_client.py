"""
llm_client.py — Multi-provider LLM client.
Supports: Gemini, OpenAI, Claude, Ollama (local).
Provider is selected via LLM_PROVIDER env var or set at runtime via set_provider().
"""
import asyncio
import logging
import os
from abc import ABC, abstractmethod
from typing import AsyncGenerator

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("datapilot.llm_client")

# ── Runtime state (can be changed via /provider API) ─────────────────────────
_active_provider: str = os.getenv("LLM_PROVIDER", "ollama").lower()
_runtime_keys: dict[str, str] = {}  # keys set via API at runtime


def get_active_provider() -> str:
    return _active_provider


def set_active_provider(provider: str, api_key: str | None = None) -> None:
    global _active_provider, _llm_instance
    _active_provider = provider.lower()
    if api_key:
        _runtime_keys[provider.lower()] = api_key
    _llm_instance = None  # reset singleton
    logger.info(f"LLM provider switched to: {_active_provider}")


# ── Base interface ────────────────────────────────────────────────────────────
class BaseLLMProvider(ABC):
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system: str = "",
        json_mode: bool = False,
        temperature: float | None = None,
    ) -> str:
        ...

    @abstractmethod
    async def stream(self, prompt: str, system: str = "") -> AsyncGenerator[str, None]:
        ...

    @abstractmethod
    async def is_online(self) -> bool:
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        ...


# ── Gemini ────────────────────────────────────────────────────────────────────
class GeminiProvider(BaseLLMProvider):
    name = "gemini"
    API_URL = "https://generativelanguage.googleapis.com/v1beta/{model}:generateContent"

    def __init__(self):
        self._api_key = (
            _runtime_keys.get("gemini")
            or os.getenv("GEMINI_API_KEY", "")
        )
        self._model_name = os.getenv("GEMINI_MODEL", "models/gemini-2.5-flash")

    async def is_online(self) -> bool:
        if not self._api_key:
            return False

        import httpx

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://generativelanguage.googleapis.com/v1beta/models",
                    params={"key": self._api_key, "pageSize": 1},
                )
                resp.raise_for_status()
                return True
        except Exception as e:
            logger.warning("Gemini online check failed: %s", self._format_error(e))
            return False

    # Known working models to try in order if configured one fails
    FALLBACK_MODELS = [
        "models/gemini-2.5-flash",
        "models/gemini-2.0-flash",
        "models/gemini-2.0-flash-lite",
        "models/gemini-flash-latest",
    ]

    def _format_error(self, exc: Exception) -> str:
        msg = str(exc)
        lowered = msg.lower()
        if "429" in msg or "quota" in lowered:
            return "Gemini quota exceeded or billing is not enabled for this API key."
        if "401" in msg or "403" in msg or "api key" in lowered:
            return "Gemini API key was rejected. Check that the key is valid and Gemini API access is enabled."
        if "404" in msg or "not found" in lowered:
            return "Configured Gemini model is unavailable."
        return msg

    async def _call(
        self,
        prompt: str,
        system: str = "",
        temperature: float | None = None,
    ) -> str:
        """Call Gemini REST API directly with httpx — avoids ADC/gRPC issues."""
        import httpx
        contents = []
        if system:
            contents.append({"role": "user", "parts": [{"text": f"{system}\n\n{prompt}"}]})
        else:
            contents.append({"role": "user", "parts": [{"text": prompt}]})

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": 0.1 if temperature is None else temperature,
                "maxOutputTokens": 2048,
            },
        }

        # Try configured model first, then fallbacks
        models_to_try = [self._model_name] + [m for m in self.FALLBACK_MODELS if m != self._model_name]

        async with httpx.AsyncClient(timeout=30) as client:
            for model in models_to_try:
                url = self.API_URL.format(model=model)
                try:
                    resp = await client.post(url, json=payload, params={"key": self._api_key})
                    if resp.status_code == 404:
                        logger.warning(f"Gemini model '{model}' not found, trying next...")
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    if model != self._model_name:
                        logger.info(f"Using fallback Gemini model: {model}")
                        self._model_name = model  # cache working model
                    return data["candidates"][0]["content"]["parts"][0]["text"]
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 404:
                        continue
                    raise
            raise RuntimeError(f"No working Gemini model found. Tried: {models_to_try}")


    async def generate(
        self,
        prompt: str,
        system: str = "",
        json_mode: bool = False,
        temperature: float | None = None,
    ) -> str:
        try:
            return await self._call(prompt, system, temperature=temperature)
        except Exception as e:
            message = self._format_error(e)
            logger.error("Gemini generate error: %s", message)
            return f"[Gemini error: {message}]"

    async def stream(self, prompt: str, system: str = "") -> AsyncGenerator[str, None]:
        """Gemini streaming via SSE REST endpoint."""
        import httpx, json as _json
        contents = []
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        contents.append({"role": "user", "parts": [{"text": full_prompt}]})
        payload = {"contents": contents, "generationConfig": {"temperature": 0.7, "maxOutputTokens": 2048}}
        # Build streaming URL: replace :generateContent with :streamGenerateContent
        stream_url = (
            "https://generativelanguage.googleapis.com/v1beta/"
            + self._model_name
            + ":streamGenerateContent"
        )

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                async with client.stream(
                    "POST", stream_url, json=payload,
                    params={"key": self._api_key, "alt": "sse"}
                ) as resp:
                    async for line in resp.aiter_lines():
                        if line.startswith("data: "):
                            try:
                                chunk = _json.loads(line[6:])
                                text = chunk["candidates"][0]["content"]["parts"][0]["text"]
                                if text:
                                    yield text
                            except Exception:
                                pass
        except Exception as e:
            logger.error("Gemini stream error: %s", self._format_error(e))
            # Fallback to non-streaming
            try:
                result = await self._call(prompt, system)
                yield result
            except Exception as e2:
                yield f"[Gemini error: {self._format_error(e2)}]"



# ── OpenAI ────────────────────────────────────────────────────────────────────
class OpenAIProvider(BaseLLMProvider):
    name = "openai"

    def __init__(self):
        self._api_key = (
            _runtime_keys.get("openai")
            or os.getenv("OPENAI_API_KEY", "")
        )
        self._model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    def _get_client(self):
        from openai import AsyncOpenAI
        return AsyncOpenAI(api_key=self._api_key)

    async def is_online(self) -> bool:
        return bool(self._api_key)

    async def generate(
        self,
        prompt: str,
        system: str = "",
        json_mode: bool = False,
        temperature: float | None = None,
    ) -> str:
        try:
            client = self._get_client()
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            kwargs = {"model": self._model, "messages": messages}
            if temperature is not None:
                kwargs["temperature"] = temperature
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            resp = await client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"OpenAI generate error: {e}")
            return ""

    async def stream(self, prompt: str, system: str = "") -> AsyncGenerator[str, None]:
        try:
            client = self._get_client()
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            async with client.chat.completions.stream(
                model=self._model, messages=messages
            ) as stream:
                async for chunk in stream:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        yield delta
        except Exception as e:
            logger.error(f"OpenAI stream error: {e}")
            yield f"[OpenAI error: {e}]"


# ── Anthropic Claude ──────────────────────────────────────────────────────────
class ClaudeProvider(BaseLLMProvider):
    name = "claude"

    def __init__(self):
        self._api_key = (
            _runtime_keys.get("claude")
            or os.getenv("ANTHROPIC_API_KEY", "")
        )
        self._model = os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-20241022")

    def _get_client(self):
        import anthropic
        return anthropic.AsyncAnthropic(api_key=self._api_key)

    async def is_online(self) -> bool:
        return bool(self._api_key)

    async def generate(
        self,
        prompt: str,
        system: str = "",
        json_mode: bool = False,
        temperature: float | None = None,
    ) -> str:
        try:
            client = self._get_client()
            kwargs = {
                "model": self._model,
                "max_tokens": 2048,
                "messages": [{"role": "user", "content": prompt}],
            }
            if temperature is not None:
                kwargs["temperature"] = temperature
            if system:
                kwargs["system"] = system
            resp = await client.messages.create(**kwargs)
            return resp.content[0].text or ""
        except Exception as e:
            logger.error(f"Claude generate error: {e}")
            return ""

    async def stream(self, prompt: str, system: str = "") -> AsyncGenerator[str, None]:
        try:
            client = self._get_client()
            kwargs = {
                "model": self._model,
                "max_tokens": 2048,
                "messages": [{"role": "user", "content": prompt}],
            }
            if system:
                kwargs["system"] = system
            async with client.messages.stream(**kwargs) as stream:
                async for text in stream.text_stream:
                    yield text
        except Exception as e:
            logger.error(f"Claude stream error: {e}")
            yield f"[Claude error: {e}]"


# ── Ollama (local) ────────────────────────────────────────────────────────────
class OllamaProvider(BaseLLMProvider):
    name = "ollama"
    PREFERRED_MODELS = ["llama3.1:8b", "llama3:8b", "mistral:7b", "phi3:mini", "phi3"]
    STUB_RESPONSE = '{"intent": "general", "confidence": 0.0}'

    def __init__(self):
        self._base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self._model: str | None = None

    async def _get_best_model(self) -> str | None:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                r = await client.get(f"{self._base_url}/api/tags")
                if r.status_code == 200:
                    names = [m["name"] for m in r.json().get("models", [])]
                    for preferred in self.PREFERRED_MODELS:
                        if any(preferred in n for n in names):
                            return next(n for n in names if preferred in n)
                    return names[0] if names else None
        except Exception as e:
            logger.warning(f"Could not list Ollama models: {e}")
        return None

    async def is_online(self) -> bool:
        model = await self._get_best_model()
        return model is not None

    async def generate(
        self,
        prompt: str,
        system: str = "",
        json_mode: bool = False,
        temperature: float | None = None,
    ) -> str:
        import httpx
        model = self._model or await self._get_best_model()
        if not model:
            logger.warning("Ollama offline or no model available - returning stub")
            return self.STUB_RESPONSE
        self._model = model
        payload = {
            "model": model,
            "prompt": prompt,
            "system": system,
            "stream": False,
        }
        if temperature is not None:
            payload["options"] = {"temperature": temperature}
        if json_mode:
            payload["format"] = "json"
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(f"{self._base_url}/api/generate", json=payload)
                return r.json().get("response", "")
        except Exception as e:
            logger.error(f"Ollama generate error: {e}")
            return self.STUB_RESPONSE

    async def stream(self, prompt: str, system: str = "") -> AsyncGenerator[str, None]:
        import httpx, json
        model = self._model or await self._get_best_model()
        if not model:
            yield "I need Ollama running to answer that. Start Ollama or switch to a cloud provider."
            return
        self._model = model
        payload = {"model": model, "prompt": prompt, "system": system, "stream": True}
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                async with client.stream("POST", f"{self._base_url}/api/generate", json=payload) as r:
                    async for line in r.aiter_lines():
                        if line:
                            token = json.loads(line).get("response", "")
                            if token:
                                yield token
        except Exception as e:
            logger.error(f"Ollama stream error: {e}")
            yield f"[Ollama error: {e}]"


# ── Factory & singleton ───────────────────────────────────────────────────────
_PROVIDERS: dict[str, type[BaseLLMProvider]] = {
    "gemini": GeminiProvider,
    "openai": OpenAIProvider,
    "claude": ClaudeProvider,
    "ollama": OllamaProvider,
}

_llm_instance: BaseLLMProvider | None = None


def get_llm_client() -> BaseLLMProvider:
    global _llm_instance
    if _llm_instance is None:
        provider_cls = _PROVIDERS.get(_active_provider, OllamaProvider)
        _llm_instance = provider_cls()
        logger.info(f"LLM client initialized: {_active_provider}")
    return _llm_instance
