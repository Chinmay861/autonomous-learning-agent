"""Pattern memory: what a code-only agent learns from playing Minesweeper.

No language model is involved. The agent describes every hidden cell by the
visible board around it (a *pattern*) and remembers, per pattern, how often such
a cell turned out to be:

* a mine (the danger it must avoid), or
* an empty "0" cell (which opens a whole region, so revealing it saves moves), or
* a numbered cell.

Each hidden cell is described two ways:

* a **3x3 picture** of what is visible around it, canonicalised over the 8
  rotations/reflections of the square ("1:" keys), and
* a **number signature** ("s:" keys): for every revealed number touching the cell,
  how many mines that number still needs and among how many hidden cells, e.g.
  "needs 1 among 1". What a signature *means* is not coded anywhere; the agent
  learns it from outcomes.

Estimates back off from signature to 3x3 picture to the board's overall mine
density, so a new memory starts as a blind guesser and sharpens as evidence
accumulates.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from app.game.minesweeper import Minesweeper

WALL = "|"       # outside the board
HIDDEN = "#"
FLAG = "F"

# Bayesian smoothing strength: how many observations an estimate needs before it
# outweighs the coarser level it backs off to.
SMOOTHING = 2.0
ZERO_PRIOR = 0.2


def _symmetries(size: int) -> list[tuple[int, ...]]:
    """Index permutations of a size x size window for the 8 symmetries of the square."""
    coords = [(r, c) for r in range(size) for c in range(size)]
    n = size - 1
    transforms = [
        lambda r, c: (r, c), lambda r, c: (c, n - r), lambda r, c: (n - r, n - c), lambda r, c: (n - c, r),
        lambda r, c: (r, n - c), lambda r, c: (n - r, c), lambda r, c: (c, r), lambda r, c: (n - c, n - r),
    ]
    perms = []
    for t in transforms:
        perms.append(tuple(t(r, c)[0] * size + t(r, c)[1] for r, c in coords))
    return perms


_SYM = {1: _symmetries(3), 2: _symmetries(5)}


def _cell_symbol(game: Minesweeper, r: int, c: int) -> str:
    if not game.in_bounds(r, c):
        return WALL
    if (r, c) in game.revealed:
        return str(game.count(r, c))
    if (r, c) in game.flags:
        return FLAG
    return HIDDEN


def pattern_key(game: Minesweeper, r: int, c: int, radius: int) -> str:
    """Canonical key of the (2*radius+1)^2 window centred on (r, c), as the player can see it."""
    raw = "".join(
        _cell_symbol(game, rr, cc)
        for rr in range(r - radius, r + radius + 1)
        for cc in range(c - radius, c + radius + 1)
    )
    return _canonical(raw, radius)


_canonical_cache: dict[tuple[str, int], str] = {}


def _canonical(raw: str, radius: int) -> str:
    """Smallest of the 8 rotations/reflections. Memoised: the same windows recur constantly."""
    key = (raw, radius)
    found = _canonical_cache.get(key)
    if found is None:
        if len(_canonical_cache) > 500_000:
            _canonical_cache.clear()
        found = f"{radius}:" + min("".join(raw[i] for i in perm) for perm in _SYM[radius])
        _canonical_cache[key] = found
    return found


def signature_key(game: Minesweeper, r: int, c: int, believed_mines: set[tuple[int, int]]) -> str:
    """For each number touching (r, c): mines it still needs / hidden cells it touches.

    Cells the agent itself believes are mines (from what it has learned) count as
    mines here, never as hidden cells.
    """
    parts = []
    for nr, nc in game.neighbors(r, c):
        if (nr, nc) not in game.revealed:
            continue
        number = game.count(nr, nc)
        if number == 0:
            continue
        around = game.neighbors(nr, nc)
        believed = sum(1 for x in around if x in believed_mines)
        hidden = sum(1 for x in around if x not in game.revealed and x not in believed_mines)
        parts.append(f"{max(0, number - believed)}/{hidden}")
    return "s:" + (",".join(sorted(parts)) if parts else "-")


def describe_signature(key: str) -> str:
    """Readable form of a signature key."""
    body = key[2:]
    if body == "-":
        return "No number touches this cell"
    bits = []
    for part in body.split(","):
        need, hidden = part.split("/")
        bits.append(f"a number needing {need} more mine{'s' if need != '1' else ''} among {hidden} hidden "
                    f"cell{'s' if hidden != '1' else ''}")
    return "Touches " + "; ".join(bits)


@dataclass
class Estimate:
    p_mine: float
    p_zero: float
    evidence: int  # observations behind the most specific level used


class PatternMemory:
    """In-memory counts {pattern: [mines, zeros, numbers]} plus the changes not yet saved."""

    def __init__(self, counts: dict[str, list[int]] | None = None):
        self.counts: dict[str, list[int]] = counts or {}
        self.pending: dict[str, list[int]] = {}

    def __len__(self) -> int:
        return len(self.counts)

    @property
    def observations(self) -> int:
        return sum(sum(v) for k, v in self.counts.items() if k.startswith("1:"))

    def record(self, key: str, outcome: str) -> None:
        """outcome: "mine" | "zero" | "number"."""
        index = {"mine": 0, "zero": 1, "number": 2}[outcome]
        for store in (self.counts, self.pending):
            row = store.setdefault(key, [0, 0, 0])
            row[index] += 1

    def absorb(self, increments: dict[str, list[int]]) -> int:
        """Add another agent's recorded experience (e.g. the no-learning agent's finished board)."""
        added = 0
        for key, values in increments.items():
            for store in (self.counts, self.pending):
                row = store.setdefault(key, [0, 0, 0])
                for i in range(3):
                    row[i] += values[i]
            added += sum(values)
        return added

    def take_pending(self) -> dict[str, list[int]]:
        pending, self.pending = self.pending, {}
        return pending

    def estimate(self, key3: str, key_sig: str, prior_mine: float, key5: str | None = None) -> Estimate:
        """Blend evidence from general to specific: board estimate -> 3x3 -> signature -> 5x5.

        Each level is pulled toward the level before it until it has seen enough cases, so a
        rare, very specific situation never overrides solid general knowledge.
        """
        p_mine, p_zero, evidence = prior_mine, ZERO_PRIOR, 0
        for key in (key3, key_sig, key5):
            if key is None:
                continue
            m, z, n = self.counts.get(key, (0, 0, 0))
            total = m + z + n
            p_mine = (m + SMOOTHING * p_mine) / (total + SMOOTHING)
            p_zero = (z + SMOOTHING * p_zero) / (total + SMOOTHING)
            if total:
                evidence = total
        return Estimate(p_mine, p_zero, evidence)


def outcome_of(game: Minesweeper, cell: tuple[int, int]) -> str:
    if cell in game.mines:
        return "mine"
    return "zero" if game.count(*cell) == 0 else "number"


def hidden_cells(game: Minesweeper) -> Iterable[tuple[int, int]]:
    for r in range(game.rows):
        for c in range(game.cols):
            if (r, c) not in game.revealed and (r, c) not in game.flags:
                yield (r, c)


def render_pattern(key: str) -> list[str]:
    """Rows of a stored key for display, with the centre cell shown as '?'."""
    radius_text, _, body = key.partition(":")
    size = 2 * int(radius_text) + 1
    rows = [body[i * size:(i + 1) * size] for i in range(size)]
    centre = size // 2
    rows[centre] = rows[centre][:centre] + "?" + rows[centre][centre + 1:]
    return rows
