"""
Controlled Memory ON/OFF study harness - 15x15 grid maze task.

Runs the *production* orchestrator in-process (same construction path as
app.workers.task_worker.process_task_local) and instruments every LLM call,
HTTP request/retry, memory retrieval, memory write, embedding call and
orchestrator event.

NO application source files are modified. All instrumentation is applied to
instances at runtime.

Phases:
  OFF : use_persistent_learning=False (retrieval disabled; learning still stored)
  ON  : use_persistent_learning=True  (production retrieval rendering)
  FIX : use_persistent_learning=True  + harness-side payload flattening so the
        planner actually receives memory content (exploratory arm, NOT part of
        the strict controlled comparison)
"""
import argparse
import asyncio
import json
import logging
import statistics
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.config import settings  # noqa: E402
from app.database.connection import async_sessionmaker_db  # noqa: E402
from app.database.models import Task, TaskStatus, User  # noqa: E402
from app.models.llm_provider import get_llm_provider  # noqa: E402
from app.memory.embeddings import EmbeddingService  # noqa: E402
from app.memory.qdrant_store import QdrantStore  # noqa: E402
from app.memory.retriever import MemoryRetriever  # noqa: E402
from app.memory.memory_manager import MemoryManager  # noqa: E402
from app.environments import get_environment_for_task  # noqa: E402
from app.agents.orchestrator import AgentOrchestrator  # noqa: E402

TASK_TITLE = "Adaptive Maze Intelligence Benchmark"

TASK_DESCRIPTION = """Objective: Build an agent that learns to solve a series of increasingly difficult grid-world mazes. The agent must discover the environment, experiment with strategies, remember useful knowledge, and improve its performance across multiple independent runs.

Environment: Each maze is a 15x15 grid containing:
S = starting position, E = exit, # = wall, . = open path, K = key, D = locked door, T = trap, ? = unknown cell.
The agent initially knows only the rules, not the maze layout.

Rules:
- The agent starts at S.
- It can move up, down, left, or right.
- The agent cannot move through walls.
- Some mazes contain a key and locked door: the key must be collected before the door can be opened.
- Some cells contain traps: entering a trap costs 5 additional moves.
- The agent receives feedback after every action.
- The agent has a limited number of actions per episode.
- The agent should record: successful strategies, failed strategies, environmental patterns, locations/types of discovered hazards, useful exploration techniques, mistakes and their causes.
- The agent is allowed to create its own strategy.
- The solution path is never provided to the agent.
"""

CURRENT = {"label": "", "task_id": "", "iteration": 0, "phase": "", "surfacing_fix": False}

ZEN_BASE_URL = "https://opencode.ai/zen/go/v1"
ZEN = True
REASONING_EFFORT: str | None = "max"
SYNTHESIS_REASONING_EFFORT: str | None = "low"
SYNTHESIS_MARKER = "Target Number of Synthesis Units"

LLM_RECS: list[dict] = []
HTTP_RECS: list[dict] = []
RETRIEVAL_RECS: list[dict] = []
WRITE_RECS: list[dict] = []
EMBED_RECS: list[dict] = []
EVENT_RECS: list[dict] = []

logger = logging.getLogger("study")


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_jsonl(path: Path, obj: dict) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, default=str) + "\n")


def instrument_httpx(http_log: Path) -> None:
    original = httpx.AsyncClient.request
    if getattr(original, "_study_wrapped", False):
        return

    async def logged_request(self, method, url, **kwargs):
        if ZEN and "opencode.ai" in str(url):
            headers = dict(kwargs.get("headers") or {})
            headers["x-opencode-session"] = CURRENT["task_id"]
            headers.setdefault("User-Agent", "ala-maze-study/1.0")
            kwargs["headers"] = headers
            kwargs.setdefault("timeout", 300.0)
        t0 = time.perf_counter()
        try:
            response = await original(self, method, url, **kwargs)
            rec = {
                "ts": _utc(), "run": CURRENT["label"], "task_id": CURRENT["task_id"],
                "method": method, "url": str(url), "status": response.status_code,
                "dur_s": round(time.perf_counter() - t0, 4), "ok": True,
            }
            HTTP_RECS.append(rec)
            _append_jsonl(http_log, rec)
            return response
        except Exception as e:
            rec = {
                "ts": _utc(), "run": CURRENT["label"], "task_id": CURRENT["task_id"],
                "method": method, "url": str(url), "status": None,
                "dur_s": round(time.perf_counter() - t0, 4), "ok": False,
                "error": f"{type(e).__name__}: {str(e)[:200]}",
            }
            HTTP_RECS.append(rec)
            _append_jsonl(http_log, rec)
            raise

    logged_request._study_wrapped = True
    httpx.AsyncClient.request = logged_request


