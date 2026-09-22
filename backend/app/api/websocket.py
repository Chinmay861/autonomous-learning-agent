"""
WebSocket endpoint for real-time task events.
Works with both Redis pub/sub and in-process event bus.
"""
import asyncio
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/{task_id}")
@router.websocket("/ws/tasks/{task_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    task_id: str,
    token: str = None,
):
    await websocket.accept()
    
    redis = websocket.app.state.redis
    job_manager = websocket.app.state.job_manager
    
    try:
        if redis:
            # Redis mode: subscribe to Redis pub/sub channel
            pubsub = redis.pubsub()
            await pubsub.subscribe(f"task_events:{task_id}")
            try:
                while True:
                    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                    if message and message['type'] == 'message':
                        await websocket.send_text(message['data'])
                    await asyncio.sleep(0.05)
            finally:
                await pubsub.unsubscribe(f"task_events:{task_id}")
        else:
            # Local mode: subscribe to in-process event bus
            event_bus = job_manager.event_bus
            queue = event_bus.subscribe(f"task_events:{task_id}")
            try:
                while True:
                    try:
                        message = await asyncio.wait_for(queue.get(), timeout=1.0)
                        await websocket.send_text(message)
                    except asyncio.TimeoutError:
                        # Send heartbeat to detect disconnects
                        try:
                            await websocket.send_text(json.dumps({"type": "heartbeat"}))
                        except Exception:
                            break
            finally:
                event_bus.unsubscribe(f"task_events:{task_id}", queue)
                
    except WebSocketDisconnect:
        logger.info(f"Client disconnected from task {task_id}")
    except Exception as e:
        logger.error(f"WebSocket error for task {task_id}: {e}")
