"""Live experiment events: /ws/experiments/{experiment_id}?token=<JWT>."""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.auth import user_from_token
from app.database.connection import async_sessionmaker_db
from app.database.models import Experiment
from app.experiments.manager import channel_for

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/experiments/{experiment_id}")
async def experiment_events(websocket: WebSocket, experiment_id: str, token: str = ""):
    async with async_sessionmaker_db() as db:
        user = await user_from_token(token, db) if token else None
        experiment = await db.get(Experiment, experiment_id) if user else None
    if user is None or experiment is None or experiment.user_id != user.id:
        # 4401/4404-style close codes let the client stop retrying.
        await websocket.close(code=4401 if user is None else 4404)
        return

    await websocket.accept()
    bus = websocket.app.state.manager.bus
    channel = channel_for(experiment_id)
    queue = bus.subscribe(channel)
    try:
        while True:
            try:
                message = await asyncio.wait_for(queue.get(), timeout=20.0)
            except asyncio.TimeoutError:
                message = json.dumps({"type": "heartbeat"})
            await websocket.send_text(message)
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception as exc:  # never let one socket take down the server
        logger.warning(f"WebSocket error for experiment {experiment_id}: {exc}")
    finally:
        bus.unsubscribe(channel, queue)