def instrument_llm(llm, llm_log: Path) -> None:
    original = llm._request

    async def instrumented(method, endpoint, **kwargs):
        payload = kwargs.get("json") or {}
        messages = payload.get("messages") or []
        prompt_chars = sum(len(str(m.get("content", ""))) for m in messages)
        user_msgs = [m for m in messages if m.get("role") == "user"]
        prompt_head = str(user_msgs[-1].get("content", ""))[:80] if user_msgs else ""
        effort_used = None
        if ZEN and REASONING_EFFORT and isinstance(payload, dict) and endpoint.endswith("/chat/completions"):
            effort_used = REASONING_EFFORT
            if SYNTHESIS_MARKER in prompt_head or any(
                SYNTHESIS_MARKER in str(m.get("content", "")) for m in messages
            ):
                # Synthesis batches under effort=max produced 20k-40k reasoning tokens and
                # the upstream returned HTTP 500, so no memories were ever stored.
                # Synthesis runs at low effort; all agent decision calls stay at max.
                effort_used = SYNTHESIS_REASONING_EFFORT
            payload.setdefault("reasoning_effort", effort_used)
        model = payload.get("model", getattr(llm, "model", "?"))
        attempt = 0
        while True:
            t0 = time.perf_counter()
            try:
                data = await original(method, endpoint, **kwargs)
                usage = (data or {}).get("usage") or {}
                details = usage.get("completion_tokens_details") or {}
                try:
                    content = ((data or {}).get("choices") or [{}])[0].get("message", {}).get("content")
                except Exception:
                    content = ""
                rec = {
                    "ts": _utc(), "run": CURRENT["label"], "task_id": CURRENT["task_id"],
                    "iteration": CURRENT["iteration"], "endpoint": endpoint, "model": model,
                    "prompt_chars": prompt_chars, "prompt_head": prompt_head,
                    "reasoning_effort": effort_used, "attempt": attempt + 1,
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "reasoning_tokens": details.get("reasoning_tokens"),
                    "total_tokens": usage.get("total_tokens"),
                    "content_chars": len(content or ""),
                    "empty_content": not bool(content),
                    "dur_s": round(time.perf_counter() - t0, 4), "ok": True,
                }
                LLM_RECS.append(rec)
                _append_jsonl(llm_log, rec)
                return data
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (500, 502, 503, 504) and attempt < 2:
                    attempt += 1
                    await asyncio.sleep(2.0 * attempt)
                    continue
                rec = {
                    "ts": _utc(), "run": CURRENT["label"], "task_id": CURRENT["task_id"],
                    "iteration": CURRENT["iteration"], "endpoint": endpoint, "model": model,
                    "prompt_chars": prompt_chars, "prompt_head": prompt_head,
                    "reasoning_effort": effort_used, "attempt": attempt + 1,
                    "status": e.response.status_code,
                    "dur_s": round(time.perf_counter() - t0, 4), "ok": False,
                    "error": f"HTTPStatusError: {e.response.status_code}",
                }
                LLM_RECS.append(rec)
                _append_jsonl(llm_log, rec)
                raise
            except Exception as e:
                rec = {
                    "ts": _utc(), "run": CURRENT["label"], "task_id": CURRENT["task_id"],
                    "iteration": CURRENT["iteration"], "endpoint": endpoint, "model": model,
                    "prompt_chars": prompt_chars, "prompt_head": prompt_head,
                    "reasoning_effort": effort_used, "attempt": attempt + 1,
                    "dur_s": round(time.perf_counter() - t0, 4), "ok": False,
                    "error": f"{type(e).__name__}: {str(e)[:300]}",
                }
                LLM_RECS.append(rec)
                _append_jsonl(llm_log, rec)
                raise

    llm._request = instrumented


