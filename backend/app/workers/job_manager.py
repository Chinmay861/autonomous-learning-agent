"""
Job Manager - Manages agent task execution.
Supports two modes:
  - Redis mode: tasks queued in Redis, processed by separate worker
  - Local mode: tasks run in-process as asyncio background tasks (no Redis needed)
"""
import json
import asyncio
import logging
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


class InProcessEventBus:
    """Simple in-process pub/sub for WebSocket events when Redis is unavailable."""
    
    def __init__(self):
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
    
    async def publish(self, channel: str, message: str):
        if channel in self._subscribers:
            for queue in self._subscribers[channel]:
                await queue.put(message)
    
    def subscribe(self, channel: str) -> asyncio.Queue:
        if channel not in self._subscribers:
            self._subscribers[channel] = []
        queue = asyncio.Queue()
        self._subscribers[channel].append(queue)
        return queue
    
    def unsubscribe(self, channel: str, queue: asyncio.Queue):
        if channel in self._subscribers:
            self._subscribers[channel] = [q for q in self._subscribers[channel] if q is not queue]


class JobManager:
    """
    Manages task execution. Works in two modes:
    
    - Redis mode (redis != None): Pushes to Redis queue for worker process
    - Local mode (redis == None): Runs tasks directly as background asyncio tasks
    """
    
    def __init__(self, redis: Any = None):
        self.redis = redis
        self.event_bus = InProcessEventBus()
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._orchestrators: dict[str, Any] = {}
    
    @property
    def is_local_mode(self) -> bool:
        return self.redis is None
    
    async def enqueue_task(self, task_config: dict) -> str:
        """Queue a task for execution."""
        task_id = task_config['task_id']
        
        if self.redis:
            # Redis mode: push to queue for separate worker
            await self.redis.lpush('task_queue', json.dumps(task_config))
            logger.info(f"Task {task_id} enqueued to Redis")
        else:
            # Local mode: run in-process
            from app.workers.task_worker import process_task_local
            
            async_task = asyncio.create_task(
                process_task_local(task_config, self.event_bus, self)
            )
            self._running_tasks[task_id] = async_task
            logger.info(f"Task {task_id} started in-process")
        
        return task_id
    
    async def pause_task(self, task_id: str):
        if self.redis:
            await self.redis.publish(f'task_control:{task_id}', json.dumps({'command': 'pause'}))
        if task_id in self._orchestrators:
            self._orchestrators[task_id].pause()
    
    async def resume_task(self, task_id: str):
        if self.redis:
            await self.redis.publish(f'task_control:{task_id}', json.dumps({'command': 'resume'}))
        if task_id in self._orchestrators:
            self._orchestrators[task_id].resume()
    
    async def stop_task(self, task_id: str):
        if self.redis:
            await self.redis.publish(f'task_control:{task_id}', json.dumps({'command': 'stop'}))
        if task_id in self._orchestrators:
            self._orchestrators[task_id].stop()
        if task_id in self._running_tasks:
            t = self._running_tasks[task_id]
            if not t.done():
                t.cancel()
            self._running_tasks.pop(task_id, None)
            self._orchestrators.pop(task_id, None)
    
    def register_orchestrator(self, task_id: str, orchestrator: Any):
        """Register an orchestrator for local-mode control."""
        self._orchestrators[task_id] = orchestrator
    
    def set_task_persistent_learning(self, task_id: str, enabled: bool):
        """Update persistent learning retrieval flag on an active orchestrator dynamically."""
        if task_id in self._orchestrators:
            orch = self._orchestrators[task_id]
            orch.retrieval_enabled = enabled
            if hasattr(orch, "memory_manager") and orch.memory_manager:
                orch.memory_manager.retrieval_enabled = enabled
            logger.info(f"Updated persistent learning retrieval for active task {task_id} to {enabled}")

    def unregister_orchestrator(self, task_id: str):
        self._orchestrators.pop(task_id, None)
        self._running_tasks.pop(task_id, None)
