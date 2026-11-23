"""Board presets and the models an experiment can use."""
from __future__ import annotations

import asyncio
import logging
import time

from fastapi import APIRouter, Depends

from app.api.auth import get_current_user
from app.config import settings
from app.database.models import User
from app.game.minesweeper import PRESETS
from app.models.llm_provider import get_llm_provider, split_model

logger = logging.getLogger(__name__)
router = APIRouter(tags=["meta"])

PROVIDER_LABELS = {
    "groq": "Groq",
    "ollama": "Ollama (local)",
    "openai": "OpenAI",
    "gemini": "Gemini",
    "openrouter": "OpenRouter",
    "custom": "Custom endpoint",
}

# Models that cannot play a text game: speech, text-to-speech, safety classifiers, embeddings.
_NON_CHAT_MARKERS = ("whisper", "orpheus", "tts", "playai", "guard", "embed", "distil", "moderation")

# Shown when the provider's model list cannot be fetched.
_GROQ_FALLBACK = ["openai/gpt-oss-20b", "openai/gpt-oss-120b", "qwen/qwen3.8-27b"]

# Preferred order: strongest general-purpose chat models first.
_GROQ_ORDER = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"]

_CACHE_SECONDS = 300
_cache: dict[str, tuple[float, list[str]]] = {}


def is_chat_model(model_id: str) -> bool:
    lowered = model_id.lower()
    return not any(marker in lowered for marker in _NON_CHAT_MARKERS)


def _configured_providers() -> list[str]:
    providers = []
    if settings.GROQ_API_KEY or (settings.LLM_PROVIDER == "groq" and settings.CLOUD_API_KEY):
        providers.append("groq")
    default_provider, _ = split_model(settings.default_model)
    if default_provider not in providers:
        providers.append(default_provider)
    if "ollama" not in providers:
        providers.append("ollama")  # listed only if a local Ollama answers
    return providers


async def _list(provider: str) -> list[str]:
    cached = _cache.get(provider)
    if cached and time.monotonic() - cached[0] < _CACHE_SECONDS:
        return cached[1]
    try:
        llm = get_llm_provider(f"{provider}:placeholder")
        models = await asyncio.wait_for(llm.list_models(), timeout=8.0)
        models = [m for m in models if m and is_chat_model(m)]
    except Exception as exc:
        logger.info(f"Could not list {provider} models: {exc}")
        models = list(_GROQ_FALLBACK) if provider == "groq" else []
    if provider == "groq":
        rank = {m: i for i, m in enumerate(_GROQ_ORDER)}
        models.sort(key=lambda m: (rank.get(m, len(rank)), m))
    else:
        models.sort()
    _cache[provider] = (time.monotonic(), models)
    return models


@router.get("/options")
async def options(user: User = Depends(get_current_user)):
    base = {
        "llm_enabled": settings.ENABLE_LLM_AGENTS,
        "presets": {name: {"rows": c.rows, "cols": c.cols, "mines": c.mines} for name, c in PRESETS.items()},
        "default_num_games": settings.DEFAULT_NUM_GAMES,
        "max_num_games": settings.MAX_NUM_GAMES,
        "default_temperature": settings.DEFAULT_TEMPERATURE,
    }
    if not settings.ENABLE_LLM_AGENTS:
        # Code-only mode: no provider is contacted.
        return {**base, "default_model": "", "provider": "", "model_groups": [], "models": []}

    default_provider, default_name = split_model(settings.default_model)
    default_value = f"{default_provider}:{default_name}"

    providers = _configured_providers()
    listings = await asyncio.gather(*(_list(p) for p in providers))
    groups = []
    for provider, models in zip(providers, listings):
        if provider == default_provider and default_name and default_name not in models:
            models = [default_name, *models]
        if not models:
            continue
        groups.append({
            "provider": provider,
            "label": PROVIDER_LABELS.get(provider, provider),
            "models": [{"value": f"{provider}:{m}", "label": m} for m in models],
        })

    return {
        "default_model": default_value,
        "provider": default_provider,
        "model_groups": groups,
        "models": [m["value"] for g in groups for m in g["models"]],
        **base,
    }
