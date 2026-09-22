from fastapi import APIRouter, Depends
from typing import Dict, Any, List
import httpx
import logging
import os
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database.connection import get_db
from app.database.models import User, Setting
from app.config import settings
from app.models.hardware import detect_hardware, recommend_model

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/settings", tags=["settings"])

@router.get("")
async def get_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Load user custom settings from SQLite database
    db_res = await db.execute(select(Setting).where(Setting.user_id == current_user.id))
    user_settings = {s.key: s.value for s in db_res.scalars().all()}

    persistent_enabled = settings.DEFAULT_USE_PERSISTENT_LEARNING
    if "persistent_learning_enabled" in user_settings:
        persistent_enabled = user_settings["persistent_learning_enabled"].lower() in ("true", "1", "yes")
        settings.DEFAULT_USE_PERSISTENT_LEARNING = persistent_enabled

    primary_model = user_settings.get("default_model", settings.PRIMARY_MODEL)
    settings.PRIMARY_MODEL = primary_model

    max_iterations = int(user_settings.get("default_max_iterations", settings.DEFAULT_MAX_ITERATIONS))
    snapshot_interval = int(user_settings.get("default_snapshot_interval", settings.DEFAULT_SNAPSHOT_INTERVAL))
    synthesis_interval = int(user_settings.get("default_synthesis_interval", settings.DEFAULT_SYNTHESIS_INTERVAL))
    llm_provider = user_settings.get("llm_provider", settings.LLM_PROVIDER)
    cloud_model = user_settings.get("cloud_model", settings.CLOUD_MODEL)
    cloud_base_url = user_settings.get("cloud_base_url", settings.CLOUD_BASE_URL)

    return {
        "default_model": primary_model,
        "default_max_iterations": max_iterations,
        "default_snapshot_interval": snapshot_interval,
        "default_synthesis_interval": synthesis_interval,
        "persistent_learning_enabled": persistent_enabled,
        "tool_permissions": "safe",
        "embedding_model": settings.EMBEDDING_MODEL,
        "ollama_base_url": settings.OLLAMA_BASE_URL,
        "llm_provider": llm_provider,
        "cloud_model": cloud_model,
        "cloud_base_url": cloud_base_url,
        "has_groq_key": bool(getattr(settings, "GROQ_API_KEY", "") or os.getenv("GROQ_API_KEY")),
        "has_gemini_key": bool(getattr(settings, "GEMINI_API_KEY", "") or os.getenv("GEMINI_API_KEY")),
        "has_openai_key": bool(getattr(settings, "OPENAI_API_KEY", "") or os.getenv("OPENAI_API_KEY")),
        "has_openrouter_key": bool(getattr(settings, "OPENROUTER_API_KEY", "") or os.getenv("OPENROUTER_API_KEY")),
    }

@router.put("")
async def update_settings(
    updates: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if "default_model" in updates:
        settings.PRIMARY_MODEL = str(updates["default_model"])
    if "default_max_iterations" in updates:
        settings.DEFAULT_MAX_ITERATIONS = int(updates["default_max_iterations"])
    if "default_snapshot_interval" in updates:
        settings.DEFAULT_SNAPSHOT_INTERVAL = int(updates["default_snapshot_interval"])
    if "default_synthesis_interval" in updates:
        settings.DEFAULT_SYNTHESIS_INTERVAL = int(updates["default_synthesis_interval"])
    if "persistent_learning_enabled" in updates:
        settings.DEFAULT_USE_PERSISTENT_LEARNING = bool(updates["persistent_learning_enabled"])
    if "llm_provider" in updates:
        settings.LLM_PROVIDER = str(updates["llm_provider"])
    if "cloud_model" in updates:
        settings.CLOUD_MODEL = str(updates["cloud_model"])
    if "cloud_base_url" in updates:
        settings.CLOUD_BASE_URL = str(updates["cloud_base_url"])

    # Persist in SQLite Setting table
    for key, val in updates.items():
        if val is not None:
            res = await db.execute(select(Setting).where(Setting.user_id == current_user.id, Setting.key == str(key)))
            record = res.scalar_one_or_none()
            if record:
                record.value = str(val)
            else:
                db.add(Setting(user_id=current_user.id, key=str(key), value=str(val)))
    await db.commit()

    return {
        "status": "updated",
        "persistent_learning_enabled": settings.DEFAULT_USE_PERSISTENT_LEARNING,
        "default_model": settings.PRIMARY_MODEL
    }

@router.get("/models", response_model=List[str])
async def list_models(current_user: User = Depends(get_current_user)):
    local_models = []
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{settings.OLLAMA_BASE_URL}/api/tags")
            if resp.status_code == 200:
                models_data = resp.json().get("models", [])
                local_models = [m.get("name") for m in models_data if m.get("name")]
    except Exception as e:
        logger.warning(f"Could not query Ollama for models: {e}")
        
    cloud_models = [
        "groq/openai/gpt-oss-120b",
        "groq/qwen/qwen3.8-27b",
        "groq/openai/gpt-oss-20b",
        "groq/groq/compound-mini",
        "gemini/gemini-2.0-flash",
        "openai/gpt-4o-mini",
        "openrouter/meta-llama/llama-3.3-70b-instruct"
    ]
    all_models = (local_models or ["qwen3:4b", "phi3:mini"]) + cloud_models
    return all_models

@router.get("/hardware")
async def get_hardware(current_user: User = Depends(get_current_user)):
    try:
        hw_info = detect_hardware()
        rec_model = recommend_model(hw_info)
        gpu_desc = f"{hw_info.gpu_name} ({hw_info.gpu_vram_gb:.1f} GB VRAM)" if hw_info.gpu_name else None
        return {
            "cpu_info": f"{hw_info.cpu_name or 'Processor'} ({hw_info.cpu_cores} Cores, {hw_info.cpu_threads} Threads)",
            "ram_total": f"{hw_info.ram_total_gb:.1f} GB RAM",
            "gpu_info": gpu_desc,
            "recommended_model": rec_model.get("primary_model", "phi3:mini")
        }
    except Exception as e:
        logger.warning(f"Error detecting hardware: {e}")
        return {
            "cpu_info": "Detected CPU",
            "ram_total": "8.0 GB RAM",
            "gpu_info": None,
            "recommended_model": "phi3:mini"
        }