def instrument_synthesis_shapes(llm, mem_log: Path) -> None:
    """Repair the synthesis response-key mismatch at the harness boundary.

    The synthesis system prompt (app/agents/prompts.py SYNTHESIS_V1) instructs the
    model to answer {"synthesized_learnings": [...]}, but LearningSynthesizer
    (app/agents/synthesis.py:60) only accepts a list or a dict with key "units".
    Consequently the stock system stores ZERO memories. This wrapper normalizes the
    response to {"units": [...]} so memory writes work; it is applied identically to
    both experimental arms. It also coerces source_iterations lists to ints, which
    otherwise crash the duplicate-merge path in MemoryManager.store_synthesized_learning.
    """
    original = llm.generate_json

    async def wrapped(prompt, system_prompt="", **kwargs):
        result = await original(prompt, system_prompt=system_prompt, **kwargs)
        if not (isinstance(prompt, str) and SYNTHESIS_MARKER in prompt):
            return result

        raw_type = type(result).__name__
        if isinstance(result, list):
            units = [u for u in result if isinstance(u, dict)]
        elif isinstance(result, dict):
            if isinstance(result.get("units"), list):
                units = result["units"]
            elif isinstance(result.get("synthesized_learnings"), list):
                units = result["synthesized_learnings"]
            else:
                units = next(
                    (v for v in result.values() if isinstance(v, list) and v and isinstance(v[0], dict)),
                    [],
                )
        else:
            units = []

        clean_units = []
        for unit in units:
            if not isinstance(unit, dict):
                continue
            unit = dict(unit)
            si = unit.get("source_iterations")
            if isinstance(si, list):
                nums = [x for x in si if isinstance(x, (int, float))]
                unit["source_iterations"] = int(max(nums)) if nums else 1
            elif not isinstance(si, int):
                unit["source_iterations"] = 1
            clean_units.append(unit)

        rec = {
            "ts": _utc(), "run": CURRENT["label"], "task_id": CURRENT["task_id"],
            "type": "synthesis_normalize", "raw_type": raw_type,
            "raw_keys": list(result.keys()) if isinstance(result, dict) else None,
            "units": len(clean_units),
        }
        _append_jsonl(mem_log, rec)
        return {"units": clean_units}

    llm.generate_json = wrapped


