# Minesweeper Learning Lab

Does persistent learning make an agent better at a game? This project answers that with a controlled,
side-by-side experiment on **Minesweeper**, run entirely in code: **no LLM, no API key, no rate limits**.

Two agents play the **same sequence of seeded boards** at the same time. Both reason from the numbers
on the board and both try to win every game:

| Agent | What it uses when it moves |
|---|---|
| **With persistent learning** | Reasoning from the visible numbers, **plus its memory**: statistics learned from every past game (its own *and* the other agent's), saved in the database. It uses them whenever reasoning alone can't decide. |
| **Without learning** | Reasoning from the visible numbers only. It figures every game out on its own and never reads any memory. Its experience and mistakes are still recorded, for the learning agent's benefit. |

An **expert solver** built from hand-written Minesweeper logic plays the same boards as a reference line
on the charts (it is not one of the compared agents).

Over hundreds or thousands of games the UI shows both boards live, rolling win rates, moves needed to win
against each board's true minimum, what the memory has learned, and every mistake.

## How it works

```
Experiment (N seeded boards)
 ├── Learning agent ──┐                    ┌── reasoning + reads the shared memory
 │                    ├── same boards, interleaved move by move
 ├── No-learning agent┘                    └── reasoning only; writes to a buffer it never reads
 └── Expert rules (reference only)

Each move:      deduce certain safe cells / mines from the numbers ─► if a cell is certainly safe, reveal it
                otherwise guess the lowest-risk cell (board estimate; the learning agent refines it with memory)
After a move:   learning agent records that cell's outcome at once (a mine hit is learned immediately)
After a board:  both agents' observations (incl. the no-learning agent's mistakes) are added to the memory,
                which is saved to the database. The no-learning agent's are added only now, so the learning
                agent never learns from a board it is still playing.
```

### The game (`backend/app/game/`): rules are hard-coded

* `minesweeper.py` is a deterministic engine and the only place the rules live. Mines come from a seed,
  so both agents get identical boards. A seeded 3×3 opening is revealed before move 1.
* Agents can only ask to reveal a hidden cell. The engine decides everything else: flood-fill of empty
  regions, mine hits, wins, invalid moves and the move budget.
* **Minimum moves (3BV).** Every board knows the fewest reveals that can clear it. "Efficiency" is
  minimum ÷ moves used, for won games.

### How the agents solve and learn (`backend/app/game/solver.py`, `backend/app/agents/code_players.py`, `backend/app/learning/`)

**Reasoning (both agents, fresh every game).** From the visible numbers each agent applies the basic counting
rules: a number whose mines are all found makes its other neighbours safe, and a number whose hidden
neighbours exactly match its remaining mines makes them all mines. Certainly-safe cells are revealed first.

**When the basic rules run out (where the agents differ).** The no-learning agent guesses the cell that looks
least risky on this board alone ("this 1 touches 3 hidden cells, so ~33%"). The learning agent first
consults the **rules it has discovered**: situations where two numbers' hidden cells overlap (e.g. "a number
needing 1 mine among 2 cells inside a number needing 1 among 3: the extra cell") that, over at least 30
sightings, never once went the other way (60 for mines). Cells such a rule marks safe are revealed; cells it
marks as mines are fed back into the basic rules, which often proves further cells safe. Only if none of
that applies does it guess, using its memory's odds for situations like this one instead of the board
estimate alone. Among cells it believes are safe it prefers the one most likely to open an empty region,
so it also finishes in fewer moves.

None of these rules are written in the code. The agent finds them in its own and the other agent's
outcomes, and they turn out to be real Minesweeper techniques (the "1-1" and "1-2" patterns), including ones
the hand-written expert below does not know.

**Memory.** For every undecided hidden cell the memory records the situation it was in and how it turned
out (mine, empty region or number):
* an **overlap situation** for each pair of numbers whose undecided cells overlap: what each still needs,
  among how many cells, how many they share, and which of them touch the cell (`backend/app/learning/overlaps.py`);
* a 3×3 and a 5×5 picture of the visible board around the cell (recognised in any rotation or reflection);
* a *number signature*: for each touching number, how many mines it still needs among how many cells.

Only situations the basic rules cannot settle are recorded, so every discovered rule is knowledge the
no-learning agent does not have.

**Shared experience.** Both agents' observations go into the same memory, but only the learning agent ever
reads it. The no-learning agent's are buffered and added after each board.

**Memory scope**, chosen per experiment: **persistent** (one memory shared by all your experiments; it keeps
growing) or **fresh** (private to this experiment, to show learning from zero).

**What to expect** (fresh memory, identical seeded boards):

| Board | Games | With learning | Without learning | Expert reference |
|---|---|---|---|---|
| 9×9, 10 mines | 1–50 | 90% wins, 2.8 extra moves/win | 82%, 3.7 | 96% |
| 9×9, 10 mines | 401–700 | **96%**, 2.2 | 87%, 3.3 | 97% |
| 16×16, 40 mines | 1–25 | 68%, 9.8 | 60%, 14.2 | 84% |
| 16×16, 40 mines | 201–300 | **90%**, 9.3 | 58%, 14.8 | 79% |

The learning agent pulls ahead within the first few dozen games and stays there. On 16×16 it even beats the
expert, because some rules it discovered go beyond the expert's. With persistent memory, later experiments
start from everything learned before. "Extra moves" are moves beyond the board's minimum.

### Speed

* **Watch:** paced (`WATCH_MOVE_DELAY_MS`, default 350 ms per move round) so you can follow both boards.
* **Fast:** as fast as the CPU allows, typically several board pairs per second; the boards refresh a few
  times a second. You can switch speed while an experiment runs.

## Running locally

Requirements: Python 3.12+ and Node 20+. Nothing else.

```bash
# Backend
cd backend
python -m venv venv
venv\Scripts\activate            # Windows  (source venv/bin/activate on Linux/Mac)
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --port 8000 --reload

# Frontend (second terminal)
cd frontend
npm install
npm run dev                      # http://localhost:5173
```

On Windows, `start.bat` launches both. Register an account, choose a board, the number of games, the
speed and the memory scope, and press **Start both agents**. The **Memory** page shows (and can reset)
the persistent memory.

## Docker

```bash
cp .env.example .env
docker compose up -d    # Postgres + backend (:8000) + frontend (:5173)
```

## Deploy on Render

`render.yaml` provisions Postgres, the backend (Docker) and the frontend (static site). Apply it as a
Blueprint; no API keys are needed.

* Keep **one** backend instance: experiments run inside the API process.
* Free web services sleep after 15 minutes without incoming requests. While an experiment runs, the
  backend requests its own public URL (`RENDER_EXTERNAL_URL`, set by Render) every `KEEP_ALIVE_SECONDS`
  (default 300) so it stays awake; when nothing runs it stops, so the service can still sleep when idle.
* If the backend restarts anyway (deploy, crash, sleep), experiments that were running **resume
  automatically** at the next unfinished board (`AUTO_RESUME_INTERRUPTED=true`). The board that was cut
  short is replayed from scratch, and nothing learned from its unfinished moves is kept. Paused experiments
  stay paused; LLM experiments are never resumed automatically.

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/auth/register`, `/api/auth/login` | Account and JWT |
| GET | `/api/options` | Board presets and defaults |
| POST | `/api/experiments` | Create (and by default start) an experiment |
| GET | `/api/experiments`, `/api/experiments/{id}` | Summaries per agent (incl. expert), current boards |
| POST | `/api/experiments/{id}/pause` · `/resume` · `/stop` | Control |
| POST | `/api/experiments/{id}/speed` | `{"speed": "watch" \| "fast"}`, also while running |
| DELETE | `/api/experiments/{id}` | Delete games and moves (and a fresh memory) |
| GET | `/api/experiments/{id}/games` | Finished games with metrics and mistakes |
| GET | `/api/experiments/{id}/games/{game_id}/moves` | Full replay with the agent's reasoning |
| GET | `/api/experiments/{id}/memory` | What the memory used by this experiment has learned |
| GET · POST | `/api/memory` · `/api/memory/reset` | The persistent memory; forget it |
| WS | `/ws/experiments/{id}?token=<JWT>` | Live events: `game_started`, `move`, `game_finished`, `memory_updated`, `experiment_status` |

Interactive docs: `http://localhost:8000/docs`.

## Tests

```bash
cd backend
pytest
```

The tests cover the engine (seed determinism, safe opening, win/loss, 3BV is reachable, invalid-move
codes), the action interface, the expert solver, the agents (the no-learning agent wins games on its own
and plays identically whatever the memory holds; immediate learning from a mine hit; learning finishes won
games in fewer moves and wins more often), learned rules (canonical overlap keys, a never-contradicted
situation becoming a rule, one counter-example revoking it, trivial situations excluded), shared experience (the no-learning agent's observations reach the memory), full
experiment runs (identical boards, persistent vs fresh memory, resume, stop) and the database migration.

## Optional: the LLM agents (disabled)

The project also contains LLM-driven agents (a playbook of text lessons, per-move LLM calls and post-game
reflection). They are kept but switched off. To use them again set `ENABLE_LLM_AGENTS=true` and the LLM
variables in `backend/.env`; the new-experiment form then offers an **Agents** choice and a model picker.
See `backend/.env.example` for the LLM settings. Free API tiers allow only a few hundred calls a day, which
is why the code-only agents are the default.

## License

MIT
