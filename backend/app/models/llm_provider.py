from abc import ABC, abstractmethod
from typing import Any, AsyncIterator
import httpx
import json
import asyncio

class QuotaExhaustedError(Exception):
    """Raised when the provider reports a daily/quota limit.

    Retrying cannot help until the quota resets, so callers should abort
    cleanly instead of burning the iteration budget on fallbacks.
    """
    pass


class LLMProvider(ABC):
    @abstractmethod
    async def generate(self, prompt: str, system: str = '', temperature: float = 0.7) -> str: ...
    
    @abstractmethod
    async def structured_generate(self, prompt: str, schema: dict, system: str = '', temperature: float = 0.7) -> dict: ...
    
    async def generate_json(self, prompt: str, system_prompt: str = '', **kwargs) -> dict | list:
        raw = await self.generate(prompt, system=system_prompt, response_format="json", **kwargs)
        text = raw.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        try:
            return json.loads(text.strip())
        except Exception:
            # Try basic recovery
            return _repair_and_parse_json(text.strip())
    
    @abstractmethod
    async def stream(self, prompt: str, system: str = '', temperature: float = 0.7) -> AsyncIterator[str]: ...
    
    @abstractmethod
    async def list_models(self) -> list[str]: ...


def _repair_and_parse_json(text: str) -> dict | list:
    import re
    # Try finding enclosed json block
    m = re.search(r'(\{[\s\S]*\}|\[[\s\S]*\])', text)
    candidate = m.group(1) if m else text
    try:
        return json.loads(candidate)
    except Exception:
        pass
    # Try closing dangling quotes and brackets
    for closer in ['"}', '"]', '}', ']']:
        try:
            return json.loads(candidate + closer)
        except Exception:
            pass
    return {}


class OllamaProvider(LLMProvider):
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3"):
        self.base_url = base_url
        self.model = model
    
    async def _request(self, method: str, endpoint: str, **kwargs) -> Any:
        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                response = await client.request(method, f"{self.base_url}{endpoint}", **kwargs)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError as e:
                # Basic retry
                await asyncio.sleep(1)
                response = await client.request(method, f"{self.base_url}{endpoint}", **kwargs)
                response.raise_for_status()
                return response.json()

    async def generate(self, prompt: str, system: str = '', temperature: float = 0.7, **kwargs) -> str:
        system_text = system or kwargs.get("system_prompt", "")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_text},
                {"role": "user", "content": prompt}
            ],
            "stream": False,
            "options": {"temperature": temperature, "num_predict": kwargs.get("num_predict", 1024)}
        }
        if "response_format" in kwargs:
            rf = kwargs["response_format"]
            if isinstance(rf, dict) and "schema" in rf:
                payload["format"] = rf["schema"]
            else:
                payload["format"] = "json"
        elif "schema" in kwargs:
            payload["format"] = kwargs["schema"]
            
        data = await self._request("POST", "/api/chat", json=payload)
        return data.get("message", {}).get("content", "")

    async def structured_generate(self, prompt: str, schema: dict, system: str = '', temperature: float = 0.7, **kwargs) -> dict:
        system_text = system or kwargs.get("system_prompt", "")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_text},
                {"role": "user", "content": prompt}
            ],
            "format": schema,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": kwargs.get("num_predict", 1024)}
        }
        data = await self._request("POST", "/api/chat", json=payload)
        content = data.get("message", {}).get("content", "{}")
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            import re
            m = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
            if m:
                try:
                    return json.loads(m.group(1))
                except Exception:
                    pass
            return _repair_and_parse_json(content)

    async def stream(self, prompt: str, system: str = '', temperature: float = 0.7) -> AsyncIterator[str]:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ],
            "stream": True,
            "options": {"temperature": temperature}
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            async with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line:
                        try:
                            chunk = json.loads(line)
                            yield chunk.get("message", {}).get("content", "")
                        except json.JSONDecodeError:
                            continue

    async def list_models(self) -> list[str]:
        data = await self._request("GET", "/api/tags")
        return [model.get("name") for model in data.get("models", [])]


