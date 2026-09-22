from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
import logging

from app.database.models import User
from app.schemas.memory import MemorySearchRequest, MemoryStatsResponse
from app.api.auth import get_current_user
from app.api.dependencies import get_memory_manager
from app.memory.memory_manager import MemoryManager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/memory", tags=["memory"])


async def _search(query: str, top_k: int, min_similarity: float, memory_manager: MemoryManager):
    try:
        return await memory_manager.search_memories(
            query=query,
            top_k=top_k,
            min_similarity=min_similarity,
        )
    except Exception as e:
        logger.error(f"Error searching memories: {e}")
        return []


@router.get("/search")
async def search_memory_get(
    query: str = Query(..., min_length=1),
    top_k: int = Query(10, ge=1, le=100),
    min_similarity: float = Query(0.3, ge=0.0, le=1.0),
    current_user: User = Depends(get_current_user),
    memory_manager: MemoryManager = Depends(get_memory_manager),
):
    return await _search(query, top_k, min_similarity, memory_manager)


@router.post("/search")
async def search_memory(
    request: MemorySearchRequest,
    current_user: User = Depends(get_current_user),
    memory_manager: MemoryManager = Depends(get_memory_manager)
):
    return await _search(request.query, request.top_k, request.min_similarity, memory_manager)

@router.get("/stats", response_model=MemoryStatsResponse)
async def get_memory_stats(
    current_user: User = Depends(get_current_user),
    memory_manager: MemoryManager = Depends(get_memory_manager)
):
    try:
        stats = await memory_manager.get_memory_stats()
        return MemoryStatsResponse(
            total_memories=stats.get("total_memories", 0),
            global_count=max(0, stats.get("global_count", 0)),
            task_count=max(0, stats.get("task_count", 0)),
            avg_confidence=max(0.0, stats.get("avg_confidence", 0.0)),
            recent_additions=max(0, stats.get("recent_additions", 0))
        )
    except Exception as e:
        logger.warning(f"Error fetching memory stats: {e}")
        return MemoryStatsResponse(
            total_memories=0,
            global_count=0,
            task_count=0,
            avg_confidence=0.0,
            recent_additions=0
        )

@router.get("/task/{task_id}")
async def get_task_memories(
    task_id: str,
    current_user: User = Depends(get_current_user),
    memory_manager: MemoryManager = Depends(get_memory_manager)
):
    try:
        return await memory_manager.qdrant_store.get_all_by_task(task_id)
    except Exception as e:
        logger.error(f"Error getting task memories: {e}")
        return []
