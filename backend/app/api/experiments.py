"""Experiments: create a memory-vs-baseline run, control it, and read its games and moves."""
from __future__ import annotations

import random

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.api.dependencies import get_manager
from app.config import settings
from app.database.connection import async_sessionmaker_db, get_db
from app.database.models import AgentKind, Experiment, ExperimentStatus, Game, Move, User
from app.experiments.manager import ExperimentManager
from app.experiments.stats import FINISHED, game_to_dict, summarize
from app.game.interface import MinesweeperEnv
from app.game.minesweeper import BoardConfig, Minesweeper
from app.models.llm_provider import LLMAuthError, get_llm_provider, split_model
from app.learning.store import bank_for, memory_summary, reset_memory
from app.schemas.experiment import ExperimentCreate

router = APIRouter(prefix="/experiments", tags=["experiments"])

AGENTS = (AgentKind.MEMORY.value, AgentKind.BASELINE.value)
# Reference player (hand-written rules) recorded alongside code-only experiments.
SUMMARY_AGENTS = (*AGENTS, "expert")


def _experiment_dict(exp: Experiment, manager: ExperimentManager) -> dict:
    status = exp.status
    runner = manager.runner(exp.id)
    if runner is not None:
        status = ExperimentStatus.PAUSED.value if runner.paused else ExperimentStatus.RUNNING.value
    return {
        "id": exp.id,
        "name": exp.name,
        "rows": exp.rows,
        "cols": exp.cols,
        "mines": exp.mines,
        "num_games": exp.num_games,
        "max_moves": exp.max_moves,
        "base_seed": exp.base_seed,
        "model": exp.model,
        "temperature": exp.temperature,
        "memory_scope": exp.memory_scope,
        "agent_type": exp.agent_type,
        "speed": exp.speed,
        "status": status,
        "is_active": manager.is_running(exp.id),
        "error": exp.error,
        "created_at": exp.created_at.isoformat() if exp.created_at else None,
        "started_at": exp.started_at.isoformat() if exp.started_at else None,
        "finished_at": exp.finished_at.isoformat() if exp.finished_at else None,
    }


async def _owned(experiment_id: str, db: AsyncSession, user: User) -> Experiment:
    exp = await db.get(Experiment, experiment_id)
    if exp is None or exp.user_id != user.id:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return exp


async def _games(db: AsyncSession, experiment_id: str) -> list[Game]:
    result = await db.execute(select(Game).where(Game.experiment_id == experiment_id).order_by(Game.game_index))
    return list(result.scalars().all())


@router.post("")
async def create_experiment(
    body: ExperimentCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    manager: ExperimentManager = Depends(get_manager),
):
    board = body.board()
    if body.agent_type == "llm":
        if not settings.ENABLE_LLM_AGENTS:
            raise HTTPException(status_code=400, detail="LLM agents are disabled (set ENABLE_LLM_AGENTS=true).")
        provider, model_name = split_model(body.model or settings.default_model)
        if not model_name:
            raise HTTPException(status_code=400, detail="No model given and no default model configured.")
        model = f"{provider}:{model_name}"
        try:
            get_llm_provider(model)  # fails fast when the provider has no API key configured
        except LLMAuthError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    else:
        model = "pattern-learner"  # code-only agents: no model is called
    exp = Experiment(
        user_id=user.id,
        name=(body.name or f"{board.rows}x{board.cols}, {board.mines} mines, {body.num_games} games").strip(),
        rows=board.rows,
        cols=board.cols,
        mines=board.mines,
        num_games=body.num_games,
        max_moves=body.max_moves or MinesweeperEnv.default_max_moves(board),
        base_seed=body.base_seed if body.base_seed is not None else random.randrange(1, 2**31 - 1 - body.num_games),
        model=model,
        temperature=body.temperature,
        memory_scope=body.memory_scope,
        agent_type=body.agent_type,
        speed=body.speed,
        status=ExperimentStatus.CREATED.value,
    )
    db.add(exp)
    await db.commit()
    if body.start:
        await manager.start(exp.id)
    return _experiment_dict(exp, manager)


@router.get("")
async def list_experiments(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    manager: ExperimentManager = Depends(get_manager),
):
    result = await db.execute(
        select(Experiment).where(Experiment.user_id == user.id).order_by(Experiment.created_at.desc())
    )
    experiments = list(result.scalars().all())
    items = []
    for exp in experiments:
        games = await _games(db, exp.id)
        items.append({
            **_experiment_dict(exp, manager),
            "summary": {agent: summarize([g for g in games if g.agent == agent]) for agent in SUMMARY_AGENTS},
        })
    return items


@router.get("/{experiment_id}")
async def get_experiment(
    experiment_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    manager: ExperimentManager = Depends(get_manager),
):
    exp = await _owned(experiment_id, db, user)
    games = await _games(db, exp.id)
    live = manager.live(exp.id) or {}
    current: dict = {}
    for agent in AGENTS:
        if live.get(agent):
            current[agent] = live[agent]
            continue
        # Not running: show the last finished board for this agent, or the opening of game 1.
        finished = [g for g in games if g.agent == agent and g.final_grid]
        if finished:
            last = finished[-1]
            current[agent] = {"game_index": last.game_index, "game_id": last.id, "last_move": None,
                              "board": {"rows": exp.rows, "cols": exp.cols, "mines": exp.mines,
                                        "grid": last.final_grid, "status": last.status, "moves": last.moves,
                                        "safe_revealed": last.safe_revealed, "safe_total": last.safe_total,
                                        "min_clicks": last.min_clicks, "max_moves": exp.max_moves}}
        else:
            game = Minesweeper(_board_config(exp), exp.base_seed)
            board = game.to_public_dict()
            board["max_moves"] = exp.max_moves
            current[agent] = {"game_index": 0, "game_id": None, "last_move": None, "board": board}
    return {
        **_experiment_dict(exp, manager),
        "summary": {agent: summarize([g for g in games if g.agent == agent]) for agent in SUMMARY_AGENTS},
        "current": current,
    }


