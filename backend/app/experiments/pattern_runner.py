"""Runs a code-only experiment (no LLM): the learning agent and the no-learning agent
play the same seeded boards side by side, plus the expert solver as a reference.

Per board ("game index"):
* both agents play it move by move, interleaved, so the screen shows them side by side;
* both reason from the visible numbers; only the learning agent also uses the memory;
* the learning agent records every move's outcome immediately and labels everything
  it looked at when the game ends;
* the no-learning agent's experience (including its mistakes) is recorded into a buffer
  and merged into the shared memory once the board is finished, so the learning agent
  learns from both agents' games but never from a board it is still playing;
* the memory is saved after every board;
* games, moves and mistakes are saved once each game pair finishes, so a restart
  resumes at the next unfinished board.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from sqlalchemy import delete, select

from app.agents.code_players import CodePlayer
from app.config import settings
from app.database.connection import async_sessionmaker_db
from app.database.models import AgentKind, Experiment, ExperimentStatus, Game, Move
from app.experiments.stats import FINISHED, game_to_dict
from app.game.interface import MinesweeperEnv
from app.game.minesweeper import BoardConfig, Minesweeper
from app.game.solver import play_expert
from app.learning.overlaps import describe_overlap, discovered_rules
from app.learning.patterns import PatternMemory
from app.learning.store import bank_for, load_memory, save_increments

logger = logging.getLogger(__name__)

Publisher = Callable[[dict], Awaitable[None]]
MEMORY, BASELINE, EXPERT = AgentKind.MEMORY.value, AgentKind.BASELINE.value, "expert"
FAST_PUBLISH_INTERVAL = 0.25  # seconds between live board updates per agent in fast mode


def _now() -> datetime:
    return datetime.now(timezone.utc)


class _Track:
    """One agent's in-progress game."""

    def __init__(self, agent: str, player: CodePlayer, env: MinesweeperEnv):
        self.agent = agent
        self.player = player
        self.env = env
        self.moves: list[dict] = []
        self.mistakes: list[dict] = []
        self.started = time.monotonic()
        self.last_publish = 0.0


