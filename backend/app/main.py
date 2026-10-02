"""
FastAPI main application.
Supports running with or without Docker/Redis/external services.
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging
import os

from app.config import settings
from app.database.connection import engine
from app.database.models import Base
from app.api.auth import router as auth_router
from app.api.tasks import router as tasks_router
from app.api.memory import router as memory_router
from app.api.settings_api import router as settings_router
from app.api.websocket import router as ws_router
from app.workers.job_manager import JobManager
from app.memory.embeddings import EmbeddingService
from app.memory.qdrant_store import get_qdrant_store
from app.memory.retriever import MemoryRetriever
from app.memory.memory_manager import MemoryManager
from app.learning.persistence import FileStorageManager

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure storage directory exists
    os.makedirs(settings.STORAGE_DIR, exist_ok=True)
    
    # Create DB tables (works for both SQLite and PostgreSQL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info(f"Database initialized: {settings.DATABASE_URL.split('://')[0]}")
    
    # Init Redis (optional)
    redis = None
    if settings.use_redis:
        try:
            from redis.asyncio import Redis
            redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
            await redis.ping()
            logger.info(f"Redis connected: {settings.REDIS_URL}")
        except Exception as e:
            logger.warning(f"Redis unavailable ({e}), using in-process mode")
            redis = None
    else:
        logger.info("Redis not configured, using in-process mode")
    
    app.state.redis = redis
    job_manager = JobManager(redis)
    app.state.job_manager = job_manager
    
    # Init Embedding Service
    embedding_service = EmbeddingService(settings.EMBEDDING_MODEL)
    app.state.embedding_service = embedding_service
    
    # Init Qdrant Store (supports in-memory, local-disk and server modes).
    # Shared per process: on-disk Qdrant takes an exclusive lock, so the API
    # layer and the task workers must use the same client instance.
    qdrant_store = get_qdrant_store(
        url=settings.QDRANT_URL,
        collection_name=settings.QDRANT_COLLECTION,
        dimension=settings.EMBEDDING_DIMENSION,
        api_key=settings.QDRANT_API_KEY,
    )
    try:
        await qdrant_store.initialize()
        logger.info(f"Qdrant initialized ({qdrant_store.mode}: {settings.QDRANT_URL})")
    except Exception as e:
        logger.warning(f"Qdrant initialization warning: {e}")
    app.state.qdrant_store = qdrant_store
    
    # Init Memory Retriever and Manager
    retriever = MemoryRetriever(
        embedding_service=embedding_service,
        qdrant_store=qdrant_store,
    )
    memory_manager = MemoryManager(
        embedding_service=embedding_service,
        qdrant_store=qdrant_store,
        retriever=retriever,
    )
    memory_manager.retrieval_enabled = settings.DEFAULT_USE_PERSISTENT_LEARNING
    app.state.memory_manager = memory_manager
    
    # File storage
    app.state.file_storage = FileStorageManager(settings.STORAGE_DIR)
    
    logger.info("=" * 50)
    logger.info("Autonomous Learning Agent API Ready")
    logger.info(f"  Database: {'SQLite' if 'sqlite' in settings.DATABASE_URL else 'PostgreSQL'}")
    logger.info(f"  Redis: {'connected' if redis else 'in-process mode'}")
    logger.info(f"  Qdrant: {'in-memory' if settings.QDRANT_URL == ':memory:' else settings.QDRANT_URL}")
    logger.info(f"  Ollama: {settings.OLLAMA_BASE_URL} ({settings.PRIMARY_MODEL})")
    logger.info("=" * 50)
    
    yield
    
    if redis:
        await redis.aclose()


app = FastAPI(lifespan=lifespan, title="Autonomous Learning Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api")
app.include_router(tasks_router, prefix="/api")
app.include_router(memory_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(ws_router)


@app.get("/api/health")
async def health_check():
    from app.config import settings as s
    return {
        "status": "healthy",
        "database": "sqlite" if "sqlite" in s.DATABASE_URL else "postgresql",
        "redis": "connected" if s.use_redis else "in-process",
        "qdrant": "in-memory" if s.QDRANT_URL == ":memory:"
                  else ("server" if s.use_qdrant_server else "local-disk"),
        "embedding_provider": s.EMBEDDING_PROVIDER,
        "hf_token_set": bool(s.HF_TOKEN),
        "synthesis_interval": s.DEFAULT_SYNTHESIS_INTERVAL,
        "qdrant_url": s.QDRANT_URL[:80] if s.QDRANT_URL else "",
        "qdrant_api_key_set": bool(s.QDRANT_API_KEY),
    }


@app.get("/api/debug/memory-test")
async def debug_memory_test():
    """End-to-end memory pipeline test (no auth needed for diagnostics).
    
    Tests: ensure collection → embed text → insert into Qdrant → scroll to verify → cleanup.
    Reports exactly which stage fails so the root cause is obvious.
    """
    import uuid as _uuid
    results = {"steps": {}}
    mm = app.state.memory_manager

    # Step 0: Ensure Qdrant collection exists
    try:
        await mm.qdrant_store.initialize()
        results["steps"]["0_collection_init"] = {
            "ok": True,
            "mode": mm.qdrant_store.mode,
            "collection": mm.qdrant_store.collection_name,
        }
    except Exception as e:
        results["steps"]["0_collection_init"] = {"ok": False, "error": str(e)[:300]}
        results["overall"] = "FAILED at Qdrant collection init"
        return results
    
    # Step 1: Test embedding
    try:
        vector = await mm.embedding_service.embed("diagnostic probe text for memory pipeline test")
        results["steps"]["1_embed"] = {"ok": True, "dims": len(vector), "provider": mm.embedding_service.provider}
    except Exception as e:
        results["steps"]["1_embed"] = {"ok": False, "error": str(e)[:300]}
        results["overall"] = "FAILED at embedding"
        return results
    
    # Step 2: Test Qdrant insert (use proper UUID, not prefixed string)
    probe_uuid = str(_uuid.uuid4())
    try:
        inserted = await mm.qdrant_store.insert(probe_uuid, vector, {
            "task_id": "__debug__",
            "title": "Memory pipeline test probe",
            "knowledge": "This is a diagnostic test point",
            "category": "debug",
            "confidence": 0.99,
            "generalizable": False,
            "created_at": "2026-01-01T00:00:00",
        })
        qdrant_err = getattr(mm.qdrant_store, 'last_error', None)
        results["steps"]["2_qdrant_insert"] = {
            "ok": inserted,
            "probe_id": probe_uuid,
            "last_error": qdrant_err,
        }
        if not inserted:
            results["overall"] = f"FAILED at Qdrant insert: {qdrant_err}"
            return results
    except Exception as e:
        results["steps"]["2_qdrant_insert"] = {"ok": False, "error": str(e)[:300]}
        results["overall"] = "FAILED at Qdrant insert (exception)"
        return results
    
    # Step 3: Verify via scroll
    try:
        payloads = await mm.qdrant_store.scroll_payloads(limit=100)
        found = any(p.get("task_id") == "__debug__" for p in payloads)
        results["steps"]["3_qdrant_scroll"] = {"ok": found, "total_points": len(payloads), "probe_found": found}
        if not found:
            results["overall"] = "FAILED at Qdrant scroll verification"
            return results
    except Exception as e:
        results["steps"]["3_qdrant_scroll"] = {"ok": False, "error": str(e)[:300]}
        results["overall"] = "FAILED at Qdrant scroll verification"
        return results
    
    # Step 4: Verify via stats
    try:
        stats = await mm.get_memory_stats()
        results["steps"]["4_stats"] = {"ok": True, **stats}
    except Exception as e:
        results["steps"]["4_stats"] = {"ok": False, "error": str(e)[:300]}
        results["overall"] = "FAILED at memory stats"
        return results
    
    # Step 5: Cleanup
    try:
        cleaned = await mm.qdrant_store.delete(probe_uuid)
        results["steps"]["5_cleanup"] = {"ok": cleaned}
        if not cleaned:
            results["overall"] = "FAILED at Qdrant cleanup"
            return results
    except Exception as e:
        results["steps"]["5_cleanup"] = {"ok": False, "error": str(e)[:300]}
        results["overall"] = "FAILED at Qdrant cleanup"
        return results
    
    # Step 6: Test search_memories (same path the Memory Explorer UI uses)
    # Insert a fresh probe, search semantically, verify match, cleanup
    search_probe_uuid = str(_uuid.uuid4())
    try:
        search_vector = await mm.embedding_service.embed("unique diagnostic knowledge about pipeline testing")
        await mm.qdrant_store.insert(search_probe_uuid, search_vector, {
            "task_id": "__search_test__",
            "title": "Pipeline search test",
            "knowledge": "Unique diagnostic knowledge about pipeline testing procedures",
            "learning_text": "Unique diagnostic knowledge about pipeline testing procedures",
            "category": "debug",
            "confidence": 0.95,
            "generalizable": False,
            "created_at": "2026-01-01T00:00:00",
        })
        # Now search using the Memory Explorer path
        search_results = await mm.search_memories(
            query="pipeline testing procedures",
            top_k=5,
            min_similarity=0.3,
        )
        found_probe = any(
            r.get("id") == search_probe_uuid or
            "pipeline testing" in (r.get("content") or "").lower()
            for r in search_results
        )
        results["steps"]["6_search"] = {
            "ok": found_probe,
            "results_count": len(search_results),
            "probe_found": found_probe,
            "sample_ids": [r.get("id") for r in search_results[:3]],
        }
        # Cleanup search probe
        await mm.qdrant_store.delete(search_probe_uuid)
        if not found_probe:
            results["overall"] = "FAILED at search: probe not found in results"
            return results
    except Exception as e:
        results["steps"]["6_search"] = {"ok": False, "error": str(e)[:300]}
        # Try cleanup
        try:
            await mm.qdrant_store.delete(search_probe_uuid)
        except Exception:
            pass
        results["overall"] = f"FAILED at search test: {str(e)[:150]}"
        return results
    
    results["overall"] = "ALL STEPS PASSED (including search)"
    return results
