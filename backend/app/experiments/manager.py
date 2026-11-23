"""Owns the running experiments of this process and fans their events out to WebSocket clients."""
from __future__ import annotations

import asyncio
import json
from typing import Any
import logging

from sqlalchemy import update

from app.database.connection import async_sessionmaker_db
from app.database.models import Experiment, ExperimentStatus
from app.experiments.pattern_runner import PatternRunner

logger = logging.getLogger(__name__)


class EventBus:
    """In-process pub/sub. Each subscriber gets a bounded queue; a slow client drops its oldest events."""

    def __init__(self, max_queue: int = 2000):
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._max_queue = max_queue

    async def publish(self, channel: str, message: dict) -> None:
        text = json.dumps(message, default=str)
        for queue in list(self._subscribers.get(channel, [])):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(text)

    def subscribe(self, channel: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._max_queue)
        self._subscribers.setdefault(channel, []).append(queue)
        return queue

    def unsubscribe(self, channel: str, queue: asyncio.Queue) -> None:
        subscribers = self._subscribers.get(channel, [])
        if queue in subscribers:
            subscribers.remove(queue)
        if not subscribers:
            self._subscribers.pop(channel, None)


def channel_for(experiment_id: str) -> str:
    return f"experiment:{experiment_id}"


class ExperimentManager:
    def __init__(self, session_factory=async_sessionmaker_db, runner_factory=None):
        self.session_factory = session_factory
        # None = pick by the experiment's agent_type (code-only agents unless it is an LLM experiment).
        self.runner_factory = runner_factory
        self.bus = EventBus()
        self._runners: dict[str, Any] = {}  # PatternRunner, or ExperimentRunner for LLM experiments
        self._tasks: dict[str, asyncio.Task] = {}

    def is_running(self, experiment_id: str) -> bool:
        task = self._tasks.get(experiment_id)
        return task is not None and not task.done()

    def runner(self, experiment_id: str) -> Any | None:
        return self._runners.get(experiment_id) if self.is_running(experiment_id) else None

    async def start(self, experiment_id: str) -> None:
        """Start, or continue from the next unfinished game."""
        if self.is_running(experiment_id):
            runner = self._runners[experiment_id]
            if runner.paused:
                await runner.resume()
            return

        channel = channel_for(experiment_id)

        async def publish(event: dict) -> None:
            await self.bus.publish(channel, {"experiment_id": experiment_id, **event})

        factory = self.runner_factory or await self._factory_for(experiment_id)
        runner = factory(experiment_id, publish, session_factory=self.session_factory)
        self._runners[experiment_id] = runner
        task = asyncio.create_task(runner.run(), name=f"experiment-{experiment_id}")
        self._tasks[experiment_id] = task

        def _done(t: asyncio.Task) -> None:
            self._tasks.pop(experiment_id, None)
            self._runners.pop(experiment_id, None)
            if not t.cancelled() and t.exception() is not None:
                logger.error(f"Experiment {experiment_id} crashed", exc_info=t.exception())

        task.add_done_callback(_done)

    async def _factory_for(self, experiment_id: str):
        async with self.session_factory() as session:
            exp = await session.get(Experiment, experiment_id)
        if exp is not None and exp.agent_type == "llm":
            from app.experiments.runner import ExperimentRunner  # LLM agents: kept, off by default

            return ExperimentRunner
        return PatternRunner

    async def pause(self, experiment_id: str) -> bool:
        runner = self.runner(experiment_id)
        if runner is None:
            return False
        await runner.pause()
        return True

    async def stop(self, experiment_id: str) -> bool:
        runner = self.runner(experiment_id)
        if runner is None:
            return False
        runner.stop()
        return True

    def live(self, experiment_id: str) -> dict | None:
        runner = self.runner(experiment_id)
        return runner.live if runner else None

    async def mark_interrupted_on_startup(self) -> int:
        """Experiments that were running when the process died can be resumed by the user."""
        async with self.session_factory() as session:
            result = await session.execute(
                update(Experiment)
                .where(Experiment.status.in_([ExperimentStatus.RUNNING.value, ExperimentStatus.PAUSED.value]))
                .values(status=ExperimentStatus.INTERRUPTED.value)
            )
            await session.commit()
            return result.rowcount or 0

    async def shutdown(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
