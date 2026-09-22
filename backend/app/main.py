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
from app.memory.qdrant_store import QdrantStore
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
    
    # Init Qdrant Store (supports in-memory, local-disk and server modes)
    qdrant_store = QdrantStore(
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
    return {
        "status": "healthy",
        "database": "sqlite" if "sqlite" in settings.DATABASE_URL else "postgresql",
        "redis": "connected" if settings.use_redis else "in-process",
        "qdrant": "in-memory" if settings.QDRANT_URL == ":memory:"
                  else ("server" if settings.use_qdrant_server else "local-disk"),
    }
