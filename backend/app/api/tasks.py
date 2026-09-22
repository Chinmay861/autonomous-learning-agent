"""
Task API endpoints - CRUD operations and execution control.
"""
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import os
import json
from datetime import datetime, timezone

from app.config import settings
from app.database.connection import get_db
from app.database.models import Task, User, TaskStatus, Iteration, Rule, LearningRecord, Snapshot
from app.schemas.task import (
    TaskCreate, TaskResponse, TaskUpdate,
    IterationResponse, RuleResponse, LearningResponse, SnapshotResponse,
)
from app.api.auth import get_current_user
from app.api.dependencies import get_job_manager, get_file_storage
from app.workers.job_manager import JobManager
from app.learning.persistence import FileStorageManager, SnapshotManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=TaskResponse)
async def create_task(
    task_in: TaskCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pl = task_in.persistent_learning if task_in.persistent_learning is not None else task_in.use_persistent_learning
    if pl is None:
        pl = settings.DEFAULT_USE_PERSISTENT_LEARNING

    new_task = Task(
        title=task_in.title if hasattr(task_in, 'title') else "Untitled",
        description=task_in.description,
        max_iterations=task_in.max_iterations,
        snapshot_interval=getattr(task_in, 'snapshot_interval', settings.DEFAULT_SNAPSHOT_INTERVAL),
        synthesis_interval=getattr(task_in, 'synthesis_interval', settings.DEFAULT_SYNTHESIS_INTERVAL),
        use_persistent_learning=bool(pl),
        top_k=getattr(task_in, 'top_k', settings.DEFAULT_TOP_K),
        min_similarity=getattr(task_in, 'min_similarity', settings.DEFAULT_MIN_SIMILARITY),
        model=getattr(task_in, 'model', settings.PRIMARY_MODEL),
        temperature=getattr(task_in, 'temperature', settings.DEFAULT_TEMPERATURE),
        user_id=current_user.id,
    )
    db.add(new_task)
    await db.commit()
    await db.refresh(new_task)
    return new_task


@router.get("", response_model=List[TaskResponse])
async def list_tasks(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Task).where(Task.user_id == current_user.id).order_by(Task.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Task).where(Task.id == task_id, Task.user_id == current_user.id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.patch("/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: str,
    task_in: TaskUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    job_manager: JobManager = Depends(get_job_manager),
):
    task = await get_task(task_id, db, current_user)
    if task_in.title is not None:
        task.title = task_in.title
    if task_in.description is not None:
        task.description = task_in.description
    if task_in.status is not None:
        task.status = task_in.status

    target_learning = None
    if task_in.persistent_learning is not None:
        target_learning = task_in.persistent_learning
    elif task_in.use_persistent_learning is not None:
        target_learning = task_in.use_persistent_learning

    if target_learning is not None:
        task.use_persistent_learning = bool(target_learning)
        if hasattr(job_manager, "set_task_persistent_learning"):
            job_manager.set_task_persistent_learning(task_id, bool(target_learning))

    await db.commit()
    await db.refresh(task)
    return task


@router.post("/{task_id}/toggle-learning", response_model=TaskResponse)
async def toggle_task_learning(
    task_id: str,
    payload: Optional[dict] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    job_manager: JobManager = Depends(get_job_manager),
):
    task = await get_task(task_id, db, current_user)
    if payload and "persistent_learning" in payload and payload["persistent_learning"] is not None:
        target_state = bool(payload["persistent_learning"])
    elif payload and "use_persistent_learning" in payload and payload["use_persistent_learning"] is not None:
        target_state = bool(payload["use_persistent_learning"])
    else:
        target_state = not task.use_persistent_learning

    task.use_persistent_learning = target_state
    await db.commit()
    await db.refresh(task)

    if hasattr(job_manager, "set_task_persistent_learning"):
        job_manager.set_task_persistent_learning(task_id, target_state)

    return task


@router.post("/{task_id}/start")
async def start_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    job_manager: JobManager = Depends(get_job_manager),
):
    task = await get_task(task_id, db, current_user)

    # Send full configuration to the worker
    await job_manager.enqueue_task({
        "task_id": str(task.id),
        "title": task.title,
        "description": task.description,
        "max_iterations": task.max_iterations,
        "snapshot_interval": task.snapshot_interval,
        "synthesis_interval": task.synthesis_interval,
        "use_persistent_learning": task.use_persistent_learning,
        "top_k": task.top_k,
        "min_similarity": task.min_similarity,
        "model": task.model or settings.PRIMARY_MODEL,
        "temperature": task.temperature or settings.DEFAULT_TEMPERATURE,
    })

    task.status = TaskStatus.RUNNING
    await db.commit()
    if hasattr(job_manager, "event_bus") and job_manager.event_bus:
        await job_manager.event_bus.publish(
            f"task_events:{task_id}",
            json.dumps({"type": "status_changed", "status": "RUNNING", "data": {"status": "RUNNING"}})
        )
    return {"status": "started", "task_id": str(task.id)}


@router.post("/{task_id}/pause")
async def pause_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    job_manager: JobManager = Depends(get_job_manager),
):
    task = await get_task(task_id, db, current_user)
    await job_manager.pause_task(task_id)
    task.status = TaskStatus.PAUSED
    await db.commit()
    if hasattr(job_manager, "event_bus") and job_manager.event_bus:
        await job_manager.event_bus.publish(
            f"task_events:{task_id}",
            json.dumps({"type": "status_changed", "status": "PAUSED", "data": {"status": "PAUSED"}})
        )
    return {"status": "paused", "task_id": task_id}


