"""Post-game reflection: turns a finished game into playbook updates (one LLM call)."""
from __future__ import annotations

from dataclasses import dataclass

from app.agents.playbook import LessonView
from app.agents.prompts import REFLECTION_SYSTEM, format_playbook, reflection_prompt
from app.game.minesweeper import Minesweeper
from app.models.llm_provider import LLMProvider


@dataclass
class GameRecord:
    game: Minesweeper
    max_moves: int
    moves: list[dict]            # {"move_index", "action_text", "message", "reasoning", "outcome", "valid"}
    fatal_board_text: str | None  # board + frontier just before the move that hit a mine


def _summary(record: GameRecord) -> str:
    g = record.game
    lines = [
        f"Result: {g.status.value.upper()} on a {g.rows}x{g.cols} board with {g.config.mines} mines.",
        f"Moves used: {g.moves} (reveals {g.reveals}, flag/unflag {g.flag_moves}, invalid {g.invalid_moves}); "
        f"move budget {record.max_moves}.",
        f"Minimum reveals needed to clear this board from the opening: {g.initial_min_clicks}.",
        f"Safe cells revealed: {g.safe_revealed}/{g.safe_total}.",
    ]
    if g.exploded:
        lines.append(f"The game was lost by revealing a mine at {g.exploded}.")
    if g.status.value == "won":
        waste = g.moves - g.initial_min_clicks
        lines.append(f"Moves above the minimum: {waste}.")
    return "\n".join(lines)


async def reflect(llm: LLMProvider, record: GameRecord, playbook: list[LessonView], cited: list[int],
                  temperature: float = 0.3) -> tuple[dict, int, int]:
    """Return (reflection JSON, prompt_tokens, completion_tokens). LLM errors propagate."""
    move_log = []
    previous_reasoning = None
    for m in record.moves[-25:]:
        reasoning = (m.get("reasoning") or "").replace("\n", " ")[:120]
        # Moves from one turn share their reasoning; print it once.
        shown = reasoning if reasoning and reasoning != previous_reasoning else ""
        previous_reasoning = reasoning
        move_log.append(f"{m['move_index'] + 1}. {m['action_text']} -> {m['message']}"
                        + (f" | {shown}" if shown else ""))
    final_board = "\n".join(record.game.grid(show_mines=True))
    prompt = reflection_prompt(
        summary=_summary(record),
        move_log=move_log or ["(no moves)"],
        fatal_context=record.fatal_board_text,
        final_board=final_board,
        playbook_text=format_playbook(playbook),
        cited=cited,
    )
    data, response = await llm.complete_json(REFLECTION_SYSTEM, prompt, temperature=temperature)
    return data, response.prompt_tokens, response.completion_tokens
