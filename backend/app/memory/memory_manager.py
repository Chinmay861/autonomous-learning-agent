import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from app.memory.embeddings import EmbeddingService
from app.memory.qdrant_store import QdrantStore
from app.memory.retriever import MemoryRetriever

class MemoryManager:
    def __init__(self, embedding_service: EmbeddingService, qdrant_store: QdrantStore, retriever: MemoryRetriever):
        self.embedding_service = embedding_service
        self.qdrant_store = qdrant_store
        self.retriever = retriever
        
        # Retrieval setting controlled by user
        self.retrieval_enabled: bool = True 
        
        # Save setting ALWAYS TRUE, NEVER CHANGES
        self.save_learning: bool = True

    async def retrieve_relevant_memories(
        self, 
        task: str, 
        state: str, 
        top_k: int = 5, 
        min_similarity: float = 0.65
    ) -> Optional[List[Dict]]:
        """
        Retrieves relevant memories for given task and state context.
        Returns None if retrieval is disabled.
        """
        if not self.retrieval_enabled:
            return None
            
        return await self.retriever.retrieve_for_context(
            task_description=task,
            environment_state=state,
            top_k=top_k,
            min_similarity=min_similarity
        )

    async def store_synthesized_learning(self, learning: Dict, task_id: str) -> str:
        """
        Always stores synthesized learning, handling duplication checks.
        """
        learning_text = (
            f"Title: {learning.get('title', '')}\n"
            f"Knowledge: {learning.get('knowledge', '')}\n"
            f"Conditions: {', '.join(learning.get('conditions', []))}\n"
            f"Exceptions: {', '.join(learning.get('exceptions', []))}"
        )
        
        vector = await self.embedding_service.embed(learning_text)
        
        # Check for duplicates
        duplicates = await self.qdrant_store.find_duplicates(vector, threshold=0.92)
        
        if duplicates:
            # Merge with existing
            existing = duplicates[0]
            existing_id = existing['id']
            existing_payload = existing['payload']
            
            # Update fields
            merged_payload = existing_payload.copy()
            merged_payload['confidence'] = min(1.0, existing_payload.get('confidence', 0.5) + 0.1)
            merged_payload['source_iterations'] = existing_payload.get('source_iterations', 1) + learning.get('source_iterations', 1)
            
            old_evidence = existing_payload.get('evidence_summary', '')
            new_evidence = learning.get('evidence_summary', '')
            merged_payload['evidence_summary'] = f"{old_evidence}\nNew Evidence: {new_evidence}"
            
            await self.qdrant_store.update_payload(existing_id, merged_payload)
            return existing_id
        else:
            # Insert new
            learning_id = str(uuid.uuid4())
            payload = {
                'learning_id': learning_id,
                'task_id': task_id,
                'learning_text': learning_text,
                'title': learning.get('title', ''),
                'knowledge': learning.get('knowledge', ''),
                'category': learning.get('category', 'general'),
                'confidence': float(learning.get('confidence', 0.5)),
                'generalizable': bool(learning.get('generalizable', False)),
                'task_domain': learning.get('task_type', ''),
                'created_at': datetime.utcnow().isoformat(),
                'source_iterations': learning.get('source_iterations', 1),
                'evidence_summary': learning.get('evidence_summary', ''),
                'version': 1
            }
            if learning.get('iteration_number') is not None:
                payload['iteration_number'] = learning['iteration_number']
            
            await self.qdrant_store.insert(learning_id, vector, payload)
            return learning_id

    async def store_batch(self, learnings: List[Dict], task_id: str) -> List[str]:
        """
        Store multiple learnings.
        """
        stored_ids = []
        for learning in learnings:
            lid = await self.store_synthesized_learning(learning, task_id)
            stored_ids.append(lid)
        return stored_ids

    async def get_memory_stats(self) -> Dict:
        """
        Real statistics computed from the vector store payloads.
        """
        payloads = await self.qdrant_store.scroll_payloads(limit=5000)
        total = len(payloads)

        global_count = 0
        confidences: List[float] = []
        recent = 0
        now = datetime.utcnow()

        for payload in payloads:
            if payload.get("generalizable"):
                global_count += 1
            try:
                confidences.append(float(payload.get("confidence")))
            except (TypeError, ValueError):
                pass
            created = payload.get("created_at")
            if isinstance(created, str):
                try:
                    if (now - datetime.fromisoformat(created.replace("Z", "+00:00").replace("+00:00", ""))).total_seconds() < 86400:
                        recent += 1
                except ValueError:
                    pass

        return {
            "total_memories": total,
            "global_count": global_count,
            "task_count": total - global_count,
            "avg_confidence": round(sum(confidences) / len(confidences), 4) if confidences else 0.0,
            "recent_additions": recent,
        }

    async def search_memories(self, query: str, top_k: int = 10, min_similarity: float = 0.5) -> List[Dict]:
        """
        For memory explorer UI - ignores retrieval_enabled setting.
        Returns a flat shape: {id, content, score, metadata}.
        """
        raw = await self.retriever.retrieve(
            query=query,
            top_k=top_k,
            min_similarity=min_similarity,
            scope='all'
        )

        results = []
        for item in raw or []:
            payload = item.get("payload") or {}
            results.append({
                "id": item.get("id"),
                "content": payload.get("knowledge") or payload.get("learning_text") or "",
                "score": item.get("score", 0.0),
                "metadata": {
                    "title": payload.get("title", ""),
                    "category": payload.get("category", ""),
                    "confidence": payload.get("confidence"),
                    "task_id": payload.get("task_id"),
                    "iteration_number": payload.get("iteration_number"),
                    "generalizable": payload.get("generalizable", False),
                    "created_at": payload.get("created_at"),
                },
            })
        return results
