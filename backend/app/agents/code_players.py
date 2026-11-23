"""The two compared Minesweeper agents. Pure code: no LLM is ever called.

Both agents solve each game the SAME way, on the same boards:

1. **Reason from the visible numbers** (fresh every game, no memory): the basic
   counting rules find cells that are certainly safe and cells that are certainly
   mines (`app.game.solver.deduce`). If a cell is certainly safe, reveal it.
2. **When nothing is certain, guess** the hidden cell judged least likely to be a mine.

The only difference is what informs that judgement:

* **Without learning**: only this game's board ("this 1 has 2 hidden neighbours,
  so ~50%"). It never reads any memory, so it figures every game out on its own.
* **With persistent learning**: the same visible estimate, refined by its
  `PatternMemory`: how often cells in this exact situation were mines in all past
  games. Among certainly-safe cells it also prefers the one its memory says is most
  likely to open an empty region, so it learns to finish in fewer moves.

What each agent sees is recorded as experience:

* the learning agent's own outcomes go into its memory immediately (a mine hit is
  learned at once) and again when the game ends and every mine is revealed;
* the no-learning agent's outcomes and mistakes are recorded into a separate buffer
  that the runner merges into the same memory only after the board is finished. The
  learning agent therefore also learns from the other agent's games, but never from
  a board it is still playing, and the no-learning agent never reads any of it.

The game rules themselves are hard-coded in `app.game.minesweeper`.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from app.game.minesweeper import Minesweeper
import math

from app.game.solver import constraints, deduce, visible_risk
from app.learning.overlaps import (
    RULE_MIN_EVIDENCE, RULE_MIN_EVIDENCE_MINE, describe_overlap, overlap_keys, undecided,
)
from app.learning.patterns import SMOOTHING, ZERO_PRIOR, PatternMemory, outcome_of, pattern_key, signature_key

# Cells within this margin of the best estimate count as equally safe; among them the
# learning agent prefers the one most likely to open an empty region.
TIE_MARGIN = 0.01

RULE_ROUNDS = 4  # learned mines can unlock further deductions; repeat a few times

Cell = tuple[int, int]


def _logit(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


@dataclass
class Choice:
    cell: Cell
    p_mine: float
    p_zero: float
    evidence: int
    reason: str
    certain: bool = False


_interior_cache: dict[tuple[int, int, int, int], tuple[str, str]] = {}


def _interior_keys(game: Minesweeper, cell: Cell) -> tuple[str, str]:
    key = (game.rows, game.cols, cell[0], cell[1])
    found = _interior_cache.get(key)
    if found is None:
        found = (pattern_key(game, cell[0], cell[1], 1), "s:-")
        _interior_cache[key] = found
    return found


class CodePlayer:
    """`reads`: the memory consulted when choosing (None = never uses past experience).
    `writes`: where observations are recorded (may be a buffer merged in later)."""

    def __init__(self, reads: PatternMemory | None, writes: PatternMemory | None, rng: random.Random,
                 use_subsets: bool = False):
        self.reads = reads
        self.writes = writes
        self.rng = rng
        self.use_subsets = use_subsets
        # Situations looked at this game, per cell: {cell: {pattern: already recorded?}}
        self._seen: dict[Cell, dict[str, bool]] = {}

    @property
    def learns(self) -> bool:
        return self.reads is not None

    @property
    def memory(self) -> PatternMemory | None:  # what this agent learns from (None for no-learning)
        return self.reads

    def new_game(self) -> None:
        self._seen = {}

    def choose(self, game: Minesweeper) -> Choice:
        safe, mines = deduce(game, use_subsets=self.use_subsets)
        found = constraints(game, mines)
        risk = visible_risk(game, mines, found)
        tracked = self.writes is not None or self.reads is not None
        keys = {cell: self._keys(game, cell, mines) for cell in risk} if tracked else {}
        # Overlap situations are only recorded where the basic rules cannot decide anything, so every
        # rule memory discovers is knowledge beyond what both agents already share.
        overlaps = overlap_keys(undecided(found, safe)) if tracked else {}
        self._observe(keys, overlaps)

        if safe:
            return self._pick_safe(sorted(safe), keys, "Certain: the numbers prove this cell is safe")

        if self.reads is None:
            best = min(risk.values())
            cell = self.rng.choice(sorted(c for c, v in risk.items() if v <= best + 1e-9))
            return Choice(cell, best, 0.0, 0,
                          f"No certain move; guessing the lowest risk visible on this board (~{best:.0%}).")

        # ---- Only the learning agent gets here: use what past games taught it. ----
        known_mines = set(mines)
        used_rules: list[tuple[str, int]] = []
        for _ in range(RULE_ROUNDS):
            learned_safe, learned_mines = self._learned_rules(constraints(game, known_mines))
            learned_safe = {c: v for c, v in learned_safe.items() if c not in known_mines}
            if learned_safe:
                cell, (key, seen) = max(learned_safe.items(), key=lambda item: item[1][1])
                options = sorted(c for c in learned_safe if learned_safe[c][1] >= seen)
                choice = self._pick_safe(options, keys,
                                         f"Learned rule ({describe_overlap(key)}): never a mine in {seen} past "
                                         f"cases", certain=False)
                return choice
            new_mines = {c: v for c, v in learned_mines.items() if c not in known_mines}
            if not new_mines:
                break
            used_rules.extend(new_mines.values())
            known_mines |= set(new_mines)
            # Learned mines feed the basic rules, which may now prove cells safe.
            proven, known_mines = deduce(game, known_mines, use_subsets=self.use_subsets)
            if proven:
                key, seen = max(used_rules, key=lambda item: item[1])
                return self._pick_safe(sorted(proven), keys,
                                       f"Safe once its learned rules mark the mines ({describe_overlap(key)}: "
                                       f"always a mine in {seen} past cases)", certain=False)

        final_found = constraints(game, known_mines)
        final_risk = visible_risk(game, known_mines, final_found)
        if not final_risk:
            # Learned "mines" covered every remaining cell, which cannot be right (the game is not won):
            # ignore them and judge from what the board itself shows.
            known_mines, final_found, final_risk = mines, found, risk
        final_overlaps = overlap_keys(final_found)
        scored = []
        for cell, visible in final_risk.items():
            p_mine, p_zero, evidence = self._combined_estimate(keys.get(cell) or self._keys(game, cell, known_mines),
                                                               final_overlaps.get(cell, ()), visible)
            scored.append((p_mine, p_zero, evidence, visible, cell))
        best = min(s[0] for s in scored)
        near = [s for s in scored if s[0] <= best + TIE_MARGIN]
        top_zero = max(s[1] for s in near)
        p_mine, p_zero, evidence, visible, cell = self.rng.choice([s for s in near if s[1] >= top_zero - 1e-9])
        if evidence:
            reason = (f"No certain move; memory puts this cell at ~{p_mine:.0%} mine (board alone says "
                      f"~{visible:.0%}) from {evidence} past sightings of situations like this.")
        else:
            reason = f"No certain move; situation never seen before, so using the board's estimate (~{visible:.0%})."
        return Choice(cell, p_mine, p_zero, evidence, reason)

    def _pick_safe(self, options: list[Cell], keys: dict, reason: str, certain: bool = True) -> Choice:
        """Choose among cells believed safe. The learning agent prefers the one its memory says most
        often opens an empty region (fewer moves); the no-learning agent takes any of them."""
        if self.reads is None:
            return Choice(self.rng.choice(options), 0.0, 0.0, 0, reason + ".", certain=certain)
        scored = [(self.reads.estimate(*keys[c][:2], 0.0, keys[c][2]).p_zero if c in keys else ZERO_PRIOR, c)
                  for c in options]
        top = max(p for p, _ in scored)
        cell = self.rng.choice([c for p, c in scored if p >= top - 1e-9])
        extra = f" It is the likeliest of {len(options)} to open an empty region (~{top:.0%})." if len(options) > 1 else ""
        return Choice(cell, 0.0, top, 0, f"{reason}.{extra}", certain=certain)

    def _learned_rules(self, found: list) -> tuple[dict[Cell, tuple[str, int]], dict[Cell, tuple[str, int]]]:
        """Overlap situations memory has seen often and never seen go the other way."""
        safe: dict[Cell, tuple[str, int]] = {}
        mines: dict[Cell, tuple[str, int]] = {}
        for cell, cell_keys in overlap_keys(found).items():
            for key in cell_keys:
                m, z, n = self.reads.counts.get(key, (0, 0, 0))
                seen = m + z + n
                if seen < RULE_MIN_EVIDENCE:
                    continue
                if m == 0 and seen > safe.get(cell, ("", 0))[1]:
                    safe[cell] = (key, seen)
                elif m == seen and seen >= RULE_MIN_EVIDENCE_MINE and seen > mines.get(cell, ("", 0))[1]:
                    mines[cell] = (key, seen)
        for cell in set(safe) & set(mines):  # contradictory evidence: trust neither
            del safe[cell], mines[cell]
        return safe, mines

    def _combined_estimate(self, keys: tuple[str, str, str], overlaps, visible: float) -> tuple[float, float, int]:
        """Blend the cell's own-picture estimate with every overlapping-number situation it is in."""
        p_chain, p_zero, evidence = self._estimate(keys, visible)
        total_weight, total_logit = 1.0, _logit(p_chain)
        for key in overlaps:
            m, z, n = self.reads.counts.get(key, (0, 0, 0))
            seen = m + z + n
            if seen < 5:
                continue
            p_key = (m + SMOOTHING * p_chain) / (seen + SMOOTHING)
            weight = seen / (seen + 20.0)
            total_weight += weight
            total_logit += weight * _logit(p_key)
            evidence = max(evidence, seen)
        return _sigmoid(total_logit / total_weight), p_zero, evidence

    def _keys(self, game: Minesweeper, cell: Cell, mines: set[Cell]) -> tuple[str, str, str]:
        """(3x3 picture, number signature, 5x5 picture): general to specific."""
        if not any(n in game.revealed for n in game.neighbors(*cell)):
            # No revealed neighbour: the 3x3 picture and signature only depend on the board edges.
            k3, ks = _interior_keys(game, cell)
        else:
            k3, ks = pattern_key(game, cell[0], cell[1], 1), signature_key(game, cell[0], cell[1], mines)
        return k3, ks, pattern_key(game, cell[0], cell[1], 2)

    def _estimate(self, keys: tuple[str, str, str], visible: float) -> tuple[float, float, int]:
        """Memory estimate, backing off to the visible-board estimate where experience is thin."""
        est = self.reads.estimate(keys[0], keys[1], visible, keys[2])
        return est.p_mine, est.p_zero, est.evidence

    def _observe(self, keys_by_cell: dict[Cell, tuple[str, str, str]], overlaps: dict[Cell, set[str]]) -> None:
        """Remember the situation of every undecided hidden cell, to record its outcome later."""
        if self.writes is None:
            return
        for cell, cell_keys in keys_by_cell.items():
            seen = self._seen.setdefault(cell, {})
            for key in (*cell_keys, *overlaps.get(cell, ())):
                seen.setdefault(key, False)

    def learn_from_move(self, game: Minesweeper, cell: Cell) -> None:
        """Record the outcome of the cell just revealed, right away (a mine hit is a lesson at once)."""
        if self.writes is None:
            return
        outcome = outcome_of(game, cell)
        keys = self._seen.get(cell, {})
        for key, recorded in keys.items():
            if not recorded:
                self.writes.record(key, outcome)
                keys[key] = True

    def learn_from_game(self, game: Minesweeper) -> int:
        """At game end every mine is known: record the outcome of every situation looked at."""
        if self.writes is None:
            return 0
        learned = 0
        for cell, keys in self._seen.items():
            outcome = outcome_of(game, cell)
            for key, recorded in keys.items():
                if not recorded:
                    self.writes.record(key, outcome)
                    learned += 1
        self._seen = {}
        return learned


__all__ = ["CodePlayer", "Choice", "SMOOTHING"]
