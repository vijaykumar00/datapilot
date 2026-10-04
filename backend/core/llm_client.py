"""
llm_client.py — Request/workspace-scoped multi-provider LLM clients.

There is NO mutable global provider or key.  Every request resolves an
``LLMSettings`` (provider, key, model) for the caller and builds a short-lived
client from it:

* platform default: ``LLM_PROVIDER`` + the matching ``*_API_KEY`` env var
  (required explicitly in production — no silent Ollama fallback);
* per-user preference: ``user_settings.llm_provider`` + the user's own encrypted
  key (``user_api_keys``) or, if the operator configured one, the platform key
  for that provider.

Robustness controls: shared pooled HTTP clients, bounded retries with jittered
exponential backoff for 429/5xx/timeouts, a per-process concurrency limit per
provider, prompt-size caps, typed errors (callers never receive error text as
if it were a model answer) and token-usage callbacks for metering.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
import weakref
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncGenerator, Callable

# Strong references to in-flight metering writes (fire-and-forget executor futures).
_PENDING_USAGE: set = set()

logger = logging.getLogger("datapilot.llm_client")

PROVIDERS = ("gemini", "openai", "claude", "ollama")
KEY_ENV = {"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY", "claude": "ANTHROPIC_API_KEY"}
MODEL_ENV = {
    "gemini": ("GEMINI_MODEL", "models/gemini-2.5-flash"),
    "openai": ("OPENAI_MODEL", "gpt-4o-mini"),
    "claude": ("ANTHROPIC_MODEL", "claude-3-5-haiku-20241022"),
    "ollama": ("OLLAMA_MODEL", ""),
}
PRODUCTION_ENVS = {"production", "prod"}
RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}


class LLMError(RuntimeError):
    def __init__(self, message: str, *, provider: str = "", retryable: bool = False, status: int | None = None):
        super().__init__(message)
        self.provider = provider
        self.retryable = retryable
        self.status = status


class LLMConfigError(LLMError):
    """The caller's provider is not usable (missing key, unknown provider)."""


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    api_key: str = ""
    model: str = ""
    base_url: str = ""
    key_source: str = "platform"  # platform | user | none

    @property
    def configured(self) -> bool:
        return self.provider == "ollama" or bool(self.api_key)


def _is_production() -> bool:
    return os.getenv("APP_ENV", "development").strip().lower() in PRODUCTION_ENVS


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def platform_provider() -> str:
    """Operator-configured default provider.  Production must set it explicitly."""
    raw = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    if not raw:
        if _is_production():
            raise LLMConfigError("LLM_PROVIDER must be set explicitly in production.")
        return "ollama"
    if raw not in PROVIDERS:
        raise LLMConfigError(f"Unsupported LLM_PROVIDER '{raw}'. Choose one of: {', '.join(PROVIDERS)}")
    return raw


def settings_for(provider: str, api_key: str | None = None, key_source: str | None = None) -> LLMSettings:
    provider = provider.lower()
    if provider not in PROVIDERS:
        raise LLMConfigError(f"Unsupported provider '{provider}'.")
    model_env, model_default = MODEL_ENV[provider]
    key = api_key if api_key is not None else os.getenv(KEY_ENV.get(provider, ""), "")
    source = key_source or ("platform" if key or provider == "ollama" else "none")
    return LLMSettings(
        provider=provider,
        api_key=key or "",
        model=os.getenv(model_env, model_default),
        base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434") if provider == "ollama" else "",
        key_source=source,
    )


def platform_settings() -> LLMSettings:
    return settings_for(platform_provider())


def get_active_provider() -> str:
    """Platform default provider name (read-only; kept for existing imports)."""
    try:
        return platform_provider()
    except LLMConfigError:
        return "unconfigured"


# ── Shared HTTP client + concurrency per event loop ───────────────────────────
_http_clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, object]" = weakref.WeakKeyDictionary()
_semaphores: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Semaphore]]" = weakref.WeakKeyDictionary()


def _http():
    import httpx

    loop = asyncio.get_running_loop()
    client = _http_clients.get(loop)
    if client is None or getattr(client, "is_closed", False):
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(_int_env("LLM_TIMEOUT_SECONDS", 60), connect=10),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
        _http_clients[loop] = client
    return client


