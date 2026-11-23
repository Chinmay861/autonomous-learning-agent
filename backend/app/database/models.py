"""Database schema.

User ── Experiment ── Game (one per agent per board) ── Move (one per action)
  └──── Lesson (the persistent playbook; owned by the user, survives across experiments)
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class ExperimentStatus(str, enum.Enum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"
    INTERRUPTED = "interrupted"  # the server restarted mid-run; can be resumed


class AgentKind(str, enum.Enum):
    MEMORY = "memory"      # reads and writes the persistent playbook
    BASELINE = "baseline"  # same model and prompt, never sees past games


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Experiment(Base):
    __tablename__ = "ms_experiments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    rows: Mapped[int] = mapped_column(Integer)
    cols: Mapped[int] = mapped_column(Integer)
    mines: Mapped[int] = mapped_column(Integer)
    num_games: Mapped[int] = mapped_column(Integer)
    max_moves: Mapped[int] = mapped_column(Integer)
    base_seed: Mapped[int] = mapped_column(Integer)
    model: Mapped[str] = mapped_column(String(200))
    temperature: Mapped[float] = mapped_column(Float)
    # "persistent": the memory agent starts from everything the user's playbook already knows.
    # "fresh": it only uses lessons learned during this experiment.
    memory_scope: Mapped[str] = mapped_column(String(20), default="persistent")
    # "pattern": code-only learning agents (default, no LLM). "llm": the LLM agents (disabled unless
    # ENABLE_LLM_AGENTS is set).
    agent_type: Mapped[str] = mapped_column(String(20), default="pattern")
    # "watch": paced so a person can follow each move. "fast": as fast as the CPU allows.
    speed: Mapped[str] = mapped_column(String(10), default="watch")
    status: Mapped[str] = mapped_column(String(20), default=ExperimentStatus.CREATED.value)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    games: Mapped[list["Game"]] = relationship(back_populates="experiment", cascade="all, delete-orphan")


class Game(Base):
    __tablename__ = "ms_games"
    __table_args__ = (UniqueConstraint("experiment_id", "agent", "game_index", name="uq_game_per_agent"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("ms_experiments.id", ondelete="CASCADE"), index=True)
    agent: Mapped[str] = mapped_column(String(20))
    game_index: Mapped[int] = mapped_column(Integer)
    seed: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="playing")  # playing | won | lost | timeout | aborted
    moves: Mapped[int] = mapped_column(Integer, default=0)
    reveals: Mapped[int] = mapped_column(Integer, default=0)
    flag_moves: Mapped[int] = mapped_column(Integer, default=0)
    invalid_moves: Mapped[int] = mapped_column(Integer, default=0)
    min_clicks: Mapped[int] = mapped_column(Integer, default=0)
    safe_revealed: Mapped[int] = mapped_column(Integer, default=0)
    safe_total: Mapped[int] = mapped_column(Integer, default=0)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    llm_errors: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    lessons_available: Mapped[int] = mapped_column(Integer, default=0)
    lessons_cited: Mapped[list[int]] = mapped_column(JSON, default=list)
    mistakes: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    final_grid: Mapped[list[str]] = mapped_column(JSON, default=list)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    experiment: Mapped[Experiment] = relationship(back_populates="games")
    move_rows: Mapped[list["Move"]] = relationship(back_populates="game", cascade="all, delete-orphan",
                                                   order_by="Move.move_index")


class Move(Base):
    __tablename__ = "ms_moves"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("ms_games.id", ondelete="CASCADE"), index=True)
    move_index: Mapped[int] = mapped_column(Integer)
    action: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    raw_response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    outcome: Mapped[str] = mapped_column(String(20))
    valid: Mapped[bool] = mapped_column(Boolean)
    message: Mapped[str] = mapped_column(Text, default="")
    grid_after: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    game: Mapped[Game] = relationship(back_populates="move_rows")


class Lesson(Base):
    """One entry in a user's persistent Minesweeper playbook."""
    __tablename__ = "ms_lessons"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    experiment_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    source_game_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(30), default="strategy")  # mistake | strategy | efficiency
    helpful: Mapped[int] = mapped_column(Integer, default=0)
    harmful: Mapped[int] = mapped_column(Integer, default=0)
    times_cited: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    @property
    def score(self) -> float:
        """Laplace-smoothed share of games where the lesson helped."""
        return (self.helpful + 1) / (self.helpful + self.harmful + 2)


class PatternStat(Base):
    """Learned statistics for one local board pattern: how often a hidden cell seen in this
    pattern turned out to be a mine, an empty (0) cell, or a numbered cell.

    `bank` scopes the memory: "user" is the persistent memory shared by all of a user's
    experiments; "exp:<id>" is a fresh memory private to one experiment.
    """
    __tablename__ = "ms_patterns"
    __table_args__ = (UniqueConstraint("user_id", "bank", "pattern", name="uq_pattern_per_bank"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    bank: Mapped[str] = mapped_column(String(60), index=True)
    pattern: Mapped[str] = mapped_column(String(40))
    mines: Mapped[int] = mapped_column(Integer, default=0)
    zeros: Mapped[int] = mapped_column(Integer, default=0)
    numbers: Mapped[int] = mapped_column(Integer, default=0)
