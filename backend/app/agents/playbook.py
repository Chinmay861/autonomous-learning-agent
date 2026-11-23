"""The persistent playbook: the memory agent's long-term memory.

Lessons live in the database (table `ms_lessons`), belong to a user, and
survive restarts and experiments. Each lesson keeps evidence counts:

* `helpful` / `harmful`: how often reflection judged it helped or misled.
* `times_cited`: how often the player said it relied on it.

Ranking uses the Laplace-smoothed helpful share. Lessons that keep misleading
are retired, and only the strongest `PLAYBOOK_MAX_ACTIVE` stay active.

Two kinds of writes happen:

1. **Immediately on a mistake** (no LLM call): an invalid move adds or
   reinforces a fixed corrective lesson for that kind of mistake, and the
   player sees it from its next move.
2. **After every game**: the reflection step adds, reinforces, revises or
   retires lessons based on the full game record.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select

from app.config import settings
from app.database.models import Lesson

# Corrective lessons written the moment the player makes an invalid move.
MISTAKE_LESSONS: dict[str, str] = {
    "already_revealed": "Only act on cells shown as '#' (hidden). Revealing or flagging a cell that already shows a number or '.' is rejected and wastes a move.",
    "out_of_bounds": "Coordinates are zero-based (row, col). Valid rows and columns run from 0 to size-1; read the indices printed on the board edges.",
    "flagged": "A flagged cell cannot be revealed. Unflag it first, or better, only flag a cell when you are certain it is a mine.",
    "already_flagged": "Check whether a cell already shows 'F' before flagging it; flagging it again is rejected and wastes a move.",
    "not_flagged": "Only unflag cells that show 'F'.",
    "unparseable": "Reply with exactly one JSON object containing \"action\", \"row\" and \"col\"; anything else is rejected as an invalid move.",
}

_WORD = re.compile(r"[a-z0-9']+")


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


@dataclass
class LessonView:
    id: int
    text: str
    category: str
    helpful: int
    harmful: int
    times_cited: int
    score: float

    @classmethod
    def of(cls, lesson: Lesson) -> "LessonView":
        return cls(lesson.id, lesson.text, lesson.category, lesson.helpful, lesson.harmful,
                   lesson.times_cited, round(lesson.score, 3))

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def _clean_ids(values) -> list[int]:
    ids: list[int] = []
    for value in values or []:
        try:
            ids.append(int(str(value).strip().lstrip("Ll")))
        except ValueError:
            continue
    return ids


class Playbook:
    DUPLICATE_THRESHOLD = 0.6

    def __init__(self, session_factory, user_id: int, experiment_id: str, scope: str = "persistent"):
        self.session_factory = session_factory
        self.user_id = user_id
        self.experiment_id = experiment_id
        self.scope = scope  # "persistent" (all of the user's lessons) | "fresh" (this experiment's only)

    def _scoped(self, stmt):
        stmt = stmt.where(Lesson.user_id == self.user_id, Lesson.active.is_(True))
        if self.scope == "fresh":
            stmt = stmt.where(Lesson.experiment_id == self.experiment_id)
        return stmt

    async def _active(self, session) -> list[Lesson]:
        result = await session.execute(self._scoped(select(Lesson)))
        lessons = list(result.scalars().all())
        lessons.sort(key=lambda l: (l.score, l.helpful, l.times_cited, l.id), reverse=True)
        return lessons

    async def top(self, limit: int | None = None) -> list[LessonView]:
        async with self.session_factory() as session:
            lessons = await self._active(session)
        return [LessonView.of(l) for l in lessons[: limit or settings.PLAYBOOK_PROMPT_LIMIT]]

    async def all_active(self) -> list[LessonView]:
        async with self.session_factory() as session:
            return [LessonView.of(l) for l in await self._active(session)]

    async def record_mistake(self, error_code: str | None, game_id: int) -> dict | None:
        """Write (or reinforce) the corrective lesson for an invalid move. Returns the change, if any."""
        text = MISTAKE_LESSONS.get(error_code or "")
        if not text:
            return None
        async with self.session_factory() as session:
            for lesson in await self._active(session):
                if similarity(lesson.text, text) >= self.DUPLICATE_THRESHOLD:
                    lesson.helpful += 1
                    await session.commit()
                    return {"type": "reinforced", "id": lesson.id, "text": lesson.text}
            lesson = Lesson(user_id=self.user_id, experiment_id=self.experiment_id, source_game_id=game_id,
                            text=text, category="mistake", helpful=1, harmful=0, times_cited=0, active=True)
            session.add(lesson)
            await session.commit()
            return {"type": "added", "id": lesson.id, "text": lesson.text}

    async def record_citations(self, lesson_ids: list[int]) -> None:
        if not lesson_ids:
            return
        async with self.session_factory() as session:
            result = await session.execute(
                select(Lesson).where(Lesson.user_id == self.user_id, Lesson.id.in_(lesson_ids))
            )
            for lesson in result.scalars():
                lesson.times_cited += 1
            await session.commit()

    async def apply_reflection(self, reflection: dict, game_id: int) -> list[dict]:
        """Apply a reflection's playbook edits. Returns a list of change records for the UI."""
        changes: list[dict] = []
        async with self.session_factory() as session:
            active = await self._active(session)
            by_id = {l.id: l for l in active}

            for lesson_id in _clean_ids(reflection.get("helpful_ids")):
                if lesson_id in by_id:
                    by_id[lesson_id].helpful += 1
                    changes.append({"type": "reinforced", "id": lesson_id, "text": by_id[lesson_id].text})

            for lesson_id in _clean_ids(reflection.get("harmful_ids")):
                if lesson_id in by_id:
                    by_id[lesson_id].harmful += 1
                    changes.append({"type": "weakened", "id": lesson_id, "text": by_id[lesson_id].text})

            for item in reflection.get("revised") or []:
                if not isinstance(item, dict):
                    continue
                ids = _clean_ids([item.get("id")])
                text = str(item.get("text") or "").strip()
                if ids and ids[0] in by_id and 10 <= len(text) <= 400:
                    by_id[ids[0]].text = text
                    changes.append({"type": "revised", "id": ids[0], "text": text})

            for lesson_id in _clean_ids(reflection.get("retire_ids")):
                if lesson_id in by_id and by_id[lesson_id].active:
                    by_id[lesson_id].active = False
                    changes.append({"type": "retired", "id": lesson_id, "text": by_id[lesson_id].text})

            for item in (reflection.get("new_lessons") or [])[:2]:
                if isinstance(item, str):
                    item = {"text": item}
                if not isinstance(item, dict):
                    continue
                text = str(item.get("text") or "").strip()
                if not (10 <= len(text) <= 400):
                    continue
                category = str(item.get("category") or "strategy").lower()
                if category not in ("mistake", "strategy", "efficiency"):
                    category = "strategy"
                duplicate = next(
                    (l for l in active if l.active and similarity(l.text, text) >= self.DUPLICATE_THRESHOLD), None
                )
                if duplicate:
                    duplicate.helpful += 1
                    changes.append({"type": "reinforced", "id": duplicate.id, "text": duplicate.text})
                    continue
                lesson = Lesson(user_id=self.user_id, experiment_id=self.experiment_id, source_game_id=game_id,
                                text=text, category=category, helpful=0, harmful=0, times_cited=0, active=True)
                session.add(lesson)
                await session.flush()
                active.append(lesson)
                changes.append({"type": "added", "id": lesson.id, "text": text})

            # Retire lessons that keep misleading, then cap the playbook size.
            for lesson in active:
                if lesson.active and lesson.harmful >= lesson.helpful + 3:
                    lesson.active = False
                    changes.append({"type": "retired", "id": lesson.id, "text": lesson.text})
            survivors = sorted((l for l in active if l.active),
                               key=lambda l: (l.score, l.helpful, l.id), reverse=True)
            for lesson in survivors[settings.PLAYBOOK_MAX_ACTIVE:]:
                lesson.active = False
                changes.append({"type": "retired", "id": lesson.id, "text": lesson.text})

            await session.commit()
        return changes
