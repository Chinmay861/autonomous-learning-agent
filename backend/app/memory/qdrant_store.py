"""
Qdrant vector store - supports both server mode and in-memory local mode.
When url=':memory:', runs entirely in-process with no external server needed.
"""
import asyncio
import os
from typing import Any, Dict, List, Optional
import uuid
import logging

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models
except ImportError:
    QdrantClient = Any
    models = Any

logger = logging.getLogger(__name__)


class QdrantStore:
    def __init__(self, url: str = 'http://localhost:6333', collection_name: str = 'agent_learnings',
                 dimension: int = 384, api_key: str = ""):
        self.url = url
        self.collection_name = collection_name
        self.dimension = dimension
        self.api_key = api_key or ""
        # Preserve the most recent backend error.  The caller needs to tell an
        # empty collection apart from a rejected vector write.
        self.last_error: str | None = None

        # In-memory mode: no server needed
        if url == ":memory:":
            self.client = QdrantClient(location=":memory:")
            self.mode = "in-memory"
            logger.info("Qdrant running in IN-MEMORY mode (no server required)")
        elif url.startswith("http://") or url.startswith("https://"):
            self.client = QdrantClient(url=self.url, api_key=self.api_key or None)
            self.mode = "server"
            logger.info(f"Qdrant connecting to server at {url}")
        else:
            # Local on-disk mode: data survives restarts, single process
            path = os.path.abspath(url)
            os.makedirs(path, exist_ok=True)
            self.client = QdrantClient(path=path)
            self.mode = "local-disk"
            logger.info(f"Qdrant running in LOCAL DISK mode at {path}")

    async def initialize(self) -> None:
        def _init_sync():
            collections = self.client.get_collections().collections
            if not any(c.name == self.collection_name for c in collections):
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=models.VectorParams(
                        size=self.dimension,
                        distance=models.Distance.COSINE
                    )
                )
                
                # Create payload indexes
                indexes = [
                    ("category", models.PayloadSchemaType.KEYWORD),
                    ("task_id", models.PayloadSchemaType.KEYWORD),
                    ("confidence", models.PayloadSchemaType.FLOAT),
                    ("generalizable", models.PayloadSchemaType.BOOL),
                ]
                for field_name, schema_type in indexes:
                    try:
                        self.client.create_payload_index(
                            collection_name=self.collection_name,
                            field_name=field_name,
                            field_schema=schema_type
                        )
                    except Exception:
                        pass  # Index may already exist
                        
        try:
            await asyncio.to_thread(_init_sync)
            self.last_error = None
        except Exception as e:
            self.last_error = str(e)
            raise

    async def insert(self, id: str, vector: list[float], payload: dict) -> bool:
        def _insert_sync():
            self.client.upsert(
                collection_name=self.collection_name,
                points=[
                    models.PointStruct(
                        id=id,
                        vector=vector,
                        payload=payload
                    )
                ]
            )
            return True
            
        try:
            inserted = await asyncio.to_thread(_insert_sync)
            self.last_error = None
            return inserted
        except Exception as e:
            self.last_error = str(e)
            logger.error(f"Error inserting to Qdrant: {e}")
            return False

    async def search(self, query_vector: list[float], limit: int = 5, min_score: float = 0.65, filters: Optional[dict] = None) -> list[dict]:
        def _search_sync():
            qdrant_filter = None
            if filters:
                must_conditions = []
                if "task_id" in filters:
                    must_conditions.append(
                        models.FieldCondition(key="task_id", match=models.MatchValue(value=filters["task_id"]))
                    )
                if "category" in filters:
                    must_conditions.append(
                        models.FieldCondition(key="category", match=models.MatchValue(value=filters["category"]))
                    )
                if "generalizable" in filters:
                    must_conditions.append(
                        models.FieldCondition(key="generalizable", match=models.MatchValue(value=filters["generalizable"]))
                    )
                if "min_confidence" in filters:
                    must_conditions.append(
                        models.FieldCondition(key="confidence", range=models.Range(gte=filters["min_confidence"]))
                    )
                    
                if must_conditions:
                    qdrant_filter = models.Filter(must=must_conditions)
                    
            if hasattr(self.client, 'query_points'):
                search_res = self.client.query_points(
                    collection_name=self.collection_name,
                    query=query_vector,
                    query_filter=qdrant_filter,
                    limit=limit,
                    score_threshold=min_score
                )
                hits = search_res.points
            else:
                hits = self.client.search(
                    collection_name=self.collection_name,
                    query_vector=query_vector,
                    query_filter=qdrant_filter,
                    limit=limit,
                    score_threshold=min_score
                )
            
            return [{"id": str(hit.id), "score": getattr(hit, 'score', 0.0), "payload": hit.payload} for hit in hits]
            
        return await asyncio.to_thread(_search_sync)

    async def update_payload(self, id: str, payload: dict) -> bool:
        def _update_sync():
            self.client.set_payload(
                collection_name=self.collection_name,
                payload=payload,
                points=[id]
            )
            return True
            
        try:
            return await asyncio.to_thread(_update_sync)
        except Exception as e:
            self.last_error = str(e)
            logger.error(f"Error updating Qdrant payload: {e}")
            return False

    async def delete(self, id: str) -> bool:
        def _delete_sync():
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=models.PointIdsList(
                    points=[id],
                )
            )
            return True
            
        try:
            return await asyncio.to_thread(_delete_sync)
        except Exception:
            return False

    async def find_duplicates(self, vector: list[float], threshold: float = 0.92) -> list[dict]:
        return await self.search(query_vector=vector, limit=5, min_score=threshold)

    async def get_stats(self) -> dict:
        def _stats_sync():
            try:
                collection_info = self.client.get_collection(collection_name=self.collection_name)
                return {
                    "total_points": collection_info.points_count,
                    "status": str(collection_info.status),
                    "segments_count": collection_info.segments_count
                }
            except Exception:
                return {"total_points": 0, "status": "unknown", "segments_count": 0}
        return await asyncio.to_thread(_stats_sync)

    async def get_all_by_task(self, task_id: str) -> list[dict]:
        def _scroll_sync():
            records, _ = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="task_id", 
                            match=models.MatchValue(value=task_id)
                        )
                    ]
                ),
                limit=10000,
                with_payload=True,
                with_vectors=False
            )
            return [{"id": str(r.id), "payload": r.payload} for r in records]
            
        return await asyncio.to_thread(_scroll_sync)

    async def scroll_payloads(self, limit: int = 5000) -> list[dict]:
        """Return payloads for up to `limit` points (used for stats aggregation)."""
        def _scroll_sync():
            records, _ = self.client.scroll(
                collection_name=self.collection_name,
                limit=limit,
                with_payload=True,
                with_vectors=False,
            )
            return [dict(r.payload or {}) for r in records]

        try:
            return await asyncio.to_thread(_scroll_sync)
        except Exception as e:
            logger.warning(f"Could not scroll Qdrant payloads: {e}")
            return []


_store_cache: dict = {}


def get_qdrant_store(url: str = 'http://localhost:6333', collection_name: str = 'agent_learnings',
                     dimension: int = 384, api_key: str = "") -> "QdrantStore":
    """Return the process-wide QdrantStore for the given configuration.

    On-disk Qdrant (QdrantClient path mode) takes an exclusive file lock, so a
    second client on the same path raises AlreadyLocked. Every in-process user
    (API lifespan, task workers) must share one client per configuration.
    """
    key = (url, collection_name, dimension, api_key or "")
    store = _store_cache.get(key)
    if store is None:
        store = QdrantStore(url=url, collection_name=collection_name, dimension=dimension, api_key=api_key or "")
        _store_cache[key] = store
    return store
