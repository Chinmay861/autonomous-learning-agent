"""End-to-end experiment runs with a scripted fake LLM and a throwaway SQLite database."""
import json
import re

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents.playbook import Playbook
from app.agents.prompts import REFLECTION_SYSTEM
from app.database.models import Base, Experiment, Game, Lesson, Move, User
from app.experiments.runner import ExperimentRunner
from app.experiments.stats import summarize
from app.models.llm_provider import LLMProvider, LLMResponse, QuotaExhaustedError


class FakeLLM(LLMProvider):
    """Reveals the first hidden cell on the board; makes one bad move first; writes a lesson on reflection."""

    def __init__(self, log: list):
        self.model = "fake"
        self.log = log
        self.calls = 0

    async def list_models(self):
        return ["fake"]

    async def complete(self, system, user, temperature=0.3, json_mode=True):
        self.calls += 1
        self.log.append({"system": system, "user": user})
        if system == REFLECTION_SYSTEM:
            ids = [int(i) for i in re.findall(r"\[L(\d+)\]", user)]
            return LLMResponse(json.dumps({
                "analysis": "Clicked blindly.",
                "new_lessons": [{"text": "Prefer cells next to a 0-count region before guessing elsewhere on the board.",
                                 "category": "strategy"}],
                "helpful_ids": ids[:1], "harmful_ids": [], "revised": [], "retire_ids": [],
            }), 100, 20)
        if self.calls == 1:
            return LLMResponse("I think I will reveal something", 50, 5)  # not JSON: an invalid move
        rows = [line for line in user.splitlines() if re.match(r"^\s*\d+ \| ", line)]
        for r, line in enumerate(rows):
            cells = line.split("|", 1)[1].split()
            for c, ch in enumerate(cells):
                if ch == "#":
                    return LLMResponse(json.dumps({"reasoning": "first hidden cell", "action": "reveal",
                                                   "row": r, "col": c, "lessons_used": []}), 50, 10)
        return LLMResponse(json.dumps({"action": "reveal", "row": 0, "col": 0}), 50, 10)


@pytest.fixture
async def db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(User(id=1, username="u", email="u@example.com", hashed_password="x"))
        await session.commit()
    yield factory
    await engine.dispose()


async def make_experiment(factory, num_games=3, scope="persistent") -> str:
    async with factory() as session:
        exp = Experiment(user_id=1, name="t", rows=6, cols=6, mines=5, num_games=num_games, max_moves=40,
                         base_seed=100, model="fake", temperature=0.0, memory_scope=scope, status="created")
        session.add(exp)
        await session.commit()
        return exp.id


async def run(factory, exp_id, log, llm_cls=FakeLLM):
    events = []

    async def publish(event):
        events.append(event)

    runner = ExperimentRunner(exp_id, publish, session_factory=factory, llm_factory=lambda model: llm_cls(log))
    await runner.run()
    return events


async def test_both_agents_play_identical_boards(db):
    exp_id = await make_experiment(db)
    await run(db, exp_id, [])
    async with db() as session:
        exp = await session.get(Experiment, exp_id)
        games = list((await session.execute(select(Game))).scalars())
    assert exp.status == "completed"
    memory = sorted((g for g in games if g.agent == "memory"), key=lambda g: g.game_index)
    baseline = sorted((g for g in games if g.agent == "baseline"), key=lambda g: g.game_index)
    assert len(memory) == len(baseline) == 3
    assert [g.seed for g in memory] == [g.seed for g in baseline] == [100, 101, 102]
    assert all(g.status in ("won", "lost", "timeout") for g in games)
    assert summarize(memory)["games_played"] == 3


async def test_only_memory_agent_reads_and_writes_the_playbook(db):
    exp_id = await make_experiment(db)
    log: list = []
    await run(db, exp_id, log)
    move_prompts = [c["user"] for c in log if c["system"] != REFLECTION_SYSTEM]
    with_playbook = [p for p in move_prompts if "PLAYBOOK (" in p]
    without = [p for p in move_prompts if "PLAYBOOK (" not in p]
    assert with_playbook and without
    reflections = [c for c in log if c["system"] == REFLECTION_SYSTEM]
    assert len(reflections) == 3  # one per memory-agent game, none for the baseline
    async with db() as session:
        lessons = list((await session.execute(select(Lesson))).scalars())
    texts = {l.text for l in lessons}
    # The invalid first move produced an immediate corrective lesson, reflection added a strategy lesson.
    assert any("JSON object" in t for t in texts)
    assert any("0-count region" in t for t in texts)
    assert all(l.experiment_id == exp_id for l in lessons)