def _semaphore(provider: str) -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    per_loop = _semaphores.setdefault(loop, {})
    if provider not in per_loop:
        per_loop[provider] = asyncio.Semaphore(_int_env("LLM_MAX_CONCURRENCY", 8))
    return per_loop[provider]


def _cap_prompt(prompt: str) -> str:
    limit = _int_env("LLM_MAX_PROMPT_CHARS", 60_000)
    if len(prompt) <= limit:
        return prompt
    return prompt[:limit] + "\n\n[Input truncated to the configured prompt size limit.]"


UsageCallback = Callable[[str, int], None]


class BaseLLMProvider(ABC):
    name = "base"

    def __init__(self, settings: LLMSettings, usage_callback: UsageCallback | None = None):
        self.settings = settings
        self._usage_cb = usage_callback

    # Public API ---------------------------------------------------------------
    async def generate(
        self,
        prompt: str,
        system: str = "",
        json_mode: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        if not self.settings.configured:
            raise LLMConfigError(f"No API key configured for provider '{self.name}'.", provider=self.name)
        prompt = _cap_prompt(prompt)
        max_tokens = max_tokens or _int_env("LLM_MAX_OUTPUT_TOKENS", 2048)
        return await self._with_retries(
            lambda: self._generate(prompt, system, json_mode, temperature, max_tokens)
        )

    async def stream(self, prompt: str, system: str = "") -> AsyncGenerator[str, None]:
        if not self.settings.configured:
            raise LLMConfigError(f"No API key configured for provider '{self.name}'.", provider=self.name)
        prompt = _cap_prompt(prompt)
        sem = _semaphore(self.name)
        try:
            await asyncio.wait_for(sem.acquire(), timeout=_int_env("LLM_QUEUE_TIMEOUT_SECONDS", 30))
        except asyncio.TimeoutError as exc:
            raise LLMError("AI provider is busy; please retry shortly.", provider=self.name, retryable=True) from exc
        try:
            async for token in self._stream(prompt, system):
                yield token
        finally:
            sem.release()

    async def is_online(self) -> bool:
        """Configuration check only — never a network call on the request path."""
        return self.settings.configured

    # Internals ----------------------------------------------------------------
    def _record_usage(self, tokens: int) -> None:
        try:
            from core.observability import LLM_TOKENS
            LLM_TOKENS.labels(self.name).inc(max(0, tokens))
        except Exception:
            pass
        if self._usage_cb and tokens:
            cb, name, n = self._usage_cb, self.name, int(tokens)

            def _run() -> None:
                try:
                    cb(name, n)
                except Exception as exc:  # metering must never break the request
                    logger.warning("LLM usage callback failed: %s", exc)

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop is None:
                _run()
            else:
                # The metering callback writes to the database.  Never run it on the
                # event loop: under pool pressure it would block the whole process for
                # up to DB_POOL_TIMEOUT_SECONDS (observed in the 250-user staging run).
                fut = loop.run_in_executor(None, _run)
                _PENDING_USAGE.add(fut)
                fut.add_done_callback(_PENDING_USAGE.discard)

    async def _with_retries(self, fn):
        attempts = _int_env("LLM_MAX_RETRIES", 3)
        sem = _semaphore(self.name)
        last_exc: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                await asyncio.wait_for(sem.acquire(), timeout=_int_env("LLM_QUEUE_TIMEOUT_SECONDS", 30))
            except asyncio.TimeoutError as exc:
                raise LLMError("AI provider is busy; please retry shortly.", provider=self.name, retryable=True) from exc
            started = time.monotonic()
            try:
                result = await fn()
                self._observe(started, "ok")
                return result
            except LLMConfigError:
                self._observe(started, "config_error")
                raise
            except LLMError as exc:
                self._observe(started, "error")
                last_exc = exc
                if not exc.retryable or attempt == attempts:
                    raise
            except Exception as exc:  # network/timeouts from SDKs
                self._observe(started, "error")
                last_exc = LLMError(str(exc), provider=self.name, retryable=True)
                if attempt == attempts:
                    raise last_exc from exc
            finally:
                sem.release()
            delay = min(10.0, 0.5 * (2 ** (attempt - 1))) + random.uniform(0, 0.5)
            await asyncio.sleep(delay)
        raise last_exc or LLMError("AI request failed", provider=self.name)

    def _observe(self, started: float, outcome: str) -> None:
        try:
            from core.observability import LLM_LATENCY, LLM_REQUESTS
            LLM_REQUESTS.labels(self.name, outcome).inc()
            LLM_LATENCY.labels(self.name).observe(time.monotonic() - started)
        except Exception:
            pass

    @abstractmethod
    async def _generate(self, prompt, system, json_mode, temperature, max_tokens) -> str: ...

    @abstractmethod
    def _stream(self, prompt: str, system: str) -> AsyncGenerator[str, None]: ...


def _http_error(provider: str, exc) -> LLMError:
    import httpx

    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        msg = {
            401: "API key was rejected.",
            403: "API key is not permitted to use this model.",
            404: "Configured model is unavailable.",
            429: "Rate limit or quota exceeded.",
        }.get(status, f"Provider returned HTTP {status}.")
        return LLMError(f"{provider}: {msg}", provider=provider, retryable=status in RETRYABLE_STATUS, status=status)
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return LLMError(f"{provider}: network error or timeout.", provider=provider, retryable=True)
    return LLMError(f"{provider}: {exc}", provider=provider, retryable=False)


# ── Gemini (REST) ──────────────────────────────────────────────────────────────
class GeminiProvider(BaseLLMProvider):
    name = "gemini"
    BASE = "https://generativelanguage.googleapis.com/v1beta/"

    async def _generate(self, prompt, system, json_mode, temperature, max_tokens) -> str:
        import httpx

        text = f"{system}\n\n{prompt}" if system else prompt
        cfg: dict = {"temperature": 0.1 if temperature is None else temperature, "maxOutputTokens": max_tokens}
        if json_mode:
            cfg["responseMimeType"] = "application/json"
        payload = {"contents": [{"role": "user", "parts": [{"text": text}]}], "generationConfig": cfg}
        try:
            resp = await _http().post(
                f"{self.BASE}{self.settings.model}:generateContent",
                json=payload,
                headers={"x-goog-api-key": self.settings.api_key},
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise _http_error(self.name, exc) from exc
        data = resp.json()
        usage = data.get("usageMetadata") or {}
        self._record_usage(int(usage.get("totalTokenCount") or 0))
        try:
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts)
        except (KeyError, IndexError, TypeError) as exc:
            reason = (data.get("promptFeedback") or {}).get("blockReason") or "empty response"
            raise LLMError(f"gemini: no content returned ({reason}).", provider=self.name) from exc

    async def _stream(self, prompt, system):
        import httpx

        text = f"{system}\n\n{prompt}" if system else prompt
        payload = {
            "contents": [{"role": "user", "parts": [{"text": text}]}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": _int_env("LLM_MAX_OUTPUT_TOKENS", 2048)},
        }
        yielded = False
        try:
            async with _http().stream(
                "POST",
                f"{self.BASE}{self.settings.model}:streamGenerateContent",
                json=payload,
                params={"alt": "sse"},
                headers={"x-goog-api-key": self.settings.api_key},
            ) as resp:
                resp.raise_for_status()
                total = 0
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    try:
                        chunk = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue
                    total = int((chunk.get("usageMetadata") or {}).get("totalTokenCount") or total)
                    for cand in chunk.get("candidates", []):
                        for part in (cand.get("content") or {}).get("parts", []):
                            if part.get("text"):
                                yielded = True
                                yield part["text"]
                self._record_usage(total)
        except httpx.HTTPError as exc:
            raise _http_error(self.name, exc) from exc
        if not yielded:
            raise LLMError("gemini: empty streaming response.", provider=self.name, retryable=True)


# ── OpenAI ─────────────────────────────────────────────────────────────────────
class OpenAIProvider(BaseLLMProvider):
    name = "openai"

    def _client(self):
        from openai import AsyncOpenAI

        return AsyncOpenAI(api_key=self.settings.api_key, max_retries=0, timeout=_int_env("LLM_TIMEOUT_SECONDS", 60))

    @staticmethod
    def _map(exc) -> LLMError:
        status = getattr(exc, "status_code", None)
        retryable = status in RETRYABLE_STATUS or exc.__class__.__name__ in {"APITimeoutError", "APIConnectionError", "RateLimitError"}
        return LLMError(f"openai: {exc.__class__.__name__}", provider="openai", retryable=retryable, status=status)

    async def _generate(self, prompt, system, json_mode, temperature, max_tokens) -> str:
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        kwargs: dict = {"model": self.settings.model, "messages": messages, "max_tokens": max_tokens}
        if temperature is not None:
            kwargs["temperature"] = temperature
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            resp = await self._client().chat.completions.create(**kwargs)
        except Exception as exc:
            raise self._map(exc) from exc
        if resp.usage:
            self._record_usage(int(resp.usage.total_tokens or 0))
        content = resp.choices[0].message.content if resp.choices else None
        if not content:
            raise LLMError("openai: empty response.", provider=self.name, retryable=True)
        return content

    async def _stream(self, prompt, system):
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        try:
            stream = await self._client().chat.completions.create(
                model=self.settings.model, messages=messages, stream=True,
                stream_options={"include_usage": True},
            )
            async for chunk in stream:
                if getattr(chunk, "usage", None):
                    self._record_usage(int(chunk.usage.total_tokens or 0))
                if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except LLMError:
            raise
        except Exception as exc:
            raise self._map(exc) from exc


# ── Anthropic ──────────────────────────────────────────────────────────────────
class ClaudeProvider(BaseLLMProvider):
    name = "claude"

    def _client(self):
        import anthropic

        return anthropic.AsyncAnthropic(api_key=self.settings.api_key, max_retries=0, timeout=_int_env("LLM_TIMEOUT_SECONDS", 60))

    @staticmethod
    def _map(exc) -> LLMError:
        status = getattr(exc, "status_code", None)
        retryable = status in RETRYABLE_STATUS or exc.__class__.__name__ in {"APITimeoutError", "APIConnectionError", "RateLimitError", "OverloadedError"}
        return LLMError(f"claude: {exc.__class__.__name__}", provider="claude", retryable=retryable, status=status)

    async def _generate(self, prompt, system, json_mode, temperature, max_tokens) -> str:
        kwargs: dict = {"model": self.settings.model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]}
        if temperature is not None:
            kwargs["temperature"] = temperature
        if system:
            kwargs["system"] = system
        try:
            resp = await self._client().messages.create(**kwargs)
        except Exception as exc:
            raise self._map(exc) from exc
        usage = getattr(resp, "usage", None)
        if usage:
            self._record_usage(int((usage.input_tokens or 0) + (usage.output_tokens or 0)))
        text = "".join(getattr(block, "text", "") for block in resp.content)
        if not text:
            raise LLMError("claude: empty response.", provider=self.name, retryable=True)
        return text

    async def _stream(self, prompt, system):
        kwargs: dict = {"model": self.settings.model, "max_tokens": _int_env("LLM_MAX_OUTPUT_TOKENS", 2048),
                        "messages": [{"role": "user", "content": prompt}]}
        if system:
            kwargs["system"] = system
        try:
            async with self._client().messages.stream(**kwargs) as stream:
                async for text in stream.text_stream:
                    yield text
                final = await stream.get_final_message()
                if final and final.usage:
                    self._record_usage(int((final.usage.input_tokens or 0) + (final.usage.output_tokens or 0)))
        except Exception as exc:
            raise self._map(exc) from exc


# ── Ollama (self-hosted) ───────────────────────────────────────────────────────
class OllamaProvider(BaseLLMProvider):
    name = "ollama"
    PREFERRED_MODELS = ["llama3.1:8b", "llama3:8b", "mistral:7b", "phi3:mini", "phi3"]
    _model_cache: dict[str, tuple[str | None, float]] = {}

    async def _resolve_model(self) -> str:
        if self.settings.model:
            return self.settings.model
        cached = self._model_cache.get(self.settings.base_url)
        if cached and time.monotonic() - cached[1] < 60 and cached[0]:
            return cached[0]
        import httpx

        try:
            r = await _http().get(f"{self.settings.base_url}/api/tags", timeout=5)
            r.raise_for_status()
            names = [m["name"] for m in r.json().get("models", [])]
        except httpx.HTTPError as exc:
            raise _http_error(self.name, exc) from exc
        model = next((n for p in self.PREFERRED_MODELS for n in names if p in n), names[0] if names else None)
        self._model_cache[self.settings.base_url] = (model, time.monotonic())
        if not model:
            raise LLMConfigError("ollama: no models installed.", provider=self.name)
        return model

    async def is_online(self) -> bool:
        try:
            await self._resolve_model()
            return True
        except LLMError:
            return False

    async def _generate(self, prompt, system, json_mode, temperature, max_tokens) -> str:
        import httpx

        payload: dict = {"model": await self._resolve_model(), "prompt": prompt, "system": system, "stream": False,
                         "options": {"num_predict": max_tokens}}
        if temperature is not None:
            payload["options"]["temperature"] = temperature
        if json_mode:
            payload["format"] = "json"
        try:
            r = await _http().post(f"{self.settings.base_url}/api/generate", json=payload)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise _http_error(self.name, exc) from exc
        data = r.json()
        self._record_usage(int(data.get("prompt_eval_count") or 0) + int(data.get("eval_count") or 0))
        if not data.get("response"):
            raise LLMError("ollama: empty response.", provider=self.name, retryable=True)
        return data["response"]

    async def _stream(self, prompt, system):
        import httpx

        payload = {"model": await self._resolve_model(), "prompt": prompt, "system": system, "stream": True}
        try:
            async with _http().stream("POST", f"{self.settings.base_url}/api/generate", json=payload) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line:
                        continue
                    data = json.loads(line)
                    if data.get("response"):
                        yield data["response"]
                    if data.get("done"):
                        self._record_usage(int(data.get("prompt_eval_count") or 0) + int(data.get("eval_count") or 0))
        except httpx.HTTPError as exc:
            raise _http_error(self.name, exc) from exc


_PROVIDERS: dict[str, type[BaseLLMProvider]] = {
    "gemini": GeminiProvider,
    "openai": OpenAIProvider,
    "claude": ClaudeProvider,
    "ollama": OllamaProvider,
}


def build_client(settings: LLMSettings, usage_callback: UsageCallback | None = None) -> BaseLLMProvider:
    return _PROVIDERS[settings.provider](settings, usage_callback)


def get_llm_client(settings: LLMSettings | None = None, usage_callback: UsageCallback | None = None) -> BaseLLMProvider:
    """Build a NEW client. Without settings, uses the platform default (no user keys)."""
    return build_client(settings or platform_settings(), usage_callback)


# ── Per-user resolution ────────────────────────────────────────────────────────

def user_preferred_provider(user_id: str, db) -> str | None:
    from core.models import UserSettings

    row = db.query(UserSettings).filter(UserSettings.user_id == user_id).first()
    return row.llm_provider if row and row.llm_provider in PROVIDERS else None


def user_api_key(user_id: str, provider: str, db) -> str | None:
    from core.encryption import decrypt_value
    from core.models import UserAPIKey

    aliases = {provider}
    if provider == "claude":
        aliases.add("anthropic")
    record = (
        db.query(UserAPIKey)
        .filter(UserAPIKey.user_id == user_id, UserAPIKey.provider.in_(list(aliases)))
        .order_by(UserAPIKey.updated_at.desc())
        .first()
    )
    if not record:
        return None
    try:
        return decrypt_value(record.encrypted_key) or None
    except Exception as exc:
        logger.warning("Stored API key for user %s/%s could not be decrypted: %s", user_id, provider, type(exc).__name__)
        return None


def resolve_settings_for_user(user_id: str | None, db) -> LLMSettings:
    """Effective settings for a caller.  Never mutates shared state."""
    if not user_id or db is None:
        return platform_settings()
    provider = user_preferred_provider(user_id, db) or platform_provider()
    key = user_api_key(user_id, provider, db) if provider != "ollama" else None
    if key:
        return settings_for(provider, key, key_source="user")
    settings = settings_for(provider)
    if not settings.configured:
        raise LLMConfigError(
            f"No API key is configured for '{provider}'. Add your own key in Settings → API keys "
            "or switch to the default provider.",
            provider=provider,
        )
    return settings
