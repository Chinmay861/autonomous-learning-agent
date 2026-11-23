"""The persistent playbook, as seen and managed by its owner."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database.connection import get_db
from app.database.models import Lesson, User

router = APIRouter(prefix="/lessons", tags=["lessons"])


def lesson_dict(lesson: Lesson) -> dict:
    return {
        "id": lesson.id,
        "text": lesson.text,
        "category": lesson.category,
        "helpful": lesson.helpful,
        "harmful": lesson.harmful,
        "times_cited": lesson.times_cited,
        "score": round(lesson.score, 3),
        "active": lesson.active,
        "experiment_id": lesson.experiment_id,
        "source_game_id": lesson.source_game_id,
        "created_at": lesson.created_at.isoformat() if lesson.created_at else None,
        "updated_at": lesson.updated_at.isoformat() if lesson.updated_at else None,
    }


@router.get("")
async def list_lessons(
    include_retired: bool = Query(False),
    experiment_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = select(Lesson).where(Lesson.user_id == user.id)
    if not include_retired:
        stmt = stmt.where(Lesson.active.is_(True))
    if experiment_id:
        stmt = stmt.where(Lesson.experiment_id == experiment_id)
    lessons = list((await db.execute(stmt)).scalars().all())
    lessons.sort(key=lambda l: (l.active, l.score, l.helpful, l.id), reverse=True)
    return [lesson_dict(l) for l in lessons]


@router.delete("/{lesson_id}")
async def retire_lesson(lesson_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    lesson = await db.get(Lesson, lesson_id)
    if lesson is None or lesson.user_id != user.id:
        raise HTTPException(status_code=404, detail="Lesson not found")
    lesson.active = False
    await db.commit()
    return lesson_dict(lesson)


@router.post("/reset")
async def reset_playbook(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Retire every active lesson (kept for history, never shown to the agent again)."""
    result = await db.execute(
        update(Lesson).where(Lesson.user_id == user.id, Lesson.active.is_(True)).values(active=False)
    )
    await db.commit()
    return {"retired": result.rowcount or 0}
