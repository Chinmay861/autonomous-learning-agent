"""Code-only agents (no LLM): pattern learning, the expert reference, and full experiment runs."""
import random

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents.code_players import CodePlayer
from app.database.models import Base, Experiment, Game, Move, PatternStat, User
from app.experiments.pattern_runner import PatternRunner
from app.game.interface import MinesweeperEnv
from app.game.minesweeper import PRESETS, Minesweeper
from app.game.solver import play_expert
from app.learning.patterns import PatternMemory, pattern_key, signature_key
from app.learning.store import load_memory, memory_summary


def play(player: CodePlayer, seed: int, config=PRESETS["beginner"]) -> Minesweeper:
    game = Minesweeper(config, seed)
    player.new_game()
    limit = MinesweeperEnv.default_max_moves(config)
    while not game.is_over and game.moves < limit:
        choice = player.choose(game)
        assert choice.cell not in game.revealed  # only legal targets are ever chosen
        game.reveal(*choice.cell)
        player.learn_from_move(game, choice.cell)
    player.learn_from_game(game)
    return game


def test_pattern_keys_ignore_rotation_and_reflection():
    game = Minesweeper(PRESETS["beginner"], 3)
    flipped = Minesweeper(PRESETS["beginner"], 3)
    # A board and its mirror image produce the same canonical keys for mirrored cells.
    flipped.revealed = {(r, game.cols - 1 - c) for r, c in game.revealed}
    flipped.counts = [list(reversed(row)) for row in game.counts]
    for r in range(game.rows):
        for c in range(game.cols):
            assert pattern_key(game, r, c, 1) == pattern_key(flipped, r, game.cols - 1 - c, 1)


def test_signature_describes_neighbouring_numbers():
    game = Minesweeper(PRESETS["beginner"], 42)
    hidden = next((r, c) for r in range(game.rows) for c in range(game.cols)
                  if (r, c) not in game.revealed
                  and any(n in game.revealed and game.count(*n) > 0 for n in game.neighbors(r, c)))
    key = signature_key(game, *hidden, believed_mines=set())
    assert key.startswith("s:") and "/" in key


def test_no_learning_agent_solves_games_on_its_own_and_never_reads_memory():
    buffer = PatternMemory()
    player = CodePlayer(None, buffer, random.Random(0))
    wins = sum(play(player, seed).status.value == "won" for seed in range(60))
    assert wins >= 30  # it reasons from the numbers, so it genuinely wins games
    assert player.memory is None and not player.learns
    assert len(buffer) > 0  # ...while its experience is recorded for the learning agent


def test_no_learning_agent_plays_identically_whatever_the_memory_holds():
    """Its choices depend only on the board: feeding the shared memory cannot change them."""
    lots_of_experience = PatternMemory()
    CodePlayer(lots_of_experience, lots_of_experience, random.Random(5)).choose(Minesweeper(PRESETS["beginner"], 1))
    a = play(CodePlayer(None, PatternMemory(), random.Random(9)), 77)
    b = play(CodePlayer(None, lots_of_experience, random.Random(9)), 77)
    assert a.grid(show_mines=True) == b.grid(show_mines=True) and a.moves == b.moves


def test_learning_agent_records_a_mine_hit_immediately():
    memory = PatternMemory()
    player = CodePlayer(memory, memory, random.Random(0))
    game = Minesweeper(PRESETS["beginner"], 7)
    player.new_game()
    player.choose(game)  # looks at (and remembers the situation of) every undecided hidden cell
    mine = next(m for m in game.mines if m in player._seen)
    keys = list(player._seen[mine])
    assert keys
    game.reveal(*mine)
    player.learn_from_move(game, mine)
    # Learned at once, before the game is even scored: each pattern it saw there now counts one mine.
    assert all(memory.counts[key][0] == 1 for key in keys)
    assert all(memory.pending[key][0] == 1 for key in keys)  # queued to be saved to the database


def test_learning_finishes_won_games_in_fewer_moves():
    memory, buffer = PatternMemory(), PatternMemory()
    learner = CodePlayer(memory, memory, random.Random(1))
    blind = CodePlayer(None, buffer, random.Random(2))
    extra = {"learner": [], "blind": []}
    for i in range(300):
        gl, gb = play(learner, 1000 + i), play(blind, 1000 + i)
        memory.absorb(buffer.take_pending())  # shared experience, merged after the board
        if i >= 100:
            for name, g in (("learner", gl), ("blind", gb)):
                if g.status.value == "won":
                    extra[name].append(g.moves - g.initial_min_clicks)
    mean = {k: sum(v) / len(v) for k, v in extra.items()}
    assert mean["learner"] < mean["blind"] - 0.5  # it learned which safe cells open regions
    assert len(memory) > 100


