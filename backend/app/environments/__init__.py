from .base import Environment, EnvironmentState, ActionResult, EnvironmentRegistry
from .benchmark_env import BenchmarkEnvironment
from .python_env import PythonEnvironment
from .http_env import HTTPEnvironment
from .grid_world_env import GridWorldEnvironment
from .maze_env import MazeEnvironment
from .universal_env import UniversalSimulationEnvironment

def get_environment_for_task(task_config: dict, llm=None) -> Environment:
    """Dynamically select and initialize the appropriate environment based on task content."""
    title = (task_config.get("title") or "").lower()
    desc = (task_config.get("description") or "").lower()
    combined = f"{title} {desc}"

    # 0. Persistent Maze Learning Benchmark (key/door/trap maze semantics)
    maze_markers = ("locked door", "key", "trap", "k = key", "d = locked")
    if ("maze" in combined or "grid" in combined) and any(marker in combined for marker in maze_markers):
        return MazeEnvironment(
            task_description=task_config.get("description", ""),
            maze_size=task_config.get("maze_size", 5),
            maze_seed=task_config.get("maze_seed"),
            key_door=task_config.get("maze_key_door"),
            traps=task_config.get("maze_traps"),
            max_moves=task_config.get("maze_max_moves"),
        )

    # 1. Grid World / Navigation tasks
    grid_keywords = ["grid", "treasure", "obstacle", "coordinate", "move up", "move down", "maze", "5x5", "(1,1)", "(1, 1)"]
    if any(k in combined for k in grid_keywords):
        return GridWorldEnvironment(task_description=task_config.get("description", ""))

    # 2. Benchmark Number Optimization game
    bench_keywords = ["benchmark", "increase", "decrease", "boost", "stabilize", "hidden mechanics", "hidden rules", "score 100", "stability"]
    if any(k in combined for k in bench_keywords) and not any(k in combined for k in ["python", "code", "http", "api"]):
        return BenchmarkEnvironment()

    # 3. Python Code Execution tasks
    python_keywords = ["python", "script", "run code", "code execution", "function", "program"]
    if any(k in combined for k in python_keywords):
        return PythonEnvironment()

    # 4. HTTP / Web API tasks
    http_keywords = ["http", "api", "rest", "endpoint", "url", "fetch"]
    if any(k in combined for k in http_keywords):
        return HTTPEnvironment()

    # 5. Default: Universal Interactive Simulation
    return UniversalSimulationEnvironment(task_description=task_config.get("description", ""), llm=llm)

__all__ = [
    "Environment",
    "EnvironmentState",
    "ActionResult",
    "EnvironmentRegistry",
    "BenchmarkEnvironment",
    "PythonEnvironment",
    "HTTPEnvironment",
    "GridWorldEnvironment",
    "MazeEnvironment",
    "UniversalSimulationEnvironment",
    "get_environment_for_task"
]
