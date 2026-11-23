from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from app.config import settings
from app.game.minesweeper import PRESETS, BoardConfig


class ExperimentCreate(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    preset: Optional[Literal["small", "beginner", "intermediate"]] = "beginner"
    rows: Optional[int] = Field(None, ge=2, le=30)
    cols: Optional[int] = Field(None, ge=2, le=30)
    mines: Optional[int] = Field(None, ge=1)
    num_games: int = Field(default_factory=lambda: settings.DEFAULT_NUM_GAMES, ge=1)
    max_moves: Optional[int] = Field(None, ge=5, le=2000)
    base_seed: Optional[int] = Field(None, ge=0, le=2**31 - 1)
    model: Optional[str] = Field(None, max_length=200)
    temperature: float = Field(default_factory=lambda: settings.DEFAULT_TEMPERATURE, ge=0.0, le=2.0)
    memory_scope: Literal["persistent", "fresh"] = "persistent"
    # "pattern" = code-only learning agents (no LLM). "llm" only works with ENABLE_LLM_AGENTS=true.
    agent_type: Literal["pattern", "llm"] = "pattern"
    speed: Literal["watch", "fast"] = "watch"
    start: bool = True

    @model_validator(mode="after")
    def _check(self) -> "ExperimentCreate":
        if self.num_games > settings.MAX_NUM_GAMES:
            raise ValueError(f"num_games may be at most {settings.MAX_NUM_GAMES}")
        if self.rows is not None or self.cols is not None or self.mines is not None:
            if None in (self.rows, self.cols, self.mines):
                raise ValueError("custom boards need rows, cols and mines")
            BoardConfig(self.rows, self.cols, self.mines)  # raises ValueError if impossible
        return self

    def board(self) -> BoardConfig:
        if self.rows is not None:
            return BoardConfig(self.rows, self.cols, self.mines)
        return PRESETS[self.preset or "beginner"]