class PatternRunner:
    def __init__(self, experiment_id: str, publish: Publisher, session_factory=async_sessionmaker_db):
        self.experiment_id = experiment_id
        self.publish = publish
        self.session_factory = session_factory
        self._unpaused = asyncio.Event()
        self._unpaused.set()
        self._stopped = False
        self.live: dict[str, dict | None] = {MEMORY: None, BASELINE: None}

    # ------------------------------------------------------------------ control
    @property
    def paused(self) -> bool:
        return not self._unpaused.is_set()

    async def pause(self) -> None:
        self._unpaused.clear()
        await self._set_status(ExperimentStatus.PAUSED)

    async def resume(self) -> None:
        await self._set_status(ExperimentStatus.RUNNING)
        self._unpaused.set()

    def stop(self) -> None:
        self._stopped = True
        self._unpaused.set()

    async def _set_status(self, status: ExperimentStatus, error: str | None = None) -> None:
        async with self.session_factory() as session:
            exp = await session.get(Experiment, self.experiment_id)
            if exp is None:
                return
            exp.status = status.value
            exp.error = error[:1000] if error else None
            if status in (ExperimentStatus.COMPLETED, ExperimentStatus.STOPPED, ExperimentStatus.FAILED):
                exp.finished_at = _now()
            await session.commit()
        await self.publish({"type": "experiment_status", "status": status.value, "error": error})

    # ------------------------------------------------------------------ run
    async def run(self) -> None:
        async with self.session_factory() as session:
            exp = await session.get(Experiment, self.experiment_id)
            if exp is None:
                raise ValueError(f"Experiment {self.experiment_id} not found")
            await session.execute(delete(Game).where(Game.experiment_id == exp.id, Game.status.notin_(FINISHED)))
            exp.status = ExperimentStatus.RUNNING.value
            exp.error = None
            exp.finished_at = None
            exp.started_at = exp.started_at or _now()
            await session.commit()
            self.exp = exp
            done = (await session.execute(
                select(Game.game_index, Game.agent).where(Game.experiment_id == exp.id, Game.status.in_(FINISHED))
            )).all()
        await self.publish({"type": "experiment_status", "status": "running", "error": None})

        finished: dict[str, set[int]] = {MEMORY: set(), BASELINE: set(), EXPERT: set()}
        for index, agent in done:
            finished.setdefault(agent, set()).add(index)

        self.bank = bank_for(exp.memory_scope, exp.id)
        memory = await load_memory(self.session_factory, exp.user_id, self.bank)
        self.rules = set(discovered_rules(memory.counts))  # rules the memory already holds
        # The no-learning agent writes its experience to a buffer it never reads; the buffer is
        # merged into the learning agent's memory after each board.
        self.shared_buffer = PatternMemory()
        self.learned_from = {MEMORY: 0, BASELINE: 0}  # observations contributed this run, per agent
        players = {
            MEMORY: CodePlayer(memory, memory, random.Random(f"{exp.base_seed}:{MEMORY}")),
            BASELINE: CodePlayer(None, self.shared_buffer, random.Random(f"{exp.base_seed}:{BASELINE}")),
        }
        await self.publish({"type": "memory_updated", "patterns": len(memory),
                            "observations": memory.observations})

        try:
            for game_index in range(exp.num_games):
                if all(game_index in finished[a] for a in (MEMORY, BASELINE)):
                    continue
                await self._unpaused.wait()
                if self._stopped:
                    break
                completed = await self._play_board(game_index, players, finished)
                if not completed:
                    break
        # Memory is saved at the end of every finished board. Whatever is still unsaved here belongs to a
        # board that was cut short; it is dropped, because that board is replayed from scratch on resume
        # and the learning agent must not get a peek at it.
        except asyncio.CancelledError:
            # The server is shutting down (deploy, restart, Render putting the service to sleep). The
            # status stays "running" (or "paused") so the next startup resumes it automatically.
            raise
        except Exception as exc:  # a bug must not leave the experiment stuck in "running"
            logger.exception("Pattern experiment crashed")
            await self._set_status(ExperimentStatus.FAILED, f"{type(exc).__name__}: {exc}")
            return

        await self._set_status(ExperimentStatus.STOPPED if self._stopped else ExperimentStatus.COMPLETED)

    async def _save_memory(self, player: CodePlayer) -> None:
        if player.memory is not None:
            await save_increments(self.session_factory, self.exp.user_id, self.bank, player.memory.take_pending())

    def _update_rules(self, memory: PatternMemory) -> list[dict]:
        """Re-check only the overlap situations touched since the last save; report newly discovered rules."""
        touched = {k: memory.counts[k] for k in memory.pending if k.startswith("o:")}
        now = discovered_rules(touched)
        found = []
        for key in touched:
            if key in now and key not in self.rules:
                self.rules.add(key)
                outcome, seen = now[key]
                found.append({"rule": describe_overlap(key), "outcome": outcome, "seen": seen})
            elif key not in now and key in self.rules:
                self.rules.discard(key)  # contradicted by new evidence: no longer trusted
        return found

    async def _play_board(self, game_index: int, players: dict[str, CodePlayer],
                          finished: dict[str, set[int]]) -> bool:
        """Play one board with both agents, interleaving their moves. Returns False if stopped."""
        exp = self.exp
        config = BoardConfig(exp.rows, exp.cols, exp.mines)
        seed = exp.base_seed + game_index
        # Everything the learning agent records from here on (per move and at game end) is its own.
        self._board_start_observations = players[MEMORY].memory.observations
        tracks = []
        for agent in (MEMORY, BASELINE):
            if game_index in finished[agent]:
                continue
            player = players[agent]
            player.new_game()
            track = _Track(agent, player, MinesweeperEnv(config, seed, exp.max_moves))
            tracks.append(track)
            board = track.env.observe().data
            self.live[agent] = {"game_index": game_index, "game_id": None, "board": board, "last_move": None}
            await self.publish({"type": "game_started", "agent": agent, "game_index": game_index,
                                "game_id": None, "board": board, "lessons": []})

        while any(not t.env.done for t in tracks):
            await self._unpaused.wait()
            if self._stopped:
                for t in tracks:
                    await self.publish({"type": "game_aborted", "agent": t.agent, "game_index": game_index})
                return False
            fast = exp.speed == "fast"  # re-read each round: speed can be switched mid-run
            for track in tracks:
                if not track.env.done:
                    await self._step(track, game_index, fast)
            # Yield to the server between rounds; in watch mode, pace the moves.
            await asyncio.sleep(0 if fast else settings.WATCH_MOVE_DELAY_MS / 1000)

        await self._finish_board(game_index, seed, config, tracks, players, finished)
        return True

    async def _step(self, track: _Track, game_index: int, fast: bool) -> None:
        game = track.env.game
        choice = track.player.choose(game)
        action = {"action": "reveal", "row": choice.cell[0], "col": choice.cell[1]}
        step = track.env.step(action)
        track.player.learn_from_move(game, choice.cell)  # immediate: a mine hit is learned at once
        move_index = len(track.moves)
        action_text = f"reveal({choice.cell[0]},{choice.cell[1]})"
        record = {
            "move_index": move_index, "action": action, "action_text": action_text,
            "reasoning": choice.reason, "outcome": step.outcome.value, "valid": step.valid,
            "message": step.message, "grid_after": step.board["grid"],
            "p_mine": round(choice.p_mine, 4),
        }
        track.moves.append(record)
        if step.outcome.value == "mine":
            track.mistakes.append({"move": move_index, "type": "mine", "action": action,
                                   "reasoning": choice.reason, "message": step.message,
                                   "estimated_risk": round(choice.p_mine, 4)})

        event = {k: v for k, v in record.items() if k != "grid_after"}
        event["lessons_used"] = []
        self.live[track.agent] = {**(self.live[track.agent] or {}), "board": step.board, "last_move": event}
        now = time.monotonic()
        if not fast or step.done or now - track.last_publish >= FAST_PUBLISH_INTERVAL:
            track.last_publish = now
            await self.publish({"type": "move", "agent": track.agent, "game_index": game_index, "game_id": None,
                                "board": step.board, **event})

    async def _finish_board(self, game_index: int, seed: int, config: BoardConfig, tracks: list[_Track],
                            players: dict[str, CodePlayer], finished: dict[str, set[int]]) -> None:
        exp = self.exp
        rows: list[tuple[Game, list[dict]]] = []
        memory_player = players[MEMORY]
        memory = memory_player.memory
        knowledge_before = len(memory)

        for track in tracks:
            g = track.env.game
            track.player.learn_from_game(g)  # the revealed board labels everything it looked at
        own = memory.observations - self._board_start_observations
        # Now that the board is over, add what the no-learning agent experienced on it.
        before_merge = memory.observations
        memory.absorb(self.shared_buffer.take_pending())
        self.shared_buffer.counts.clear()
        shared = memory.observations - before_merge
        self.learned_from[MEMORY] += own
        self.learned_from[BASELINE] += shared
        new_rules = self._update_rules(memory)

        for track in tracks:
            g = track.env.game
            rows.append((Game(
                experiment_id=exp.id, agent=track.agent, game_index=game_index, seed=seed, status=g.status.value,
                moves=g.moves, reveals=g.reveals, flag_moves=g.flag_moves, invalid_moves=g.invalid_moves,
                min_clicks=g.initial_min_clicks, safe_revealed=g.safe_revealed, safe_total=g.safe_total,
                llm_calls=0, llm_errors=0, prompt_tokens=0, completion_tokens=0,
                lessons_available=knowledge_before if track.player.learns else 0,
                lessons_cited=[], mistakes=track.mistakes, final_grid=g.grid(show_mines=True),
                duration_ms=int((time.monotonic() - track.started) * 1000), finished_at=_now(),
            ), track.moves))

        if game_index not in finished[EXPERT]:
            expert = play_expert(Minesweeper(config, seed), exp.max_moves, f"{exp.base_seed}:{EXPERT}:{game_index}")
            rows.append((Game(
                experiment_id=exp.id, agent=EXPERT, game_index=game_index, seed=seed, status=expert.status.value,
                moves=expert.moves, reveals=expert.reveals, flag_moves=0, invalid_moves=expert.invalid_moves,
                min_clicks=expert.initial_min_clicks, safe_revealed=expert.safe_revealed,
                safe_total=expert.safe_total, llm_calls=0, llm_errors=0, prompt_tokens=0, completion_tokens=0,
                lessons_available=0, lessons_cited=[], mistakes=[], final_grid=expert.grid(show_mines=True),
                duration_ms=0, finished_at=_now(),
            ), []))

        async with self.session_factory() as session:
            for game_row, moves in rows:
                session.add(game_row)
                await session.flush()
                session.add_all(Move(game_id=game_row.id, move_index=m["move_index"], action=m["action"],
                                     reasoning=m["reasoning"], outcome=m["outcome"], valid=m["valid"],
                                     message=m["message"], grid_after=m["grid_after"]) for m in moves)
            await session.commit()
            summaries = [(row.agent, game_to_dict(row)) for row, _ in rows]

        await self._save_memory(memory_player)

        for agent, summary in summaries:
            finished.setdefault(agent, set()).add(game_index)
            event = {"type": "game_finished", "agent": agent, "game_index": game_index, "game": summary,
                     "analysis": None}
            if agent != EXPERT:
                track = next(t for t in tracks if t.agent == agent)
                event["board"] = track.env.observe().data
                self.live[agent] = {**(self.live[agent] or {}), "game_id": summary["id"], "board": event["board"]}
            await self.publish(event)

        mistakes = [{**t.mistakes[-1], "agent": t.agent} for t in tracks if t.mistakes]
        await self.publish({
            "type": "memory_updated",
            "game_index": game_index,
            "patterns": len(memory),
            "observations": memory.observations,
            "new_patterns": len(memory) - knowledge_before,
            "learned_from": dict(self.learned_from),
            "rules": len(self.rules),
            "new_rules": new_rules[:5],
            "mistakes": mistakes,
            "mistake": next((m for m in mistakes if m["agent"] == MEMORY), None),
        })