class OpenAICompatibleProvider(LLMProvider):
    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        # Set to the provider's message when a daily/quota limit is hit.
        # The orchestrator checks this flag to abort the run instead of
        # burning iterations on fallbacks that cannot succeed.
        self.quota_exhausted: str | None = None

    @staticmethod
    def _quota_message(response) -> str | None:
        """Extract a daily/quota-limit signal from a 429 response, if present."""
        try:
            body = response.json()
        except Exception:
            return None
        message = ((body.get("error") or {}).get("message", "")) if isinstance(body, dict) else ""
        if any(signal in message for signal in ("per day", "TPD", "tokens per day", "daily limit", "per-day", "quota")):
            return message[:300]
        return None
    
    async def _request(self, method: str, endpoint: str, **kwargs) -> Any:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        # verify=False prevents SSL: CERTIFICATE_VERIFY_FAILED on Windows corporate/antivirus intercepts
        async with httpx.AsyncClient(timeout=45.0, verify=False) as client:
            last_err = None
            for attempt in range(4):
                try:
                    response = await client.request(method, f"{self.base_url}{endpoint}", headers=headers, **kwargs)
                    if response.status_code == 429:
                        quota_message = self._quota_message(response)
                        if quota_message:
                            self.quota_exhausted = quota_message
                            raise QuotaExhaustedError(
                                "LLM daily quota exhausted. No further calls will succeed "
                                f"until it resets. Provider says: {quota_message}"
                            )
                        retry_after = float(response.headers.get("retry-after", 1.5 * (attempt + 1)))
                        await asyncio.sleep(min(retry_after, 4.0))
                        if "json" in kwargs and isinstance(kwargs["json"], dict):
                            curr_m = kwargs["json"].get("model", "")
                            if "120b" in curr_m:
                                kwargs["json"]["model"] = "qwen/qwen3.8-27b"
                            elif "27b" in curr_m and attempt >= 2:
                                kwargs["json"]["model"] = "groq/compound-mini"
                        continue
                    response.raise_for_status()
                    return response.json()
                except httpx.HTTPStatusError as e:
                    last_err = e
                    if e.response.status_code == 429:
                        quota_message = self._quota_message(e.response)
                        if quota_message:
                            self.quota_exhausted = quota_message
                            raise QuotaExhaustedError(
                                "LLM daily quota exhausted. No further calls will succeed "
                                f"until it resets. Provider says: {quota_message}"
                            ) from e
                        await asyncio.sleep(1.5 * (attempt + 1))
                        continue
                    # 404/5xx from Groq are frequently transient (model routing
                    # flaps); retry them a few times before failing.
                    if e.response.status_code in (404, 500, 502, 503, 529):
                        await asyncio.sleep(1.5 * (attempt + 1))
                        continue
                    raise
                except httpx.HTTPError as e:
                    last_err = e
                    await asyncio.sleep(1.0)
            if last_err:
                raise last_err

    async def generate(self, prompt: str, system: str = '', temperature: float = 0.7, **kwargs) -> str:
        system_text = system or kwargs.get("system_prompt", "")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_text},
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature
        }
        data = await self._request("POST", "/chat/completions", json=payload)
        return data["choices"][0]["message"]["content"]

    async def generate_json(self, prompt: str, system_prompt: str = '', **kwargs) -> dict | list:
        sys_text = system_prompt or kwargs.get("system", "You must respond with valid JSON.")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": sys_text},
                {"role": "user", "content": prompt}
            ],
            "response_format": {"type": "json_object"}
        }
        try:
            data = await self._request("POST", "/chat/completions", json=payload)
            content = data["choices"][0]["message"]["content"]
            return json.loads(content)
        except Exception:
            # Fallback to plain generate
            raw = await self.generate(prompt, system=sys_text)
            return _repair_and_parse_json(raw)

    async def structured_generate(self, prompt: str, schema: dict, system: str = '', temperature: float = 0.7, **kwargs) -> dict:
        sys_text = system or kwargs.get("system_prompt", "") or "You must output strictly valid JSON conforming to the requested schema."
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": sys_text},
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature,
            "response_format": {"type": "json_object"}
        }
        try:
            data = await self._request("POST", "/chat/completions", json=payload)
            content = data["choices"][0]["message"]["content"]
            return json.loads(content)
        except Exception:
            raw = await self.generate(prompt, system=sys_text, temperature=temperature)
            return _repair_and_parse_json(raw)

    async def stream(self, prompt: str, system: str = '', temperature: float = 0.7, **kwargs) -> AsyncIterator[str]:
        sys_text = system or kwargs.get("system_prompt", "")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": sys_text},
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature,
            "stream": True
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=45.0, verify=False) as client:
            async with client.stream("POST", f"{self.base_url}/chat/completions", headers=headers, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            delta = chunk["choices"][0].get("delta", {})
                            if "content" in delta:
                                yield delta["content"]
                        except json.JSONDecodeError:
                            continue

    async def list_models(self) -> list[str]:
        try:
            data = await self._request("GET", "/models")
            return [model.get("id") for model in data.get("data", [])]
        except Exception:
            return [self.model]


def get_llm_provider(config: dict | None = None) -> LLMProvider:
    import os
    from app.config import settings
    
    cfg = config or {}
    model = cfg.get("model") or settings.CLOUD_MODEL or settings.PRIMARY_MODEL
    provider_type = cfg.get("type") or settings.LLM_PROVIDER or "ollama"
    api_key = cfg.get("api_key") or settings.CLOUD_API_KEY
    base_url = cfg.get("base_url") or settings.CLOUD_BASE_URL

    # Auto-detect from model string prefix
    if model:
        if model.startswith("groq/"):
            provider_type = "groq"
            model = model.replace("groq/", "", 1)
        elif model.startswith("gemini/"):
            provider_type = "gemini"
            model = model.replace("gemini/", "", 1)
        elif model.startswith("openrouter/"):
            provider_type = "openrouter"
            model = model.replace("openrouter/", "", 1)
        elif model.startswith("openai/") and provider_type != "groq":
            provider_type = "openai"
            model = model.replace("openai/", "", 1)

    # Extract keys from settings or os.environ (.env)
    groq_key = api_key or getattr(settings, "GROQ_API_KEY", "") or os.getenv("GROQ_API_KEY", "")
    gemini_key = api_key or getattr(settings, "GEMINI_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")
    openai_key = api_key or getattr(settings, "OPENAI_API_KEY", "") or os.getenv("OPENAI_API_KEY", "")
    openrouter_key = api_key or getattr(settings, "OPENROUTER_API_KEY", "") or os.getenv("OPENROUTER_API_KEY", "")

    # Auto-detect from environment keys if cloud provider not explicitly chosen
    if provider_type == "ollama":
        if groq_key:
            provider_type = "groq"
        elif gemini_key:
            provider_type = "gemini"
        elif openai_key:
            provider_type = "openai"
        elif openrouter_key:
            provider_type = "openrouter"

    provider_type = provider_type.lower().strip()
    
    if provider_type == "groq":
        if not groq_key:
            import logging
            logging.getLogger(__name__).warning("GROQ_API_KEY is not set in backend/.env. Falling back to local Ollama (phi3:mini).")
            return OllamaProvider(base_url=settings.OLLAMA_BASE_URL, model="phi3:mini")
        default_groq_model = "qwen/qwen3.8-27b"
        groq_model = model
        if not groq_model or any(groq_model.startswith(p) for p in ["phi", "qwen3:", "llama3:"]) or groq_model in ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]:
            groq_model = default_groq_model
        return OpenAICompatibleProvider(
            base_url=base_url or "https://api.groq.com/openai/v1",
            api_key=groq_key,
            model=groq_model
        )
    elif provider_type == "gemini":
        if not gemini_key:
            import logging
            logging.getLogger(__name__).warning("GEMINI_API_KEY is not set in backend/.env. Falling back to local Ollama (phi3:mini).")
            return OllamaProvider(base_url=settings.OLLAMA_BASE_URL, model="phi3:mini")
        return OpenAICompatibleProvider(
            base_url=base_url or "https://generativelanguage.googleapis.com/v1beta/openai",
            api_key=gemini_key,
            model=model if model and not model.startswith("qwen") and not model.startswith("phi") else "gemini-2.0-flash"
        )
    elif provider_type == "openai":
        if not openai_key:
            import logging
            logging.getLogger(__name__).warning("OPENAI_API_KEY is not set in backend/.env. Falling back to local Ollama (phi3:mini).")
            return OllamaProvider(base_url=settings.OLLAMA_BASE_URL, model="phi3:mini")
        return OpenAICompatibleProvider(
            base_url=base_url or "https://api.openai.com/v1",
            api_key=openai_key,
            model=model if model and not model.startswith("qwen") and not model.startswith("phi") else "gpt-4o-mini"
        )
    elif provider_type == "openrouter":
        if not openrouter_key:
            import logging
            logging.getLogger(__name__).warning("OPENROUTER_API_KEY is not set in backend/.env. Falling back to local Ollama (phi3:mini).")
            return OllamaProvider(base_url=settings.OLLAMA_BASE_URL, model="phi3:mini")
        return OpenAICompatibleProvider(
            base_url=base_url or "https://openrouter.ai/api/v1",
            api_key=openrouter_key,
            model=model if model and not model.startswith("qwen") and not model.startswith("phi") else "meta-llama/llama-3.3-70b-instruct"
        )
    elif provider_type == "custom":
        return OpenAICompatibleProvider(
            base_url=base_url or "http://localhost:8000/v1",
            api_key=api_key or "dummy",
            model=model or "default"
        )
    else:
        return OllamaProvider(
            base_url=settings.OLLAMA_BASE_URL,
            model=model or settings.PRIMARY_MODEL
        )
