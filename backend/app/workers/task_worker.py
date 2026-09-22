"""
Task Worker - Processes agent tasks.
Supports two modes:
  - Redis mode: runs as separate process, pulls from Redis queue
  - Local mode: called directly by JobManager as asyncio background task
"""
import asyncio
import json
import logging
import traceback

from sqlalchemy import select

from app.config import settings
from app.database.connection import async_sessionmaker_db as AsyncSessionLocal
from app.database.models import Task, TaskStatus
from app.models.llm_provider import OllamaProvider
from app.environments.benchmark_env import BenchmarkEnvironment
from app.agents.orchestrator import AgentOrchestrator
from app.memory.memory_manager import MemoryManager
from app.memory.qdrant_store import QdrantStore
from app.memory.embeddings import EmbeddingService
from app.memory.retriever import MemoryRetriever

logger = logging.getLogger(__name__)


async def update_task_status(task_id: str, status: TaskStatus, iteration: int | None = None):
    """Update task status in database."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Task).where(Task.id == task_id))
        task = result.scalar_one_or_none()
        if task:
            task.status = status
            if iteration is not None:
                task.current_iteration = iteration
            await db.commit()


def _create_memory_stack():
    """Create the memory system components."""
    embedding_service = EmbeddingService(settings.EMBEDDING_MODEL)
    qdrant_store = QdrantStore(
        url=settings.QDRANT_URL,
        collection_name=settings.QDRANT_COLLECTION,
        dimension=settings.EMBEDDING_DIMENSION,
    )
    retriever = MemoryRetriever(
        embedding_service=embedding_service,
        qdrant_store=qdrant_store,
    )
    memory_manager = MemoryManager(
        embedding_service=embedding_service,
        qdrant_store=qdrant_store,
        retriever=retriever,
    )
    return embedding_service, qdrant_store, memory_manager


async def _run_orchestrator(task_config: dict, event_callback) -> None:
    """Common orchestrator setup and execution."""
    task_id = task_config["task_id"]
    logger.info(f"Processing task {task_id}: {task_config.get('title', 'Untitled')}")

    await update_task_status(task_id, TaskStatus.RUNNING)

    # Create LLM provider
    from app.models.llm_provider import get_llm_provider
    llm = get_llm_provider({
        "model": task_config.get("model", settings.PRIMARY_MODEL),
    })

    # Create environment dynamically based on task
    from app.environments import get_environment_for_task
    env = get_environment_for_task(task_config, llm)

    # Create memory system
    _, qdrant_store, memory_manager = _create_memory_stack()
    try:
        await qdrant_store.initialize()
    except Exception as e:
        logger.warning(f"Qdrant init warning: {e}")

    memory_manager.retrieval_enabled = task_config.get(
        "use_persistent_learning", settings.DEFAULT_USE_PERSISTENT_LEARNING
    )

    # Create orchestrator
    orchestrator = AgentOrchestrator(
        llm=llm,
        environment=env,
        task_id=task_id,
        task_description=task_config.get("description", ""),
        max_iterations=task_config.get("max_iterations", settings.DEFAULT_MAX_ITERATIONS),
        use_persistent_learning=task_config.get(
            "use_persistent_learning", settings.DEFAULT_USE_PERSISTENT_LEARNING
        ),
        snapshot_interval=task_config.get("snapshot_interval", settings.DEFAULT_SNAPSHOT_INTERVAL),
        synthesis_interval=task_config.get("synthesis_interval", settings.DEFAULT_SYNTHESIS_INTERVAL),
        storage_dir=settings.STORAGE_DIR,
        top_k=task_config.get("top_k", settings.DEFAULT_TOP_K),
        min_similarity=task_config.get("min_similarity", settings.DEFAULT_MIN_SIMILARITY),
        memory_manager=memory_manager,
        event_callback=event_callback,
    )

    return orchestrator


# ============================================================
# LOCAL MODE - runs in-process, no Redis needed
# ============================================================

async def process_task_local(task_config: dict, event_bus, job_manager: Any = None) -> None:
    """Process a task in local (in-process) mode. No Redis required."""
    task_id = task_config["task_id"]
    
    async def local_event_callback(event_type: str, data: dict):
        """Publish events via in-process event bus."""
        channel = f"task_events:{task_id}"
        await event_bus.publish(channel, json.dumps({"type": event_type, "data": data, **data}, default=str))
    
    try:
        orchestrator = await _run_orchestrator(task_config, local_event_callback)
        if job_manager:
            job_manager.register_orchestrator(task_id, orchestrator)
        
        final_state = await orchestrator.run()
        
        if final_state.completion_status == "completed":
            await update_task_status(task_id, TaskStatus.COMPLETED, final_state.iteration)
        elif final_state.completion_status == "stopped":
            await update_task_status(task_id, TaskStatus.STOPPED, final_state.iteration)
        else:
            await update_task_status(task_id, TaskStatus.COMPLETED, final_state.iteration)
            
        logger.info(f"Task {task_id} finished: {final_state.completion_status} at iteration {final_state.iteration}")
        
    except asyncio.CancelledError:
        logger.info(f"Task {task_id} was cancelled.")
        await update_task_status(task_id, TaskStatus.STOPPED)
        try:
            await local_event_callback("status_changed", {"status": "STOPPED", "completion_status": "stopped"})
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Error processing task {task_id}: {e}\n{traceback.format_exc()}")
        await update_task_status(task_id, TaskStatus.FAILED)
    finally:
        if job_manager:
            job_manager.unregister_orchestrator(task_id)


# ============================================================
# REDIS MODE - runs as separate worker process
# ============================================================

async def process_task_redis(redis, task_config: dict) -> None:
    """Process a task using Redis for events and commands."""
    task_id = task_config["task_id"]

    async def redis_event_callback(event_type: str, data: dict):
        channel = f"task_events:{task_id}"
        await redis.publish(channel, json.dumps({"type": event_type, "data": data, **data}, default=str))

    try:
        orchestrator = await _run_orchestrator(task_config, redis_event_callback)

        # Listen for control commands
        async def listen_for_commands():
            pubsub = redis.pubsub()
            await pubsub.subscribe(f"task_control:{task_id}")
            try:
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        data = json.loads(message["data"])
                        command = data.get("command")
                        if command == "pause":
                            orchestrator.pause()
                        elif command == "resume":
                            orchestrator.resume()
                        elif command == "stop":
                            orchestrator.stop()
            except asyncio.CancelledError:
                pass
            finally:
                await pubsub.unsubscribe(f"task_control:{task_id}")

        command_task = asyncio.create_task(listen_for_commands())

        try:
            final_state = await orchestrator.run()
            if final_state.completion_status == "completed":
                await update_task_status(task_id, TaskStatus.COMPLETED, final_state.iteration)
            elif final_state.completion_status == "stopped":
                await update_task_status(task_id, TaskStatus.STOPPED, final_state.iteration)
            else:
                await update_task_status(task_id, TaskStatus.COMPLETED, final_state.iteration)
        except Exception as e:
            logger.error(f"Orchestrator error: {e}\n{traceback.format_exc()}")
            await update_task_status(task_id, TaskStatus.FAILED)
        finally:
            command_task.cancel()

    except Exception as e:
        logger.error(f"Error processing task {task_id}: {e}\n{traceback.format_exc()}")
        await update_task_status(task_id, TaskStatus.FAILED)


async def run_worker():
    """Main Redis worker loop - pulls tasks from Redis queue."""
    from redis.asyncio import Redis
    
    redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    logger.info("=" * 60)
    logger.info("Task Worker Started (Redis mode)")
    logger.info(f"Redis: {settings.REDIS_URL}")
    logger.info("Waiting for tasks...")
    logger.info("=" * 60)

    try:
        while True:
            try:
                result = await redis.brpop("task_queue", timeout=5)
                if result:
                    _, task_data = result
                    task_config = json.loads(task_data)
                    logger.info(f"Received task: {task_config.get('task_id')}")
                    await process_task_redis(redis, task_config)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in worker loop: {e}")
                await asyncio.sleep(2)
    finally:
        await redis.aclose()
        logger.info("Task worker shut down.")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    asyncio.run(run_worker())
