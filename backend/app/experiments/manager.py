"""Owns the running experiments of this process and fans their events out to WebSocket clients."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import httpx
from sqlalchemy import select, update

from app.config import settings
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
        self._keep_alive_task: asyncio.Task | None = None

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
        self._ensure_keep_alive()

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

    async def recover_on_startup(self) -> dict[str, int]:
        """After a restart (deploy, crash, or the host putting the service to sleep):

        * code-only experiments that were running continue automatically at the next unfinished board;
        * paused ones stay paused (Resume starts them again);
        * LLM experiments are never restarted on their own (they would spend API quota unattended):
          they are marked "interrupted" for the user to continue.
        """
        async with self.session_factory() as session:
            rows = (await session.execute(
                select(Experiment.id, Experiment.status, Experiment.agent_type)
                .where(Experiment.status.in_([ExperimentStatus.RUNNING.value, ExperimentStatus.PAUSED.value]))
            )).all()
            to_resume, to_interrupt = [], []
            for experiment_id, status, agent_type in rows:
                if agent_type == "llm" or (status == ExperimentStatus.RUNNING.value
                                           and not settings.AUTO_RESUME_INTERRUPTED):
                    to_interrupt.append(experiment_id)
                elif status == ExperimentStatus.RUNNING.value:
                    to_resume.append(experiment_id)
            if to_interrupt:
                await session.execute(
                    update(Experiment).where(Experiment.id.in_(to_interrupt))
                    .values(status=ExperimentStatus.INTERRUPTED.value)
                )
                await session.commit()
        for experiment_id in to_resume:
            await self.start(experiment_id)
        return {"resumed": len(to_resume), "interrupted": len(to_interrupt)}

    # ------------------------------------------------------------------ keep-alive
    @staticmethod
    def keep_alive_url() -> str | None:
        """Where to ping to keep the host awake: KEEP_ALIVE_URL, or Render's own public URL."""
        base = settings.KEEP_ALIVE_URL or os.environ.get("RENDER_EXTERNAL_URL", "")
        return f"{base.rstrip('/')}/api/health" if base else None

    def _ensure_keep_alive(self) -> None:
        if self.keep_alive_url() and (self._keep_alive_task is None or self._keep_alive_task.done()):
            self._keep_alive_task = asyncio.create_task(self._keep_alive(), name="keep-alive")

    async def _keep_alive(self) -> None:
        """Free hosting (e.g. Render) stops a service after ~15 minutes without incoming requests, which
        would kill a long experiment. While any experiment runs, request our own public URL now and then.
        It stops by itself when nothing is running, so an idle service can still sleep."""
        url = self.keep_alive_url()
        async with httpx.AsyncClient(timeout=30.0) as client:
            while any(not task.done() for task in self._tasks.values()):
                await asyncio.sleep(settings.KEEP_ALIVE_SECONDS)
                if not any(not task.done() for task in self._tasks.values()):
                    break
                try:
                    await client.get(url)
                except Exception as exc:
                    logger.warning(f"Keep-alive request to {url} failed: {exc}")

    async def shutdown(self) -> None:
        tasks = list(self._tasks.values())
        if self._keep_alive_task is not None:
            tasks.append(self._keep_alive_task)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
