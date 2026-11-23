"""Overlapping-number situations: the experience that lets the learning agent go
beyond the basic counting rules.

The basic rules look at one number at a time. Many Minesweeper positions are only
solved by looking at two numbers whose hidden cells overlap. This module describes
such a pair compactly, and nothing in it says what the description *means*:

    o:<need A>/<cells A>|<need B>/<cells B>|<shared cells>|<role>

* need/cells: mines each number still needs, among how many undecided hidden cells;
* shared cells: how many of those cells both numbers touch;
* role: where the cell being judged sits: "A" (only the first number touches it),
  "B" (only the second) or "AB" (both).

The pair is put in a canonical order so the same situation always gets the same key.
Some of these situations turn out the same way every single time (for example the
cells outside a number that already accounts for its neighbour's mines are always
safe). The agent discovers that from outcomes, its own and the other agent's, and
from then on treats it as a rule it has learned.
"""
from __future__ import annotations

from collections import defaultdict

Cell = tuple[int, int]
Constraint = tuple[frozenset[Cell], int]

PREFIX = "o:"

# An overlap situation becomes a *learned rule* once memory has seen it this many times and it
# has never once gone the other way. Mines need more evidence, because a wrong "mine" feeds the
# counting rules and could turn into a wrong "safe".
RULE_MIN_EVIDENCE = 30
RULE_MIN_EVIDENCE_MINE = 60


def undecided(found: list[Constraint], safe: set[Cell] = frozenset()) -> list[Constraint]:
    """Numbers the basic rules cannot settle: some, but not all, of their open cells are mines."""
    out = []
    for cells, need in found:
        open_cells = cells - safe
        if open_cells and 0 < need < len(open_cells):
            out.append((frozenset(open_cells), need))
    return out


def is_trivial(key: str) -> bool:
    """True for situations the basic rules already decide (a number needing 0, or needing all its cells)."""
    first, second = key[len(PREFIX):].split("|")[:2]
    for part in (first, second):
        need, cells = (int(x) for x in part.split("/"))
        if need == 0 or need == cells:
            return True
    return False


def overlap_keys(found: list[Constraint]) -> dict[Cell, set[str]]:
    """For every hidden cell in an overlapping pair of numbers: the keys of those pairs."""
    by_cell: dict[Cell, list[int]] = defaultdict(list)
    for index, (cells, _) in enumerate(found):
        for cell in cells:
            by_cell[cell].append(index)

    pairs: set[tuple[int, int]] = set()
    for indices in by_cell.values():
        for i in range(len(indices)):
            for j in range(i + 1, len(indices)):
                pairs.add((indices[i], indices[j]))

    out: dict[Cell, set[str]] = defaultdict(set)
    for a, b in pairs:
        cells_a, need_a = found[a]
        cells_b, need_b = found[b]
        if cells_a == cells_b:
            continue  # two numbers over the very same cells say nothing new together
        if (need_b, len(cells_b)) < (need_a, len(cells_a)):
            cells_a, need_a, cells_b, need_b = cells_b, need_b, cells_a, need_a
        shared = cells_a & cells_b
        symmetric = (need_a, len(cells_a)) == (need_b, len(cells_b))
        prefix = f"{PREFIX}{need_a}/{len(cells_a)}|{need_b}/{len(cells_b)}|{len(shared)}|"
        for cell in cells_a | cells_b:
            if cell in shared:
                role = "AB"
            elif cell in cells_a or symmetric:
                role = "A"
            else:
                role = "B"
            out[cell].add(prefix + role)
    return out


def describe_overlap(key: str) -> str:
    """Plain-language reading of an overlap key, for the memory panel."""
    body = key[len(PREFIX):]
    first, second, shared, role = body.split("|")
    need_a, cells_a = first.split("/")
    need_b, cells_b = second.split("/")

    def number(need: str, cells: str) -> str:
        return f"a number needing {need} mine{'' if need == '1' else 's'} among {cells} cell{'' if cells == '1' else 's'}"

    where = {
        "AB": "a cell both numbers touch",
        "A": "a cell only the first number touches",
        "B": "a cell only the second number touches",
    }[role]
    return (f"{number(need_a, cells_a).capitalize()} overlapping {number(need_b, cells_b)} "
            f"({shared} shared): {where}")


def discovered_rules(counts: dict[str, list[int]], min_safe: int = RULE_MIN_EVIDENCE,
                     min_mine: int = RULE_MIN_EVIDENCE_MINE) -> dict[str, tuple[str, int]]:
    """Overlap situations seen often enough that never went the other way: {key: ("safe"|"mine", seen)}."""
    rules: dict[str, tuple[str, int]] = {}
    for key, (m, z, n) in counts.items():
        if not key.startswith(PREFIX) or is_trivial(key):
            continue
        seen = m + z + n
        if m == 0 and seen >= min_safe:
            rules[key] = ("safe", seen)
        elif m == seen and seen >= min_mine:
            rules[key] = ("mine", seen)
    return rules
