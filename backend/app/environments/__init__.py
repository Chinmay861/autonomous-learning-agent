from .base import Environment, EnvironmentState, ActionResult, EnvironmentRegistry
from .benchmark_env import BenchmarkEnvironment
from .python_env import PythonEnvironment
from .http_env import HTTPEnvironment
from .grid_world_env import GridWorldEnvironment
from .maze_env import MazeEnvironment
from .universal_env import UniversalSimulationEnvironment
import re


_HTTP_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_HTTP_INTENT_RE = re.compile(
    r"\b(?:make|send|perform|issue|call)\s+(?:an?\s+)?(?:http\s+)?"
    r"(?:get|post|put|delete|request)\b|"
    r"\b(?:interact|connect|communicate)\s+(?:with|to)\s+(?:an?\s+)?"
    r"(?:http\s*|rest\s*)?(?:api|endpoint)\b|"
    r"\b(?:api|endpoint)\s+(?:base\s+)?url\s*[:=]|\bcurl\b",
    re.IGNORECASE,
)


def _is_explicit_http_task(text: str) -> bool:
    """Return true only when the task actually supplies an HTTP interface.

    Words such as "API", "URL", or "fetch" occur in ordinary research and
    simulation prompts.  Treating one word as proof of an HTTP environment
    makes the planner invent localhost endpoints instead of operating in the
    supplied simulation.  A concrete URL or an explicit request instruction
    is required before exposing the HTTP tool.
    """
    return bool(_HTTP_URL_RE.search(text) or _HTTP_INTENT_RE.search(text))

def get_environment_for_task(task_config: dict, llm=None) -> Environment:
    """Dynamically select and initialize the appropriate environment based on task content."""
    title = (task_config.get("title") or "").lower()
    desc = (task_config.get("description") or "").lower()
    combined = f"{title} {desc}"

    # Explicit executable interfaces take precedence over simulation words.
    # For example, "write a Python maze solver" is a coding task, not a maze
    # interaction task.
    python_keywords = ["python", "python code", "python script", "run code", "execute code", "code execution"]
    if any(k in combined for k in python_keywords):
        return PythonEnvironment()

    if _is_explicit_http_task(combined):
        return HTTPEnvironment()

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
    grid_keywords = [
        "grid", "treasure", "maze", "5x5", "(1,1)", "(1, 1)",
        "move up", "move down", "move left", "move right", "navigate",
    ]
    if any(k in combined for k in grid_keywords):
        return GridWorldEnvironment(task_description=task_config.get("description", ""))

    # 2. Benchmark Number Optimization game
    bench_markers = ["benchmark", "hidden mechanics", "hidden rules", "score 100", "stability"]
    optimization_verbs = ["increase", "decrease", "boost", "stabilize"]
    if (
        any(k in combined for k in bench_markers)
        or ("score" in combined and any(k in combined for k in optimization_verbs))
    ):
        return BenchmarkEnvironment()

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
