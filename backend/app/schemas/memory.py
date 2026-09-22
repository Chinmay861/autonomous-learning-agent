from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class MemorySearchRequest(BaseModel):
    query: str
    top_k: int = 5
    min_similarity: float = 0.7
    scope: str = "all"
    category: Optional[str] = None
    task_id: Optional[str] = None

class MemorySearchResult(BaseModel):
    id: int
    learning: str
    similarity: float
    category: str
    confidence: float
    task_id: str
    created_at: datetime

class MemorySearchResponse(BaseModel):
    results: List[MemorySearchResult]

class MemoryStatsResponse(BaseModel):
    total_memories: int
    global_count: int
    task_count: int
    avg_confidence: float
    recent_additions: int
