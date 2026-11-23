"""Runs one experiment: the memory agent and the baseline agent play the same
sequence of seeded boards concurrently, move by move.

Everything is persisted as it happens (each move, each finished game, each
playbook change), so a restarted server can resume an experiment at the next
unfinished game.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from sqlalchemy import delete, select

from app.agents.player import MinesweeperPlayer
from app.agents.playbook import Playbook
from app.agents.reflection import GameRecord, reflect
from app.config import settings
from app.database.connection import async_sessionmaker_db
from app.database.models import AgentKind, Experiment, ExperimentStatus, Game, Move
from app.experiments.stats import FINISHED, game_to_dict
from app.game.interface import MinesweeperEnv, parse_action
from app.game.minesweeper import BoardConfig, MoveOutcome
from app.models.llm_provider import (
    LLMAuthError, LLMProvider, QuotaExhaustedError, RateLimitedError, get_llm_provider,
)

logger = logging.getLogger(__name__)

Publisher = Callable[[dict], Awaitable[None]]


class FatalRunError(RuntimeError):
    """Stops the whole experiment (both agents): bad credentials, exhausted quota, repeated LLM failures."""


def _action_text(action: dict | None, raw) -> str:
    if action:
        return f"{action['action']}({action['row']},{action['col']})"
    text = raw if isinstance(raw, str) else json.dumps(raw, default=str)
    return f"unparseable action {text[:60]!r}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ExperimentRunner:
    def __init__(self, experiment_id: str, publish: Publisher,
                 session_factory=async_sessionmaker_db,
                 llm_factory: Callable[[str], LLMProvider] = get_llm_provider):
        self.experiment_id = experiment_id
        self.publish = publish
        self.session_factory = session_factory
        self.llm_factory = llm_factory
        self._unpaused = asyncio.Event()
        self._unpaused.set()
        self._stopped = False
        self._fatal: str | None = None
        self.live: dict[str, dict | None] = {AgentKind.MEMORY.value: None, AgentKind.BASELINE.value: None}

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

    async def _wait_if_paused(self) -> None:
        await self._unpaused.wait()

    async def _set_status(self, status: ExperimentStatus, error: str | None = None) -> None:
        async with self.session_factory() as session:
            exp = await session.get(Experiment, self.experiment_id)
            if exp is None:
                return
            exp.status = status.value
            if error is not None:
                exp.error = error[:1000]
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
            # Games left half-played by a crash or stop are replayed from scratch.
            await session.execute(delete(Game).where(Game.experiment_id == exp.id, Game.status.notin_(FINISHED)))
            exp.status = ExperimentStatus.RUNNING.value
            exp.error = None
            exp.finished_at = None
            exp.started_at = exp.started_at or _now()
            await session.commit()
            self.exp = exp
        await self.publish({"type": "experiment_status", "status": "running", "error": None})

        try:
            await self._preflight()
            results = await asyncio.gather(
                self._run_agent(AgentKind.MEMORY.value),
                self._run_agent(AgentKind.BASELINE.value),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
                    if not isinstance(result, FatalRunError):
                        logger.error("Agent crashed", exc_info=result)
                    self._fatal = self._fatal or str(result) or type(result).__name__
        except asyncio.CancelledError:
            await self._set_status(ExperimentStatus.INTERRUPTED)
            raise
        except FatalRunError as exc:
            self._fatal = str(exc)

        # A game cut short by a fatal error or stop is not a result; drop it (it is replayed on resume).
        async with self.session_factory() as session:
            await session.execute(
                delete(Game).where(Game.experiment_id == self.experiment_id, Game.status.notin_(FINISHED))
            )
            await session.commit()

        if self._fatal:
            await self._set_status(ExperimentStatus.FAILED, self._fatal)
        elif self._stopped:
            await self._set_status(ExperimentStatus.STOPPED)
        else:
            await self._set_status(ExperimentStatus.COMPLETED)

    async def _preflight(self) -> None:
        """Fail fast on missing or rejected credentials instead of burning a run on errors."""
        try:
            llm = self.llm_factory(self.exp.model)
            await llm.list_models()
        except LLMAuthError as exc:
            raise FatalRunError(f"LLM authentication failed: {exc}") from exc
        except Exception as exc:  # listing models is optional for some providers
            logger.warning(f"Model listing failed, continuing: {exc}")

    def _abort_all(self, reason: str) -> None:
        self._fatal = self._fatal or reason
        self._stopped = True
        self._unpaused.set()

    async def _run_agent(self, agent: str) -> None:
        exp = self.exp
        try:
            llm = self.llm_factory(exp.model)  # one client per agent so they never share state
        except LLMAuthError as exc:
            self._abort_all(str(exc))
            raise FatalRunError(str(exc)) from exc
        uses_memory = agent == AgentKind.MEMORY.value
        player = MinesweeperPlayer(llm, uses_memory=uses_memory, temperature=exp.temperature)
        playbook = Playbook(self.session_factory, exp.user_id, exp.id, exp.memory_scope) if uses_memory else None

        async with self.session_factory() as session:
            result = await session.execute(
                select(Game.game_index).where(Game.experiment_id == exp.id, Game.agent == agent,
                                              Game.status.in_(FINISHED))
            )
            finished = set(result.scalars().all())

        for game_index in range(exp.num_games):
            if game_index in finished:
                continue
            await self._wait_if_paused()
            if self._stopped:
                return
            try:
                await self._play_game(agent, game_index, player, llm, playbook)
            except (LLMAuthError, QuotaExhaustedError, FatalRunError) as exc:
                if isinstance(exc, QuotaExhaustedError):
                    reason = f"LLM quota exhausted, run stopped (resume once it resets): {exc}"
                elif isinstance(exc, LLMAuthError):
                    reason = f"LLM authentication failed: {exc}"
                else:
                    reason = str(exc)
                self._abort_all(reason)
                raise FatalRunError(reason) from exc

    async def _play_game(self, agent: str, game_index: int, player: MinesweeperPlayer, llm: LLMProvider,
                         playbook: Playbook | None) -> None:
        exp = self.exp
        config = BoardConfig(exp.rows, exp.cols, exp.mines)
        seed = exp.base_seed + game_index
        env = MinesweeperEnv(config, seed, exp.max_moves)
        lessons = await playbook.top() if playbook else []

        async with self.session_factory() as session:
            game_row = Game(experiment_id=exp.id, agent=agent, game_index=game_index, seed=seed, status="playing",
                            min_clicks=env.game.initial_min_clicks, safe_total=env.game.safe_total,
                            safe_revealed=env.game.safe_revealed, lessons_available=len(lessons),
                            lessons_cited=[], mistakes=[], final_grid=[])
            session.add(game_row)
            await session.commit()
            game_id = game_row.id

        board = env.observe().data
        self.live[agent] = {"game_index": game_index, "game_id": game_id, "board": board, "last_move": None,
                            "lessons": [l.to_dict() for l in lessons]}
        await self.publish({"type": "game_started", "agent": agent, "game_index": game_index, "game_id": game_id,
                            "board": board, "lessons": [l.to_dict() for l in lessons]})

        history: list[dict] = []
        mistakes: list[dict] = []
        cited: list[int] = []
        llm_calls = llm_errors = prompt_tokens = completion_tokens = 0
        consecutive_errors = 0
        last_feedback: str | None = None
        fatal_board_text: str | None = None
        started = time.monotonic()

        while not env.done:
            await self._wait_if_paused()
            if self._stopped:
                async with self.session_factory() as session:
                    row = await session.get(Game, game_id)
                    if row is not None:
                        await session.delete(row)
                        await session.commit()
                await self.publish({"type": "game_aborted", "agent": agent, "game_index": game_index})
                return

            board_text_before = env.observe().text
            try:
                decision = await player.decide(env, game_index, history, lessons if playbook else None, last_feedback)
            except (LLMAuthError, QuotaExhaustedError):
                raise
            except RateLimitedError as exc:
                # Provider per-minute limit: wait it out; it never counts as a failure or a move.
                await self.publish({"type": "agent_error", "agent": agent, "game_index": game_index,
                                    "error": f"Rate limited by the provider, waiting 30s. {str(exc)[:160]}"})
                await asyncio.sleep(30)
                continue
            except Exception as exc:  # transport errors, timeouts: retry without spending a move
                llm_errors += 1
                consecutive_errors += 1
                await self.publish({"type": "agent_error", "agent": agent, "game_index": game_index,
                                    "error": str(exc)[:300]})
                if consecutive_errors >= settings.MAX_CONSECUTIVE_LLM_ERRORS:
                    raise FatalRunError(f"{agent} agent: {consecutive_errors} consecutive LLM failures; last: {exc}")
                await asyncio.sleep(min(2.0 * consecutive_errors, 15.0))
                continue
            consecutive_errors = 0
            llm_calls += 1
            prompt_tokens += decision.prompt_tokens
            completion_tokens += decision.completion_tokens
            for lesson_id in decision.lessons_used:
                if lesson_id not in cited:
                    cited.append(lesson_id)

            # Apply the turn's moves in order. Every applied action is one move; the turn
            # ends early at the first invalid move, a mine, or the end of the game.
            revealed_at_decision = set(env.game.revealed)
            turn_size = len(decision.actions)
            for turn_index, raw_action in enumerate(decision.actions):
                if env.done:
                    break
                parsed, _ = parse_action(raw_action)
                if parsed and turn_index > 0:
                    cell = (parsed["row"], parsed["col"])
                    # Opened by an earlier move of this same turn (an empty region cascades):
                    # the plan was right, the cell is simply done. Skip it rather than charge a move.
                    if cell in env.game.revealed and cell not in revealed_at_decision:
                        continue
                step_board_text = env.observe().text if turn_index > 0 else board_text_before
                move_index = len(history)
                step = env.step(raw_action)
                action_text = _action_text(step.action, raw_action)
                last_feedback = None if step.valid else step.message

                if step.outcome == MoveOutcome.MINE:
                    fatal_board_text = step_board_text
                    mistakes.append({"move": move_index, "type": "mine", "action": step.action,
                                     "reasoning": decision.reasoning, "message": step.message})
                elif not step.valid:
                    mistakes.append({"move": move_index, "type": step.error_code or "invalid",
                                     "action": step.action, "reasoning": decision.reasoning,
                                     "message": step.message})

                history.append({"move_index": move_index, "action_text": action_text, "message": step.message,
                                "reasoning": decision.reasoning, "outcome": step.outcome.value,
                                "valid": step.valid})

                async with self.session_factory() as session:
                    session.add(Move(game_id=game_id, move_index=move_index, action=step.action,
                                     raw_response=decision.raw_text[:4000] if turn_index == 0 else None,
                                     reasoning=decision.reasoning, outcome=step.outcome.value, valid=step.valid,
                                     message=step.message, grid_after=step.board["grid"]))
                    await session.commit()

                move_event = {"move_index": move_index, "action": step.action, "action_text": action_text,
                              "reasoning": decision.reasoning, "outcome": step.outcome.value, "valid": step.valid,
                              "message": step.message, "lessons_used": decision.lessons_used,
                              "turn_index": turn_index, "turn_size": turn_size}
                self.live[agent] = {**(self.live[agent] or {}), "board": step.board, "last_move": move_event}
                await self.publish({"type": "move", "agent": agent, "game_index": game_index, "game_id": game_id,
                                    "board": step.board, **move_event})

                # Learn from an invalid move immediately: the corrective lesson is visible from the next turn.
                if playbook and not step.valid:
                    change = await playbook.record_mistake(step.error_code, game_id)
                    if change:
                        lessons = await playbook.top()
                        self.live[agent]["lessons"] = [l.to_dict() for l in lessons]
                        await self.publish({"type": "lessons_updated", "agent": agent, "game_index": game_index,
                                            "changes": [change], "lessons": [l.to_dict() for l in lessons]})

                if not step.valid or step.outcome == MoveOutcome.MINE:
                    break  # the rest of the plan was made on a board that no longer holds

            if settings.MOVE_DELAY_SECONDS > 0:
                await asyncio.sleep(settings.MOVE_DELAY_SECONDS)

        # ---------------------------------------------------------- game over
        reflection_changes: list[dict] = []
        analysis = None
        if playbook:
            await playbook.record_citations(cited)
            record = GameRecord(env.game, env.max_moves, history, fatal_board_text)
            try:
                reflection, pt, ct = await reflect(llm, record, await playbook.all_active(), cited, exp.temperature)
                llm_calls += 1
                prompt_tokens += pt
                completion_tokens += ct
                analysis = str(reflection.get("analysis") or "")[:600] or None
                reflection_changes = await playbook.apply_reflection(reflection, game_id)
            except (LLMAuthError, QuotaExhaustedError):
                raise
            except Exception as exc:
                llm_errors += 1
                logger.warning(f"Reflection failed for game {game_id}: {exc}")
                await self.publish({"type": "agent_error", "agent": agent, "game_index": game_index,
                                    "error": f"Reflection failed: {str(exc)[:200]}"})

        g = env.game
        async with self.session_factory() as session:
            row = await session.get(Game, game_id)
            row.status = g.status.value
            row.moves = g.moves
            row.reveals = g.reveals
            row.flag_moves = g.flag_moves
            row.invalid_moves = g.invalid_moves
            row.safe_revealed = g.safe_revealed
            row.llm_calls = llm_calls
            row.llm_errors = llm_errors
            row.prompt_tokens = prompt_tokens
            row.completion_tokens = completion_tokens
            row.lessons_cited = cited
            row.mistakes = mistakes
            row.final_grid = g.grid(show_mines=True)
            row.duration_ms = int((time.monotonic() - started) * 1000)
            row.finished_at = _now()
            await session.commit()
            summary = game_to_dict(row)

        final_board = env.observe().data
        self.live[agent] = {**(self.live[agent] or {}), "board": final_board}
        await self.publish({"type": "game_finished", "agent": agent, "game_index": game_index,
                            "game": summary, "board": final_board, "analysis": analysis})
        if playbook:
            lessons = await playbook.top()
            self.live[agent]["lessons"] = [l.to_dict() for l in lessons]
            await self.publish({"type": "lessons_updated", "agent": agent, "game_index": game_index,
                                "changes": reflection_changes, "analysis": analysis,
                                "lessons": [l.to_dict() for l in lessons]})
