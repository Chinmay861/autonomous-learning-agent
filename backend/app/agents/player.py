"""The Minesweeper-playing agent: one LLM call per turn, one or more moves per turn."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agents.prompts import player_prompt, player_system
from app.config import settings
from app.game.interface import MinesweeperEnv
from app.models.llm_provider import LLMProvider, parse_json_object


@dataclass
class Decision:
    # Each item is passed to env.step() in order: a parsed JSON action, or raw text if the reply was not JSON.
    actions: list[Any]
    reasoning: str
    raw_text: str
    lessons_used: list[int] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0


def extract_actions(data: dict, limit: int) -> list[Any]:
    """Accept {"moves": [...]} (a turn) and, for robustness, a single bare action object."""
    moves = data.get("moves")
    if isinstance(moves, list) and moves:
        return moves[:max(1, limit)]
    if isinstance(moves, dict):
        return [moves]
    return [data]


class MinesweeperPlayer:
    def __init__(self, llm: LLMProvider, uses_memory: bool, temperature: float = 0.3):
        self.llm = llm
        self.uses_memory = uses_memory
        self.temperature = temperature

    async def decide(self, env: MinesweeperEnv, game_number: int, history: list[dict],
                     lessons: list | None = None, last_feedback: str | None = None) -> Decision:
        """Ask the LLM for its next turn. LLM transport errors propagate to the caller."""
        prompt = player_prompt(
            env.observe().text,
            game_number,
            history,
            last_feedback,
            (lessons or []) if self.uses_memory else None,
        )
        response = await self.llm.complete(player_system(self.uses_memory), prompt,
                                           temperature=self.temperature, json_mode=True)
        usage = {"prompt_tokens": response.prompt_tokens, "completion_tokens": response.completion_tokens}

        if not response.text.strip():
            reason = ("ran out of tokens before answering" if response.finish_reason == "length"
                      else "returned an empty reply")
            return Decision(actions=[f"(no answer: the model {reason})"], reasoning="", raw_text="", **usage)

        try:
            data = parse_json_object(response.text)
        except ValueError:
            # Not JSON: hand the raw text to the environment, which will try to read
            # "reveal 3 4"-style text and otherwise reject it as an invalid move.
            return Decision(actions=[response.text.strip()[:500]], reasoning="", raw_text=response.text, **usage)

        valid_ids = {lesson.id for lesson in lessons or []}
        cited: list[int] = []
        for item in data.get("lessons_used") or []:
            try:
                lesson_id = int(str(item).lstrip("Ll"))
            except ValueError:
                continue
            if lesson_id in valid_ids and lesson_id not in cited:
                cited.append(lesson_id)

        return Decision(
            actions=extract_actions(data, settings.MAX_MOVES_PER_TURN),
            reasoning=str(data.get("reasoning") or "")[:600],
            raw_text=response.text,
            lessons_used=cited if self.uses_memory else [],
            **usage,
        )