def test_absorb_adds_counts_and_queues_them_for_saving():
    memory = PatternMemory({"1:x": [1, 0, 0]})
    added = memory.absorb({"1:x": [1, 2, 3], "s:y": [0, 1, 0]})
    assert added == 7
    assert memory.counts["1:x"] == [2, 2, 3] and memory.pending["s:y"] == [0, 1, 0]


def test_expert_solver_is_strong_and_only_reveals():
    config = PRESETS["beginner"]
    wins = 0
    for seed in range(60):
        game = play_expert(Minesweeper(config, seed), MinesweeperEnv.default_max_moves(config), str(seed))
        assert game.invalid_moves == 0 and game.flag_moves == 0
        wins += game.status.value == "won"
    assert wins >= 45


# ---------------------------------------------------------------- full runs (database)
@pytest.fixture
async def db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'code.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(User(id=1, username="u", email="u@example.com", hashed_password="x"))
        await session.commit()
    yield factory
    await engine.dispose()


async def make(factory, num_games=6, scope="persistent") -> str:
    async with factory() as session:
        exp = Experiment(user_id=1, name="code", rows=9, cols=9, mines=10, num_games=num_games, max_moves=91,
                         base_seed=300, model="pattern-learner", temperature=0.0, memory_scope=scope,
                         agent_type="pattern", speed="fast", status="created")
        session.add(exp)
        await session.commit()
        return exp.id


async def run(factory, exp_id):
    events = []

    async def publish(event):
        events.append(event)

    await PatternRunner(exp_id, publish, session_factory=factory).run()
    return events


async def test_run_plays_identical_boards_side_by_side_with_expert_reference(db):
    exp_id = await make(db)
    events = await run(db, exp_id)
    async with db() as session:
        exp = await session.get(Experiment, exp_id)
        games = list((await session.execute(select(Game))).scalars())
        moves = list((await session.execute(select(Move))).scalars())
    assert exp.status == "completed"
    by_agent = {a: sorted((g for g in games if g.agent == a), key=lambda g: g.game_index)
                for a in ("memory", "baseline", "expert")}
    assert all(len(v) == 6 for v in by_agent.values())
    assert [g.seed for g in by_agent["memory"]] == [g.seed for g in by_agent["baseline"]] == list(range(300, 306))
    assert all(g.llm_calls == 0 for g in games)  # no LLM anywhere
    assert sum(g.moves for g in games if g.agent != "expert") == len(moves)
    assert any(e["type"] == "memory_updated" for e in events)
    assert {e["agent"] for e in events if e["type"] == "move"} == {"memory", "baseline"}


async def test_memory_persists_across_experiments_and_fresh_scope_is_separate(db):
    first = await make(db, num_games=4, scope="persistent")
    await run(db, first)
    persistent = await load_memory(db, 1, "user")
    assert len(persistent) > 0

    second = await make(db, num_games=2, scope="persistent")
    await run(db, second)
    assert (await load_memory(db, 1, "user")).observations > persistent.observations  # kept growing

    fresh = await make(db, num_games=2, scope="fresh")
    await run(db, fresh)
    assert len(await load_memory(db, 1, f"exp:{fresh}")) > 0
    summary = await memory_summary(db, 1, "user", min_seen=1)
    assert summary["patterns_3x3"] > 0 and summary["observations"] > 0


async def test_resume_continues_at_the_next_board(db):
    exp_id = await make(db, num_games=3)
    await run(db, exp_id)
    async with db() as session:
        exp = await session.get(Experiment, exp_id)
        exp.num_games = 5
        exp.status = "interrupted"
        await session.commit()
    await run(db, exp_id)
    async with db() as session:
        indices = sorted(g.game_index for g in (await session.execute(select(Game))).scalars()
                         if g.agent == "memory")
    assert indices == [0, 1, 2, 3, 4]


async def test_stop_keeps_finished_boards_and_saves_memory(db):
    exp_id = await make(db, num_games=50)
    runner_box = {}

    async def publish(event):
        if event["type"] == "game_finished" and event["game_index"] == 1:
            runner_box["r"].stop()

    runner = PatternRunner(exp_id, publish, session_factory=db)
    runner_box["r"] = runner
    await runner.run()
    async with db() as session:
        exp = await session.get(Experiment, exp_id)
        games = list((await session.execute(select(Game))).scalars())
        stats = list((await session.execute(select(PatternStat))).scalars())
    assert exp.status == "stopped"
    assert 0 < len({g.game_index for g in games}) < 50
    assert stats  # learned patterns were saved before stopping


