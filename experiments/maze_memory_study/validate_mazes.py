import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.environments.maze_env import MazeEnvironment, generate_maze, optimal_moves  # noqa: E402

TRAIN = (
    [(5, 1001 + i, False, 0) for i in range(5)]
    + [(6, 2001 + i, True, min(3, 1 + i // 2)) for i in range(5)]
    + [(7, 3001 + i, True, [2, 2, 3, 3, 3][i]) for i in range(5)]
)
EVAL = [(5, 9001, False, 0), (6, 9002, True, 2), (7, 9003, True, 3)]

print(f"{'ep':>3} {'size':>4} {'seed':>6} {'key/door':>8} {'traps':>5} {'optimal':>7}")
for i, (size, seed, kd, tr) in enumerate(TRAIN + EVAL, start=1):
    maze = generate_maze(size, seed, kd, tr)
    assert optimal_moves(maze) is not None
    tag = "TRAIN" if i <= 15 else "EVAL"
    print(f"{i:>3} {size:>4} {seed:>6} {str(kd):>8} {tr:>5} {maze['optimal_moves']:>7}   {tag}")

print()
for size, seed, kd, tr in [(5, 1003, False, 0), (6, 2003, True, 2), (7, 3003, True, 3)]:
    env = MazeEnvironment(maze_size=size, maze_seed=seed, key_door=kd, traps=tr)
    print("=" * 64)
    print(env._render())
