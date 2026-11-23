"""Deterministic Minesweeper engine.

Design choices that matter for the learning experiment:

* **Seeded, fixed boards.** Mines are placed from the seed before any move, so
  two agents given the same seed play exactly the same board.
* **Guaranteed opening.** A seeded start cell and its 8 neighbours are kept
  mine-free and revealed before move 1. Nobody loses on a blind first click,
  and both agents start from the same position.
* **Minimum clicks (3BV).** `min_clicks_remaining()` is the fewest reveals
  that can clear the board from the current position (each unopened zero
  region counts 1, each numbered cell not bordering a zero region counts 1).
  It is the "minimum steps" target that move counts are compared against.

Coordinates are (row, col), zero-based, row 0 at the top.
"""
from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass, field
from enum import Enum

Cell = tuple[int, int]


class GameStatus(str, Enum):
    PLAYING = "playing"
    WON = "won"
    LOST = "lost"        # revealed a mine
    TIMEOUT = "timeout"  # ran out of the move budget


class MoveOutcome(str, Enum):
    REVEALED = "revealed"
    FLAGGED = "flagged"
    UNFLAGGED = "unflagged"
    MINE = "mine"
    INVALID = "invalid"


@dataclass(frozen=True)
class BoardConfig:
    rows: int
    cols: int
    mines: int

    def __post_init__(self):
        if not (2 <= self.rows <= 30 and 2 <= self.cols <= 30):
            raise ValueError("rows and cols must be between 2 and 30")
        # The 3x3 opening must stay mine-free, so at most rows*cols-9 mines fit.
        max_mines = self.rows * self.cols - 9
        if not (1 <= self.mines <= max_mines):
            raise ValueError(f"mines must be between 1 and {max_mines} for a {self.rows}x{self.cols} board")

    @property
    def safe_cells(self) -> int:
        return self.rows * self.cols - self.mines


PRESETS: dict[str, BoardConfig] = {
    "small": BoardConfig(6, 6, 5),
    "beginner": BoardConfig(9, 9, 10),
    "intermediate": BoardConfig(16, 16, 40),
}


@dataclass
class MoveResult:
    outcome: MoveOutcome
    valid: bool
    message: str
    newly_revealed: list[Cell] = field(default_factory=list)
    # Why an invalid move was rejected: out_of_bounds | already_revealed | flagged |
    # already_flagged | not_flagged | unparseable | game_over
    error_code: str | None = None