@router.post("/{task_id}/resume")
async def resume_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    job_manager: JobManager = Depends(get_job_manager),
):
    task = await get_task(task_id, db, current_user)
    if task_id not in job_manager._running_tasks or job_manager._running_tasks[task_id].done():
        await job_manager.enqueue_task({
            "task_id": str(task.id),
            "title": task.title,
            "description": task.description,
            "max_iterations": task.max_iterations,
            "snapshot_interval": task.snapshot_interval,
            "synthesis_interval": task.synthesis_interval,
            "use_persistent_learning": task.use_persistent_learning,
            "top_k": task.top_k,
            "min_similarity": task.min_similarity,
            "model": task.model or settings.PRIMARY_MODEL,
            "temperature": task.temperature or settings.DEFAULT_TEMPERATURE,
        })
    else:
        await job_manager.resume_task(task_id)
    task.status = TaskStatus.RUNNING
    await db.commit()
    if hasattr(job_manager, "event_bus") and job_manager.event_bus:
        await job_manager.event_bus.publish(
            f"task_events:{task_id}",
            json.dumps({"type": "status_changed", "status": "RUNNING", "data": {"status": "RUNNING"}})
        )
    return {"status": "resumed", "task_id": task_id}


@router.post("/{task_id}/stop")
async def stop_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    job_manager: JobManager = Depends(get_job_manager),
):
    task = await get_task(task_id, db, current_user)
    await job_manager.stop_task(task_id)
    task.status = TaskStatus.STOPPED
    await db.commit()
    if hasattr(job_manager, "event_bus") and job_manager.event_bus:
        await job_manager.event_bus.publish(
            f"task_events:{task_id}",
            json.dumps({"type": "status_changed", "status": "STOPPED", "data": {"status": "STOPPED"}})
        )
    return {"status": "stopped", "task_id": task_id}