async def test_old_databases_gain_the_new_columns(tmp_path):
    from app.database import connection

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'old.db'}")
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE ms_experiments (id VARCHAR(36) PRIMARY KEY, name VARCHAR(200))"))
        await conn.execute(text("INSERT INTO ms_experiments (id, name) VALUES ('old', 'llm run')"))
        await conn.run_sync(connection._add_missing_columns)
        row = (await conn.execute(text("SELECT agent_type, speed FROM ms_experiments"))).one()
    await engine.dispose()
    assert tuple(row) == ("llm", "watch")


async def test_no_learning_agents_experience_feeds_the_shared_memory(db):
    exp_id = await make(db, num_games=4, scope="fresh")
    events = await run(db, exp_id)
    updates = [e for e in events if e["type"] == "memory_updated" and "learned_from" in e]
    assert updates
    contributed = updates[-1]["learned_from"]
    assert contributed["memory"] > 0 and contributed["baseline"] > 0
    stored = await load_memory(db, 1, f"exp:{exp_id}")
    assert stored.observations == contributed["memory"] + contributed["baseline"]


# ---------------------------------------------------------------- learned overlap rules
def test_overlap_keys_describe_a_subset_situation_canonically():
    from app.learning.overlaps import overlap_keys

    a, b, c = (0, 0), (0, 1), (0, 2)
    keys = overlap_keys([(frozenset({a, b}), 1), (frozenset({a, b, c}), 1)])
    assert keys[c] == {"o:1/2|1/3|2|B"}  # c: only the larger number touches it
    assert keys[a] == keys[b] == {"o:1/2|1/3|2|AB"}
    # Listing the numbers the other way round gives the same keys.
    assert overlap_keys([(frozenset({a, b, c}), 1), (frozenset({a, b}), 1)]) == keys


def test_a_situation_that_never_had_a_mine_becomes_a_learned_safe_rule():
    from app.learning.overlaps import RULE_MIN_EVIDENCE, discovered_rules

    memory = PatternMemory({"o:1/2|1/3|2|B": [0, 5, RULE_MIN_EVIDENCE - 5]})
    player = CodePlayer(memory, memory, random.Random(0))
    a, b, c = (0, 0), (0, 1), (0, 2)
    safe, mines = player._learned_rules([(frozenset({a, b}), 1), (frozenset({a, b, c}), 1)])
    assert c in safe and not mines
    assert discovered_rules(memory.counts) == {"o:1/2|1/3|2|B": ("safe", RULE_MIN_EVIDENCE)}
    memory.record("o:1/2|1/3|2|B", "mine")  # one counter-example and it is no longer a rule
    assert discovered_rules(memory.counts) == {}


def test_learning_agent_wins_more_often_than_the_no_learning_agent():
    memory, buffer = PatternMemory(), PatternMemory()
    learner = CodePlayer(memory, memory, random.Random(1))
    blind = CodePlayer(None, buffer, random.Random(2))
    wins = {"learner": 0, "blind": 0}
    for i in range(250):
        gl, gb = play(learner, 4000 + i), play(blind, 4000 + i)
        memory.absorb(buffer.take_pending())
        if i >= 50:  # after it has had some experience
            wins["learner"] += gl.status.value == "won"
            wins["blind"] += gb.status.value == "won"
    assert wins["learner"] >= wins["blind"] + 10, wins


def test_rules_the_basic_rules_already_cover_are_not_counted_as_discoveries():
    from app.learning.overlaps import discovered_rules, is_trivial, undecided

    assert is_trivial("o:0/1|1/3|1|B") and is_trivial("o:1/2|2/2|1|A")
    assert not is_trivial("o:1/2|1/3|2|B")
    assert discovered_rules({"o:0/1|1/3|1|B": [0, 50, 50]}) == {}
    a, b, c = (0, 0), (0, 1), (0, 2)
    # A number needing 0 (all safe) or needing all its cells is settled by the basic rules: not recorded.
    assert undecided([(frozenset({a, b}), 0), (frozenset({a, b, c}), 3), (frozenset({a, b, c}), 1)]) == [
        (frozenset({a, b, c}), 1)]
