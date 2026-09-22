"""
Persistent Maze Learning Benchmark environment.

Supports 5x5 / 6x6 / 7x7 mazes with S, E, ., #, K, D, T semantics:
  S start, E exit, . open, # wall, K key, D locked door, T trap

- Deterministic generation from a seed (same maze sequence for every experiment).
- Partial observability: the agent sees its current cell and the 3x3 around it;
  previously seen cells stay in its map, unseen cells render as '?'.
- Key must be collected before the locked door can be passed.
- Entering a trap adds a 5-move penalty.
- Episode ends on reaching E (success) or exhausting the move budget (failure).
"""
import random
from collections import deque
from typing import Set, Tuple

from .base import Environment, EnvironmentState, ActionResult

DIRECTIONS = {"up": (-1, 0), "down": (1, 0), "left": (0, -1), "right": (0, 1)}

DEFAULT_SIZE_CONFIG = {
    5: {"key_door": False, "traps": 0, "max_moves": 30},
    6: {"key_door": True, "traps": 2, "max_moves": 40},
    7: {"key_door": True, "traps": 3, "max_moves": 55},
}


def _in_bounds(size: int, cell: Tuple[int, int]) -> bool:
    r, c = cell
    return 0 <= r < size and 0 <= c < size


def _neighbors(size: int, cell: Tuple[int, int]):
    r, c = cell
    for dr, dc in DIRECTIONS.values():
        nxt = (r + dr, c + dc)
        if _in_bounds(size, nxt):
            yield nxt


def _bfs(size: int, grid, start: Tuple[int, int], blocked: Set[Tuple[int, int]] = frozenset()):
    dist = {start: 0}
    queue = deque([start])
    while queue:
        cell = queue.popleft()
        for nxt in _neighbors(size, cell):
            if nxt in dist or nxt in blocked:
                continue
            if grid[nxt[0]][nxt[1]] == "#":
                continue
            dist[nxt] = dist[cell] + 1
            queue.append(nxt)
    return dist


def optimal_moves(maze: dict) -> int | None:
    """Shortest move count from S to E, collecting K before D and avoiding traps."""
    size = maze["size"]
    grid = maze["grid"]
    start, exit_cell = maze["start"], maze["exit"]
    key, door, traps = maze["key"], maze["door"], set(maze["traps"])

    dist = {(start, False): 0}
    queue = deque([(start, False)])
    while queue:
        cell, has_key = queue.popleft()
        if cell == exit_cell:
            return dist[(cell, has_key)]
        for nxt in _neighbors(size, cell):
            if grid[nxt[0]][nxt[1]] == "#" or nxt in traps:
                continue
            if nxt == door and not has_key:
                continue
            new_key = has_key or (nxt == key)
            state = (nxt, new_key)
            if state in dist:
                continue
            dist[state] = dist[(cell, has_key)] + 1
            queue.append(state)
    return None


