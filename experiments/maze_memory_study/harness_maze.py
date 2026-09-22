"""
Persistent Maze Learning Benchmark - episode harness.

Runs ONE experiment (A = persistence OFF, B = persistence ON) as its own
process with an isolated SQLite DB and storage directory, so A and B can run
in parallel without interference.

Each episode = one maze = one orchestrator run. 18 episodes per experiment:
15 training (5x 5x5, 5x 6x6, 5x 7x7) + 3 unseen evaluation (one per size).

Usage:
  python harness_maze.py --experiment A --tag full
  python harness_maze.py --experiment B --tag full
"""
import argparse
import asyncio
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1] / "backend"


def _early_arg(flag: str, default=None):
    if flag in sys.argv:
        return sys.argv[sys.argv.index(flag) + 1]
    return default


# Must be set before importing app modules (env vars override .env in pydantic-settings)
EXP = _early_arg("--experiment", "A").upper()
TAG = _early_arg("--tag", "full")
DB_NAME = _early_arg("--db", f"study_{EXP.lower()}")

import os  # noqa: E402

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///./storage/{DB_NAME}.db"
os.environ["STORAGE_DIR"] = f"./storage/{DB_NAME}"
os.environ.setdefault("QDRANT_URL", ":memory:")

sys.path.insert(0, str(BACKEND))

import harness as H  # noqa: E402  (instrumentation + helpers)
from app.agents.orchestrator import AgentOrchestrator  # noqa: E402
from app.database.models import Task, TaskStatus  # noqa: E402
from app.environments import get_environment_for_task  # noqa: E402
from app.memory.embeddings import EmbeddingService  # noqa: E402
from app.memory.memory_manager import MemoryManager  # noqa: E402
from app.memory.qdrant_store import QdrantStore  # noqa: E402
from app.memory.retriever import MemoryRetriever  # noqa: E402
from app.config import settings  # noqa: E402

TASK_TITLE = "Persistent Maze Learning Benchmark"

TASK_DESCRIPTION = """Persistent Maze Learning Benchmark. Solve grid mazes by interacting one action at a time.

Environment: mazes of size 5x5, 6x6 or 7x7 containing:
S = starting position, E = exit, . = open cell, # = wall, K = key, D = locked door, T = trap.
The agent initially knows the rules but does not know the maze layout.

Rules:
- The agent starts at S and must reach E.
- The agent can move only Up, Down, Left or Right. Diagonal movement is not allowed.
- The agent cannot move through #.
- The agent must collect K before passing through D.
- Entering T is allowed but adds a penalty of 5 moves.
- The agent receives feedback after every action.
- The agent has a limited number of moves per episode.
- The agent must maintain knowledge of: visited cells, blocked cells, successful moves, failed moves, dead ends, trap locations, key locations, door locations, successful strategies, failed strategies, mistakes and their causes.
- The agent should avoid repeating actions it has learned are unsuccessful.
- The agent should record successful and failed strategies, environmental patterns, discovered hazards, useful exploration techniques, and mistakes with their causes.
- The agent is allowed to create its own strategy. The solution path is never provided.
"""