async def test_moves_and_mistakes_are_persisted(db):
    exp_id = await make_experiment(db, num_games=1)
    await run(db, exp_id, [])
    async with db() as session:
        games = list((await session.execute(select(Game))).scalars())
        moves = list((await session.execute(select(Move))).scalars())
    assert sum(g.moves for g in games) == len(moves)
    first_game_mistakes = [m for g in games for m in g.mistakes]
    assert any(m["type"] == "unparseable" for m in first_game_mistakes)


async def test_resume_skips_finished_games(db):
    exp_id = await make_experiment(db, num_games=2)
    await run(db, exp_id, [])
    async with db() as session:
        exp = await session.get(Experiment, exp_id)
        exp.num_games = 4
        exp.status = "interrupted"
        await session.commit()
    await run(db, exp_id, [])
    async with db() as session:
        games = list((await session.execute(select(Game))).scalars())
    assert sorted(g.game_index for g in games if g.agent == "memory") == [0, 1, 2, 3]


async def test_fresh_scope_hides_older_lessons(db):
    async with db() as session:
        session.add(Lesson(user_id=1, experiment_id="older", text="Old lesson about corners being risky.",
                           category="strategy", helpful=5, harmful=0, times_cited=0, active=True))
        await session.commit()
    fresh = Playbook(db, user_id=1, experiment_id="new", scope="fresh")
    persistent = Playbook(db, user_id=1, experiment_id="new", scope="persistent")
    assert await fresh.top() == []
    assert [l.text for l in await persistent.top()] == ["Old lesson about corners being risky."]


async def test_quota_exhaustion_fails_the_experiment(db):
    class QuotaLLM(FakeLLM):
        async def complete(self, *args, **kwargs):
            raise QuotaExhaustedError("tokens per day limit reached")

    exp_id = await make_experiment(db)
    await run(db, exp_id, [], llm_cls=QuotaLLM)
    async with db() as session:
        exp = await session.get(Experiment, exp_id)
        games = list((await session.execute(select(Game))).scalars())
    assert exp.status == "failed" and "quota" in (exp.error or "").lower()
    assert games == []  # unfinished games are not kept


class TurnLLM(FakeLLM):
    """Plays every safe cell it can see in one turn (it reads the mines from the board it was built for)."""

    def __init__(self, log, mines_by_seed):
        super().__init__(log)
        self.mines_by_seed = mines_by_seed

    async def complete(self, system, user, temperature=0.3, json_mode=True):
        if system == REFLECTION_SYSTEM:
            return await super().complete(system, user, temperature, json_mode)
        self.calls += 1
        rows = [line for line in user.splitlines() if re.match(r"^\s*\d+ \| ", line)]
        hidden = [(r, c) for r, line in enumerate(rows)
                  for c, ch in enumerate(line.split("|", 1)[1].split()) if ch == "#"]
        mines = next(iter(self.mines_by_seed.values()))
        safe = [cell for cell in hidden if cell not in mines]
        moves = [{"action": "reveal", "row": r, "col": c} for r, c in safe[:8]]
        return LLMResponse(json.dumps({"reasoning": "certain", "moves": moves}), 50, 10)


async def test_one_call_can_play_several_moves_and_skips_cascaded_cells(db):
    from app.game.minesweeper import BoardConfig, Minesweeper

    exp_id = await make_experiment(db, num_games=1)
    mines = {100: Minesweeper(BoardConfig(6, 6, 5), 100).mines}
    log: list = []

    async def publish(event):
        pass

    runner = ExperimentRunner(exp_id, publish, session_factory=db,
                              llm_factory=lambda model: TurnLLM(log, mines))
    await runner.run()
    async with db() as session:
        games = list((await session.execute(select(Game))).scalars())
    for g in games:
        assert g.status == "won"
        assert g.invalid_moves == 0  # cells opened by an earlier move in the same turn were skipped
    baseline = next(g for g in games if g.agent == "baseline")
    assert baseline.llm_calls < baseline.moves


def test_rate_limit_duration_parsing():
    from app.models.llm_provider import parse_duration

    assert parse_duration("7.66s") == pytest.approx(7.66)
    assert parse_duration("2m59.5s") == pytest.approx(179.5)
    assert parse_duration("120ms") == pytest.approx(0.12)
    assert parse_duration("1h2m3s") == pytest.approx(3723)
    assert parse_duration("") is None


async def test_rate_gate_waits_for_the_bucket_to_refill():
    import asyncio

    from app.models.llm_provider import RateGate

    gate = RateGate()
    gate.update({"x-ratelimit-remaining-tokens": "0", "x-ratelimit-limit-tokens": "60000",
                 "x-ratelimit-reset-tokens": "1m"})
    loop = asyncio.get_running_loop()
    start = loop.time()
    await gate.wait_for(500)  # 60000/min refills 1000 tokens per second
    assert 0.3 <= loop.time() - start < 2.0
