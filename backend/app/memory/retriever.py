from typing import Any, Dict, List, Optional
from app.memory.embeddings import EmbeddingService
from app.memory.qdrant_store import QdrantStore

class MemoryRetriever:
    def __init__(self, embedding_service: EmbeddingService, qdrant_store: QdrantStore):
        self.embedding_service = embedding_service
        self.qdrant_store = qdrant_store

    async def retrieve(
        self, 
        query: str, 
        top_k: int = 5, 
        min_similarity: float = 0.65, 
        scope: str = 'all', 
        task_id: Optional[str] = None, 
        category: Optional[str] = None
    ) -> List[Dict]:
        """
        Retrieve memories based on text query and filters.
        Scope can be 'global', 'task', or 'all'.
        """
        # Embed query
        query_vector = await self.embedding_service.embed(query)
        
        # Build filters
        filters = {}
        if scope == 'global':
            filters["generalizable"] = True
        elif scope == 'task':
            if task_id:
                filters["task_id"] = task_id
            else:
                raise ValueError("task_id must be provided when scope is 'task'")
                
        if category:
            filters["category"] = category
            
        # Search Qdrant
        results = await self.qdrant_store.search(
            query_vector=query_vector,
            limit=top_k,
            min_score=min_similarity,
            filters=filters if filters else None
        )
        
        return results

    async def retrieve_for_context(
        self, 
        task_description: str, 
        environment_state: str, 
        top_k: int = 5, 
        min_similarity: float = 0.65
    ) -> List[Dict]:
        """
        Retrieves contextually relevant memories by combining task and state.
        """
        combined_query = f"Task: {task_description}\nEnvironment: {environment_state}"
        
        results = await self.retrieve(
            query=combined_query,
            top_k=top_k,
            min_similarity=min_similarity,
            scope='all'
        )
        
        # Add relevance labels based on score
        for res in results:
            score = res.get('score', 0)
            if score >= 0.85:
                res['relevance'] = 'high'
            elif score >= 0.75:
                res['relevance'] = 'medium'
            else:
                res['relevance'] = 'low'
                
        return results
