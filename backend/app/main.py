"""FastAPI application: Minesweeper memory-vs-baseline learning experiments."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.experiments import router as experiments_router
from app.api.lessons import router as lessons_router
from app.api.memory import router as memory_router
from app.api.meta import router as meta_router
from app.api.websocket import router as ws_router
from app.config import settings
from app.database.connection import init_db
from app.experiments.manager import ExperimentManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.DATABASE_URL.startswith("sqlite"):
        os.makedirs("storage", exist_ok=True)
    await init_db()
    manager = ExperimentManager()
    interrupted = await manager.mark_interrupted_on_startup()
    if interrupted:
        logger.info(f"{interrupted} experiment(s) were running before the restart; they can be resumed.")
    app.state.manager = manager
    logger.info("Minesweeper Learning Agent ready (code-only agents%s)"
                % (", LLM agents enabled" if settings.ENABLE_LLM_AGENTS else ""))
    yield
    await manager.shutdown()


app = FastAPI(lifespan=lifespan, title="Minesweeper Learning Agent API")

origins = settings.cors_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    # Auth uses bearer tokens, not cookies, so credentials are never needed cross-origin.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api")
app.include_router(experiments_router, prefix="/api")
app.include_router(lessons_router, prefix="/api")
app.include_router(memory_router, prefix="/api")
app.include_router(meta_router, prefix="/api")
app.include_router(ws_router)


@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "database": "sqlite" if settings.DATABASE_URL.startswith("sqlite") else "postgresql",
        "agents": "code-only (no LLM)" + (", LLM agents enabled" if settings.ENABLE_LLM_AGENTS else ""),
    }