def _board_config(exp: Experiment) -> BoardConfig:
    return BoardConfig(exp.rows, exp.cols, exp.mines)


@router.get("/{experiment_id}/games")
async def list_games(
    experiment_id: str,
    agent: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _owned(experiment_id, db, user)
    games = await _games(db, experiment_id)
    # Only finished games: the game in progress is reported live by GET /experiments/{id}.
    return [game_to_dict(g) for g in games if g.status in FINISHED and (agent is None or g.agent == agent)]


@router.get("/{experiment_id}/games/{game_id}/moves")
async def list_moves(
    experiment_id: str,
    game_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    exp = await _owned(experiment_id, db, user)
    game = await db.get(Game, game_id)
    if game is None or game.experiment_id != experiment_id:
        raise HTTPException(status_code=404, detail="Game not found")
    result = await db.execute(select(Move).where(Move.game_id == game_id).order_by(Move.move_index))
    return {
        "game": game_to_dict(game),
        # Boards are deterministic, so the opening position is rebuilt from the seed.
        "opening_grid": Minesweeper(_board_config(exp), game.seed).grid(),
        "moves": [{
            "move_index": m.move_index,
            "action": m.action,
            "reasoning": m.reasoning,
            "outcome": m.outcome,
            "valid": m.valid,
            "message": m.message,
            "grid_after": m.grid_after,
        } for m in result.scalars().all()],
    }


@router.post("/{experiment_id}/start")
async def start_experiment(
    experiment_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    manager: ExperimentManager = Depends(get_manager),
):
    exp = await _owned(experiment_id, db, user)
    if exp.status == ExperimentStatus.COMPLETED.value and not manager.is_running(exp.id):
        raise HTTPException(status_code=400, detail="Experiment already completed")
    await manager.start(exp.id)
    return {"status": "running"}


# Resuming is the same as starting: the runner continues at the next unfinished game.
router.add_api_route("/{experiment_id}/resume", start_experiment, methods=["POST"])


@router.post("/{experiment_id}/pause")
async def pause_experiment(
    experiment_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    manager: ExperimentManager = Depends(get_manager),
):
    await _owned(experiment_id, db, user)
    if not await manager.pause(experiment_id):
        raise HTTPException(status_code=400, detail="Experiment is not running")
    return {"status": "paused"}


@router.post("/{experiment_id}/stop")
async def stop_experiment(
    experiment_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    manager: ExperimentManager = Depends(get_manager),
):
    exp = await _owned(experiment_id, db, user)
    if not await manager.stop(experiment_id):
        if exp.status in (ExperimentStatus.INTERRUPTED.value, ExperimentStatus.PAUSED.value,
                          ExperimentStatus.CREATED.value):
            exp.status = ExperimentStatus.STOPPED.value
            await db.commit()
            return {"status": "stopped"}
        raise HTTPException(status_code=400, detail="Experiment is not running")
    return {"status": "stopping"}


@router.delete("/{experiment_id}")
async def delete_experiment(
    experiment_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    manager: ExperimentManager = Depends(get_manager),
):
    """Delete the experiment's games and moves. Lessons it produced stay in the playbook."""
    exp = await _owned(experiment_id, db, user)
    if manager.is_running(exp.id):
        raise HTTPException(status_code=400, detail="Stop the experiment before deleting it")
    game_ids = select(Game.id).where(Game.experiment_id == exp.id)
    await db.execute(delete(Move).where(Move.game_id.in_(game_ids)))
    await db.execute(delete(Game).where(Game.experiment_id == exp.id))
    await db.delete(exp)
    await db.commit()
    # A "fresh" memory belonged to this experiment only; the persistent memory is kept.
    await reset_memory(async_sessionmaker_db, user.id, bank_for("fresh", experiment_id))
    return {"deleted": experiment_id}


@router.get("/{experiment_id}/memory")
async def experiment_memory(
    experiment_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """What the learning agent's memory (as used by this experiment) has learned so far."""
    exp = await _owned(experiment_id, db, user)
    return await memory_summary(async_sessionmaker_db, user.id, bank_for(exp.memory_scope, exp.id))


@router.post("/{experiment_id}/speed")
async def set_speed(
    experiment_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    manager: ExperimentManager = Depends(get_manager),
):
    """Switch between "watch" (paced) and "fast" while an experiment runs."""
    speed = body.get("speed")
    if speed not in ("watch", "fast"):
        raise HTTPException(status_code=400, detail='speed must be "watch" or "fast"')
    exp = await _owned(experiment_id, db, user)
    exp.speed = speed
    await db.commit()
    runner = manager.runner(experiment_id)
    if runner is not None and hasattr(runner, "exp"):
        runner.exp.speed = speed  # takes effect from the next move
    return {"speed": speed}
