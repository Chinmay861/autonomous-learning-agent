from .base import Environment, EnvironmentState, ActionResult, EnvironmentRegistry
from .benchmark_env import BenchmarkEnvironment
from .python_env import PythonEnvironment
from .http_env import HTTPEnvironment
from .grid_world_env import GridWorldEnvironment
from .maze_env import MazeEnvironment
from .universal_env import UniversalSimulationEnvironment
import re
import logging

logger = logging.getLogger(__name__)

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
    """Return true only when the task actually supplies an HTTP interface."""
    return bool(_HTTP_URL_RE.search(text) or _HTTP_INTENT_RE.search(text))


def get_environment_for_task(task_config: dict, llm=None) -> Environment:
    """Dynamically select and initialize the appropriate environment based on task content.

    ROUTING PHILOSOPHY
    ==================
    Hardcoded environments (GridWorld, Maze, Benchmark) each simulate one
    narrow scenario. They MUST only activate when the task description is
    clearly asking for that EXACT scenario. Any creative, open-ended, or
    domain-specific task (farm, trading, city building, etc.) belongs in the
    UniversalSimulationEnvironment which uses the LLM to simulate the
    described world faithfully.

    Common false-positive keywords like "grid", "navigate", "score", or
    "discover" appear in many creative tasks and must NOT be used as sole
    routing signals.
    """
    title = (task_config.get("title") or "").lower()
    desc = (task_config.get("description") or "").lower()
    combined = f"{title} {desc}"

    # ── 1. Executable environments (Python, HTTP) ──────────────────────
    # These provide a real runtime, so they take highest precedence.
    python_keywords = ["python", "python code", "python script", "run code",
                       "execute code", "code execution"]
    if any(k in combined for k in python_keywords):
        logger.info(f"[Router] → PythonEnvironment (matched python keywords)")
        return PythonEnvironment()

    if _is_explicit_http_task(combined):
        logger.info(f"[Router] → HTTPEnvironment (matched HTTP URL/intent)")
        return HTTPEnvironment()

    # ── 2. Maze with key/door/trap mechanics ───────────────────────────
    # Only matches when the task explicitly describes maze navigation with
    # specific maze features (keys, locked doors, traps, S/E/K/D/T symbols).
    maze_markers = ("locked door", "key", "trap", "k = key", "d = locked",
                    "find the exit", "reach the exit", "maze exit")
    if "maze" in combined and any(m in combined for m in maze_markers):
        logger.info(f"[Router] → MazeEnvironment (matched maze + key/door/trap)")
        return MazeEnvironment(
            task_description=task_config.get("description", ""),
            maze_size=task_config.get("maze_size", 5),
            maze_seed=task_config.get("maze_seed"),
            key_door=task_config.get("maze_key_door"),
            traps=task_config.get("maze_traps"),
            max_moves=task_config.get("maze_max_moves"),
        )

    # ── 3. Grid World treasure hunt ────────────────────────────────────
    # Only matches when the task is specifically about navigating a grid to
    # find a treasure/goal at coordinates. Must mention "treasure" or
    # explicit coordinate targets like "(5,5)". Generic words like "grid"
    # or "navigate" alone do NOT trigger this.
    has_treasure = "treasure" in combined
    has_coord_target = bool(re.search(r"reach\s+\(\d+\s*,\s*\d+\)", combined))
    has_grid_nav = ("grid" in combined and
                    any(d in combined for d in ["move up", "move down",
                                                 "move left", "move right"]))
    if has_treasure and ("grid" in combined or "navigate" in combined):
        logger.info(f"[Router] → GridWorldEnvironment (matched treasure + grid)")
        return GridWorldEnvironment(task_description=task_config.get("description", ""))
    if has_coord_target and has_grid_nav:
        logger.info(f"[Router] → GridWorldEnvironment (matched coordinate target + grid nav)")
        return GridWorldEnvironment(task_description=task_config.get("description", ""))

    # ── 4. Benchmark number optimization game ──────────────────────────
    # Only matches the specific "hidden mechanics" optimization game where
    # the valid actions are increase/decrease/reset/boost/stabilize.
    bench_exact = ["hidden mechanics", "score 100", "number optimization",
                   "benchmark environment"]
    if any(k in combined for k in bench_exact):
        # Extra check: the task must mention the benchmark game actions
        bench_actions = ["increase", "decrease", "boost", "stabilize"]
        if sum(1 for a in bench_actions if a in combined) >= 2:
            logger.info(f"[Router] → BenchmarkEnvironment (matched benchmark markers + actions)")
            return BenchmarkEnvironment()

    # ── 5. Default: Universal Interactive Simulation ───────────────────
    # This is the catch-all for ALL creative, open-ended, domain-specific,
    # or custom tasks. The LLM simulates the described world, respects the
    # task's own rules, actions, and mechanics.
    logger.info(f"[Router] → UniversalSimulationEnvironment (default — custom/creative task)")
    return UniversalSimulationEnvironment(
        task_description=task_config.get("description", ""), llm=llm
    )

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