@router.get("/{task_id}/iterations")
async def list_iterations(
    task_id: str,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await get_task(task_id, db, current_user)
    result = await db.execute(
        select(Iteration)
        .where(Iteration.task_id == task_id)
        .order_by(Iteration.iteration_number)
        .offset(skip)
        .limit(limit)
    )
    rows = result.scalars().all()
    formatted = []
    for r in rows:
        formatted.append({
            "id": str(r.id),
            "task_id": r.task_id,
            "iteration_number": r.iteration_number,
            "observation": r.observation or "",
            "hypothesis": r.hypothesis or "",
            "action": json.dumps(r.action) if isinstance(r.action, dict) else str(r.action or ""),
            "result": r.action_result or "",
            "action_result": r.action_result or "",
        })
    if not formatted:
        history_file = os.path.join(settings.STORAGE_DIR, "tasks", task_id, "history.json")
        if os.path.exists(history_file):
            try:
                with open(history_file, "r", encoding="utf-8") as f:
                    hist = json.load(f)
                for h in hist:
                    formatted.append({
                        "id": f"{task_id}_{h.get('iteration', 1)}",
                        "task_id": task_id,
                        "iteration_number": h.get("iteration", 1),
                        "observation": "Phase: calm, Energy: high",
                        "hypothesis": h.get("hypothesis", ""),
                        "action": json.dumps(h.get("action", {}), indent=2) if isinstance(h.get("action"), (dict, list)) else str(h.get("action", "")),
                        "result": h.get("result_summary", ""),
                        "action_result": h.get("result_summary", ""),
                        "evaluation": f"Success: {h.get('success')}, Reward: {h.get('reward', 0)}",
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "timestamp": datetime.now(timezone.utc)
                    })
            except Exception as e:
                logger.warning(f"Error reading history fallback: {e}")
    return formatted


@router.get("/{task_id}/learnings")
async def get_learnings(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await get_task(task_id, db, current_user)
    result = await db.execute(
        select(LearningRecord)
        .where(LearningRecord.task_id == task_id)
        .order_by(LearningRecord.created_at)
    )
    db_learnings = result.scalars().all()
    if db_learnings:
        return [{
            "id": str(l.id),
            "task_id": l.task_id,
            "content": l.content,
            "category": l.category.value if hasattr(l.category, 'value') else str(l.category),
            "iteration_number": l.iteration_number,
            "created_at": l.created_at.isoformat() if l.created_at else datetime.now(timezone.utc).isoformat()
        } for l in db_learnings]
        
    # Read from learnings.txt if present
    learnings_file = os.path.join(settings.STORAGE_DIR, "tasks", task_id, "learnings.txt")
    if os.path.exists(learnings_file):
        try:
            items = []
            with open(learnings_file, "r", encoding="utf-8") as f:
                content = f.read()
                import re
                blocks = re.split(r'-{10,}', content)
                for idx, b in enumerate(blocks):
                    m_iter = re.search(r'\[Iteration\s+(\d+)\]', b)
                    iter_num = int(m_iter.group(1)) if m_iter else idx + 1
                    
                    sections = re.findall(r'(Observation|Hypothesis|Action|Evaluation|Learning|New Discovery|Strategy Change):\s*\n(.*?)(?=\n[A-Z][A-Za-z ]+:\s*\n|\Z)', b, re.DOTALL)
                    for title, sec_content in sections:
                        cleaned = sec_content.strip()
                        if cleaned and title in ['Learning', 'New Discovery', 'Hypothesis']:
                            items.append({
                                "id": f"lrn_{idx}_{title}",
                                "task_id": task_id,
                                "content": cleaned,
                                "category": "DISCOVERY" if "Discovery" in title else ("RULE" if "Learning" in title else "OBSERVATION"),
                                "iteration_number": iter_num,
                                "created_at": datetime.now(timezone.utc).isoformat()
                            })
            return items
        except Exception:
            pass
    return []


@router.get("/{task_id}/rules")
async def get_rules(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await get_task(task_id, db, current_user)
    result = await db.execute(
        select(Rule).where(Rule.task_id == task_id).order_by(Rule.confidence.desc())
    )
    db_rules = result.scalars().all()
    if db_rules:
        return [{
            "id": str(r.id),
            "task_id": r.task_id,
            "content": r.rule_text,
            "status": r.status.value.lower() if hasattr(r.status, 'value') else str(r.status).lower(),
            "confidence": r.confidence,
            "evidence_count": len(r.evidence) if r.evidence else 1,
            "last_updated": r.updated_at.isoformat() if r.updated_at else datetime.now(timezone.utc).isoformat()
        } for r in db_rules]
        
    rules_file = os.path.join(settings.STORAGE_DIR, "tasks", task_id, "rules.json")
    if os.path.exists(rules_file):
        try:
            with open(rules_file, "r") as f:
                rules_data = json.load(f)
                known = rules_data.get("known_rules", [])
                hypo = rules_data.get("hypothesized_rules", [])
                confirmed = rules_data.get("confirmed_rules", [])
                rejected = rules_data.get("rejected_rules", [])
                all_r = [("verified", r) for r in known] + [("confirmed", r) for r in confirmed] + [("hypothesized", r) for r in hypo] + [("rejected", r) for r in rejected]
                out = []
                for i, (st, r) in enumerate(all_r):
                    out.append({
                        "id": str(i + 1),
                        "task_id": task_id,
                        "content": r.get("rule", r.get("rule_text", "")),
                        "status": r.get("status", st),
                        "confidence": float(r.get("confidence", 0.5)),
                        "evidence_count": len(r.get("evidence", [])) or 1,
                        "last_updated": datetime.now(timezone.utc).isoformat()
                    })
                return out
        except Exception:
            pass
    return []


@router.get("/{task_id}/snapshots")
async def list_snapshots(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await get_task(task_id, db, current_user)
    # Read snapshots from file system
    snapshot_mgr = SnapshotManager(settings.STORAGE_DIR, task_id)
    return snapshot_mgr.list_snapshots()


@router.get("/{task_id}/snapshots/{iteration}/compare/{other_iteration}")
async def compare_snapshots(
    task_id: str,
    iteration: int,
    other_iteration: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await get_task(task_id, db, current_user)
    snapshot_mgr = SnapshotManager(settings.STORAGE_DIR, task_id)
    comparison = snapshot_mgr.compare_snapshots(iteration, other_iteration)
    if "error" in comparison:
        raise HTTPException(status_code=404, detail=comparison["error"])
    return comparison


@router.get("/{task_id}/learnings-file")
async def get_learnings_file(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await get_task(task_id, db, current_user)
    file_path = os.path.join(settings.STORAGE_DIR, "tasks", task_id, "learnings.txt")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Learnings file not found. Task may not have started yet.")
    return FileResponse(file_path, filename=f"learnings_{task_id}.txt", media_type="text/plain")
