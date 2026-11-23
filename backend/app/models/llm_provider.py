"""LLM providers: Ollama (local) and any OpenAI-compatible API (Groq, OpenAI, Gemini, OpenRouter).

Every call returns an `LLMResponse` with token usage so experiments can report cost.

Model strings may carry a provider prefix: "groq:openai/gpt-oss-20b", "ollama:qwen3:4b".
Without a known prefix the model is sent to `settings.LLM_PROVIDER`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import ssl
from functools import lru_cache
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

PROVIDERS = ("ollama", "groq", "openai", "gemini", "openrouter", "custom")

_DEFAULT_BASE_URLS = {
    "groq": "https://api.groq.com/openai/v1",
    "openai": "https://api.openai.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "openrouter": "https://openrouter.ai/api/v1",
    "custom": "http://localhost:8000/v1",
}


class LLMError(RuntimeError):
    """A call failed after retries."""


class LLMAuthError(LLMError):
    """The provider rejected the credentials (401/403). Retrying cannot help."""


class QuotaExhaustedError(LLMError):
    """The provider reported a daily/quota limit. Retrying cannot help until it resets."""


class RateLimitedError(LLMError):
    """Per-minute rate limit still hit after waiting. Transient: the caller should wait and retry."""


@dataclass
class LLMResponse:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    finish_reason: str = ""


_DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s)")


def parse_duration(text: str | None) -> float | None:
    """Parse rate-limit durations such as "7.66s", "2m59.56s", "120ms", "1h2m3s" into seconds."""
    if not text:
        return None
    total, found = 0.0, False
    for value, unit in _DURATION_PART.findall(text):
        found = True
        total += float(value) * {"ms": 0.001, "s": 1, "m": 60, "h": 3600}[unit]
    return total if found else None


def estimate_tokens(system: str, user: str) -> int:
    """Rough request size: ~4 characters per prompt token plus a typical short reasoned answer."""
    return (len(system) + len(user)) // 4 + 600


class RateGate:
    """Paces calls to one provider model from its `x-ratelimit-*` response headers.

    Both agents share the gate for their model, so instead of firing requests that
    come back 429, a call waits just long enough for the token bucket to refill.
    """

    def __init__(self):
        self.limit: float | None = None       # tokens per minute
        self.remaining: float | None = None   # tokens left in the current window
        self.updated_at = 0.0
        self.reset_after: float | None = None

    def _available(self, now: float) -> float | None:
        if self.remaining is None:
            return None
        if self.limit:  # the bucket refills continuously at limit/60 tokens per second
            return min(self.limit, self.remaining + (now - self.updated_at) * self.limit / 60.0)
        if self.reset_after is not None and now - self.updated_at >= self.reset_after:
            return None
        return self.remaining

    async def wait_for(self, tokens: int) -> None:
        loop = asyncio.get_running_loop()
        for _ in range(30):
            now = loop.time()
            available = self._available(now)
            if available is None or available >= tokens or (self.limit and tokens > self.limit):
                break
            if self.limit:
                wait = (tokens - available) / (self.limit / 60.0)
            else:
                wait = max(0.5, (self.reset_after or 1.0) - (now - self.updated_at))
            await asyncio.sleep(min(max(wait, 0.2), 30.0))
        # Reserve the tokens so a concurrent caller (the other agent) sees the reduced budget.
        if self.remaining is not None:
            now = loop.time()
            available = self._available(now)
            if available is not None:
                self.remaining = available - tokens
                self.updated_at = now

    def update(self, headers) -> None:
        remaining = headers.get("x-ratelimit-remaining-tokens")
        if remaining is None:
            return
        try:
            self.remaining = float(remaining)
        except ValueError:
            return
        try:
            self.limit = float(headers.get("x-ratelimit-limit-tokens") or 0) or None
        except ValueError:
            self.limit = None
        self.reset_after = parse_duration(headers.get("x-ratelimit-reset-tokens"))
        self.updated_at = asyncio.get_running_loop().time()


_gates: dict[tuple[str, str], RateGate] = {}


def rate_gate(base_url: str, model: str) -> RateGate:
    return _gates.setdefault((base_url, model), RateGate())


def default_reasoning_effort(model: str, configured: str = "") -> str:
    """Reasoning models given no effort level can spend the whole token budget thinking
    and return an empty answer. Default gpt-oss to "low": one short decision per move."""
    if configured:
        return configured
    return "low" if "gpt-oss" in model.lower() else ""


_RETRY_IN = re.compile(r"try again in (?:(\d+)m)?([\d.]+)(ms|s)", re.IGNORECASE)


def _rate_limit_wait(response: httpx.Response, fallback: float) -> float:
    """Seconds to wait after a 429: retry-after header, else the "try again in 6.5s" hint."""
    header = response.headers.get("retry-after")
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    match = _RETRY_IN.search(response.text or "")
    if match:
        minutes = float(match.group(1) or 0)
        value = float(match.group(2))
        return minutes * 60 + (value / 1000 if match.group(3).lower() == "ms" else value)
    return fallback


@lru_cache(maxsize=1)
def tls_verify() -> ssl.SSLContext | bool:
    """Verify HTTPS against the operating system's certificate store.

    Antivirus and corporate proxies often re-sign HTTPS traffic with a root
    certificate that only the OS store trusts. `truststore` makes Python use
    that store, so certificate verification stays ON instead of being disabled.
    Falls back to certifi's bundle if truststore is unavailable.
    """
    try:
        import truststore

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception as exc:  # pragma: no cover - depends on the platform
        logger.warning(f"truststore unavailable ({exc}); using the default certificate bundle")
        return True


def parse_json_object(text: str) -> dict:
    """Parse a JSON object from model output, tolerating code fences and surrounding prose."""
    cleaned = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        value = json.loads(cleaned)
        if isinstance(value, dict):
            return value
    except ValueError:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            value = json.loads(cleaned[start:end + 1])
            if isinstance(value, dict):
                return value
        except ValueError:
            pass
    raise ValueError(f"No JSON object in model output: {cleaned[:200]!r}")


class LLMProvider(ABC):
    model: str

    @abstractmethod
    async def complete(self, system: str, user: str, temperature: float = 0.3, json_mode: bool = True) -> LLMResponse:
        ...

    @abstractmethod
    async def list_models(self) -> list[str]:
        ...

    async def complete_json(self, system: str, user: str, temperature: float = 0.3) -> tuple[dict, LLMResponse]:
        response = await self.complete(system, user, temperature=temperature, json_mode=True)
        return parse_json_object(response.text), response


class OllamaProvider(LLMProvider):
    def __init__(self, base_url: str, model: str, max_tokens: int = 2048, timeout: float = 90.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout

    async def complete(self, system: str, user: str, temperature: float = 0.3, json_mode: bool = True) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "options": {"temperature": temperature, "num_predict": self.max_tokens},
        }
        if json_mode:
            payload["format"] = "json"
        last_error: Exception | None = None
        async with httpx.AsyncClient(timeout=self.timeout, verify=tls_verify()) as client:
            for attempt in range(3):
                try:
                    response = await client.post(f"{self.base_url}/api/chat", json=payload)
                    response.raise_for_status()
                    data = response.json()
                    return LLMResponse(
                        text=data.get("message", {}).get("content", ""),
                        prompt_tokens=int(data.get("prompt_eval_count") or 0),
                        completion_tokens=int(data.get("eval_count") or 0),
                    )
                except httpx.HTTPError as exc:
                    last_error = exc
                    await asyncio.sleep(1.5 * (attempt + 1))
        raise LLMError(f"Ollama call failed: {last_error}")

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=5.0, verify=tls_verify()) as client:
            response = await client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            return [m.get("name") for m in response.json().get("models", []) if m.get("name")]


class OpenAICompatibleProvider(LLMProvider):
    def __init__(self, base_url: str, api_key: str, model: str, max_tokens: int = 2048,
                 timeout: float = 90.0, reasoning_effort: str = ""):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.reasoning_effort = reasoning_effort

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    @staticmethod
    def _quota_message(response: httpx.Response) -> str | None:
        try:
            body = response.json()
        except ValueError:
            return None
        error = body.get("error") if isinstance(body, dict) else None
        message = (error.get("message", "") if isinstance(error, dict) else str(error or ""))
        if any(s in message for s in ("per day", "TPD", "RPD", "tokens per day", "daily", "quota")):
            return message[:300]
        return None

    async def complete(self, system: str, user: str, temperature: float = 0.3, json_mode: bool = True) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": temperature,
            "max_tokens": self.max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort

        last_error: str = ""
        attempt = 0
        rate_limited = 0
        gate = rate_gate(self.base_url, self.model)
        estimate = estimate_tokens(system, user)
        async with httpx.AsyncClient(timeout=self.timeout, verify=tls_verify()) as client:
            while attempt < 5:
                attempt += 1
                await gate.wait_for(estimate)
                try:
                    response = await client.post(f"{self.base_url}/chat/completions",
                                                 headers=self._headers(), json=payload)
                except httpx.HTTPError as exc:
                    last_error = str(exc)
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                gate.update(response.headers)

                if response.status_code in (401, 403):
                    raise LLMAuthError(f"{response.status_code} from provider: {response.text[:200]}")
                if response.status_code == 429:
                    quota = self._quota_message(response)
                    # Daily limits are rolling windows: when the provider says capacity frees up
                    # within a few minutes, wait instead of failing, so long runs keep going at
                    # whatever pace the daily budget allows.
                    if quota and _rate_limit_wait(response, 1e9) > 600:
                        raise QuotaExhaustedError(f"Provider quota exhausted: {quota}")
                    # Per-minute limits are expected on free tiers: wait as instructed and
                    # retry without spending one of the error attempts.
                    rate_limited += 1
                    if rate_limited > 12:
                        raise RateLimitedError(f"Still rate limited after {rate_limited - 1} waits: "
                                               f"{response.text[:200]}")
                    wait = _rate_limit_wait(response, 2.0 * rate_limited)
                    attempt -= 1
                    await asyncio.sleep(min(max(wait, 0.5) + 0.25, 60.0))
                    continue
                if response.status_code == 400 and json_mode and "response_format" in payload:
                    # Some models reject JSON mode or fail to produce valid JSON under it
                    # ("json_validate_failed"). Retry once without it; the prompt still asks for JSON.
                    payload.pop("response_format", None)
                    last_error = f"400: {response.text[:200]}"
                    continue
                if response.status_code >= 500 or response.status_code == 404:
                    last_error = f"{response.status_code}: {response.text[:200]}"
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                if response.status_code >= 400:
                    raise LLMError(f"{response.status_code} from provider: {response.text[:300]}")

                data = response.json()
                usage = data.get("usage") or {}
                choice = (data.get("choices") or [{}])[0]
                message = choice.get("message") or {}
                return LLMResponse(
                    text=message.get("content") or "",
                    prompt_tokens=int(usage.get("prompt_tokens") or 0),
                    completion_tokens=int(usage.get("completion_tokens") or 0),
                    finish_reason=str(choice.get("finish_reason") or ""),
                )
        raise LLMError(f"LLM call failed after retries: {last_error}")

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=10.0, verify=tls_verify()) as client:
            response = await client.get(f"{self.base_url}/models", headers=self._headers())
            if response.status_code in (401, 403):
                raise LLMAuthError(f"{response.status_code} from provider: {response.text[:200]}")
            response.raise_for_status()
            return [m.get("id") for m in response.json().get("data", []) if m.get("id")]


def split_model(model: str | None) -> tuple[str, str]:
    """Return (provider, model_name) for a possibly-prefixed model string."""
    from app.config import settings

    value = (model or settings.default_model or "").strip()
    prefix, _, rest = value.partition(":")
    if prefix.lower() in PROVIDERS and rest:
        return prefix.lower(), rest
    # Legacy "groq/<model>" form. "openai/" is NOT treated as a prefix because
    # Groq's own model ids look like "openai/gpt-oss-20b".
    prefix, _, rest = value.partition("/")
    if prefix.lower() in ("groq", "gemini", "openrouter", "ollama") and rest:
        return prefix.lower(), rest
    return (settings.LLM_PROVIDER or "ollama").lower(), value


def get_llm_provider(model: str | None = None) -> LLMProvider:
    from app.config import settings

    provider, name = split_model(model)
    common = {"max_tokens": settings.LLM_MAX_TOKENS, "timeout": settings.LLM_TIMEOUT_SECONDS}
    if provider == "ollama":
        return OllamaProvider(settings.OLLAMA_BASE_URL, name or settings.PRIMARY_MODEL, **common)

    keys = {
        "groq": settings.GROQ_API_KEY,
        "openai": settings.OPENAI_API_KEY,
        "gemini": settings.GEMINI_API_KEY,
        "openrouter": settings.OPENROUTER_API_KEY,
        "custom": "",
    }
    api_key = settings.CLOUD_API_KEY or keys.get(provider, "")
    if not api_key and provider != "custom":
        raise LLMAuthError(f"No API key configured for provider {provider!r} (set {provider.upper()}_API_KEY).")
    base_url = settings.CLOUD_BASE_URL or _DEFAULT_BASE_URLS[provider]
    return OpenAICompatibleProvider(base_url, api_key or "none", name,
                                    reasoning_effort=default_reasoning_effort(name, settings.LLM_REASONING_EFFORT),
                                    **common)
