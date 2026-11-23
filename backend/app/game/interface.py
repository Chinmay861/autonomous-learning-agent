"""The LLM-facing interface to Minesweeper.

An agent interacts only through `MinesweeperEnv`:

    env = MinesweeperEnv(config, seed, max_moves)
    obs = env.observe()          # Observation: .text for the prompt, .data for the UI
    step = env.step({"action": "reveal", "row": 3, "col": 4})

`step` accepts the shapes LLMs commonly produce ({"action", "row", "col"},
{"tool", "parameters"}, {"action": {"type", "row", "col"}}, "reveal 3 4", ...)
and never raises: anything it cannot parse costs one invalid move, with a
message explaining what went wrong so the agent can correct itself.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.game.minesweeper import BoardConfig, GameStatus, Minesweeper, MoveOutcome, MoveResult

ACTIONS = ("reveal", "flag", "unflag")

_ACTION_ALIASES = {
    "reveal": "reveal", "open": "reveal", "click": "reveal", "dig": "reveal", "uncover": "reveal",
    "flag": "flag", "mark": "flag", "place_flag": "flag",
    "unflag": "unflag", "remove_flag": "unflag", "clear_flag": "unflag",
}

ACTION_SPEC = """Actions (each costs one move, invalid ones included):
- reveal(row,col): uncover a hidden cell. A mine loses the game; a 0 opens its whole empty region.
- flag(row,col): mark a suspected mine. Optional: the game is won by revealing every safe cell.
- unflag(row,col): remove a flag.
An action is {"action": "reveal"|"flag"|"unflag", "row": <int>, "col": <int>}."""

LEGEND = "# hidden, F flag, . empty, 1-8 = adjacent mines; (row,col) zero-based"


@dataclass
class Observation:
    text: str
    data: dict


@dataclass
class StepResult:
    action: dict | None          # normalised {"action", "row", "col"} or None if unparseable
    outcome: MoveOutcome
    valid: bool
    message: str
    done: bool
    status: GameStatus
    newly_revealed: int = 0
    board: dict = field(default_factory=dict)
    error_code: str | None = None


def parse_action(raw: Any) -> tuple[dict | None, str]:
    """Normalise an LLM action into {"action", "row", "col"}. Returns (action, error_message)."""
    if isinstance(raw, str):
        text = raw.strip()
        try:
            raw = json.loads(text)
        except (ValueError, TypeError):
            m = re.match(r"^\s*([a-z_]+)\s*\(?\s*(-?\d+)\s*[, ]\s*(-?\d+)\s*\)?\s*$", text, re.IGNORECASE)
            if not m:
                return None, f"Could not parse action text {text[:80]!r}."
            raw = {"action": m.group(1), "row": m.group(2), "col": m.group(3)}

    if not isinstance(raw, dict):
        return None, "Action must be a JSON object like {\"action\": \"reveal\", \"row\": 0, \"col\": 0}."

    merged: dict = {}
    nested = raw.get("action")
    if isinstance(nested, dict):
        merged.update(nested)
    for key in ("parameters", "arguments", "args", "params"):
        if isinstance(raw.get(key), dict):
            merged.update(raw[key])
    for key, value in raw.items():
        if not isinstance(value, dict):
            merged.setdefault(key, value)

    name = None
    for key in ("action", "type", "tool", "name", "move", "command"):
        value = merged.get(key)
        if isinstance(value, str) and value.strip():
            name = value.strip().lower().replace(" ", "_").replace("-", "_")
            break
    if name is None:
        return None, "Missing \"action\" (one of reveal, flag, unflag)."
    canonical = _ACTION_ALIASES.get(name)
    if canonical is None:
        return None, f"Unknown action {name!r}. Use one of: reveal, flag, unflag."

    row, col = merged.get("row"), merged.get("col", merged.get("column"))
    cell = merged.get("cell") or merged.get("position") or merged.get("coords")
    if (row is None or col is None) and cell is not None:
        if isinstance(cell, (list, tuple)) and len(cell) == 2:
            row, col = cell
        elif isinstance(cell, dict):
            row, col = cell.get("row"), cell.get("col", cell.get("column"))
        elif isinstance(cell, str):
            nums = re.findall(r"-?\d+", cell)
            if len(nums) == 2:
                row, col = nums
    if row is None and "r" in merged:
        row = merged["r"]
    if col is None and "c" in merged:
        col = merged["c"]
    try:
        row_i, col_i = int(row), int(col)
    except (TypeError, ValueError):
        return None, f"\"row\" and \"col\" must be integers (got row={row!r}, col={col!r})."
    return {"action": canonical, "row": row_i, "col": col_i}, ""


class MinesweeperEnv:
    def __init__(self, config: BoardConfig, seed: int, max_moves: int | None = None):
        self.game = Minesweeper(config, seed)
        self.max_moves = max_moves or self.default_max_moves(config)

    @staticmethod
    def default_max_moves(config: BoardConfig) -> int:
        # Generous: every safe cell clicked one by one, plus room for flags and mistakes.
        return config.safe_cells + config.mines + 10

    @property
    def done(self) -> bool:
        return self.game.is_over

    # ------------------------------------------------------------------ observe
    def frontier(self, limit: int = 60) -> list[dict]:
        """Revealed numbers that still touch hidden, unflagged cells: the cells where a decision is needed."""
        g = self.game
        facts = []
        for r in range(g.rows):
            for c in range(g.cols):
                if (r, c) not in g.revealed or g.count(r, c) == 0:
                    continue
                hidden = [n for n in g.neighbors(r, c) if n not in g.revealed and n not in g.flags]
                if not hidden:
                    continue
                flagged = sum(1 for n in g.neighbors(r, c) if n in g.flags)
                facts.append({
                    "cell": [r, c],
                    "number": g.count(r, c),
                    "flagged_neighbors": flagged,
                    "hidden_neighbors": [list(n) for n in hidden],
                })
        return facts[:limit]

    def board_text(self) -> str:
        g = self.game
        width = 2 if g.cols > 10 or g.rows > 10 else 1
        pad = " " * (len(str(g.rows - 1)) + 1)
        header = pad + "  " + " ".join(str(c).rjust(width) for c in range(g.cols))
        lines = [header]
        for r, row in enumerate(g.grid()):
            lines.append(f"{str(r).rjust(len(str(g.rows - 1)))} | " + " ".join(ch.rjust(width) for ch in row))
        return "\n".join(lines)

    def observe(self) -> Observation:
        g = self.game
        frontier = self.frontier()
        if frontier:
            frontier_lines = []
            for f in frontier:
                r, c = f["cell"]
                cells = " ".join(f"({hr},{hc})" for hr, hc in f["hidden_neighbors"])
                flags = f", {f['flagged_neighbors']} flagged" if f["flagged_neighbors"] else ""
                frontier_lines.append(f"({r},{c}) shows {f['number']}{flags}; hidden neighbours: {cells}")
            frontier_text = "\n".join(frontier_lines)
        else:
            frontier_text = "none (only isolated hidden areas remain)"

        text = (
            f"Board {g.rows}x{g.cols}, {g.config.mines} mines ({LEGEND}):\n"
            f"{self.board_text()}\n"
            f"Moves {g.moves}/{self.max_moves} | safe revealed {g.safe_revealed}/{g.safe_total} | "
            f"flags {len(g.flags)} | hidden {g.hidden_count} | fewest reveals left {g.min_clicks_remaining()}\n"
            f"Only '#' cells can be revealed or flagged.\n"
            f"Numbers next to hidden cells:\n"
            f"{frontier_text}"
        )
        data = g.to_public_dict()
        data["max_moves"] = self.max_moves
        data["frontier"] = frontier
        return Observation(text=text, data=data)

    # ------------------------------------------------------------------ act
    def step(self, raw_action: Any) -> StepResult:
        g = self.game
        if g.is_over:
            return StepResult(None, MoveOutcome.INVALID, False, "The game is already over.", True, g.status,
                              board=self._board(), error_code="game_over")

        action, error = parse_action(raw_action)
        if action is None:
            result: MoveResult = g.register_invalid(error)
        elif action["action"] == "reveal":
            result = g.reveal(action["row"], action["col"])
        elif action["action"] == "flag":
            result = g.flag(action["row"], action["col"])
        else:
            result = g.unflag(action["row"], action["col"])

        message = result.message
        if not g.is_over and g.moves >= self.max_moves:
            g.end_by_timeout()
            message += f" Move budget of {self.max_moves} exhausted: game over."

        return StepResult(
            action=action,
            outcome=result.outcome,
            valid=result.valid,
            message=message,
            done=g.is_over,
            status=g.status,
            newly_revealed=len(result.newly_revealed),
            board=self._board(),
            error_code=result.error_code,
        )

    def _board(self) -> dict:
        data = self.game.to_public_dict()
        data["max_moves"] = self.max_moves
        return data

    @staticmethod
    def available_actions() -> list[dict]:
        cell = {"row": "int, zero-based row", "col": "int, zero-based column"}
        return [
            {"name": "reveal", "description": "Uncover a hidden cell.", "parameters": cell},
            {"name": "flag", "description": "Mark a hidden cell as a suspected mine.", "parameters": cell},
            {"name": "unflag", "description": "Remove a flag.", "parameters": cell},
        ]
