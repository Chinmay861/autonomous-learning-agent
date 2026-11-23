"""Prompts for the Minesweeper agents.

Both agents get the SAME system prompt and move prompt. The only difference is
that the memory agent's move prompt also contains its playbook (lessons from
earlier games). The shared prompt deliberately teaches the rules and the
interface but no strategy, so any strategic edge has to be learned.
"""
from __future__ import annotations

from app.config import settings
from app.game.interface import ACTION_SPEC

# One LLM call is one *turn*: the agent may play several moves it is certain of
# at once. Every action still counts as a move, so step counts are unaffected;
# turns only cut the number of (rate-limited) LLM calls.
PLAYER_SYSTEM = f"""You are an AI agent playing Minesweeper.
Goal: reveal every safe cell without ever revealing a mine, in as FEW moves as possible.
Each number is the count of mines among that cell's 8 neighbours.

{ACTION_SPEC}

Each turn, list IN ORDER every move you are certain is correct right now (at most MAX_MOVES_PER_TURN).
They are applied one by one; the turn stops at the first invalid move or mine.
If no move is certain, list exactly one: your best guess.
Reply with ONE JSON object and nothing else:
{{"reasoning": "<at most 2 short sentences>", "moves": [<action>, ...]}}"""

PLAYER_SYSTEM_WITH_MEMORY = PLAYER_SYSTEM.replace(
    '"moves": [<action>, ...]}',
    '"moves": [<action>, ...], "lessons_used": [<ids of playbook lessons you relied on>]}',
)


def player_system(uses_memory: bool) -> str:
    template = PLAYER_SYSTEM_WITH_MEMORY if uses_memory else PLAYER_SYSTEM
    return template.replace("MAX_MOVES_PER_TURN", str(settings.MAX_MOVES_PER_TURN))


def format_playbook(lessons: list) -> str:
    if not lessons:
        return "Your playbook is empty: no lessons from previous games yet."
    lines = [
        f"[L{lesson.id}] ({lesson.category}, helped {lesson.helpful}x, misled {lesson.harmful}x) {lesson.text}"
        for lesson in lessons
    ]
    return "\n".join(lines)


def player_prompt(observation_text: str, game_number: int, history: list[dict],
                  last_feedback: str | None, lessons: list | None) -> str:
    parts = [f"Game #{game_number + 1}, move {len(history) + 1}.", observation_text]

    if history:
        # The board already reflects every move; a short tail is enough to avoid repeats.
        parts.append("Last moves: " + "; ".join(
            f"{h['action_text']} -> {h['message']}" for h in history[-5:]
        ))

    if last_feedback:
        parts.append(f"IMPORTANT: your previous action was rejected: {last_feedback} Pick a different, valid action.")

    if lessons is not None:
        parts.append("PLAYBOOK (lessons from your previous games, strongest first; apply the relevant ones):")
        parts.append(format_playbook(lessons))

    parts.append("Your turn.")
    return "\n".join(parts)


REFLECTION_SYSTEM = """You are a Minesweeper coach. You maintain a short playbook of lessons that an AI
player reads before every move. After each game you review what happened and update the playbook so the
player wins more often and needs fewer moves.

Rules for lessons:
- General and actionable: they must apply to future boards. Never mention specific coordinates.
- One idea per lesson, at most 35 words.
- Prefer concrete deduction rules and move-saving habits over vague advice ("be careful").
- Do not add a lesson that repeats an existing one: mark the existing one as helpful instead.

Reply with ONE JSON object:
{
  "analysis": "<1-3 sentences: what decided this game>",
  "new_lessons": [{"text": "<lesson>", "category": "mistake" | "strategy" | "efficiency"}],
  "helpful_ids": [<ids of existing lessons that this game confirmed or that helped>],
  "harmful_ids": [<ids of existing lessons that misled the player in this game>],
  "revised": [{"id": <id>, "text": "<improved wording>"}],
  "retire_ids": [<ids of lessons that are wrong or useless>]
}
Add at most 2 new lessons. Empty lists are fine."""


def reflection_prompt(summary: str, move_log: list[str], fatal_context: str | None,
                      final_board: str, playbook_text: str, cited: list[int]) -> str:
    parts = [
        "GAME SUMMARY",
        summary,
        "",
        "MOVE LOG (action -> result | player's reasoning)",
        *move_log,
        "",
    ]
    if fatal_context:
        parts += ["BOARD JUST BEFORE THE FATAL MOVE", fatal_context, ""]
    parts += [
        "FINAL BOARD (* = mine, X = the mine that was hit, F = flag)",
        final_board,
        "",
        "CURRENT PLAYBOOK",
        playbook_text,
        "",
        f"Lessons the player said it relied on this game: {', '.join(f'L{i}' for i in cited) or 'none'}",
        "",
        "Update the playbook.",
    ]
    return "\n".join(parts)