TRAINING_MAZES = (
    [(5, 1001 + i, False, 0) for i in range(5)]
    + [(6, 2001 + i, True, min(3, 1 + i // 2)) for i in range(5)]
    + [(7, 3001 + i, True, [2, 2, 3, 3, 3][i]) for i in range(5)]
)
EVAL_MAZES = [(5, 9001, False, 0), (6, 9002, True, 2), (7, 9003, True, 3)]
BUDGETS = {5: 30, 6: 40, 7: 55}


async def run_episode(episode: dict, args, user_id: int, memory_manager: MemoryManager,
                      out_dir: Path) -> dict:
    label = episode["label"]
    size, seed, key_door, traps = episode["size"], episode["seed"], episode["key_door"], episode["traps"]
    budget = BUDGETS[size]
    if getattr(args, "budget_cap", None):
        budget = min(budget, args.budget_cap)
    task_id = str(uuid.uuid4())
    phase = episode["phase"]

    run_dir = out_dir / "runs" / label
    run_dir.mkdir(parents=True, exist_ok=True)
    events_log = run_dir / "events.jsonl"

    H.CURRENT.update(label=label, task_id=task_id, iteration=0, phase="ON" if phase == "ON" else "OFF",
                     surfacing_fix=(phase == "ON"))

    async with H.async_sessionmaker_db() as session:
        task = Task(
            id=task_id, user_id=user_id,
            title=f"MAZE-STUDY-{args.tag}-{EXP}-{label}",
            description=TASK_DESCRIPTION,
            max_iterations=budget, snapshot_interval=20, synthesis_interval=100,
            use_persistent_learning=(phase == "ON"),
            top_k=5, min_similarity=0.65,
            model=args.model, temperature=0.7,
            status=TaskStatus.CREATED, current_iteration=0,
        )
        session.add(task)
        await session.commit()
    await H.set_task_status(task_id, TaskStatus.RUNNING)

    llm = H.build_llm(args.model)
    H.instrument_llm(llm, out_dir / "llm_calls.jsonl")
    H.instrument_synthesis_shapes(llm, out_dir / "memory.jsonl")

    task_config = {
        "title": TASK_TITLE,
        "description": TASK_DESCRIPTION,
        "maze_size": size,
        "maze_seed": seed,
        "maze_key_door": key_door,
        "maze_traps": traps,
        "maze_max_moves": budget,
    }
    env = get_environment_for_task(task_config, llm)

    memory_manager.retrieval_enabled = (phase == "ON")

    iter_stats: dict[int, dict] = {}
    counters = {"learnings_created": 0, "rule_updates": 0, "strategy_changes": 0,
                "snapshots": 0, "synthesis_events": 0, "synthesis_units": 0,
                "synthesis_stored": 0}
    callback = H.make_event_callback(events_log, iter_stats, counters)

    orchestrator = AgentOrchestrator(
        llm=llm,
        environment=env,
        task_id=task_id,
        task_description=TASK_DESCRIPTION,
        max_iterations=budget,
        use_persistent_learning=(phase == "ON"),
        snapshot_interval=20,
        synthesis_interval=100,
        storage_dir=settings.STORAGE_DIR,
        top_k=5,
        min_similarity=0.65,
        memory_manager=memory_manager,
        event_callback=callback,
    )

    idx = {name: len(recs) for name, recs in (
        ("llm", H.LLM_RECS), ("http", H.HTTP_RECS), ("retrieval", H.RETRIEVAL_RECS),
        ("write", H.WRITE_RECS), ("embed", H.EMBED_RECS), ("event", H.EVENT_RECS))}
    stats_before = await memory_manager.qdrant_store.get_stats()

    started = H._utc()
    t0 = time.perf_counter()
    state = None
    error = None
    try:
        state = await orchestrator.run()
    except Exception as e:
        error = f"{type(e).__name__}: {str(e)[:400]}"
        H.logger.exception("episode %s failed", label)
    duration = time.perf_counter() - t0
    ended = H._utc()

    stats_after = await memory_manager.qdrant_store.get_stats()

    status = TaskStatus.FAILED if error else (
        TaskStatus.COMPLETED if state and state.completion_status == "completed" else TaskStatus.STOPPED)
    await H.set_task_status(task_id, status, state.iteration if state else None)

    llm_recs = H.LLM_RECS[idx["llm"]:]
    http_recs = H.HTTP_RECS[idx["http"]:]
    retrieval_recs = H.RETRIEVAL_RECS[idx["retrieval"]:]
    write_recs = H.WRITE_RECS[idx["write"]:]
    embed_recs = H.EMBED_RECS[idx["embed"]:]

    env_metrics = env.episode_metrics() if hasattr(env, "episode_metrics") else {}
    maze_map = env.maze_map() if hasattr(env, "maze_map") else {}

    db_iterations = await H.fetch_iterations(task_id)

    retrieved_counts = [r["count"] for r in retrieval_recs]
    all_scores = [s for r in retrieval_recs for s in r.get("scores", [])]
    llm_metrics = H.compute_llm_metrics(llm_recs)

    per_iteration = []
    for n in sorted(iter_stats):
        st = dict(iter_stats[n])
        tool, direction = H.parse_action(st.get("action"))
        st["tool"] = tool
        st["direction"] = direction
        st.pop("action", None)
        if "retrieved" in st:
            st["retrieved_top"] = [x["title"] for x in st["retrieved"][:3]]
            st.pop("retrieved")
        per_iteration.append(st)

    steps = env_metrics.get("steps", 0) or 0
    moves_used = env_metrics.get("moves_used", 0) or 0
    invalid = env_metrics.get("invalid_moves", 0) or 0
    repeated = env_metrics.get("repeated_moves", 0) or 0
    useful_moves = max(0, steps - invalid - repeated)

    metrics = {
        "episode": episode["index"],
        "episode_label": label,
        "phase": phase,
        "experiment": EXP,
        "tag": args.tag,
        "maze_size": size,
        "maze_seed": seed,
        "key_door": key_door,
        "traps": traps,
        "budget": budget,
        "task_id": task_id,
        "model": args.model,
        "reasoning_effort": H.REASONING_EFFORT,
        "started_at": started,
        "ended_at": ended,
        "duration_s": round(duration, 2),
        "error": error,
        "completion_status": state.completion_status if state else None,
        "success": bool(env_metrics.get("success")),
        "iterations_used": state.iteration if state else None,
        "llm": llm_metrics,
        "http": H.compute_http_metrics(http_recs),
        "env": env_metrics,
        "derived": {
            "path_efficiency": round(env_metrics.get("optimal_moves", 0) / moves_used, 3) if moves_used else None,
            "exploration_efficiency": round(useful_moves / steps, 3) if steps else None,
            "excess_moves_over_optimal": (moves_used - env_metrics.get("optimal_moves", 0)) if moves_used else None,
            "successful": bool(env_metrics.get("success")),
        },
        "memory": {
            "retrieval_calls": len(retrieval_recs),
            "retrieved_total": sum(retrieved_counts),
            "retrieved_mean_per_iteration": round(sum(retrieved_counts) / len(retrieved_counts), 3) if retrieved_counts else 0.0,
            "iterations_with_memory": sum(1 for c in retrieved_counts if c > 0),
            "avg_similarity": round(sum(all_scores) / len(all_scores), 4) if all_scores else None,
            "writes_insert": sum(1 for r in write_recs if r["op"] == "insert"),
            "writes_merge": sum(1 for r in write_recs if r["op"] == "merge"),
            "store_calls": len(write_recs),
            "points_before": stats_before.get("total_points"),
            "points_after": stats_after.get("total_points"),
            "embed_calls": len(embed_recs),
            "embed_time_s": round(sum(r["dur_s"] for r in embed_recs), 3),
        },
        "agent": {
            "learnings_created": counters["learnings_created"],
            "rule_updates": counters["rule_updates"],
            "strategy_changes": counters["strategy_changes"],
            "snapshots": counters["snapshots"],
            "synthesis_events": counters["synthesis_events"],
            "synthesis_units": counters["synthesis_units"],
            "synthesis_stored": counters["synthesis_stored"],
            "known_rules_final": len(orchestrator.rule_model.known_rules),
            "db_iterations": len(db_iterations),
        },
        "maze_map": maze_map,
        "per_iteration": per_iteration,
        "db_iterations": db_iterations,
    }

    with open(run_dir / "metrics.json", "w", encoding="utf-8") as f:
        H.json.dump(metrics, f, indent=2, default=str)

    H.logger.info(
        "episode %s (%sx%s) done: success=%s moves=%s optimal=%s iters=%s dur=%.0fs retrieved=%s writes=%s",
        label, size, size, metrics["success"], moves_used, env_metrics.get("optimal_moves"),
        metrics["iterations_used"], duration, metrics["memory"]["retrieved_total"],
        metrics["memory"]["store_calls"],
    )
    return metrics


async def ensure_db_and_user() -> int:
    from app.database.connection import engine
    from app.database.models import Base, User

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with H.async_sessionmaker_db() as session:
        row = (await session.execute(H.select(User))).scalars().first()
        if row:
            return row.id
        user = User(username="study", email="study@local", hashed_password="not-used", is_active=True)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", choices=["A", "B", "a", "b"], default="A")
    parser.add_argument("--tag", default="full")
    parser.add_argument("--db", default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument("--provider", choices=["zen", "groq"], default="zen")
    parser.add_argument("--reasoning-effort", default="max")
    parser.add_argument("--model", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--budget-cap", type=int, default=None)
    parser.add_argument("--scope", choices=["full", "5x5"], default="full")
    args = parser.parse_args()

    H.ZEN = args.provider == "zen"
    H.REASONING_EFFORT = args.reasoning_effort or None
    if args.model is None:
        args.model = "deepseek-v4.1-flash" if H.ZEN else settings.PRIMARY_MODEL

    out_dir = Path(args.out) if args.out else (HERE / "results" / f"maze_{EXP.lower()}")
    (out_dir / "runs").mkdir(parents=True, exist_ok=True)
    H.logging.basicConfig(
        level=H.logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[H.logging.FileHandler(out_dir / "harness.log", encoding="utf-8"),
                  H.logging.StreamHandler()],
    )

    phase = "OFF" if EXP == "A" else "ON"
    episodes = [
        {"index": i + 1, "label": f"EP{i+1:02d}-train", "phase": phase, "size": s, "seed": seed,
         "key_door": kd, "traps": tr}
        for i, (s, seed, kd, tr) in enumerate(TRAINING_MAZES)
    ] + [
        {"index": 16 + i, "label": f"EP{16+i:02d}-eval", "phase": phase, "size": s, "seed": seed,
         "key_door": kd, "traps": tr}
        for i, (s, seed, kd, tr) in enumerate(EVAL_MAZES)
    ]

    with open(out_dir / "protocol.json", "w", encoding="utf-8") as f:
        H.json.dump({
            "experiment": EXP, "phase": phase, "tag": args.tag,
            "task_title": TASK_TITLE, "task_description": TASK_DESCRIPTION,
            "model": args.model, "provider": args.provider, "reasoning_effort": H.REASONING_EFFORT,
            "synthesis_reasoning_effort": H.SYNTHESIS_REASONING_EFFORT,
            "temperature": 0.7,
            "training_mazes": TRAINING_MAZES, "eval_mazes": EVAL_MAZES, "budgets": BUDGETS,
            "db": os.environ["DATABASE_URL"], "storage_dir": os.environ["STORAGE_DIR"],
            "episodes": episodes,
            "started_at": H._utc(),
        }, f, indent=2)
    if args.scope == "5x5":
        episodes = [e for e in episodes if e["size"] == 5]
    if args.limit:
        episodes = episodes[: args.limit]

    H.instrument_httpx(out_dir / "http_calls.jsonl")

    embedding_service = EmbeddingService(settings.EMBEDDING_MODEL)
    qdrant_store = QdrantStore(url=":memory:", collection_name=settings.QDRANT_COLLECTION,
                               dimension=settings.EMBEDDING_DIMENSION)
    await qdrant_store.initialize()
    retriever = MemoryRetriever(embedding_service=embedding_service, qdrant_store=qdrant_store)
    memory_manager = MemoryManager(embedding_service=embedding_service, qdrant_store=qdrant_store,
                                   retriever=retriever)
    H.instrument_memory(memory_manager, qdrant_store, embedding_service, out_dir / "memory.jsonl")

    H.logger.info("warmup: loading embedding model ...")
    t0 = time.perf_counter()
    await embedding_service.embed("warmup")
    H.logger.info("embedding model ready in %.1fs", time.perf_counter() - t0)

    user_id = await ensure_db_and_user()
    H.logger.info("experiment %s | phase %s | model %s | effort %s | %d episodes",
                  EXP, phase, args.model, H.REASONING_EFFORT, len(episodes))

    summary_path = out_dir / "study_summary.json"
    all_metrics = []
    for episode in episodes:
        metrics = await run_episode(episode, args, user_id, memory_manager, out_dir)
        all_metrics.append(metrics)
        with open(summary_path, "w", encoding="utf-8") as f:
            H.json.dump({"experiment": EXP, "phase": phase, "tag": args.tag,
                         "episodes": all_metrics, "updated_at": H._utc()},
                        f, indent=2, default=str)

    succeeded = sum(1 for m in all_metrics if m["success"])
    H.logger.info("experiment %s complete: %d/%d episodes succeeded", EXP, succeeded, len(all_metrics))


if __name__ == "__main__":
    asyncio.run(main())
