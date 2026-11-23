"""The persistent pattern memory shared by a user's code-only experiments."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.auth import get_current_user
from app.database.connection import async_sessionmaker_db
from app.database.models import User
from app.learning.store import PERSISTENT_BANK, memory_summary, reset_memory

router = APIRouter(prefix="/memory", tags=["memory"])


@router.get("")
async def get_memory(user: User = Depends(get_current_user)):
    return await memory_summary(async_sessionmaker_db, user.id, PERSISTENT_BANK, limit=20)


@router.post("/reset")
async def reset(user: User = Depends(get_current_user)):
    """Forget everything the persistent memory has learned."""
    return {"deleted_patterns": await reset_memory(async_sessionmaker_db, user.id, PERSISTENT_BANK)}