def generate_maze(size: int, seed, key_door: bool, traps: int) -> dict:
    """Deterministically generate a valid maze. Raises RuntimeError if impossible."""
    for attempt in range(200):
        rng = random.Random(f"{size}-{seed}-{attempt}")
        grid = [["#" for _ in range(size)] for _ in range(size)]
        rooms = [(r, c) for r in range(1, size, 2) for c in range(1, size, 2)]
        if not rooms:
            continue

        start_room = rooms[0]
        stack = [start_room]
        seen = {start_room}
        grid[start_room[0]][start_room[1]] = "."
        while stack:
            r, c = stack[-1]
            options = []
            for dr, dc in ((0, 2), (0, -2), (2, 0), (-2, 0)):
                nr, nc = r + dr, c + dc
                if (nr, nc) in rooms and (nr, nc) not in seen:
                    options.append((nr, nc, dr, dc))
            if not options:
                stack.pop()
                continue
            nr, nc, dr, dc = rng.choice(options)
            grid[r + dr // 2][c + dc // 2] = "."
            grid[nr][nc] = "."
            seen.add((nr, nc))
            stack.append((nr, nc))

        # Add a few loops so multiple routes can exist
        wall_candidates = []
        for r in range(1, size - 1):
            for c in range(1, size - 1):
                if grid[r][c] != "#":
                    continue
                horizontal = grid[r][c - 1] == "." and grid[r][c + 1] == "."
                vertical = grid[r - 1][c] == "." and grid[r + 1][c] == "."
                if horizontal or vertical:
                    wall_candidates.append((r, c))
        rng.shuffle(wall_candidates)
        for r, c in wall_candidates[: max(1, len(wall_candidates) // 6)]:
            grid[r][c] = "."

        open_cells = [(r, c) for r in range(size) for c in range(size) if grid[r][c] == "."]
        start = (1, 1) if grid[1][1] == "." else open_cells[0]

        dist = _bfs(size, grid, start)
        if len(dist) < len(open_cells):
            continue
        exit_cell = max(dist, key=lambda cell: (dist[cell], cell))
        if dist[exit_cell] < 4:
            continue

        # Reconstruct BFS path start -> exit to place the door
        path = [exit_cell]
        while path[-1] != start:
            cur = path[-1]
            for nxt in _neighbors(size, cur):
                if nxt in dist and dist[nxt] == dist[cur] - 1:
                    path.append(nxt)
                    break
            else:
                path = []
                break
        path.reverse()

        key_cell = door_cell = None
        if key_door:
            door_idx = max(1, min(len(path) - 2, int(len(path) * 0.6)))
            door_cell = path[door_idx]
            pre_door = _bfs(size, grid, start, blocked={door_cell})
            candidates = [cell for cell in pre_door if cell not in (start, door_cell) and pre_door[cell] >= 3]
            if not candidates:
                continue
            key_cell = max(candidates, key=lambda cell: pre_door[cell])

        trap_cells = []
        if traps:
            path_set = set(path)
            blocked = set()
            for _ in range(traps):
                options = [
                    cell for cell in open_cells
                    if cell not in path_set and cell not in blocked
                    and cell not in (start, exit_cell, key_cell, door_cell)
                    and abs(cell[0] - start[0]) + abs(cell[1] - start[1]) >= 3
                ]
                if not options:
                    break
                choice = rng.choice(options)
                trap_cells.append(choice)
                blocked.add(choice)

        maze = {
            "size": size,
            "grid": grid,
            "start": start,
            "exit": exit_cell,
            "key": key_cell,
            "door": door_cell,
            "traps": trap_cells,
            "seed": seed,
        }
        optimum = optimal_moves(maze)
        if optimum is None:
            continue
        maze["optimal_moves"] = optimum
        return maze

    raise RuntimeError(f"Could not generate a valid {size}x{size} maze for seed {seed}")


class MazeEnvironment(Environment):
    name = "maze"
    description = "Persistent Maze Learning Benchmark (5x5/6x6/7x7 with key, door, traps)"

    def __init__(
        self,
        task_description: str = "",
        maze_size: int = 5,
        maze_seed: int | None = None,
        key_door: bool | None = None,
        traps: int | None = None,
        max_moves: int | None = None,
    ):
        self.task_description = task_description
        config = DEFAULT_SIZE_CONFIG.get(maze_size, DEFAULT_SIZE_CONFIG[5])
        self.maze_size = maze_size
        self.maze_seed = maze_seed if maze_seed is not None else 1000 + maze_size
        self.maze = generate_maze(
            maze_size,
            self.maze_seed,
            config["key_door"] if key_door is None else key_door,
            config["traps"] if traps is None else traps,
        )
        self.max_moves = config["max_moves"] if max_moves is None else max_moves
        self.reset_sync()

    # ------------------------------------------------------------------
    def reset_sync(self):
        maze = self.maze
        self.pos = maze["start"]
        self.steps = 0
        self.penalty_moves = 0
        self.key_collected = False
        self.door_opened = False
        self.exit_reached = False
        self.episode_failed = False
        self.visits: dict[Tuple[int, int], int] = {}
        self.known: dict[Tuple[int, int], str] = {}
        self.cells_visited: Set[Tuple[int, int]] = set()
        self.invalid_moves = 0
        self.repeated_moves = 0
        self.trap_activations = 0
        self.reward_total = 0.0
        self.last_event = "Episode started."
        self._reveal()
        self._mark_visit(self.pos)

    @property
    def moves_used(self) -> int:
        return self.steps + self.penalty_moves

    def _symbol(self, cell: Tuple[int, int]) -> str:
        maze = self.maze
        if cell == self.pos:
            return "S" if cell == maze["start"] else "A"
        if cell == maze["start"]:
            return "S"
        if cell == maze["exit"]:
            return "E"
        if cell == maze["key"] and not self.key_collected:
            return "K"
        if cell == maze["door"]:
            return "D" if not self.door_opened else "d"
        if cell in maze["traps"]:
            return "T"
        return "#" if maze["grid"][cell[0]][cell[1]] == "#" else "."

    def _reveal(self):
        r, c = self.pos
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                cell = (r + dr, c + dc)
                if _in_bounds(self.maze_size, cell):
                    self.known[cell] = self._symbol(cell)

    def _mark_visit(self, cell: Tuple[int, int]):
        self.visits[cell] = self.visits.get(cell, 0) + 1
        self.cells_visited.add(cell)
        self._reveal()

    def _render(self) -> str:
        size = self.maze_size
        header = "    " + " ".join(str(i + 1) for i in range(size))
        lines = [f"Maze: {size}x{size} | Moves used: {self.moves_used}/{self.max_moves} | "
                 f"Key: {'yes' if self.key_collected else 'no'} | "
                 f"Status: {'EXIT FOUND' if self.exit_reached else ('FAILED (move budget exhausted)' if self.episode_failed else 'exploring')}"]
        lines.append(header)
        for r in range(size):
            row = []
            for c in range(size):
                cell = (r, c)
                row.append(self.known.get(cell, "?"))
            lines.append(f"{r + 1:>2}  " + " ".join(row))
        lines.append(
            f"Position: ({self.pos[1] + 1}, {self.pos[0] + 1}) (x, y) | "
            f"Visited cells: {len(self.cells_visited)} | Traps triggered: {self.trap_activations} | "
            f"Invalid moves: {self.invalid_moves}"
        )
        lines.append(f"Last event: {self.last_event}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    async def observe(self) -> EnvironmentState:
        return EnvironmentState(
            score=self.reward_total,
            description=self._render(),
            is_terminal=self.exit_reached or self.episode_failed,
            metadata={
                "position": (self.pos[1] + 1, self.pos[0] + 1),
                "moves_used": self.moves_used,
                "max_moves": self.max_moves,
                "key": self.key_collected,
                "exit_reached": self.exit_reached,
                "failed": self.episode_failed,
                "optimal_moves": self.maze["optimal_moves"],
            },
        )

    @staticmethod
    def _parse_direction(action) -> str | None:
        valid = set(DIRECTIONS)
        if isinstance(action, str):
            text = action.strip().lower()
            return text if text in valid else None
        if isinstance(action, dict):
            for key in ("direction", "action", "move", "tool", "command"):
                value = action.get(key)
                if isinstance(value, str) and value.strip().lower() in valid:
                    return value.strip().lower()
            params = action.get("parameters")
            if isinstance(params, dict):
                for key in ("direction", "action", "move", "dir", "to"):
                    value = params.get(key)
                    if isinstance(value, str) and value.strip().lower() in valid:
                        return value.strip().lower()
                for value in params.values():
                    if isinstance(value, str) and value.strip().lower() in valid:
                        return value.strip().lower()
        return None

    async def act(self, action: dict | str) -> ActionResult:
        direction = self._parse_direction(action)
        if not direction:
            self.invalid_moves += 1
            self.last_event = "Invalid action: no valid direction supplied."
            return ActionResult(
                success=False,
                error="Invalid direction. Use one of: Up, Down, Left, Right.",
                reward=-1.0,
            )

        dr, dc = DIRECTIONS[direction]
        target = (self.pos[0] + dr, self.pos[1] + dc)
        self.steps += 1

        if not _in_bounds(self.maze_size, target):
            self.invalid_moves += 1
            self.reward_total -= 2.0
            self.last_event = f"BLOCKED by outer boundary moving {direction}."
            return ActionResult(
                success=False,
                output=f"Result: BLOCKED. Moving {direction} would leave the maze. "
                       f"Position: ({self.pos[1] + 1}, {self.pos[0] + 1}).",
                reward=-2.0,
                metadata={"status": "boundary_blocked"},
            )

        cell_symbol = self.maze["grid"][target[0]][target[1]]
        if cell_symbol == "#":
            self.invalid_moves += 1
            self.known[target] = "#"
            self.reward_total -= 2.0
            self.last_event = f"BLOCKED by wall at ({target[1] + 1}, {target[0] + 1})."
            return ActionResult(
                success=False,
                output=f"Result: BLOCKED. Wall at ({target[1] + 1}, {target[0] + 1}). "
                       f"Position: ({self.pos[1] + 1}, {self.pos[0] + 1}).",
                reward=-2.0,
                metadata={"status": "wall_blocked", "wall": (target[1] + 1, target[0] + 1)},
            )

        if target == self.maze["door"] and not self.key_collected:
            self.invalid_moves += 1
            self.reward_total -= 2.0
            self.last_event = f"BLOCKED by locked door at ({target[1] + 1}, {target[0] + 1}); key required."
            return ActionResult(
                success=False,
                output=f"Result: BLOCKED. Locked door at ({target[1] + 1}, {target[0] + 1}). "
                       f"You need the key first. Position: ({self.pos[1] + 1}, {self.pos[0] + 1}).",
                reward=-2.0,
                metadata={"status": "door_locked"},
            )

        revisiting = target in self.cells_visited
        self.pos = target
        self._mark_visit(target)
        if revisiting:
            self.repeated_moves += 1

        events = []
        reward = 1.0 if not revisiting else 0.0

        if target == self.maze["exit"]:
            self.exit_reached = True
            reward += 100.0
            events.append("EXIT FOUND")
        if target == self.maze["key"] and not self.key_collected:
            self.key_collected = True
            reward += 5.0
            events.append("KEY collected")
        if target == self.maze["door"] and self.key_collected:
            self.door_opened = True
            events.append("door unlocked and passed")
        if target in self.maze["traps"]:
            self.trap_activations += 1
            self.penalty_moves += 5
            reward -= 5.0
            events.append("TRAP triggered (+5 move penalty)")

        if self.moves_used > self.max_moves and not self.exit_reached:
            self.episode_failed = True

        if self.exit_reached:
            self.last_event = f"EXIT FOUND in {self.steps} steps ({self.moves_used} moves)."
        elif self.episode_failed:
            self.last_event = f"Move budget exhausted ({self.moves_used}/{self.max_moves})."
        elif events:
            self.last_event = "; ".join(events) + f" at ({target[1] + 1}, {target[0] + 1})."
        else:
            self.last_event = f"Moved {direction} to ({target[1] + 1}, {target[0] + 1})."

        self.reward_total += reward

        result_bits = ["Result: SAFE."]
        if self.exit_reached:
            result_bits = ["Result: EXIT FOUND."]
        if events and not self.exit_reached:
            result_bits.append("; ".join(events) + ".")
        result_bits.append(f"Position: ({target[1] + 1}, {target[0] + 1}).")
        result_bits.append(f"Moves used: {self.moves_used}/{self.max_moves}.")

        return ActionResult(
            success=True,
            output=" ".join(result_bits),
            reward=reward,
            state_change=f"Moved {direction} from ({self.pos[1] + 1}, {self.pos[0] + 1})",
            metadata={"status": "exit" if self.exit_reached else "safe"},
        )

    async def reset(self) -> EnvironmentState:
        self.reset_sync()
        return await self.observe()

    async def is_finished(self) -> bool:
        return self.exit_reached or self.episode_failed

    def get_available_actions(self) -> list[dict]:
        return [
            {
                "name": "move",
                "description": (
                    "Move one cell on the maze grid. 'Right' increases x, 'Left' decreases x, "
                    "'Up' increases y, 'Down' decreases y. Walls block movement; the locked door "
                    "requires the key; traps cost 5 extra moves."
                ),
                "parameters": {"direction": "string (One of: 'Right', 'Up', 'Left', 'Down')"},
            }
        ]

    def episode_metrics(self) -> dict:
        return {
            "maze_size": self.maze_size,
            "maze_seed": self.maze_seed,
            "optimal_moves": self.maze["optimal_moves"],
            "success": self.exit_reached,
            "failed_budget": self.episode_failed,
            "steps": self.steps,
            "moves_used": self.moves_used,
            "penalty_moves": self.penalty_moves,
            "invalid_moves": self.invalid_moves,
            "repeated_moves": self.repeated_moves,
            "trap_activations": self.trap_activations,
            "cells_visited": len(self.cells_visited),
            "cells_seen": len(self.known),
            "key_collected": self.key_collected,
            "door_opened": self.door_opened,
            "final_position": (self.pos[1] + 1, self.pos[0] + 1),
            "reward_total": round(self.reward_total, 2),
        }

    def maze_map(self) -> dict:
        maze = self.maze
        return {
            "size": maze["size"],
            "grid": ["".join(row) for row in maze["grid"]],
            "start": (maze["start"][1] + 1, maze["start"][0] + 1),
            "exit": (maze["exit"][1] + 1, maze["exit"][0] + 1),
            "key": (maze["key"][1] + 1, maze["key"][0] + 1) if maze["key"] else None,
            "door": (maze["door"][1] + 1, maze["door"][0] + 1) if maze["door"] else None,
            "traps": [(c + 1, r + 1) for r, c in maze["traps"]],
            "optimal_moves": maze["optimal_moves"],
        }
