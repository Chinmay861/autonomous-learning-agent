"""In-game Minesweeper reasoning from the visible board. No learning and no LLM.

`deduce()` is the reasoning every player can do inside a single game, from the
numbers it can see:

1. A number whose known mines already match it: its other hidden neighbours are safe.
2. A number whose hidden neighbours exactly account for its remaining mines: they are all mines.
3. Subset rule: if one number's hidden neighbours are a subset of another's, the
   difference holds exactly the difference in remaining mines.

`visible_risk()` is the best a player can say about a cell from this game's board
alone when nothing is certain. Both compared agents use these each game; the
expert reference player is built from the same two functions.
"""
from __future__ import annotations

import random

from app.game.minesweeper import Minesweeper

Cell = tuple[int, int]


def _numbers(game: Minesweeper) -> list[tuple[int, list[Cell]]]:
    """Revealed numbers that still touch a hidden cell: (number, neighbours)."""
    out = []
    for (r, c) in game.revealed:
        n = game.count(r, c)
        if n == 0:
            continue
        around = game.neighbors(r, c)
        if any(x not in game.revealed for x in around):
            out.append((n, around))
    return out


def constraints(game: Minesweeper, known_mines: set[Cell],
                numbers: list[tuple[int, list[Cell]]] | None = None) -> list[tuple[frozenset[Cell], int]]:
    """For each revealed number: (its unknown hidden neighbours, mines still needed among them)."""
    out = []
    revealed = game.revealed
    for n, around in (numbers if numbers is not None else _numbers(game)):
        unknown = [x for x in around if x not in revealed and x not in known_mines]
        if not unknown:
            continue
        mines_known = sum(1 for x in around if x in known_mines)
        out.append((frozenset(unknown), n - mines_known))
    return out


def deduce(game: Minesweeper, known_mines: set[Cell] | None = None,
           use_subsets: bool = True) -> tuple[set[Cell], set[Cell]]:
    """Apply the counting rules until nothing changes. Returns (cells proven safe, cells proven mines).

    `use_subsets=False` applies only rules 1 and 2 (the basic rules every player knows).
    """
    mines: set[Cell] = set(known_mines or ())
    safe: set[Cell] = set()
    numbers = _numbers(game)  # the board does not change while deducing
    changed = True
    while changed:
        changed = False
        found = [(cells - safe, need) for cells, need in constraints(game, mines, numbers)]
        found = [(cells, need) for cells, need in found if cells]
        for cells, need in found:
            if need == 0:
                if not cells <= safe:
                    safe |= cells
                    changed = True
            elif need == len(cells):
                if not cells <= mines:
                    mines |= cells
                    changed = True
        if changed or not use_subsets:
            continue
        for a, need_a in found:
            for b, need_b in found:
                if a is b or not a < b:
                    continue
                rest, rest_need = b - a, need_b - need_a
                if rest_need == 0 and not rest <= safe:
                    safe |= rest
                    changed = True
                elif rest_need == len(rest) and not rest <= mines:
                    mines |= rest
                    changed = True
    return safe - game.revealed, mines


def visible_risk(game: Minesweeper, mines: set[Cell],
                 found: list[tuple[frozenset[Cell], int]] | None = None) -> dict[Cell, float]:
    """Mine estimate for every unknown hidden cell, using only this board: the worst
    "mines needed / hidden cells" of the numbers touching it, else the remaining density."""
    unknown = [(r, c) for r in range(game.rows) for c in range(game.cols)
               if (r, c) not in game.revealed and (r, c) not in mines]
    density = (game.config.mines - len(mines)) / max(1, len(unknown))
    risk = {cell: density for cell in unknown}
    for cells, need in (found if found is not None else constraints(game, mines)):
        for cell in cells:
            risk[cell] = max(risk.get(cell, density), need / len(cells))
    return risk


class ExpertSolver:
    """Reference player: deduction, then the lowest visible risk. Never learns."""

    def __init__(self, rng: random.Random):
        self.rng = rng
        self.known_mines: set[Cell] = set()

    def choose(self, game: Minesweeper) -> tuple[Cell, str]:
        safe, self.known_mines = deduce(game, self.known_mines)
        if safe:
            return sorted(safe)[0], "Proven safe by the counting rules."
        risk = visible_risk(game, self.known_mines)
        best = min(risk.values())
        options = sorted(cell for cell, value in risk.items() if value <= best + 1e-9)
        return self.rng.choice(options), f"No certain move; guessing a cell with ~{best:.0%} estimated risk."


def play_expert(game: Minesweeper, max_moves: int, seed_text: str) -> Minesweeper:
    """Play one full game with the expert solver (reveals only)."""
    solver = ExpertSolver(random.Random(seed_text))
    while not game.is_over and game.moves < max_moves:
        cell, _ = solver.choose(game)
        game.reveal(*cell)
    if not game.is_over:
        game.end_by_timeout()
    return game