def instrument_memory(memory_manager: MemoryManager, qdrant_store: QdrantStore,
                      embedding_service: EmbeddingService, mem_log: Path) -> None:
    original_retrieve = memory_manager.retrieve_relevant_memories

    async def retrieve_wrapper(task, state, top_k=5, min_similarity=0.65):
        t0 = time.perf_counter()
        result = await original_retrieve(task=task, state=state, top_k=top_k, min_similarity=min_similarity)
        dur = time.perf_counter() - t0
        items = result or []
        rec = {
            "ts": _utc(), "run": CURRENT["label"], "task_id": CURRENT["task_id"],
            "iteration": CURRENT["iteration"], "count": len(items),
            "scores": [round(i.get("score", 0.0), 4) for i in items],
            "ids": [i.get("id") for i in items],
            "dur_s": round(dur, 4),
        }
        RETRIEVAL_RECS.append(rec)
        _append_jsonl(mem_log, {"type": "retrieval", **rec})

        if CURRENT["surfacing_fix"] and items:
            for item in items:
                payload = item.get("payload") or {}
                item["similarity"] = item.get("score", 0.0)
                item["learning"] = (
                    payload.get("knowledge") or payload.get("learning_text")
                    or payload.get("title") or "?"
                )
        return items

    memory_manager.retrieve_relevant_memories = retrieve_wrapper

    original_insert = qdrant_store.insert

    async def insert_wrapper(point_id, vector, payload):
        ok = await original_insert(point_id, vector, payload)
        rec = {
            "ts": _utc(), "run": CURRENT["label"], "task_id": CURRENT["task_id"],
            "op": "insert", "id": point_id, "title": payload.get("title", ""),
            "category": payload.get("category", ""), "ok": ok,
        }
        WRITE_RECS.append(rec)
        _append_jsonl(mem_log, {"type": "write", **rec})
        return ok

    qdrant_store.insert = insert_wrapper

    original_update = qdrant_store.update_payload

    async def update_wrapper(point_id, payload):
        ok = await original_update(point_id, payload)
        rec = {
            "ts": _utc(), "run": CURRENT["label"], "task_id": CURRENT["task_id"],
            "op": "merge", "id": point_id, "title": payload.get("title", ""),
            "ok": ok,
        }
        WRITE_RECS.append(rec)
        _append_jsonl(mem_log, {"type": "write", **rec})
        return ok

    qdrant_store.update_payload = update_wrapper

    original_embed_batch = embedding_service.embed_batch

    async def embed_wrapper(texts):
        t0 = time.perf_counter()
        result = await original_embed_batch(texts)
        rec = {
            "ts": _utc(), "run": CURRENT["label"], "task_id": CURRENT["task_id"],
            "n": len(texts), "dur_s": round(time.perf_counter() - t0, 4),
        }
        EMBED_RECS.append(rec)
        _append_jsonl(mem_log, {"type": "embed", **rec})
        return result

    embedding_service.embed_batch = embed_wrapper


def make_event_callback(events_log: Path, iter_stats: dict, counters: dict):
    async def callback(event_type: str, data: dict):
        rec = {
            "ts": _utc(), "run": CURRENT["label"], "task_id": CURRENT["task_id"],
            "event": event_type, "data": data,
        }
        EVENT_RECS.append(rec)
        _append_jsonl(events_log, rec)

        iteration = data.get("iteration", CURRENT["iteration"])
        if event_type == "iteration_started":
            CURRENT["iteration"] = iteration
            iter_stats.setdefault(iteration, {"iteration": iteration})
        elif event_type == "memories_retrieved":
            st = iter_stats.setdefault(iteration, {"iteration": iteration})
            st["retrieved_count"] = data.get("count", 0)
            st["retrieved"] = [
                {"score": round(m.get("score", 0.0), 4),
                 "title": (m.get("payload") or {}).get("title", "")}
                for m in (data.get("memories") or [])
            ]
        elif event_type == "observation":
            st = iter_stats.setdefault(iteration, {"iteration": iteration})
            st["score"] = data.get("score")
        elif event_type == "action":
            st = iter_stats.setdefault(iteration, {"iteration": iteration})
            st["action"] = data.get("action")
        elif event_type == "result":
            st = iter_stats.setdefault(iteration, {"iteration": iteration})
            st["success"] = data.get("success")
            st["reward"] = data.get("reward")
            st["result"] = (data.get("output") or "")[:200]
            st["error"] = data.get("error")
        elif event_type == "evaluation":
            st = iter_stats.setdefault(iteration, {"iteration": iteration})
            st["evaluation"] = {
                "success": data.get("success"),
                "mistake": str(data.get("mistake", ""))[:200],
                "discovery": str(data.get("discovery", ""))[:200],
            }
        elif event_type == "learning_created":
            st = iter_stats.setdefault(iteration, {"iteration": iteration})
            st["learnings"] = st.get("learnings", 0) + 1
            counters["learnings_created"] += 1
        elif event_type == "rule_updated":
            counters["rule_updates"] += 1
        elif event_type == "strategy_changed":
            counters["strategy_changes"] += 1
        elif event_type == "snapshot_created":
            counters["snapshots"] += 1
        elif event_type == "synthesis_completed":
            counters["synthesis_events"] += 1
            counters["synthesis_units"] += data.get("count", 0)
            counters["synthesis_stored"] += data.get("stored", 0)

    return callback