class Minesweeper:
    """One Minesweeper game. Every call to `reveal`/`flag`/`unflag`/`register_invalid` is one move."""

    def __init__(self, config: BoardConfig, seed: int):
        self.config = config
        self.seed = seed
        self.rows, self.cols = config.rows, config.cols

        # Neighbour lists never change, and players ask for them constantly: build them once.
        self._neighbors: dict[Cell, list[Cell]] = {
            (r, c): [
                (r + dr, c + dc)
                for dr in (-1, 0, 1)
                for dc in (-1, 0, 1)
                if (dr or dc) and 0 <= r + dr < self.rows and 0 <= c + dc < self.cols
            ]
            for r in range(self.rows) for c in range(self.cols)
        }

        rng = random.Random(seed)
        self.start: Cell = (rng.randrange(self.rows), rng.randrange(self.cols))
        protected = {self.start, *self.neighbors(*self.start)}
        candidates = [
            (r, c) for r in range(self.rows) for c in range(self.cols) if (r, c) not in protected
        ]
        self.mines: frozenset[Cell] = frozenset(rng.sample(candidates, config.mines))
        self.counts: list[list[int]] = [
            [sum(1 for n in self.neighbors(r, c) if n in self.mines) for c in range(self.cols)]
            for r in range(self.rows)
        ]

        self.revealed: set[Cell] = set()
        self.flags: set[Cell] = set()
        self.status = GameStatus.PLAYING
        self.exploded: Cell | None = None

        self.moves = 0
        self.reveals = 0
        self.flag_moves = 0
        self.invalid_moves = 0

        self._flood_reveal(self.start)
        self.initial_min_clicks = self.min_clicks_remaining()

    # ------------------------------------------------------------------ geometry
    def in_bounds(self, r: int, c: int) -> bool:
        return 0 <= r < self.rows and 0 <= c < self.cols

    def neighbors(self, r: int, c: int) -> list[Cell]:
        """The up-to-8 surrounding cells. The returned list is shared: do not modify it."""
        return self._neighbors[(r, c)]

    # ------------------------------------------------------------------ queries
    @property
    def is_over(self) -> bool:
        return self.status != GameStatus.PLAYING

    @property
    def safe_total(self) -> int:
        return self.config.safe_cells

    @property
    def safe_revealed(self) -> int:
        return len(self.revealed)

    @property
    def hidden_count(self) -> int:
        return self.rows * self.cols - len(self.revealed)

    def is_mine(self, cell: Cell) -> bool:
        return cell in self.mines

    def count(self, r: int, c: int) -> int:
        return self.counts[r][c]

    def min_clicks_remaining(self) -> int:
        """3BV of the unrevealed part of the board: the fewest reveals that finish the game."""
        covered: set[Cell] = set()
        clicks = 0
        for r in range(self.rows):
            for c in range(self.cols):
                cell = (r, c)
                if cell in self.mines or cell in self.revealed or cell in covered:
                    continue
                if self.counts[r][c] == 0:
                    # One click opens the whole zero region plus its numbered border.
                    clicks += 1
                    queue = deque([cell])
                    covered.add(cell)
                    while queue:
                        cr, cc = queue.popleft()
                        for n in self.neighbors(cr, cc):
                            if n in covered or n in self.mines:
                                continue
                            covered.add(n)
                            if self.counts[n[0]][n[1]] == 0:
                                queue.append(n)
        for r in range(self.rows):
            for c in range(self.cols):
                cell = (r, c)
                if cell not in self.mines and cell not in self.revealed and cell not in covered:
                    clicks += 1
        return clicks

    # ------------------------------------------------------------------ moves
    def reveal(self, r: int, c: int) -> MoveResult:
        if self.is_over:
            return self._invalid("The game is already over.", "game_over", count_move=False)
        if not self.in_bounds(r, c):
            return self._invalid(f"({r},{c}) is outside the board (rows 0-{self.rows - 1}, cols 0-{self.cols - 1}).", "out_of_bounds")
        cell = (r, c)
        if cell in self.revealed:
            return self._invalid(f"({r},{c}) is already revealed.", "already_revealed")
        if cell in self.flags:
            return self._invalid(f"({r},{c}) is flagged. Unflag it before revealing.", "flagged")

        self.moves += 1
        self.reveals += 1
        if cell in self.mines:
            self.status = GameStatus.LOST
            self.exploded = cell
            return MoveResult(MoveOutcome.MINE, True, f"({r},{c}) was a mine. Game lost.")

        newly = self._flood_reveal(cell)
        if self.safe_revealed == self.safe_total:
            self.status = GameStatus.WON
            return MoveResult(MoveOutcome.REVEALED, True,
                              f"Revealed {len(newly)} cell(s). All safe cells revealed: game won!", newly)
        n = self.counts[r][c]
        detail = "an empty region" if n == 0 else f"a {n}"
        return MoveResult(MoveOutcome.REVEALED, True, f"({r},{c}) is {detail}; revealed {len(newly)} cell(s).", newly)

    def flag(self, r: int, c: int) -> MoveResult:
        if self.is_over:
            return self._invalid("The game is already over.", "game_over", count_move=False)
        if not self.in_bounds(r, c):
            return self._invalid(f"({r},{c}) is outside the board (rows 0-{self.rows - 1}, cols 0-{self.cols - 1}).", "out_of_bounds")
        cell = (r, c)
        if cell in self.revealed:
            return self._invalid(f"({r},{c}) is already revealed and cannot be flagged.", "already_revealed")
        if cell in self.flags:
            return self._invalid(f"({r},{c}) is already flagged.", "already_flagged")
        self.moves += 1
        self.flag_moves += 1
        self.flags.add(cell)
        return MoveResult(MoveOutcome.FLAGGED, True, f"Flagged ({r},{c}).")

    def unflag(self, r: int, c: int) -> MoveResult:
        if self.is_over:
            return self._invalid("The game is already over.", "game_over", count_move=False)
        cell = (r, c)
        if cell not in self.flags:
            return self._invalid(f"({r},{c}) is not flagged.", "not_flagged")
        self.moves += 1
        self.flag_moves += 1
        self.flags.discard(cell)
        return MoveResult(MoveOutcome.UNFLAGGED, True, f"Removed the flag at ({r},{c}).")

    def register_invalid(self, message: str) -> MoveResult:
        """Count an action that could not be understood (bad format, unknown action) as a wasted move."""
        return self._invalid(message, "unparseable")

    def end_by_timeout(self) -> None:
        if not self.is_over:
            self.status = GameStatus.TIMEOUT

    def _invalid(self, message: str, code: str, count_move: bool = True) -> MoveResult:
        if count_move:
            self.moves += 1
            self.invalid_moves += 1
        return MoveResult(MoveOutcome.INVALID, False, message, error_code=code)

    def _flood_reveal(self, cell: Cell) -> list[Cell]:
        newly: list[Cell] = []
        queue = deque([cell])
        seen = {cell}
        while queue:
            current = queue.popleft()
            if current in self.revealed or current in self.mines:
                continue
            self.revealed.add(current)
            self.flags.discard(current)  # a wrong flag inside an opened region is cleared
            newly.append(current)
            if self.counts[current[0]][current[1]] == 0:
                for n in self.neighbors(*current):
                    if n not in seen:
                        seen.add(n)
                        queue.append(n)
        return newly

    # ------------------------------------------------------------------ views
    def symbol(self, r: int, c: int, show_mines: bool = False) -> str:
        """`#` hidden, `F` flag, `.` empty, `1`-`8` count; after the game `*` mine, `X` exploded mine."""
        cell = (r, c)
        if show_mines and cell == self.exploded:
            return "X"
        if cell in self.revealed:
            n = self.counts[r][c]
            return "." if n == 0 else str(n)
        if cell in self.flags:
            return "F"
        if show_mines and cell in self.mines:
            return "*"
        return "#"

    def grid(self, show_mines: bool = False) -> list[str]:
        return ["".join(self.symbol(r, c, show_mines) for c in range(self.cols)) for r in range(self.rows)]

    def to_public_dict(self) -> dict:
        """State safe to send to a browser. Mines are only included once the game is over."""
        over = self.is_over
        return {
            "rows": self.rows,
            "cols": self.cols,
            "mines": self.config.mines,
            "seed": self.seed,
            "status": self.status.value,
            "grid": self.grid(show_mines=over),
            "moves": self.moves,
            "reveals": self.reveals,
            "flags": len(self.flags),
            "invalid_moves": self.invalid_moves,
            "safe_revealed": self.safe_revealed,
            "safe_total": self.safe_total,
            "min_clicks": self.initial_min_clicks,
            "start": list(self.start),
            "exploded": list(self.exploded) if self.exploded else None,
        }