async def get_user_id() -> int:
    async with async_sessionmaker_db() as session:
        row = (await session.execute(select(User.id).order_by(User.id))).first()
        if not row:
            raise RuntimeError("No user in database; register via the API first.")
        return row[0]


def build_llm(model: str):
    if ZEN:
        auth_path = Path.home() / ".local" / "share" / "opencode" / "auth.json"
        auth = json.loads(auth_path.read_text(encoding="utf-8"))
        key = auth["opencode-go"]["key"]
        return get_llm_provider({
            "type": "custom",
            "base_url": ZEN_BASE_URL,
            "api_key": key,
            "model": model,
        })
    return get_llm_provider({"model": model})


async def set_task_status(task_id: str, status: TaskStatus, iteration: int | None = None) -> None:
    async with async_sessionmaker_db() as session:
        row = (await session.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
        if row:
            row.status = status
            if iteration is not None:
                row.current_iteration = iteration
            await session.commit()


async def create_task_row(task_id: str, label: str, user_id: int, args) -> None:
    async with async_sessionmaker_db() as session:
        task = Task(
            id=task_id,
            user_id=user_id,
            title=f"MAZE15-{args.tag}-{label}",
            description=TASK_DESCRIPTION,
            max_iterations=args.max_iterations,
            snapshot_interval=args.snapshot_interval,
            synthesis_interval=args.synthesis_interval,
            use_persistent_learning=label.startswith(("ON", "FIX")),
            top_k=args.top_k,
            min_similarity=args.min_similarity,
            model=args.model,
            temperature=args.temperature,
            status=TaskStatus.CREATED,
            current_iteration=0,
        )
        session.add(task)
        await session.commit()


async def fetch_iterations(task_id: str) -> list[dict]:
    from app.database.models import Iteration
    async with async_sessionmaker_db() as session:
        rows = (await session.execute(
            select(Iteration).where(Iteration.task_id == task_id).order_by(Iteration.iteration_number)
        )).scalars().all()
        out = []
        for r in rows:
            out.append({
                "iteration": r.iteration_number,
                "action": r.action,
                "action_result": (r.action_result or "")[:300],
                "score": r.score,
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            })
        return out


def summarize_records(records: list[dict], start: int) -> list[dict]:
    return records[start:]


def compute_llm_metrics(recs: list[dict]) -> dict:
    ok = [r for r in recs if r.get("ok")]
    failed = [r for r in recs if not r.get("ok")]
    durations = [r["dur_s"] for r in ok]
    prompt_tokens = [r["prompt_tokens"] for r in ok if r.get("prompt_tokens") is not None]
    completion_tokens = [r["completion_tokens"] for r in ok if r.get("completion_tokens") is not None]
    reasoning_tokens = [r["reasoning_tokens"] for r in ok if r.get("reasoning_tokens") is not None]
    models = {}
    for r in ok:
        models[r.get("model", "?")] = models.get(r.get("model", "?"), 0) + 1
    heads = {}
    for r in ok:
        head = r.get("prompt_head", "")
        key = head.split(":")[0][:40]
        heads[key] = heads.get(key, 0) + 1
    return {
        "calls": len(recs),
        "ok": len(ok),
        "failed": len(failed),
        "empty_content": sum(1 for r in ok if r.get("empty_content")),
        "call_time_s": round(sum(durations), 3),
        "avg_latency_s": round(statistics.mean(durations), 3) if durations else None,
        "max_latency_s": round(max(durations), 3) if durations else None,
        "prompt_tokens": sum(prompt_tokens) if prompt_tokens else None,
        "completion_tokens": sum(completion_tokens) if completion_tokens else None,
        "reasoning_tokens": sum(reasoning_tokens) if reasoning_tokens else None,
        "total_tokens": (sum(prompt_tokens) + sum(completion_tokens)) if (prompt_tokens or completion_tokens) else None,
        "prompt_chars": sum(r.get("prompt_chars", 0) for r in ok),
        "models": models,
        "call_types": heads,
    }


def compute_http_metrics(recs: list[dict]) -> dict:
    statuses = {}
    for r in recs:
        key = str(r.get("status"))
        statuses[key] = statuses.get(key, 0) + 1
    return {
        "requests": len(recs),
        "statuses": statuses,
        "retries_429": statuses.get("429", 0),
        "errors": sum(1 for r in recs if not r.get("ok")),
    }


def parse_action(action) -> tuple[str, str]:
    if not isinstance(action, dict):
        return ("?", "?")
    tool = action.get("tool") or action.get("name") or "?"
    params = action.get("parameters") if isinstance(action.get("parameters"), dict) else action
    direction = "?"
    for key in ("direction", "move", "action", "dir"):
        value = params.get(key)
        if isinstance(value, str):
            direction = value
            break
    return (str(tool), str(direction).capitalize())


async def run_one(spec: dict, args, user_id: int, qdrant_store: QdrantStore,
                  memory_manager: MemoryManager, out_dir: Path) -> dict:
    label = spec["label"]
    phase = spec["phase"]
    task_id = str(uuid.uuid4())
    run_dir = out_dir / "runs" / label
    run_dir.mkdir(parents=True, exist_ok=True)
    events_log = run_dir / "events.jsonl"
    llm_log = out_dir / "llm_calls.jsonl"
    http_log = out_dir / "http_calls.jsonl"
    mem_log = run_dir / "memory.jsonl"

    CURRENT.update(label=label, task_id=task_id, iteration=0, phase=phase,
                   surfacing_fix=(phase == "FIX"))

    await create_task_row(task_id, label, user_id, args)
    await set_task_status(task_id, TaskStatus.RUNNING)

    llm = build_llm(args.model)
    instrument_llm(llm, llm_log)

    task_config = {"title": TASK_TITLE, "description": TASK_DESCRIPTION}
    env = get_environment_for_task(task_config, llm)

    memory_manager.retrieval_enabled = phase in ("ON", "FIX")

    iter_stats: dict[int, dict] = {}
    counters = {"learnings_created": 0, "rule_updates": 0, "strategy_changes": 0,
                "snapshots": 0, "synthesis_events": 0, "synthesis_units": 0,
                "synthesis_stored": 0}
    callback = make_event_callback(events_log, iter_stats, counters)

    orchestrator = AgentOrchestrator(
        llm=llm,
        environment=env,
        task_id=task_id,
        task_description=TASK_DESCRIPTION,
        max_iterations=args.max_iterations,
        use_persistent_learning=phase in ("ON", "FIX"),
        snapshot_interval=args.snapshot_interval,
        synthesis_interval=args.synthesis_interval,
        storage_dir=settings.STORAGE_DIR,
        top_k=args.top_k,
        min_similarity=args.min_similarity,
        memory_manager=memory_manager,
        event_callback=callback,
    )

    stats_before = await qdrant_store.get_stats()
    idx = {name: len(recs) for name, recs in (
        ("llm", LLM_RECS), ("http", HTTP_RECS), ("retrieval", RETRIEVAL_RECS),
        ("write", WRITE_RECS), ("embed", EMBED_RECS), ("event", EVENT_RECS))}

    started = _utc()
    t0 = time.perf_counter()
    state = None
    error = None
    try:
        state = await orchestrator.run()
    except Exception as e:
        error = f"{type(e).__name__}: {str(e)[:400]}"
        logger.exception("run %s failed", label)
    duration = time.perf_counter() - t0
    ended = _utc()

    stats_after = await qdrant_store.get_stats()

    status = TaskStatus.FAILED if error else (
        TaskStatus.COMPLETED if state and state.completion_status == "completed" else TaskStatus.STOPPED)
    await set_task_status(task_id, status,
                          state.iteration if state else None)

    llm_recs = LLM_RECS[idx["llm"]:]
    http_recs = HTTP_RECS[idx["http"]:]
    retrieval_recs = RETRIEVAL_RECS[idx["retrieval"]:]
    write_recs = WRITE_RECS[idx["write"]:]
    embed_recs = EMBED_RECS[idx["embed"]:]

    db_iterations = await fetch_iterations(task_id)

    blocked_obstacle = sum(1 for r in db_iterations if "obstacle is present" in r["action_result"])
    blocked_boundary = sum(1 for r in db_iterations if "boundary reached" in r["action_result"])
    invalid_actions = sum(1 for r in db_iterations if "Invalid direction" in r["action_result"])

    env_final = None
    if env is not None:
        env_final = {
            "x": getattr(env, "x", None), "y": getattr(env, "y", None),
            "goal": list(getattr(env, "goal_pos", ())) or None,
            "found_treasure": getattr(env, "found_treasure", None),
            "step_count": getattr(env, "step_count", None),
            "score": round(float(getattr(env, "score", 0.0)), 2),
            "known_obstacles": [list(p) for p in getattr(env, "known_obstacles", [])],
        }

    retrieved_counts = [r["count"] for r in retrieval_recs]
    all_scores = [s for r in retrieval_recs for s in r.get("scores", [])]

    llm_metrics = compute_llm_metrics(llm_recs)
    per_iteration = []
    for n in sorted(iter_stats):
        st = dict(iter_stats[n])
        tool, direction = parse_action(st.get("action"))
        st["tool"] = tool
        st["direction"] = direction
        st.pop("action", None)
        if "retrieved" in st:
            st["retrieved_top"] = [x["title"] for x in st["retrieved"][:3]]
            st.pop("retrieved")
        per_iteration.append(st)

    metrics = {
        "run_label": label,
        "phase": phase,
        "tag": args.tag,
        "task_id": task_id,
        "surfacing_fix": CURRENT["surfacing_fix"],
        "model": args.model,
        "temperature": args.temperature,
        "max_iterations": args.max_iterations,
        "top_k": args.top_k,
        "min_similarity": args.min_similarity,
        "started_at": started,
        "ended_at": ended,
        "duration_s": round(duration, 2),
        "error": error,
        "completion_status": state.completion_status if state else None,
        "task_status": status.value,
        "success": bool(env_final and env_final.get("found_treasure")),
        "iterations_used": state.iteration if state else None,
        "llm": llm_metrics,
        "http": compute_http_metrics(http_recs),
        "memory": {
            "retrieval_calls": len(retrieval_recs),
            "retrieved_total": sum(retrieved_counts),
            "retrieved_mean": round(statistics.mean(retrieved_counts), 3) if retrieved_counts else 0.0,
            "retrieved_max": max(retrieved_counts) if retrieved_counts else 0,
            "iterations_with_memory": sum(1 for c in retrieved_counts if c > 0),
            "avg_similarity": round(statistics.mean(all_scores), 4) if all_scores else None,
            "max_similarity": round(max(all_scores), 4) if all_scores else None,
            "unique_ids_retrieved": len({i for r in retrieval_recs for i in r.get("ids", [])}),
            "retrieval_time_s": round(sum(r["dur_s"] for r in retrieval_recs), 3),
            "writes_insert": sum(1 for r in write_recs if r["op"] == "insert"),
            "writes_merge": sum(1 for r in write_recs if r["op"] == "merge"),
            "store_calls": len(write_recs),
            "points_before": stats_before.get("total_points"),
            "points_after": stats_after.get("total_points"),
            "embed_calls": len(embed_recs),
            "embed_texts": sum(r["n"] for r in embed_recs),
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
            "blocked_obstacle": blocked_obstacle,
            "blocked_boundary": blocked_boundary,
            "invalid_actions": invalid_actions,
            "db_iterations": len(db_iterations),
            "known_rules_final": len(orchestrator.rule_model.known_rules) if orchestrator else None,
        },
        "env_final": env_final,
        "per_iteration": per_iteration,
        "db_iterations": db_iterations,
    }

    with open(run_dir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, default=str)

    logger.info(
        "run %s done: status=%s success=%s iterations=%s duration=%.1fs llm_calls=%s tokens=%s retrieved=%s writes=%s",
        label, status.value, metrics["success"], metrics["iterations_used"], duration,
        llm_metrics["calls"], llm_metrics["total_tokens"],
        metrics["memory"]["retrieved_total"], metrics["memory"]["store_calls"],
    )
    return metrics


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="full")
    parser.add_argument("--runs-off", type=int, default=5)
    parser.add_argument("--runs-on", type=int, default=5)
    parser.add_argument("--runs-fix", type=int, default=0)
    parser.add_argument("--max-iterations", type=int, default=60)
    parser.add_argument("--snapshot-interval", type=int, default=30)
    parser.add_argument("--synthesis-interval", type=int, default=100)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--min-similarity", type=float, default=0.65)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--provider", choices=["zen", "groq"], default="zen")
    parser.add_argument("--reasoning-effort", default="max")
    parser.add_argument("--model", default=None)
    parser.add_argument("--out", default=str(HERE / "results"))
    args = parser.parse_args()

    global ZEN, REASONING_EFFORT
    ZEN = args.provider == "zen"
    REASONING_EFFORT = args.reasoning_effort or None
    if args.model is None:
        args.model = "deepseek-v4.1-flash" if ZEN else settings.PRIMARY_MODEL

    out_dir = Path(args.out)
    (out_dir / "runs").mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "harness.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler()],
    )

    with open(out_dir / "protocol.json", "w", encoding="utf-8") as f:
        json.dump({
            "tag": args.tag,
            "task_title": TASK_TITLE,
            "task_description": TASK_DESCRIPTION,
            "model": args.model,
            "temperature": args.temperature,
            "max_iterations": args.max_iterations,
            "snapshot_interval": args.snapshot_interval,
            "synthesis_interval": args.synthesis_interval,
            "top_k": args.top_k,
            "min_similarity": args.min_similarity,
            "runs_off": args.runs_off,
            "runs_on": args.runs_on,
            "runs_fix": args.runs_fix,
            "provider": args.provider,
            "endpoint": ZEN_BASE_URL if ZEN else "",
            "reasoning_effort": REASONING_EFFORT,
            "started_at": _utc(),
        }, f, indent=2)

    instrument_httpx(out_dir / "http_calls.jsonl")

    embedding_service = EmbeddingService(settings.EMBEDDING_MODEL)
    qdrant_store = QdrantStore(
        url=settings.QDRANT_URL,
        collection_name=settings.QDRANT_COLLECTION,
        dimension=settings.EMBEDDING_DIMENSION,
    )
    await qdrant_store.initialize()
    retriever = MemoryRetriever(embedding_service=embedding_service, qdrant_store=qdrant_store)
    memory_manager = MemoryManager(
        embedding_service=embedding_service, qdrant_store=qdrant_store, retriever=retriever)
    instrument_memory(memory_manager, qdrant_store, embedding_service, out_dir / "memory.jsonl")

    logger.info("warmup: loading embedding model %s ...", settings.EMBEDDING_MODEL)
    t0 = time.perf_counter()
    await embedding_service.embed("warmup")
    logger.info("embedding model ready in %.1fs", time.perf_counter() - t0)

    user_id = await get_user_id()
    logger.info("user_id=%s model=%s max_iterations=%s", user_id, args.model, args.max_iterations)

    specs = (
        [{"label": f"OFF-{i+1}", "phase": "OFF"} for i in range(args.runs_off)]
        + [{"label": f"ON-{i+1}", "phase": "ON"} for i in range(args.runs_on)]
        + [{"label": f"FIX-{i+1}", "phase": "FIX"} for i in range(args.runs_fix)]
    )

    summary_path = out_dir / "study_summary.json"
    all_metrics = []
    for spec in specs:
        metrics = await run_one(spec, args, user_id, qdrant_store, memory_manager, out_dir)
        all_metrics.append(metrics)
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump({"tag": args.tag, "runs": all_metrics, "updated_at": _utc()}, f,
                      indent=2, default=str)

    logger.info("study complete: %d runs", len(all_metrics))


if __name__ == "__main__":
    asyncio.run(main())
